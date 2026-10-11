"""GameService: PGN uploads, saved games, listing, export and deletion."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import chess.pgn
from sqlalchemy import delete

from app.core.config import Settings
from app.core.errors import InvalidInputError, NotFoundError
from app.db.session import Database
from app.models import Game, GameReview, HttpCacheEntry
from app.repositories.games import GameFilters, GameRepository, SortKey

from .chess.normalize import UnsupportedGameError, normalize_game
from .chess.pgn import MalformedGameError, ParseFailure, iter_pgn_games, mainline_moves, parse_single_game

MAX_REPORTED_ERRORS = 50


@dataclass
class UploadSummary:
    total: int = 0
    imported: int = 0
    duplicates: int = 0
    failed: int = 0
    skipped: int = 0
    game_ids: list[int] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    def add_error(self, index: int, message: str, headers: dict[str, str] | None = None) -> None:
        if len(self.errors) < MAX_REPORTED_ERRORS:
            label = None
            if headers:
                label = f"{headers.get('White', '?')} vs {headers.get('Black', '?')} ({headers.get('Date', '?')})"
            self.errors.append({"index": index, "game": label, "error": message})


class GameService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def import_pgn(self, text: str, *, owner: str | None = None, source_override: str | None = None) -> UploadSummary:
        """Import every game in a (multi-game) PGN text.

        Games with Chess.com / Lichess links keep that source and id, so they
        deduplicate against the same games imported through the APIs.
        ``source_override="local"`` is used for games played inside ChessLab.
        """
        if len(text.encode("utf-8")) > self.settings.max_pgn_bytes:
            raise InvalidInputError(
                f"PGN is larger than {self.settings.max_pgn_bytes // (1024 * 1024)} MB.", code="pgn_too_large"
            )
        summary = UploadSummary()
        with self.db.session() as session:
            repo = GameRepository(session)
            for item in iter_pgn_games(text, self.settings.max_pgn_games_per_upload):
                summary.total += 1
                if isinstance(item, ParseFailure):
                    summary.failed += 1
                    summary.add_error(item.index, item.error, item.headers)
                    continue
                try:
                    kwargs: dict[str, Any] = {"owner": owner}
                    if source_override == "local":
                        kwargs.update(source="local", external_id=str(uuid.uuid4()))
                    record = normalize_game(item.game, **kwargs)
                    if source_override == "local" and record.played_at is None:
                        record.played_at = datetime.now(UTC)
                except UnsupportedGameError as exc:
                    summary.skipped += 1
                    summary.add_error(item.index, str(exc), dict(item.game.headers))
                    continue
                except MalformedGameError as exc:
                    summary.failed += 1
                    summary.add_error(item.index, f"Invalid game: {exc}", dict(item.game.headers))
                    continue
                game = repo.insert(record)
                if game is None:
                    summary.duplicates += 1
                else:
                    summary.imported += 1
                    summary.game_ids.append(game.id)
        if summary.total == 0:
            raise InvalidInputError("No games were found in the PGN text.", code="invalid_pgn")
        if summary.failed == summary.total:
            raise InvalidInputError(
                "No valid games were found in the PGN text.", code="invalid_pgn", details={"errors": summary.errors}
            )
        return summary

    def list_games(
        self, filters: GameFilters, *, sort: SortKey, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        with self.db.session() as session:
            games, total = GameRepository(session).page(
                filters, sort=sort, offset=(page - 1) * page_size, limit=page_size
            )
            review_status = self._review_status(session, [g.id for g in games])
            return [self.summary(g, review_status.get(g.id)) for g in games], total

    @staticmethod
    def _review_status(session: Any, ids: list[int]) -> dict[int, dict[str, Any]]:
        if not ids:
            return {}
        rows = (
            session.query(GameReview.game_id, GameReview.id, GameReview.status, GameReview.summary)
            .filter(GameReview.game_id.in_(ids))
            .order_by(GameReview.id.asc())
            .all()
        )
        latest: dict[int, dict[str, Any]] = {}
        for game_id, review_id, status, summary in rows:
            latest[game_id] = {"id": review_id, "status": status, "summary": summary}
        return latest

    @staticmethod
    def summary(game: Game, review: dict[str, Any] | None = None) -> dict[str, Any]:
        user_rating = opponent_rating = None
        opponent = None
        if game.user_color == "white":
            user_rating, opponent_rating, opponent = game.white_elo, game.black_elo, game.black
        elif game.user_color == "black":
            user_rating, opponent_rating, opponent = game.black_elo, game.white_elo, game.white
        return {
            "id": game.id,
            "source": game.source,
            "external_id": game.external_id,
            "owner_username": game.owner_username,
            "white": game.white,
            "black": game.black,
            "white_elo": game.white_elo,
            "black_elo": game.black_elo,
            "result": game.result,
            "termination": game.termination,
            "user_color": game.user_color,
            "user_result": game.user_result,
            "user_rating": user_rating,
            "opponent": opponent,
            "opponent_rating": opponent_rating,
            "time_control": game.time_control,
            "time_class": game.time_class,
            "rated": game.rated,
            "eco": game.eco,
            "opening": game.opening,
            "url": game.url,
            "played_at": game.played_at,
            "imported_at": game.imported_at,
            "ply_count": game.ply_count,
            "review": review,
        }

    def detail(self, game_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            game = GameRepository(session).get(game_id)
            if game is None:
                raise NotFoundError("Game not found.")
            review = self._review_status(session, [game_id]).get(game_id)
            data = self.summary(game, review)
            parsed, _ = parse_single_game(game.pgn)
            data["pgn"] = game.pgn
            data["initial_fen"] = game.initial_fen or chess.STARTING_FEN
            data["moves"] = mainline_moves(parsed)
            data["headers"] = dict(parsed.headers)
            return data

    def pgn(self, game_id: int) -> tuple[str, str]:
        with self.db.session() as session:
            game = GameRepository(session).get(game_id)
            if game is None:
                raise NotFoundError("Game not found.")
            return game.pgn, self.filename(game)

    @staticmethod
    def filename(game: Game) -> str:
        def safe(name: str) -> str:
            return "".join(ch for ch in name if ch.isalnum() or ch in "-_")[:30] or "player"

        day = game.played_at.strftime("%Y%m%d") if game.played_at else "undated"
        return f"{safe(game.white)}_vs_{safe(game.black)}_{day}_{game.id}.pgn"

    def export(self, filters: GameFilters, limit: int = 10_000) -> str:
        with self.db.session() as session:
            games = GameRepository(session).iterate(filters, sort="played_asc", limit=limit)
            return "\n\n".join(g.pgn.strip() for g in games) + ("\n" if games else "")

    # Deleting games invalidates the "this archive month is fully imported"
    # validators, otherwise a refresh could skip re-importing deleted games.
    @staticmethod
    def _forget_validators(session: Any) -> None:
        session.execute(delete(HttpCacheEntry))

    def delete(self, game_id: int) -> None:
        with self.db.session() as session:
            if not GameRepository(session).delete(game_id):
                raise NotFoundError("Game not found.")
            self._forget_validators(session)

    def delete_many(self, ids: list[int]) -> int:
        with self.db.session() as session:
            deleted = GameRepository(session).delete_many(ids)
            if deleted:
                self._forget_validators(session)
            return deleted

    def delete_all(self) -> int:
        with self.db.session() as session:
            deleted = GameRepository(session).delete_all()
            self._forget_validators(session)
            return deleted

    def owners(self) -> list[dict[str, Any]]:
        with self.db.session() as session:
            return [{"source": s, "username": o, "games": c} for s, o, c in GameRepository(session).owners()]
