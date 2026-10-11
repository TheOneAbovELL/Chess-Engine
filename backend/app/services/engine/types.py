"""Engine-neutral data types.

The rest of the application (and the frontend) only ever sees these
normalised structures, never raw UCI output or Stockfish-specific fields.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EngineId = Literal["stockfish", "custom"]
ENGINE_IDS: tuple[EngineId, ...] = ("stockfish", "custom")


class Evaluation(BaseModel):
    """White-POV score. ``mate == 0`` means the side to move is checkmated."""

    cp: int | None = None
    mate: int | None = None


class SearchLimits(BaseModel):
    depth: int | None = Field(default=None, ge=1)
    movetime_ms: int | None = Field(default=None, ge=10)
    nodes: int | None = Field(default=None, ge=1)


class EngineLine(BaseModel):
    multipv: int
    depth: int
    seldepth: int | None = None
    score: Evaluation
    pv: list[str]  # UCI
    pv_san: list[str]


class AnalysisSnapshot(BaseModel):
    """Latest state of a search. ``final`` is True once the engine has
    returned ``bestmove``; ``depth`` is the depth of the best line as reported
    by the engine (never inferred)."""

    engine_id: str
    engine_name: str
    fen: str
    depth: int = 0
    seldepth: int | None = None
    nodes: int | None = None
    nps: int | None = None
    time_ms: int | None = None
    hashfull: int | None = None
    lines: list[EngineLine] = Field(default_factory=list)
    best_move: str | None = None
    best_move_san: str | None = None
    ponder: str | None = None
    final: bool = False
    stop_reason: str | None = None  # "limit", "stopped", "terminal"
    terminal: str | None = None  # set when the position is already game-over


class EngineCapabilities(BaseModel):
    multipv: bool = True
    max_multipv: int = 5
    depth_limit: bool = True
    time_limit: bool = True
    node_limit: bool = True
    limit_strength: bool = False
    eval_breakdown: bool = False
    threads: bool = False
    hash: bool = True


class EngineDescriptor(BaseModel):
    id: str
    display_name: str
    available: bool
    status: Literal["stopped", "starting", "ready", "busy", "error", "unavailable"]
    name: str | None = None  # as reported by "id name"
    author: str | None = None
    detail: str | None = None  # why unavailable / last error (no filesystem paths)
    capabilities: EngineCapabilities
