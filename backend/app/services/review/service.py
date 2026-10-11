"""GameReviewService: analyse every position of a game in the background.

* One review runs at a time on a dedicated engine process (bounded CPU).
* Results are stored position by position, so a review interrupted by a
  restart or crash resumes where it stopped instead of starting over.
* Each position is searched with the same limits (depth, with a per-position
  time cap) so evaluations are comparable within the game.
* Classifications are derived from stored evaluations and can be recomputed
  with new thresholds without re-running the engine.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from datetime import timedelta
from typing import Any

import chess
import chess.pgn
from sqlalchemy import func, select, update

from app.core.config import Settings
from app.core.errors import (
    ConflictError,
    EngineUnavailableError,
    InvalidInputError,
    NotFoundError,
    RateLimitedError,
)
from app.db.base import utcnow
from app.db.session import Database
from app.jobs.worker import BackgroundWorker, claim, requeue_stale, touch
from app.models import Game, GameReview, PositionEvaluation
from app.models.jobs import ACTIVE_STATUSES, CANCELLED, COMPLETED, FAILED, QUEUED, RUNNING
from app.services.chess.pgn import parse_single_game
from app.services.chess.positions import terminal_reason
from app.services.chess.scoring import terminal_evaluation
from app.services.engine.manager import EngineManager, SearchPreemptedError
from app.services.engine.types import AnalysisSnapshot, Evaluation, SearchLimits
from app.services.settings_store import ClassificationThresholds, SettingsStore

from .classification import MoveVerdict, classify_move, summarize

log = logging.getLogger("chesslab.review")
MAX_ATTEMPTS = 3
MAX_REVIEW_PLIES = 600


def review_to_dict(review: GameReview, *, with_positions: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": review.id,
        "game_id": review.game_id,
        "status": review.status,
        "engine_id": review.engine_id,
        "engine_name": review.engine_name,
        "settings": review.settings,
        "thresholds": review.thresholds,
        "progress_done": review.progress_done,
        "progress_total": review.progress_total,
        "error": review.error,
        "summary": review.summary,
        "created_at": review.created_at,
        "started_at": review.started_at,
        "finished_at": review.finished_at,
    }
    if with_positions:
        data["positions"] = [position_to_dict(p) for p in review.positions]
    return data


def position_to_dict(p: PositionEvaluation) -> dict[str, Any]:
    return {
        "ply": p.ply,
        "fen": p.fen,
        "eval": {"cp": p.cp, "mate": p.mate},
        "depth": p.depth,
        "nodes": p.nodes,
        "best_move_uci": p.best_move_uci,
        "best_move_san": p.best_move_san,
        "lines": p.lines,
        "terminal": p.terminal,
        "move_uci": p.move_uci,
        "move_san": p.move_san,
        "classification": p.classification,
        "cp_loss": p.cp_loss,
        "win_loss": p.win_loss,
        "clock_s": p.clock_s,
    }


class GameReviewService(BackgroundWorker[int]):
    """Review jobs. Each review worker owns one engine process; run several
    (``review_workers``) to review games in parallel on a bigger machine."""

    name = "review-worker"
    kind = "reviews"
    poll_interval_s = 3.0

    def __init__(
        self, db: Database, settings: Settings, manager: EngineManager, store: SettingsStore, index: int = 0
    ) -> None:
        super().__init__(db, settings.job_stale_after_s, index)
        self.settings = settings
        self.manager = manager
        self.store = store

    def _check_quotas(self, session: Any, user_id: int, new: int = 1) -> None:
        queued = session.execute(
            select(func.count(GameReview.id)).where(
                GameReview.user_id == user_id, GameReview.status.in_(ACTIVE_STATUSES)
            )
        ).scalar_one()
        if queued + new > self.settings.max_queued_reviews_per_user:
            raise ConflictError(
                f"You can have at most {self.settings.max_queued_reviews_per_user} reviews waiting.",
                code="review_queue_full",
            )
        if self.settings.max_reviews_per_day is not None:
            since = utcnow() - timedelta(days=1)
            today = session.execute(
                select(func.count(GameReview.id)).where(GameReview.user_id == user_id, GameReview.created_at >= since)
            ).scalar_one()
            if today + new > self.settings.max_reviews_per_day:
                raise RateLimitedError(
                    f"Daily review limit reached ({self.settings.max_reviews_per_day} per 24 hours). Try again later.",
                    code="review_quota",
                )

    # -------------------------------------------------------------- enqueue
    def enqueue(
        self,
        user_id: int,
        game_id: int,
        *,
        engine_id: str | None = None,
        depth: int | None = None,
        movetime_ms: int | None = None,
        multipv: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        es = self.manager.engine_settings
        engine_id = self.manager.resolve_engine_id(engine_id or es.review_engine)
        depth = depth or es.review_depth
        movetime_ms = movetime_ms or es.review_movetime_ms
        multipv = multipv or es.review_multipv
        if movetime_ms > self.settings.max_review_movetime_ms:
            raise InvalidInputError(f"Time per position must be at most {self.settings.max_review_movetime_ms} ms.")
        if depth > self.settings.max_search_depth:
            raise InvalidInputError(f"Depth must be at most {self.settings.max_search_depth}.")
        with self.db.session() as session:
            game = session.get(Game, game_id)
            if game is None or game.user_id != user_id:
                raise NotFoundError("Game not found.")
            if game.ply_count > MAX_REVIEW_PLIES:
                raise InvalidInputError("This game is too long to review.", code="game_too_long")
            existing = session.execute(
                select(GameReview).where(GameReview.game_id == game_id).order_by(GameReview.id.desc()).limit(1)
            ).scalar_one_or_none()
            if existing is not None and existing.status in ACTIVE_STATUSES:
                return review_to_dict(existing)
            if existing is not None and existing.status == COMPLETED and not force:
                same = existing.engine_id == engine_id and existing.settings.get("depth") == depth
                if same:
                    return review_to_dict(existing)
            self._check_quotas(session, user_id)
            review = GameReview(
                game_id=game_id,
                user_id=user_id,
                status=QUEUED,
                engine_id=engine_id,
                settings={"depth": depth, "movetime_ms": movetime_ms, "multipv": multipv},
                thresholds=self.store.thresholds(user_id).model_dump(),
                progress_total=game.ply_count + 1,
            )
            session.add(review)
            session.flush()
            result = review_to_dict(review)
        self.notify()
        return result

    def enqueue_many(self, user_id: int, game_ids: list[int], **kwargs: Any) -> list[dict[str, Any]]:
        if len(game_ids) > self.settings.max_batch_review_games:
            raise InvalidInputError(f"At most {self.settings.max_batch_review_games} games per batch.")
        results = []
        for game_id in game_ids:
            try:
                results.append(self.enqueue(user_id, game_id, **kwargs))
            except (NotFoundError, InvalidInputError, ConflictError, RateLimitedError) as exc:
                results.append({"game_id": game_id, "error": exc.message})
        return results

    # --------------------------------------------------------------- queries
    @staticmethod
    def _owned(session: Any, user_id: int, review_id: int) -> GameReview:
        review = session.get(GameReview, review_id)
        if review is None or review.user_id != user_id:
            raise NotFoundError("Review not found.")
        return review  # type: ignore[no-any-return]

    def get(self, user_id: int, review_id: int, *, with_positions: bool = False) -> dict[str, Any]:
        with self.db.session() as session:
            return review_to_dict(self._owned(session, user_id, review_id), with_positions=with_positions)

    def latest_for_game(self, user_id: int, game_id: int) -> dict[str, Any] | None:
        with self.db.session() as session:
            review = session.execute(
                select(GameReview)
                .where(GameReview.game_id == game_id, GameReview.user_id == user_id)
                .order_by(GameReview.id.desc())
                .limit(1)
            ).scalar_one_or_none()
            return review_to_dict(review, with_positions=True) if review else None

    def queue(self, user_id: int) -> list[dict[str, Any]]:
        with self.db.session() as session:
            rows = session.execute(
                select(GameReview, Game.white, Game.black)
                .join(Game, Game.id == GameReview.game_id)
                .where(GameReview.status.in_(ACTIVE_STATUSES), GameReview.user_id == user_id)
                .order_by(GameReview.id.asc())
            ).all()
            return [{**review_to_dict(r), "white": w, "black": b} for r, w, b in rows]

    def cancel(self, user_id: int, review_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            review = self._owned(session, user_id, review_id)
            if review.status == QUEUED:
                review.status, review.finished_at = CANCELLED, utcnow()
            elif review.status == RUNNING:
                review.cancel_requested = True
            return review_to_dict(review)

    def retry(self, user_id: int, review_id: int) -> dict[str, Any]:
        with self.db.session() as session:
            review = self._owned(session, user_id, review_id)
            if review.status in ACTIVE_STATUSES:
                raise ConflictError("This review is still in progress.")
            if review.status == COMPLETED:
                return review_to_dict(review)
            review.status, review.error, review.cancel_requested, review.attempts = QUEUED, None, False, 0
            result = review_to_dict(review)
        self.notify()
        return result

    def reclassify(self, user_id: int, review_id: int) -> dict[str, Any]:
        """Re-label moves with the current thresholds (no engine work)."""
        thresholds = self.store.thresholds(user_id)
        with self.db.session() as session:
            review = self._owned(session, user_id, review_id)
            if review.status != COMPLETED:
                raise ConflictError("Only completed reviews can be reclassified.")
            review.thresholds = thresholds.model_dump()
            self._classify(session, review, thresholds)
            return review_to_dict(review, with_positions=True)

    # --------------------------------------------------------------- worker
    def requeue(self) -> None:
        requeue_stale(self.db, GameReview, self.stale_after_s)

    def claim_next(self) -> int | None:
        job = claim(self.db, GameReview, GameReview.id, self.worker_id)
        return int(job) if job is not None else None

    def touch_job(self, job: int) -> None:
        touch(self.db, GameReview, job, self.worker_id)

    def mark_crashed(self, job: int) -> None:
        with self.db.session() as session:
            review = session.get(GameReview, job)
            if review is not None:
                review.status, review.finished_at = FAILED, utcnow()
                review.error = "The review stopped because of an unexpected error. Retry to resume."

    def _load(self, review_id: int) -> tuple[GameReview, Game, set[int]] | None:
        with self.db.session() as session:
            review = session.get(GameReview, review_id)
            if review is None:
                return None
            game = session.get(Game, review.game_id)
            if game is None:
                return None
            done = set(
                session.execute(
                    select(PositionEvaluation.ply).where(PositionEvaluation.review_id == review_id)
                ).scalars()
            )
            session.expunge(review)
            session.expunge(game)
            return review, game, done

    def _cancel_requested(self, review_id: int) -> bool:
        with self.db.session() as session:
            review = session.get(GameReview, review_id)
            return review is None or review.cancel_requested

    async def process(self, job: int) -> None:
        loaded = await asyncio.to_thread(self._load, job)
        if loaded is None:
            return
        review, game, done = loaded
        try:
            parsed, _ = parse_single_game(game.pgn)
        except Exception:
            await asyncio.to_thread(self._fail, job, "The stored PGN could not be parsed.")
            return

        board = parsed.board()
        positions: list[tuple[int, chess.Board, chess.Move | None, float | None]] = [(0, board.copy(), None, None)]
        for ply, node in enumerate(parsed.mainline(), start=1):
            board.push(node.move)
            positions.append((ply, board.copy(), node.move, node.clock()))

        settings = review.settings
        limits = SearchLimits(depth=int(settings["depth"]), movetime_ms=int(settings["movetime_ms"]))
        multipv = int(settings.get("multipv", 1))
        try:
            slot = self.manager.slot(review.engine_id, "review", self.index)
        except EngineUnavailableError as exc:
            await asyncio.to_thread(self._fail, job, exc.message)
            return

        log.info("review started", extra={"review": job, "game": game.id, "plies": len(positions) - 1})
        for ply, position, move, clock in positions:
            if ply in done:
                continue
            if await asyncio.to_thread(self._cancel_requested, job):
                await asyncio.to_thread(self._set_status, job, CANCELLED)
                return
            reason = terminal_reason(position)
            snapshot: AnalysisSnapshot | None = None
            if reason is None:
                try:
                    async with slot.use(preempt=False) as lease:
                        snapshot = await lease.analyse(position, limits, multipv=multipv)
                except (EngineUnavailableError, SearchPreemptedError) as exc:
                    message = exc.message if isinstance(exc, EngineUnavailableError) else "Engine was busy."
                    log.warning("review engine error", extra={"review": job, "ply": ply})
                    if review.attempts < MAX_ATTEMPTS:
                        await asyncio.to_thread(self._set_status, job, QUEUED)  # resume from this ply
                    else:
                        await asyncio.to_thread(self._fail, job, message)
                    return
            prev_board = positions[ply - 1][1] if ply > 0 else None
            await asyncio.to_thread(self._store_position, job, ply, position, prev_board, move, clock, snapshot, reason)

        await asyncio.to_thread(self._complete, job)
        log.info("review completed", extra={"review": job, "game": game.id})

    # ------------------------------------------------------------- storage
    def _store_position(
        self,
        review_id: int,
        ply: int,
        board: chess.Board,
        prev_board: chess.Board | None,
        move: chess.Move | None,
        clock: float | None,
        snapshot: AnalysisSnapshot | None,
        terminal: str | None,
    ) -> None:
        depth: int | None = None
        nodes: int | None = None
        if snapshot is not None and snapshot.lines:
            top = snapshot.lines[0]
            evaluation = top.score
            depth, nodes = top.depth, snapshot.nodes
            lines = [
                {
                    "multipv": line.multipv,
                    "eval": line.score.model_dump(),
                    "depth": line.depth,
                    "pv": line.pv[:10],
                    "pv_san": line.pv_san[:10],
                }
                for line in snapshot.lines
            ]
            best_uci, best_san = snapshot.best_move, snapshot.best_move_san
        else:
            evaluation = terminal_evaluation(board) if terminal else Evaluation(cp=0)
            lines = []
            best_uci = best_san = None
        row = PositionEvaluation(
            review_id=review_id,
            ply=ply,
            fen=board.fen(),
            cp=evaluation.cp,
            mate=evaluation.mate,
            depth=depth,
            nodes=nodes,
            best_move_uci=best_uci,
            best_move_san=best_san,
            lines=lines,
            terminal=terminal,
            move_uci=move.uci() if move else None,
            move_san=prev_board.san(move) if (move and prev_board is not None) else None,
            clock_s=clock,
        )
        with self.db.session() as session:
            existing = session.execute(
                select(PositionEvaluation).where(
                    PositionEvaluation.review_id == review_id, PositionEvaluation.ply == ply
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(row)
            session.execute(
                update(GameReview)
                .where(GameReview.id == review_id)
                .values(progress_done=GameReview.progress_done + (existing is None))
            )

    def _classify(self, session: Any, review: GameReview, thresholds: ClassificationThresholds) -> None:
        positions = sorted(review.positions, key=lambda p: p.ply)
        verdicts: list[tuple[chess.Color, MoveVerdict]] = []
        for prev, cur in itertools.pairwise(positions):
            if cur.move_uci is None:
                continue
            board = chess.Board(prev.fen)
            mover = board.turn
            verdict = classify_move(
                Evaluation(cp=prev.cp, mate=prev.mate),
                Evaluation(cp=cur.cp, mate=cur.mate),
                mover,
                played_uci=cur.move_uci,
                best_uci=prev.best_move_uci,
                legal_move_count=board.legal_moves.count(),
                thresholds=thresholds,
            )
            cur.classification, cur.win_loss, cur.cp_loss = verdict.classification, verdict.win_loss, verdict.cp_loss
            verdicts.append((mover, verdict))
        review.summary = summarize(verdicts)

    def _complete(self, review_id: int) -> None:
        with self.db.session() as session:
            review = session.get(GameReview, review_id)
            if review is None:
                return
            thresholds = self.store.thresholds(review.user_id)
            review.thresholds = thresholds.model_dump()
            self._classify(session, review, thresholds)
            review.status, review.finished_at, review.error = COMPLETED, utcnow(), None
            review.engine_name = (
                self.manager.slot(review.engine_id, "review", self.index).engine.identity[0] or review.engine_id
            )
            review.progress_done = len(review.positions)

    def _set_status(self, review_id: int, status: str) -> None:
        with self.db.session() as session:
            values: dict[str, Any] = {"status": status}
            if status in (CANCELLED, FAILED):
                values["finished_at"] = utcnow()
            session.execute(update(GameReview).where(GameReview.id == review_id).values(**values))

    def _fail(self, review_id: int, message: str) -> None:
        with self.db.session() as session:
            session.execute(
                update(GameReview)
                .where(GameReview.id == review_id)
                .values(status=FAILED, error=message, finished_at=utcnow())
            )
