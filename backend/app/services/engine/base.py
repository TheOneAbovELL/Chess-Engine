"""The engine interface every chess engine implementation provides.

Implementations:

* :class:`app.services.engine.stockfish.StockfishEngine` - the reference engine
* :class:`app.services.engine.custom.CustomChessEngine` - ChessLab's own engine

Both happen to speak UCI and share :class:`app.services.engine.uci.UciEngine`,
but callers depend only on this interface, so an in-process or remote engine
could be added without touching analysis, play or review code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping

import chess

from .runtime import StopSignal
from .types import AnalysisSnapshot, EngineCapabilities, SearchLimits

ConfigValue = str | int | bool | None
UpdateCallback = Callable[[AnalysisSnapshot], None]


class ChessEngine(ABC):
    engine_id: str
    display_name: str

    @property
    @abstractmethod
    def is_running(self) -> bool: ...

    @property
    @abstractmethod
    def identity(self) -> tuple[str | None, str | None]:
        """(name, author) as reported by the engine, once started."""

    @abstractmethod
    def capabilities(self) -> EngineCapabilities: ...

    @abstractmethod
    async def start(self) -> None:
        """Start the engine (idempotent). Raises EngineUnavailableError."""

    @abstractmethod
    async def close(self) -> None:
        """Stop the engine process and release resources (idempotent)."""

    @abstractmethod
    async def configure(self, options: Mapping[str, ConfigValue]) -> None:
        """Persistently change engine options (e.g. threads, hash)."""

    @abstractmethod
    async def analyse(
        self,
        board: chess.Board,
        limits: SearchLimits,
        *,
        multipv: int = 1,
        on_update: UpdateCallback | None = None,
        stop: StopSignal | None = None,
    ) -> AnalysisSnapshot:
        """Analyse ``board`` (with its move history) within ``limits``.

        ``on_update`` receives intermediate snapshots on the caller's event
        loop. ``stop`` ends the search early; the returned snapshot is the last
        one the engine reported, with ``final=True``.
        """

    @abstractmethod
    async def play(
        self, board: chess.Board, limits: SearchLimits, *, options: Mapping[str, ConfigValue] | None = None
    ) -> AnalysisSnapshot:
        """Choose a move to play. ``options`` apply to this search only (e.g.
        strength limiting) and are reverted afterwards."""
