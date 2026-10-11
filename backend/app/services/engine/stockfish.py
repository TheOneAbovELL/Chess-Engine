"""Stockfish: discovery, options and play-strength levels."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from app.core.config import Settings

from .runtime import EngineRuntime
from .types import EngineCapabilities
from .uci import UciEngine

# Baseline options are always part of the persistent configuration so that
# per-search overrides (strength limiting during play) are reverted afterwards.
BASELINE_OPTIONS = {"UCI_LimitStrength": False, "Skill Level": 20, "UCI_ShowWDL": False}


def discover_stockfish(settings: Settings) -> Path | None:
    """Locate a Stockfish executable from server configuration only:
    1. ``CHESSLAB_STOCKFISH_PATH``  2. ``stockfish`` on PATH  3. ``engines/`` folder."""
    if settings.stockfish_path is not None:
        candidate = settings.stockfish_path.expanduser()
        return candidate if candidate.is_file() else None
    on_path = shutil.which("stockfish")
    if on_path:
        return Path(on_path)
    root = settings.engines_dir
    if root.is_dir():
        pattern = "stockfish*.exe" if sys.platform == "win32" else "stockfish*"
        for candidate in sorted(root.rglob(pattern)):
            if candidate.is_file() and candidate.suffix.lower() not in {".zip", ".tar", ".txt", ".md", ".sh", ".nnue"}:
                return candidate
    return None


class StockfishEngine(UciEngine):
    def __init__(
        self,
        path: Path,
        runtime: EngineRuntime,
        *,
        threads: int,
        hash_mb: int,
        start_timeout_s: float,
        low_priority: bool = False,
    ) -> None:
        super().__init__(
            "stockfish",
            "Stockfish",
            [str(path)],
            runtime,
            base_options={**BASELINE_OPTIONS, "Threads": threads, "Hash": hash_mb},
            start_timeout_s=start_timeout_s,
            low_priority=low_priority,
        )

    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(limit_strength=True, threads=True)


# Play levels. Elo values are Stockfish's own UCI_Elo calibration (anchored to
# CCRL-style engine ratings at a given time control), *not* a Chess.com or
# FIDE rating. Low levels use "Skill Level" with a shallow depth instead.
STOCKFISH_LEVELS: dict[int, dict[str, object]] = {
    1: {"label": "Novice", "options": {"Skill Level": 0}, "depth": 2, "movetime_ms": 100},
    2: {"label": "Beginner", "options": {"Skill Level": 3}, "depth": 4, "movetime_ms": 150},
    3: {"label": "Casual", "options": {"Skill Level": 6}, "depth": 6, "movetime_ms": 200},
    4: {"label": "Club", "options": {"UCI_LimitStrength": True, "UCI_Elo": 1500}, "movetime_ms": 300},
    5: {"label": "Intermediate", "options": {"UCI_LimitStrength": True, "UCI_Elo": 1800}, "movetime_ms": 400},
    6: {"label": "Advanced", "options": {"UCI_LimitStrength": True, "UCI_Elo": 2100}, "movetime_ms": 500},
    7: {"label": "Expert", "options": {"UCI_LimitStrength": True, "UCI_Elo": 2400}, "movetime_ms": 600},
    8: {"label": "Master", "options": {"UCI_LimitStrength": True, "UCI_Elo": 2800}, "movetime_ms": 800},
    9: {"label": "Full strength (1s)", "options": {}, "movetime_ms": 1000},
    10: {"label": "Full strength (3s)", "options": {}, "movetime_ms": 3000},
}
