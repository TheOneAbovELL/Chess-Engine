"""Request/response schemas for the v1 API (validated with Pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.services.engine.types import AnalysisSnapshot

UciMove = Annotated[str, StringConstraints(pattern=r"^[a-h][1-8][a-h][1-8][qrbn]?$")]
EngineChoice = Literal["stockfish", "custom"]
DEFAULT_COMPARE: tuple[EngineChoice, ...] = ("stockfish", "custom")


class PositionRequest(BaseModel):
    fen: str | None = Field(None, max_length=100, description="Start position (default: standard start)")
    moves: list[UciMove] = Field(default_factory=list, max_length=1000, description="UCI moves played from `fen`")


class AnalyzeRequest(PositionRequest):
    engine: EngineChoice | None = None
    depth: int | None = Field(None, ge=1, le=99)
    movetime_ms: int | None = Field(None, ge=50, le=600_000)
    multipv: int | None = Field(None, ge=1, le=10)


class BestMoveRequest(PositionRequest):
    engine: EngineChoice | None = None
    level: int | None = Field(None, ge=1, le=10)
    depth: int | None = Field(None, ge=1, le=99)
    movetime_ms: int | None = Field(None, ge=50, le=600_000)


class CompareRequest(PositionRequest):
    engines: list[EngineChoice] = Field(default_factory=lambda: list(DEFAULT_COMPARE), min_length=1, max_length=2)
    depth: int | None = Field(None, ge=1, le=99)
    movetime_ms: int | None = Field(None, ge=50, le=600_000)
    multipv: int = Field(1, ge=1, le=5)


class CompareResult(BaseModel):
    engine_id: str
    snapshot: AnalysisSnapshot | None
    error: str | None


class LegalMove(BaseModel):
    uci: str
    san: str


class PositionInfo(BaseModel):
    fen: str
    turn: Literal["white", "black"]
    is_check: bool
    is_game_over: bool
    outcome: str | None
    result: str | None
    can_claim_draw: bool
    legal_moves: list[LegalMove]


class PgnText(BaseModel):
    pgn: str = Field(min_length=1, max_length=6_000_000)


class PgnImportRequest(PgnText):
    owner: str | None = Field(None, max_length=64, description="Your name in these games, to compute your results")


class PgnParseResponse(BaseModel):
    headers: dict[str, str]
    nodes: list[dict[str, Any]]
    games_in_text: int


class UploadSummaryOut(BaseModel):
    total: int
    imported: int
    duplicates: int
    failed: int
    skipped: int
    game_ids: list[int]
    errors: list[dict[str, Any]]


class IdsRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=5000)


class ReviewRequest(BaseModel):
    engine: EngineChoice | None = None
    depth: int | None = Field(None, ge=4, le=40)
    movetime_ms: int | None = Field(None, ge=100, le=60_000)
    multipv: int | None = Field(None, ge=1, le=3)
    force: bool = False


class BatchReviewRequest(ReviewRequest):
    game_ids: list[int] = Field(min_length=1, max_length=500)


class GameSummary(BaseModel):
    id: int
    source: str
    external_id: str
    owner_username: str | None
    white: str
    black: str
    white_elo: int | None
    black_elo: int | None
    result: str
    termination: str | None
    user_color: str | None
    user_result: str | None
    user_rating: int | None
    opponent: str | None
    opponent_rating: int | None
    time_control: str | None
    time_class: str
    rated: bool | None
    eco: str | None
    opening: str | None
    url: str | None
    played_at: datetime | None
    imported_at: datetime
    ply_count: int
    review: dict[str, Any] | None


class GamePage(BaseModel):
    items: list[GameSummary]
    total: int
    page: int
    page_size: int


class GameDetail(GameSummary):
    pgn: str
    initial_fen: str
    moves: list[dict[str, Any]]
    headers: dict[str, str]


class ImportJobOut(BaseModel):
    id: str
    provider: str
    username: str
    params: dict[str, Any]
    status: str
    discovered: int
    imported: int
    duplicates: int
    failed: int
    skipped: int
    phase: str | None
    message: str | None
    errors: list[dict[str, Any]]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ProviderUserOut(BaseModel):
    provider: str
    username: str
    exists: bool
    url: str | None
    display_name: str | None
    status: str | None
    closed: bool
    joined: datetime | None
    last_online: datetime | None
    game_counts: dict[str, int]
    notes: list[str]
