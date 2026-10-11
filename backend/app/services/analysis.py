"""AnalysisService: interactive analysis, engine play and engine comparison.

Every search gets an explicit time cap derived from server settings, even when
the caller asks only for a depth, so no request can keep an engine busy forever.
"""

from __future__ import annotations

import logging
from typing import Any

import chess

from app.core.config import Settings
from app.core.errors import ConflictError, EngineUnavailableError, InvalidInputError

from .engine.base import UpdateCallback
from .engine.custom import CUSTOM_LEVELS
from .engine.manager import EngineManager, SearchPreemptedError
from .engine.runtime import StopSignal
from .engine.stockfish import STOCKFISH_LEVELS
from .engine.types import AnalysisSnapshot, SearchLimits

log = logging.getLogger("chesslab.analysis")


class AnalysisService:
    def __init__(self, manager: EngineManager, settings: Settings) -> None:
        self.manager = manager
        self.settings = settings

    # ---------------------------------------------------------------- limits
    def limits(
        self, depth: int | None, movetime_ms: int | None, nodes: int | None = None, *, live: bool
    ) -> SearchLimits:
        cap_ms = int((self.settings.max_live_analysis_seconds if live else self.settings.max_analysis_seconds) * 1000)
        if depth is not None and depth > self.settings.max_search_depth:
            raise InvalidInputError(f"Depth must be at most {self.settings.max_search_depth}.", code="limit_too_high")
        if movetime_ms is not None and movetime_ms > cap_ms:
            raise InvalidInputError(f"Time limit must be at most {cap_ms // 1000} seconds.", code="limit_too_high")
        return SearchLimits(depth=depth, movetime_ms=movetime_ms or cap_ms, nodes=nodes)

    def multipv(self, requested: int | None) -> int:
        value = requested or self.manager.engine_settings.analysis_multipv
        if not 1 <= value <= self.settings.max_multipv:
            raise InvalidInputError(
                f"Candidate lines must be between 1 and {self.settings.max_multipv}.", code="invalid_multipv"
            )
        return value

    # -------------------------------------------------------------- analysis
    async def analyse(
        self,
        board: chess.Board,
        engine_id: str | None,
        limits: SearchLimits,
        multipv: int,
        *,
        on_update: UpdateCallback | None = None,
        stop: StopSignal | None = None,
    ) -> AnalysisSnapshot:
        slot = self.manager.slot(self.manager.resolve_engine_id(engine_id))
        try:
            async with slot.use(preempt=True, stop=stop) as lease:
                return await lease.analyse(board, limits, multipv=multipv, on_update=on_update)
        except SearchPreemptedError as exc:
            raise ConflictError("Superseded by a newer analysis request.", code="superseded") from exc

    # ------------------------------------------------------------------ play
    @staticmethod
    def levels() -> dict[str, list[dict[str, Any]]]:
        def fmt(table: dict[int, dict[str, object]]) -> list[dict[str, Any]]:
            return [{"level": level, "label": spec["label"]} for level, spec in table.items()]

        return {"stockfish": fmt(STOCKFISH_LEVELS), "custom": fmt(CUSTOM_LEVELS)}

    async def best_move(
        self,
        board: chess.Board,
        engine_id: str | None,
        *,
        level: int | None = None,
        depth: int | None = None,
        movetime_ms: int | None = None,
    ) -> AnalysisSnapshot:
        if board.is_game_over():
            raise InvalidInputError("The game is already over in this position.", code="game_over")
        engine_id = self.manager.resolve_engine_id(engine_id)
        options: dict[str, Any] = {}
        if level is not None:
            table = STOCKFISH_LEVELS if engine_id == "stockfish" else CUSTOM_LEVELS
            spec = table.get(level)
            if spec is None:
                raise InvalidInputError(f"Unknown level {level} for this engine.", code="invalid_level")
            depth = spec.get("depth")  # type: ignore[assignment]
            movetime_ms = spec.get("movetime_ms")  # type: ignore[assignment]
            options = dict(spec.get("options", {}))  # type: ignore[call-overload]
        limits = self.limits(depth, movetime_ms, live=False)
        slot = self.manager.slot(engine_id)
        try:
            async with slot.use(preempt=True) as lease:
                return await lease.play(board, limits, options=options)
        except SearchPreemptedError as exc:
            raise ConflictError("Superseded by a newer request.", code="superseded") from exc

    # --------------------------------------------------------------- compare
    async def compare(
        self, board: chess.Board, engine_ids: list[str], limits: SearchLimits, multipv: int
    ) -> list[dict[str, Any]]:
        """Run each engine on the same position with the same limits.

        Engines run one after the other (not in parallel) so neither competes
        with the other for CPU, which would distort speed and depth figures.
        """
        results: list[dict[str, Any]] = []
        for engine_id in engine_ids:
            try:
                snapshot = await self.analyse(board, engine_id, limits, multipv)
                results.append({"engine_id": engine_id, "snapshot": snapshot, "error": None})
            except (EngineUnavailableError, ConflictError) as exc:
                results.append({"engine_id": engine_id, "snapshot": None, "error": exc.message})
        return results
