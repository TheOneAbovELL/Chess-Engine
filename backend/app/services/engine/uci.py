"""Generic UCI engine adapter built on python-chess's asyncio UCI protocol.

Process handling is always argument-list based (no shell), the executable is
chosen from server configuration only, and every command runs with a timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import sys
import time
from collections.abc import Mapping
from typing import Any

import chess
import chess.engine

from app.core.errors import EngineUnavailableError
from app.services.chess.positions import pv_to_san, terminal_reason
from app.services.chess.scoring import from_pov_score

from .base import ChessEngine, ConfigValue, UpdateCallback
from .runtime import EngineRuntime, StopSignal
from .types import AnalysisSnapshot, EngineCapabilities, EngineLine, SearchLimits

log = logging.getLogger("chesslab.engine")
EMIT_INTERVAL_S = 0.12  # throttle intermediate updates to ~8 per second
MANAGED = {"multipv", "ponder", "uci_analysemode", "uci_chess960"}


def _popen_kwargs(low_priority: bool) -> dict[str, Any]:
    if sys.platform == "win32":
        # No console window. Optionally below-normal priority (see Settings.engine_low_priority).
        flags = subprocess.CREATE_NO_WINDOW
        if low_priority:
            flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return {"creationflags": flags}
    return {}


def _safe_kill(transport: asyncio.SubprocessTransport) -> None:
    """Kill an engine process; it may already have exited."""
    with contextlib.suppress(ProcessLookupError, OSError):
        transport.kill()


def to_limit(limits: SearchLimits) -> chess.engine.Limit:
    return chess.engine.Limit(
        depth=limits.depth,
        time=limits.movetime_ms / 1000 if limits.movetime_ms else None,
        nodes=limits.nodes,
    )


class SnapshotBuilder:
    """Accumulates UCI ``info`` dictionaries into a normalised snapshot.

    Only *completed* iterations are published: with MultiPV the engine reports
    lines 1..k for a depth one after another, and mixing line 1 of depth N with
    line 2 of depth N-1 can show two lines starting with the same move. So
    lines are collected per depth, and the snapshot shows the deepest depth for
    which every expected line has arrived (falling back to the best partial
    data only before the first iteration completes).

    Lines flagged ``lowerbound``/``upperbound`` (aspiration-window fail
    highs/lows) are not final results, so they only update statistics.
    """

    def __init__(self, engine_id: str, engine_name: str, board: chess.Board, multipv: int = 1) -> None:
        self.engine_id = engine_id
        self.engine_name = engine_name
        self.board = board
        self.expected = max(1, min(multipv, board.legal_moves.count()))
        self.pending: dict[int, dict[int, EngineLine]] = {}
        self.completed: list[EngineLine] = []
        self.stats: dict[str, int | None] = {}

    def update(self, info: chess.engine.InfoDict) -> bool:
        """Record an info line. Returns True when a new iteration completed."""
        for key in ("nodes", "nps", "hashfull", "seldepth"):
            if key in info:
                self.stats[key] = int(info[key])  # type: ignore[literal-required]
        if "time" in info:
            self.stats["time_ms"] = int(info["time"] * 1000)
        if "pv" not in info or "score" not in info or "depth" not in info:
            return False
        if info.get("lowerbound") or info.get("upperbound"):
            return False
        pv = info["pv"]
        if not pv:
            return False
        multipv = int(info.get("multipv", 1))
        depth = int(info["depth"])
        line = EngineLine(
            multipv=multipv,
            depth=depth,
            seldepth=int(info["seldepth"]) if "seldepth" in info else None,
            score=from_pov_score(info["score"]),
            pv=[m.uci() for m in pv],
            pv_san=pv_to_san(self.board, pv),
        )
        bucket = self.pending.setdefault(depth, {})
        bucket[multipv] = line
        if len(bucket) >= self.expected and all(k in bucket for k in range(1, self.expected + 1)):
            self.completed = [bucket[k] for k in range(1, self.expected + 1)]
            for older in [d for d in self.pending if d <= depth]:
                del self.pending[older]
            return True
        return False

    def _lines(self) -> list[EngineLine]:
        if self.completed:
            return self.completed
        if self.pending:  # nothing complete yet: show the deepest partial iteration
            bucket = self.pending[max(self.pending)]
            return [bucket[k] for k in sorted(bucket)]
        return []

    @property
    def depth(self) -> int:
        lines = self._lines()
        return lines[0].depth if lines else 0

    def snapshot(self, *, final: bool) -> AnalysisSnapshot:
        lines = self._lines()
        return AnalysisSnapshot(
            engine_id=self.engine_id,
            engine_name=self.engine_name,
            fen=self.board.fen(),
            depth=lines[0].depth if lines else 0,
            seldepth=lines[0].seldepth if lines else None,
            nodes=self.stats.get("nodes"),
            nps=self.stats.get("nps"),
            time_ms=self.stats.get("time_ms"),
            hashfull=self.stats.get("hashfull"),
            lines=lines,
            final=final,
        )


class UciEngine(ChessEngine):
    def __init__(
        self,
        engine_id: str,
        display_name: str,
        command: list[str],
        runtime: EngineRuntime,
        *,
        base_options: Mapping[str, ConfigValue] | None = None,
        start_timeout_s: float = 20.0,
        low_priority: bool = False,
    ) -> None:
        self.engine_id = engine_id
        self.display_name = display_name
        self.command = command
        self.runtime = runtime
        self.base_options: dict[str, ConfigValue] = dict(base_options or {})
        self.start_timeout_s = start_timeout_s
        self.low_priority = low_priority
        self._transport: asyncio.SubprocessTransport | None = None
        self._protocol: chess.engine.UciProtocol | None = None
        self._name: str | None = None
        self._author: str | None = None
        self.last_error: str | None = None

    # ------------------------------------------------------------ lifecycle
    @property
    def is_running(self) -> bool:
        protocol = self._protocol
        return protocol is not None and not protocol.returncode.done()

    @property
    def identity(self) -> tuple[str | None, str | None]:
        return self._name, self._author

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities()

    def _filter_options(
        self, protocol: chess.engine.UciProtocol, options: Mapping[str, ConfigValue]
    ) -> dict[str, ConfigValue]:
        """Drop options the engine does not offer and clamp spin values."""
        supported = {name.lower(): opt for name, opt in protocol.options.items()}
        result: dict[str, ConfigValue] = {}
        for name, value in options.items():
            opt = supported.get(name.lower())
            if opt is None or name.lower() in MANAGED or value is None:
                continue
            if opt.type == "spin" and isinstance(value, int) and not isinstance(value, bool):
                if opt.min is not None:
                    value = max(opt.min, value)
                if opt.max is not None:
                    value = min(opt.max, value)
            result[opt.name] = value
        return result

    async def start(self) -> None:
        if self.is_running:
            return
        await self._discard()

        async def _start() -> tuple[asyncio.SubprocessTransport, chess.engine.UciProtocol]:
            transport, protocol = await chess.engine.popen_uci(self.command, **_popen_kwargs(self.low_priority))
            try:
                await protocol.configure(self._filter_options(protocol, self.base_options))
            except Exception:
                transport.kill()
                raise
            return transport, protocol

        started = time.perf_counter()
        try:
            self._transport, self._protocol = await asyncio.wait_for(
                self.runtime.call(_start()), timeout=self.start_timeout_s
            )
        except (OSError, chess.engine.EngineError, TimeoutError) as exc:
            self.last_error = f"{type(exc).__name__}: could not start the engine"
            log.warning("engine failed to start", extra={"engine": self.engine_id, "error": repr(exc)})
            raise EngineUnavailableError(f"{self.display_name} could not be started.") from exc
        protocol = self._protocol
        assert protocol is not None
        self._name = protocol.id.get("name")
        self._author = protocol.id.get("author")
        self.last_error = None
        log.info(
            "engine started",
            extra={
                "engine": self.engine_id,
                "engine_name": self._name,
                "ms": int((time.perf_counter() - started) * 1000),
            },
        )

    async def _discard(self) -> None:
        transport = self._transport
        self._transport = None
        self._protocol = None
        if transport is not None:
            with contextlib.suppress(RuntimeError):  # runtime already stopped
                self.runtime.call_soon(_safe_kill, transport)

    async def close(self) -> None:
        protocol = self._protocol
        if protocol is None:
            return
        try:
            if not protocol.returncode.done():
                await asyncio.wait_for(self.runtime.call(protocol.quit()), timeout=5)
        except Exception:
            log.warning("engine did not quit cleanly; killing", extra={"engine": self.engine_id})
        finally:
            await self._discard()
            log.info("engine stopped", extra={"engine": self.engine_id})

    async def configure(self, options: Mapping[str, ConfigValue]) -> None:
        self.base_options.update(options)
        protocol = self._protocol
        if protocol is not None and self.is_running:
            await self.runtime.call(protocol.configure(self._filter_options(protocol, options)))

    def _require_protocol(self) -> chess.engine.UciProtocol:
        if self._protocol is None or not self.is_running:
            raise EngineUnavailableError(f"{self.display_name} is not running.")
        return self._protocol

    def _handle_failure(self, exc: BaseException) -> EngineUnavailableError:
        self.last_error = f"{type(exc).__name__}: engine failure"
        log.error("engine failure", extra={"engine": self.engine_id, "error": repr(exc)})
        transport = self._transport
        self._transport = None
        self._protocol = None
        if transport is not None:
            with contextlib.suppress(RuntimeError):
                self.runtime.call_soon(_safe_kill, transport)
        return EngineUnavailableError(
            f"{self.display_name} stopped unexpectedly. It will be restarted on the next request."
        )

    # ------------------------------------------------------------- analysis
    def _terminal_snapshot(self, board: chess.Board, reason: str) -> AnalysisSnapshot:
        return AnalysisSnapshot(
            engine_id=self.engine_id,
            engine_name=self._name or self.display_name,
            fen=board.fen(),
            final=True,
            stop_reason="terminal",
            terminal=reason,
        )

    async def analyse(
        self,
        board: chess.Board,
        limits: SearchLimits,
        *,
        multipv: int = 1,
        on_update: UpdateCallback | None = None,
        stop: StopSignal | None = None,
    ) -> AnalysisSnapshot:
        reason = terminal_reason(board)
        if reason is not None:
            return self._terminal_snapshot(board, reason)
        await self.start()
        protocol = self._require_protocol()
        stop = stop or StopSignal()
        caller_loop = asyncio.get_running_loop()
        emit = (lambda snap: caller_loop.call_soon_threadsafe(on_update, snap)) if on_update else None
        coro = self._analyse_on_engine_loop(protocol, board.copy(), to_limit(limits), multipv, emit, stop)
        try:
            return await self.runtime.call(coro)
        except chess.engine.EngineTerminatedError as exc:
            raise self._handle_failure(exc) from exc
        except chess.engine.EngineError as exc:
            raise self._handle_failure(exc) from exc

    async def _analyse_on_engine_loop(
        self,
        protocol: chess.engine.UciProtocol,
        board: chess.Board,
        limit: chess.engine.Limit,
        multipv: int,
        emit: Any,
        stop: StopSignal,
    ) -> AnalysisSnapshot:
        builder = SnapshotBuilder(self.engine_id, self._name or self.display_name, board, multipv)
        analysis = await protocol.analysis(board, limit, multipv=multipv, info=chess.engine.INFO_ALL)
        loop = asyncio.get_running_loop()

        def request_stop() -> None:
            loop.call_soon_threadsafe(analysis.stop)

        stop.bind(request_stop)
        last_emit = 0.0
        last_depth = 0
        try:
            async for info in analysis:
                completed = builder.update(info)
                if emit is not None and (completed or not builder.completed):
                    now = time.monotonic()
                    if builder.depth != last_depth or now - last_emit >= EMIT_INTERVAL_S:
                        emit(builder.snapshot(final=False))
                        last_emit, last_depth = now, builder.depth
            best = await analysis.wait()
        finally:
            analysis.stop()
        snapshot = builder.snapshot(final=True)
        move = best.move or (chess.Move.from_uci(snapshot.lines[0].pv[0]) if snapshot.lines else None)
        if move is not None and move in board.legal_moves:
            snapshot.best_move = move.uci()
            snapshot.best_move_san = board.san(move)
        snapshot.ponder = best.ponder.uci() if best.ponder else None
        snapshot.stop_reason = "stopped" if stop.requested else "limit"
        return snapshot

    async def play(
        self, board: chess.Board, limits: SearchLimits, *, options: Mapping[str, ConfigValue] | None = None
    ) -> AnalysisSnapshot:
        reason = terminal_reason(board)
        if reason is not None:
            return self._terminal_snapshot(board, reason)
        await self.start()
        protocol = self._require_protocol()
        filtered = self._filter_options(protocol, options or {})

        async def _play() -> AnalysisSnapshot:
            result = await protocol.play(board.copy(), to_limit(limits), info=chess.engine.INFO_ALL, options=filtered)
            builder = SnapshotBuilder(self.engine_id, self._name or self.display_name, board)
            builder.update(result.info)
            snapshot = builder.snapshot(final=True)
            if result.move is not None:
                snapshot.best_move = result.move.uci()
                snapshot.best_move_san = board.san(result.move)
            snapshot.ponder = result.ponder.uci() if result.ponder else None
            snapshot.stop_reason = "limit"
            return snapshot

        try:
            return await self.runtime.call(_play())
        except (chess.engine.EngineTerminatedError, chess.engine.EngineError) as exc:
            raise self._handle_failure(exc) from exc
