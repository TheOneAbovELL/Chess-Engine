"""ChessLab's own engine, run as a UCI subprocess (``python -m chesslab_engine``).

Running it out of process keeps its CPU-heavy pure-Python search from holding
the web server's GIL, gives it the same lifecycle/cancellation path as
Stockfish, and keeps the engine independently testable and usable from any
UCI GUI.
"""

from __future__ import annotations

import importlib.util
import sys

from .runtime import EngineRuntime
from .types import EngineCapabilities
from .uci import UciEngine


def custom_engine_installed() -> bool:
    return importlib.util.find_spec("chesslab_engine") is not None


class CustomChessEngine(UciEngine):
    def __init__(
        self, runtime: EngineRuntime, *, hash_mb: int, start_timeout_s: float, low_priority: bool = False
    ) -> None:
        super().__init__(
            "custom",
            "ChessLab Engine",
            [sys.executable, "-m", "chesslab_engine"],
            runtime,
            base_options={"Hash": hash_mb},
            start_timeout_s=start_timeout_s,
            low_priority=low_priority,
        )

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(eval_breakdown=True, max_multipv=5)


# The custom engine is weak and slow in Python, so levels use depth/time only.
CUSTOM_LEVELS: dict[int, dict[str, object]] = {
    1: {"label": "Depth 1", "depth": 1, "movetime_ms": 2000},
    2: {"label": "Depth 2", "depth": 2, "movetime_ms": 3000},
    3: {"label": "Depth 3", "depth": 3, "movetime_ms": 4000},
    4: {"label": "Depth 4 (capped at 5s)", "depth": 4, "movetime_ms": 5000},
    5: {"label": "2 seconds per move", "movetime_ms": 2000},
    6: {"label": "5 seconds per move", "movetime_ms": 5000},
}
