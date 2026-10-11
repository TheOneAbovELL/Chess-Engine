"""Explicit application wiring: every long-lived service, created once by
:mod:`app.core.bootstrap` and reachable from requests via
``request.app.state.container``."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.core.config import Settings
from app.core.observability import Metrics
from app.core.ratelimit import RateLimiter
from app.db.session import Database
from app.jobs.maintenance import MaintenanceTask
from app.services.analysis import AnalysisService
from app.services.auth import AuthService
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
    auth: AuthService
    runtime: EngineRuntime
    engines: EngineManager
    analysis: AnalysisService
    games: GameService
    providers: dict[str, ChessHistoryProvider]
    imports: GameImportService
    reviews: GameReviewService  # enqueue/query API; also review worker #0
    stats: StatisticsService
    explorer: ExplorerService
    limiter: RateLimiter
    metrics: Metrics
    maintenance: MaintenanceTask
    lookup_limiter: RateLimiter = field(
        default_factory=lambda: RateLimiter(30, message="Too many account lookups. Please wait a moment.")
    )
    review_workers: list[GameReviewService] = field(default_factory=list)
    http_clients: list[httpx.AsyncClient] = field(default_factory=list)
    live_connections: dict[int, int] = field(default_factory=dict)  # user id -> open sockets
    workers_started: bool = False

    @property
    def live_total(self) -> int:
        return sum(self.live_connections.values())
