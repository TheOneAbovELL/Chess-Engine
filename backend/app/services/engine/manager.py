"""EngineManager: a bounded, well-defined engine process lifecycle.

Resource model
--------------
Engine processes live in *slots* keyed by (engine, purpose, index):

* interactive pool per engine: ``interactive_engine_pool`` processes (default 1)
  for live analysis, play and comparisons;
* one review process per review worker (``review_workers``, default 1).

The number of processes is therefore fixed by configuration, never by load.
Each slot serialises work with a lock. In the interactive pool every user
holds at most one engine: a user's new request *preempts their own* previous
search (so clicking through positions never queues stale searches), while
requests from other users wait for a free engine, fairly and with a timeout.

Processes start lazily, are restarted automatically after a crash, and are shut
down after ``engine_idle_shutdown_s`` of inactivity to free memory.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Literal

import chess

from app.core.config import Settings
from app.core.errors import EngineUnavailableError, InvalidInputError
from app.services.settings_store import EngineSettings

from .base import ChessEngine, ConfigValue, UpdateCallback
from .custom import CustomChessEngine, custom_engine_installed
from .runtime import EngineRuntime, StopSignal
from .stockfish import StockfishEngine, discover_stockfish
from .types import ENGINE_IDS, AnalysisSnapshot, EngineCapabilities, EngineDescriptor, SearchLimits

Purpose = Literal["interactive", "review"]
SlotKey = tuple[str, Purpose, int]


class SearchPreemptedError(Exception):
    """A newer request took over the engine before this one started."""


class EngineBusyError(EngineUnavailableError):
    code = "engine_busy"


log = logging.getLogger("chesslab.engine")


class EngineLease:
    """Exclusive use of a slot's engine. The lease's ``stop`` signal is wired
    into every search it runs, so preempting the slot stops that search."""

    def __init__(self, engine: ChessEngine, stop: StopSignal) -> None:
        self.engine = engine
        self.stop = stop

    async def analyse(
        self,
        board: chess.Board,
        limits: SearchLimits,
        *,
        multipv: int = 1,
        on_update: UpdateCallback | None = None,
    ) -> AnalysisSnapshot:
        return await self.engine.analyse(board, limits, multipv=multipv, on_update=on_update, stop=self.stop)

    async def play(
        self, board: chess.Board, limits: SearchLimits, *, options: Mapping[str, ConfigValue] | None = None
    ) -> AnalysisSnapshot:
        return await self.engine.play(board, limits, options=options)


class EngineSlot:
    def __init__(self, engine: ChessEngine) -> None:
        self.engine = engine
        self.lock = asyncio.Lock()
        self.current_stop: StopSignal | None = None
        self.last_used = time.monotonic()
        self.busy = False

    @contextlib.asynccontextmanager
    async def use(self, *, preempt: bool, stop: StopSignal | None = None) -> AsyncIterator[EngineLease]:
        """Acquire the engine. With ``preempt`` the search currently holding the
        slot is asked to stop first, so the newest request wins quickly."""
        if preempt and self.current_stop is not None:
            self.current_stop.request()
        stop = stop or StopSignal()
        async with self.lock:
            if stop.requested:  # preempted while waiting for the lock
                raise SearchPreemptedError
            self.current_stop = stop
            self.busy = True
            try:
                await self.engine.start()
                yield EngineLease(self.engine, stop)
            finally:
                self.busy = False
                self.current_stop = None
                self.last_used = time.monotonic()


class EnginePool:
    """A fixed set of interactive engine slots shared fairly between users."""

    def __init__(self, slots: list[EngineSlot], timeout_s: float) -> None:
        self.slots = slots
        self.timeout_s = timeout_s
        self._cond = asyncio.Condition()
        self._holders: dict[int, tuple[object, StopSignal]] = {}

    @property
    def in_use(self) -> int:
        return len(self._holders)

    def _held_by(self, owner: object) -> int | None:
        return next((i for i, (o, _s) in self._holders.items() if o == owner), None)

    def stop(self, owner: object) -> bool:
        """Stop this owner's running search (never anyone else's)."""
        index = self._held_by(owner)
        if index is None:
            return False
        self._holders[index][1].request()
        return True

    def _free(self) -> int | None:
        return next((i for i in range(len(self.slots)) if i not in self._holders), None)

    @contextlib.asynccontextmanager
    async def use(self, owner: object, stop: StopSignal | None = None) -> AsyncIterator[EngineLease]:
        stop = stop or StopSignal()
        async with self._cond:
            index = self._held_by(owner)
            if index is not None:
                # Same user again: stop their previous search and take its engine.
                self._holders[index][1].request()
                current = self.slots[index].current_stop
                if current is not None:
                    current.request()
            else:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + self.timeout_s
                while (index := self._free()) is None:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise EngineBusyError(
                            "All engines are busy right now. Try again in a moment, or use the in-browser engine."
                        )
                    try:
                        await asyncio.wait_for(self._cond.wait(), remaining)
                    except TimeoutError:
                        continue
            self._holders[index] = (owner, stop)
        try:
            async with self.slots[index].use(preempt=False, stop=stop) as lease:
                yield lease
        finally:
            async with self._cond:
                held = self._holders.get(index)
                if held is not None and held[1] is stop:
                    del self._holders[index]
                self._cond.notify_all()


class EngineManager:
    def __init__(self, settings: Settings, runtime: EngineRuntime, engine_settings: EngineSettings) -> None:
        self.settings = settings
        self.runtime = runtime
        self.engine_settings = engine_settings
        self.stockfish_path: Path | None = discover_stockfish(settings)
        self.custom_available = settings.custom_engine_enabled and custom_engine_installed()
        self._slots: dict[SlotKey, EngineSlot] = {}
        self._pools: dict[str, EnginePool] = {}
        self._reaper: asyncio.Task[None] | None = None
        if self.stockfish_path is None:
            log.warning("Stockfish not found; set CHESSLAB_STOCKFISH_PATH or run scripts/install_stockfish.ps1")

    # ------------------------------------------------------------ discovery
    def is_available(self, engine_id: str) -> bool:
        if engine_id == "stockfish":
            return self.stockfish_path is not None
        if engine_id == "custom":
            return self.custom_available
        return False

    def unavailable_reason(self, engine_id: str) -> str | None:
        if engine_id == "stockfish" and self.stockfish_path is None:
            return (
                "Stockfish executable not found. Install it with scripts/install_stockfish.ps1, "
                "put it on PATH, or set CHESSLAB_STOCKFISH_PATH in .env, then restart."
            )
        if engine_id == "custom" and not self.custom_available:
            return "The ChessLab engine package is not installed (pip install -e engine-lab)."
        return None

    def resolve_engine_id(self, requested: str | None) -> str:
        engine_id = requested or self.engine_settings.default_engine
        if engine_id not in ENGINE_IDS:
            raise InvalidInputError(f"Unknown engine '{engine_id}'.", code="unknown_engine")
        if not self.is_available(engine_id):
            raise EngineUnavailableError(self.unavailable_reason(engine_id) or "Engine unavailable.")
        return engine_id

    # ------------------------------------------------------------- creation
    def _options_for(self, engine_id: str, purpose: Purpose) -> dict[str, int]:
        s = self.engine_settings
        if engine_id == "stockfish":
            if purpose == "review":
                return {"Threads": s.review_threads, "Hash": min(256, s.stockfish_hash_mb)}
            return {"Threads": s.stockfish_threads, "Hash": s.stockfish_hash_mb}
        return {"Hash": s.custom_hash_mb}

    def _create(self, engine_id: str, purpose: Purpose) -> ChessEngine:
        options = self._options_for(engine_id, purpose)
        timeout = self.settings.engine_start_timeout_s
        low = self.settings.engine_low_priority
        if engine_id == "stockfish":
            assert self.stockfish_path is not None
            return StockfishEngine(
                self.stockfish_path,
                self.runtime,
                threads=options["Threads"],
                hash_mb=options["Hash"],
                start_timeout_s=timeout,
                low_priority=low,
            )
        return CustomChessEngine(self.runtime, hash_mb=options["Hash"], start_timeout_s=timeout, low_priority=low)

    def slot(self, engine_id: str, purpose: Purpose = "interactive", index: int = 0) -> EngineSlot:
        engine_id = self.resolve_engine_id(engine_id)
        key: SlotKey = (engine_id, purpose, index)
        if key not in self._slots:
            if purpose == "review":
                # One review process per review worker, whichever engine it uses.
                for other in [k for k in self._slots if k[1] == "review" and k[2] == index and k[0] != engine_id]:
                    old = self._slots.pop(other)
                    asyncio.get_running_loop().create_task(self._close_slot(old))
            self._slots[key] = EngineSlot(self._create(engine_id, purpose))
        return self._slots[key]

    def pool(self, engine_id: str) -> EnginePool:
        engine_id = self.resolve_engine_id(engine_id)
        if engine_id not in self._pools:
            size = self.settings.interactive_engine_pool
            slots = [self.slot(engine_id, "interactive", i) for i in range(size)]
            self._pools[engine_id] = EnginePool(slots, self.settings.engine_queue_timeout_s)
        return self._pools[engine_id]

    def pools(self) -> dict[str, EnginePool]:
        return dict(self._pools)

    async def _close_slot(self, slot: EngineSlot) -> None:
        async with slot.lock:
            await slot.engine.close()

    # ------------------------------------------------------------- settings
    async def apply_settings(self, new: EngineSettings) -> None:
        self.engine_settings = new
        for (engine_id, purpose, _index), slot in list(self._slots.items()):
            options = self._options_for(engine_id, purpose)
            if slot.current_stop is not None:
                slot.current_stop.request()
            async with slot.lock:
                await slot.engine.configure(options)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._reaper = asyncio.get_running_loop().create_task(self._reap_idle())

    async def _reap_idle(self) -> None:
        interval = min(60.0, self.settings.engine_idle_shutdown_s / 2)
        while True:
            await asyncio.sleep(interval)
            now = time.monotonic()
            for slot in list(self._slots.values()):
                if (
                    slot.engine.is_running
                    and not slot.busy
                    and not slot.lock.locked()
                    and now - slot.last_used > self.settings.engine_idle_shutdown_s
                ):
                    log.info("stopping idle engine", extra={"engine": slot.engine.engine_id})
                    await self._close_slot(slot)

    async def shutdown(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reaper
        for slot in self._slots.values():
            if slot.current_stop is not None:
                slot.current_stop.request()
        for slot in self._slots.values():
            try:
                await asyncio.wait_for(self._close_slot(slot), timeout=10)
            except Exception:
                log.exception("error stopping engine", extra={"engine": slot.engine.engine_id})
        self._slots.clear()
        self._pools.clear()

    # ------------------------------------------------------------- describe
    def describe(self) -> list[EngineDescriptor]:
        result = []
        for engine_id in ENGINE_IDS:
            available = self.is_available(engine_id)
            slot = self._slots.get((engine_id, "interactive", 0))
            engine = slot.engine if slot else None
            status: str
            if not available:
                status = "unavailable"
            elif engine is None or not engine.is_running:
                status = "error" if engine is not None and getattr(engine, "last_error", None) else "stopped"
            else:
                status = "busy" if slot and slot.busy else "ready"
            name, author = engine.identity if engine else (None, None)
            caps = (
                engine.capabilities()
                if engine
                else EngineCapabilities(
                    limit_strength=engine_id == "stockfish",
                    threads=engine_id == "stockfish",
                    eval_breakdown=engine_id == "custom",
                )
            )
            caps.max_multipv = self.settings.max_multipv
            result.append(
                EngineDescriptor(
                    id=engine_id,
                    display_name="Stockfish" if engine_id == "stockfish" else "ChessLab Engine",
                    available=available,
                    status=status,  # type: ignore[arg-type]
                    name=name,
                    author=author,
                    detail=self.unavailable_reason(engine_id)
                    or (getattr(engine, "last_error", None) if engine else None),
                    capabilities=caps,
                )
            )
        return result
