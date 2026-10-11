"""Engine integration: real processes (the custom engine always; Stockfish when installed)."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import chess
import pytest

from app.core.config import Settings
from app.core.errors import EngineUnavailableError
from app.services.engine.manager import EngineManager
from app.services.engine.runtime import EngineRuntime, StopSignal
from app.services.engine.stockfish import discover_stockfish
from app.services.engine.types import AnalysisSnapshot, SearchLimits
from app.services.engine.uci import UciEngine
from app.services.settings_store import EngineSettings

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
STOCKFISH = discover_stockfish(Settings(environment="test"))
needs_stockfish = pytest.mark.skipif(STOCKFISH is None, reason="Stockfish executable not found")


@pytest.fixture()
async def manager(tmp_path: Path) -> AsyncIterator[EngineManager]:
    runtime = EngineRuntime()
    runtime.start()
    settings = Settings(environment="test", data_dir=tmp_path, engine_idle_shutdown_s=30)
    mgr = EngineManager(settings, runtime, EngineSettings(stockfish_threads=1, stockfish_hash_mb=16).clamp(settings))
    yield mgr
    await mgr.shutdown()
    runtime.stop()


async def test_custom_engine_analysis_and_updates(manager: EngineManager) -> None:
    updates: list[AnalysisSnapshot] = []
    async with manager.slot("custom").use(preempt=True) as lease:
        snap = await lease.analyse(chess.Board(), SearchLimits(depth=3), multipv=2, on_update=updates.append)
    await asyncio.sleep(0.05)  # updates are delivered via call_soon_threadsafe
    assert snap.final and snap.depth == 3 and snap.stop_reason == "limit"
    assert len(snap.lines) == 2 and snap.lines[0].pv[0] != snap.lines[1].pv[0]
    assert snap.best_move in {m.uci() for m in chess.Board().legal_moves}
    assert snap.engine_name.startswith("ChessLab Engine")
    assert updates and all(not u.final for u in updates)
    assert [u.depth for u in updates] == sorted(u.depth for u in updates)


async def test_scores_are_white_pov(manager: EngineManager) -> None:
    """A Black advantage must be negative whichever side is to move."""
    black_up_a_queen = "q3k3/8/8/8/8/8/8/4K3"
    async with manager.slot("custom").use(preempt=True) as lease:
        white_to_move = await lease.analyse(chess.Board(f"{black_up_a_queen} w - - 0 1"), SearchLimits(depth=2))
        black_to_move = await lease.analyse(chess.Board(f"{black_up_a_queen} b - - 0 1"), SearchLimits(depth=2))
        black_mates = await lease.analyse(chess.Board("r5k1/8/8/8/8/8/5PPP/6K1 b - - 0 1"), SearchLimits(depth=3))
    assert white_to_move.lines[0].score.cp is not None and white_to_move.lines[0].score.cp < -500
    assert black_to_move.lines[0].score.cp is not None and black_to_move.lines[0].score.cp < -500
    assert black_mates.lines[0].score.mate == -1


async def test_stop_returns_last_completed_result(manager: EngineManager) -> None:
    stop = StopSignal()
    loop = asyncio.get_running_loop()
    loop.call_later(1.0, stop.request)
    started = time.perf_counter()
    async with manager.slot("custom").use(preempt=True, stop=stop) as lease:
        snap = await lease.analyse(chess.Board(KIWIPETE), SearchLimits(movetime_ms=60_000))
    assert time.perf_counter() - started < 5
    assert snap.stop_reason == "stopped" and snap.depth >= 1 and snap.best_move


async def test_new_request_preempts_running_search(manager: EngineManager) -> None:
    slot = manager.slot("custom")

    async def long() -> AnalysisSnapshot:
        async with slot.use(preempt=True) as lease:
            return await lease.analyse(chess.Board(KIWIPETE), SearchLimits(movetime_ms=60_000))

    task = asyncio.create_task(long())
    await asyncio.sleep(1.5)
    async with slot.use(preempt=True) as lease:
        quick = await lease.analyse(chess.Board(), SearchLimits(depth=2))
    first = await asyncio.wait_for(task, timeout=10)
    assert first.stop_reason == "stopped" and quick.depth == 2


async def test_time_limit_is_enforced(manager: EngineManager) -> None:
    started = time.perf_counter()
    async with manager.slot("custom").use(preempt=True) as lease:
        snap = await lease.analyse(chess.Board(KIWIPETE), SearchLimits(depth=30, movetime_ms=500))
    assert time.perf_counter() - started < 4
    assert snap.final and snap.depth < 30


async def test_terminal_positions_skip_the_engine(manager: EngineManager) -> None:
    async with manager.slot("custom").use(preempt=True) as lease:
        mate = await lease.analyse(chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"), SearchLimits(depth=5))
        stale = await lease.analyse(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"), SearchLimits(depth=5))
    assert (mate.terminal, stale.terminal) == ("checkmate", "stalemate")
    assert mate.lines == [] and mate.best_move is None


async def test_crash_recovery(manager: EngineManager) -> None:
    slot = manager.slot("custom")
    async with slot.use(preempt=True) as lease:
        await lease.analyse(chess.Board(), SearchLimits(depth=1))
    engine = slot.engine
    assert isinstance(engine, UciEngine) and engine._transport is not None
    manager.runtime.call_soon(engine._transport.kill)
    await asyncio.sleep(0.5)
    assert not engine.is_running
    async with slot.use(preempt=True) as lease:  # restarted transparently
        snap = await lease.analyse(chess.Board(), SearchLimits(depth=2))
    assert snap.depth == 2 and engine.is_running


async def test_crash_during_search_reports_unavailable(manager: EngineManager) -> None:
    slot = manager.slot("custom")
    async with slot.use(preempt=True) as lease:
        await lease.analyse(chess.Board(), SearchLimits(depth=1))
        engine = slot.engine
        assert isinstance(engine, UciEngine) and engine._transport is not None
        manager.runtime.loop.call_later(0.5, engine._transport.kill)
        with pytest.raises(EngineUnavailableError):
            await lease.analyse(chess.Board(KIWIPETE), SearchLimits(movetime_ms=20_000))


async def test_missing_executable_is_unavailable() -> None:
    runtime = EngineRuntime()
    runtime.start()
    try:
        engine = UciEngine(
            "x",
            "Broken",
            [str(Path(sys.executable).parent / "definitely-not-an-engine.exe")],
            runtime,
            start_timeout_s=5,
        )
        with pytest.raises(EngineUnavailableError):
            await engine.start()
        assert engine.last_error and "definitely" not in engine.last_error  # no paths leaked
        not_uci = UciEngine(
            "y", "NotUci", [sys.executable, "-c", "import time; time.sleep(30)"], runtime, start_timeout_s=1
        )
        with pytest.raises(EngineUnavailableError):
            await not_uci.start()  # never answers "uciok": start times out
    finally:
        runtime.stop()


async def test_clean_shutdown_stops_processes(manager: EngineManager) -> None:
    slot = manager.slot("custom")
    async with slot.use(preempt=True) as lease:
        await lease.analyse(chess.Board(), SearchLimits(depth=1))
    assert slot.engine.is_running
    await manager.shutdown()
    assert not slot.engine.is_running


async def test_describe_reports_status(manager: EngineManager) -> None:
    custom = next(d for d in manager.describe() if d.id == "custom")
    assert custom.available and custom.status == "stopped"
    async with manager.slot("custom").use(preempt=True) as lease:
        await lease.analyse(chess.Board(), SearchLimits(depth=1))
    custom = next(d for d in manager.describe() if d.id == "custom")
    assert custom.status == "ready" and custom.name and custom.name.startswith("ChessLab")


# ---------------------------------------------------------------- Stockfish


@needs_stockfish
@pytest.mark.stockfish
async def test_stockfish_real_analysis(manager: EngineManager) -> None:
    async with manager.slot("stockfish").use(preempt=True) as lease:
        snap = await lease.analyse(chess.Board(), SearchLimits(depth=12), multipv=3)
        mate = await lease.analyse(chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"), SearchLimits(depth=10))
    assert snap.engine_name.startswith("Stockfish")
    assert snap.depth >= 12 and len(snap.lines) == 3
    assert snap.nodes and snap.nps and snap.lines[0].score.cp is not None and abs(snap.lines[0].score.cp) < 100
    assert mate.best_move == "a1a8" and mate.lines[0].score.mate == 1


@needs_stockfish
@pytest.mark.stockfish
async def test_stockfish_strength_limit_is_per_search(manager: EngineManager) -> None:
    async with manager.slot("stockfish").use(preempt=True) as lease:
        weak = await lease.play(
            chess.Board(), SearchLimits(movetime_ms=100), options={"UCI_LimitStrength": True, "UCI_Elo": 1400}
        )
        strong = await lease.analyse(chess.Board(KIWIPETE), SearchLimits(depth=10))
    assert weak.best_move in {m.uci() for m in chess.Board().legal_moves}
    assert strong.depth >= 10


@needs_stockfish
@pytest.mark.stockfish
async def test_stockfish_settings_apply_live(manager: EngineManager) -> None:
    async with manager.slot("stockfish").use(preempt=True) as lease:
        await lease.analyse(chess.Board(), SearchLimits(depth=5))
    await manager.apply_settings(EngineSettings(stockfish_threads=2, stockfish_hash_mb=32))
    async with manager.slot("stockfish").use(preempt=True) as lease:
        snap = await lease.analyse(chess.Board(), SearchLimits(depth=8))
    assert snap.depth >= 8
