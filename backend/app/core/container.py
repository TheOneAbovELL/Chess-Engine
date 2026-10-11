"""Explicit application wiring: every long-lived service, created once in the
lifespan handler and reachable from requests via ``request.app.state.container``."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.db.session import Database
from app.services.analysis import AnalysisService
from app.services.engine.manager import EngineManager
from app.services.engine.runtime import EngineRuntime
from app.services.games import GameService
from app.services.imports import GameImportService
from app.services.providers.base import ChessHistoryProvider
from app.services.review.service import GameReviewService
from app.services.settings_store import SettingsStore
from app.services.statistics.service import ExplorerService, StatisticsService


@dataclass
class Container:
    settings: Settings
    db: Database
    store: SettingsStore
    runtime: EngineRuntime
    engines: EngineManager
    analysis: AnalysisService
    games: GameService
    providers: dict[str, ChessHistoryProvider]
    imports: GameImportService
    reviews: GameReviewService
    stats: StatisticsService
    explorer: ExplorerService
    limiter: RateLimiter
    http_clients: list[httpx.AsyncClient] = field(default_factory=list)
    live_connections: int = 0
