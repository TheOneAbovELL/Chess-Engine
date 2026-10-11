"""Load facts from the database and feed the pure statistics functions;
plus the personal opening explorer built from the user's own games."""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from typing import Any

import chess
from sqlalchemy import func, select

from app.core.errors import InvalidInputError
from app.db.session import Database
from app.models import Game, GameReview, PositionEvaluation
from app.repositories.games import GameFilters, GameRepository
from app.services.chess.positions import board_from_request

from .compute import ERROR_CLASSES, GameFact, MoveFact, compute_summary

EXPLORER_MAX_PLY = 30
OPENING_PLIES = 20


def _base_time(time_control: str | None) -> float | None:
    match = re.fullmatch(r"(\d+)(?:\+\d+)?", time_control or "")
    return float(match.group(1)) if match else None


def _phase(ply: int, fen: str) -> str:
    if ply <= OPENING_PLIES:
        return "opening"
    placement = fen.split(" ", 1)[0]
    minor_major = sum(1 for ch in placement if ch.lower() in "nbrq")
    return "endgame" if minor_major <= 6 else "middlegame"


def _is_forcing(fen: str, uci: str | None) -> bool:
    if not uci:
        return False
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
    except ValueError:
        return False
    if move not in board.legal_moves:
        return False
    return board.is_capture(move) or board.gives_check(move)


class StatisticsService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _game_facts(self, games: list[Game]) -> list[GameFact]:
        facts = []
        for g in games:
            user_rating = opponent_rating = None
            if g.user_color == "white":
                user_rating, opponent_rating = g.white_elo, g.black_elo
            elif g.user_color == "black":
                user_rating, opponent_rating = g.black_elo, g.white_elo
            facts.append(
                GameFact(
                    id=g.id,
                    played_at=g.played_at,
                    source=g.source,
                    user_color=g.user_color,
                    user_result=g.user_result,
                    user_rating=user_rating,
                    opponent_rating=opponent_rating,
                    time_class=g.time_class,
                    opening=g.opening,
                    eco=g.eco,
                    ply_count=g.ply_count,
                    termination=g.termination,
                    rated=g.rated,
                )
            )
        return facts

    def _move_facts(self, session: Any, games: list[Game]) -> list[MoveFact]:
        by_id = {g.id: g for g in games if g.user_color}
        if not by_id:
            return []
        latest = (
            select(GameReview.game_id, func.max(GameReview.id).label("rid"))
            .where(GameReview.status == "completed", GameReview.game_id.in_(list(by_id)))
            .group_by(GameReview.game_id)
            .subquery()
        )
        rows = session.execute(
            select(latest.c.game_id, PositionEvaluation)
            .join(PositionEvaluation, PositionEvaluation.review_id == latest.c.rid)
            .order_by(latest.c.game_id, PositionEvaluation.ply)
        ).all()
        facts: list[MoveFact] = []
        previous: dict[int, PositionEvaluation] = {}
        for game_id, pos in rows:
            prev = previous.get(game_id)
            previous[game_id] = pos
            if prev is None or pos.classification is None or pos.classification == "forced":
                continue
            mover = "white" if prev.fen.split(" ")[1] == "w" else "black"
            game = by_id[game_id]
            if mover != game.user_color:
                continue
            is_error = pos.classification in ERROR_CLASSES
            facts.append(
                MoveFact(
                    game_id=game_id,
                    ply=pos.ply,
                    classification=pos.classification,
                    win_loss=pos.win_loss or 0.0,
                    phase=_phase(pos.ply, prev.fen),
                    clock_s=pos.clock_s,
                    base_time_s=_base_time(game.time_control),
                    missed_tactic=is_error and _is_forcing(prev.fen, prev.best_move_uci),
                    allowed_tactic=is_error and (pos.mate is not None or _is_forcing(pos.fen, pos.best_move_uci)),
                )
            )
        return facts

    def summary(self, filters: GameFilters) -> dict[str, Any]:
        with self.db.session() as session:
            games = GameRepository(session).iterate(filters, sort="played_asc")
            facts = self._game_facts(games)
            moves = self._move_facts(session, games)
            result = compute_summary(facts, moves)
            result["owners"] = [
                {"source": s, "username": o, "games": c} for s, o, c in GameRepository(session).owners()
            ]
            return result


class ExplorerService:
    """ "What did I play here, and how did it go?" built from stored games.

    The index maps positions (EPD, so move counters do not matter and
    transpositions merge) to the moves played from them, with results from the
    user's perspective. It is cached in memory and rebuilt when games change.
    """

    def __init__(self, db: Database, cache_size: int = 8) -> None:
        self.db = db
        self._cache: OrderedDict[tuple[Any, ...], dict[str, dict[str, dict[str, Any]]]] = OrderedDict()
        self._lock = threading.Lock()
        self.cache_size = cache_size

    def _build(self, games: list[Game]) -> dict[str, dict[str, dict[str, Any]]]:
        index: dict[str, dict[str, dict[str, Any]]] = {}
        for game in games:
            if game.initial_fen or not game.user_result or not game.moves_uci:
                continue
            board = chess.Board()
            for ply, uci in enumerate(game.moves_uci.split()):
                if ply >= EXPLORER_MAX_PLY:
                    break
                key = board.epd()
                stats = index.setdefault(key, {}).setdefault(
                    uci, {"games": 0, "win": 0, "draw": 0, "loss": 0, "last_played": None, "game_ids": []}
                )
                stats["games"] += 1
                stats[game.user_result] += 1
                if game.played_at and (stats["last_played"] is None or game.played_at > stats["last_played"]):
                    stats["last_played"] = game.played_at
                if len(stats["game_ids"]) < 5:
                    stats["game_ids"].append(game.id)
                try:
                    board.push_uci(uci)
                except ValueError:
                    break
        return index

    def _index(self, filters: GameFilters) -> dict[str, dict[str, dict[str, Any]]]:
        with self.db.session() as session:
            repo = GameRepository(session)
            key = (tuple(sorted((k, str(v)) for k, v in filters.__dict__.items())), repo.version_key())
            with self._lock:
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key]
            index = self._build(repo.iterate(filters, sort="played_asc"))
        with self._lock:
            self._cache[key] = index
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return index

    def query(self, fen: str | None, moves: list[str] | None, filters: GameFilters) -> dict[str, Any]:
        board = board_from_request(fen, moves)
        if board.ply() > EXPLORER_MAX_PLY:
            raise InvalidInputError(f"The explorer covers the first {EXPLORER_MAX_PLY // 2} moves of each game.")
        index = self._index(filters)
        entries = index.get(board.epd(), {})
        total = sum(e["games"] for e in entries.values())
        result = []
        for uci, stats in entries.items():
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                continue
            n = stats["games"]
            result.append(
                {
                    "uci": uci,
                    "san": board.san(move),
                    "games": n,
                    "wins": stats["win"],
                    "draws": stats["draw"],
                    "losses": stats["loss"],
                    "score": round((stats["win"] + 0.5 * stats["draw"]) / n, 4) if n else None,
                    "share": round(n / total, 4) if total else 0,
                    "last_played": stats["last_played"],
                    "game_ids": stats["game_ids"],
                }
            )
        result.sort(key=lambda r: r["games"], reverse=True)
        return {"fen": board.fen(), "total_games": total, "moves": result, "max_ply": EXPLORER_MAX_PLY}
