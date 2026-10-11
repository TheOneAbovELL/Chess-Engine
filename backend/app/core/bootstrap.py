"""Builds and tears down the service container.

Shared by the web app (:mod:`app.main`) and the standalone worker
(:mod:`app.worker`), so both run exactly the same wiring. In a single-process
install the web app also runs the background workers (``run_workers=true``);
a larger deployment sets ``run_workers=false`` on the web processes and runs
``python -m app.worker`` separately.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import Callable, Iterable
from typing import Any

import certifi
import httpx
from sqlalchemy import func, select

from app.core.config import APP_VERSION, Settings
from app.core.container import Container
from app.core.observability import Metrics
from app.core.ratelimit import RateLimiter
from app.db.migrate import run_migrations
from app.db.session import Database
from app.jobs.maintenance import MaintenanceTask
from app.models import Game, GameReview, ImportJob, User, WorkerHeartbeat
from app.services.analysis import AnalysisService
from app.services.auth import AuthService
from app.services.chess.openings import book
from app.services.engine.manager import EngineManager
from app.services.engine.runtime import EngineRuntime
from app.services.games import GameService
from app.services.imports import GameImportService
from app.services.providers.base import ChessHistoryProvider
from app.services.providers.chesscom import ChessComProvider
from app.services.providers.http import PoliteClient
from app.services.providers.lichess import LichessProvider
from app.services.review.service import GameReviewService
from app.services.settings_store import SettingsStore
from app.services.statistics.service import ExplorerService, StatisticsService

log = logging.getLogger("chesslab")
ProviderFactory = Callable[[Settings], tuple[dict[str, ChessHistoryProvider], list[httpx.AsyncClient]]]


def default_providers(settings: Settings) -> tuple[dict[str, ChessHistoryProvider], list[httpx.AsyncClient]]:
    # One verified TLS context for both clients: loading the CA bundle is the
    # slowest part of creating an HTTPS client.
    tls = ssl.create_default_context(cafile=certifi.where())

    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": settings.user_agent, "Accept-Encoding": "gzip"},
            timeout=httpx.Timeout(settings.http_timeout_s, connect=10.0),
            follow_redirects=True,
            verify=tls,
        )

    chesscom_client, lichess_client = client(), client()
    providers: dict[str, ChessHistoryProvider] = {
        "chesscom": ChessComProvider(
            PoliteClient(
                chesscom_client,
                provider_name="Chess.com",
                max_retries=settings.http_max_retries,
                rate_limit_wait_s=10.0,
            ),
            settings.chesscom_base_url,
        ),
        "lichess": LichessProvider(
            # Lichess: "wait a full minute" after a 429.
            PoliteClient(
                lichess_client, provider_name="Lichess", max_retries=settings.http_max_retries, rate_limit_wait_s=60.0
            ),
            settings.lichess_base_url,
        ),
    }
    return providers, [chesscom_client, lichess_client]


def _collector(c: Container) -> Callable[[], Iterable[tuple[str, str, dict[str, str], float]]]:
    def collect() -> Iterable[tuple[str, str, dict[str, str], float]]:
        with c.db.session() as session:
            yield (
                "chesslab_users",
                "Registered accounts",
                {},
                float(session.execute(select(func.count(User.id))).scalar_one()),
            )
            yield "chesslab_games", "Stored games", {}, float(session.execute(select(func.count(Game.id))).scalar_one())
            for model, kind in ((ImportJob, "imports"), (GameReview, "reviews")):
                rows = session.execute(select(model.status, func.count(model.id)).group_by(model.status)).all()
                for status, count in rows:
                    yield "chesslab_jobs", "Background jobs by status", {"kind": kind, "status": status}, float(count)
            beats = session.execute(
                select(WorkerHeartbeat.kind, func.max(WorkerHeartbeat.seen_at)).group_by(WorkerHeartbeat.kind)
            ).all()
            for kind, seen in beats:
                yield (
                    "chesslab_worker_last_seen",
                    "Unix time of the last worker heartbeat",
                    {"kind": kind},
                    float(seen.timestamp()),
                )
        for engine_id, pool in c.engines.pools().items():
            yield "chesslab_engine_pool_in_use", "Interactive engines in use", {"engine": engine_id}, float(pool.in_use)
            yield (
                "chesslab_engine_pool_size",
                "Interactive engine processes",
                {"engine": engine_id},
                float(len(pool.slots)),
            )
        yield "chesslab_live_connections", "Open live-analysis sockets", {}, float(c.live_total)

    return collect


async def build_container(
    settings: Settings, provider_factory: ProviderFactory | None = None, *, metrics: Metrics | None = None
) -> Container:
    db = Database(settings.resolved_database_url)
    await asyncio.to_thread(run_migrations, db, settings)
    await asyncio.to_thread(book.positions.__len__)  # warm the opening book off the event loop
    store = SettingsStore(db, settings)
    auth = AuthService(db, settings)
    runtime = EngineRuntime()
    runtime.start()
    engines = EngineManager(settings, runtime, await asyncio.to_thread(store.engine))
    engines.start()
    providers, clients = (provider_factory or default_providers)(settings)
    reviews = [GameReviewService(db, settings, engines, store, index=i) for i in range(settings.review_workers)]
    for worker in reviews:
        worker.peers = [w for w in reviews if w is not worker]
    metrics = metrics or Metrics()
    container = Container(
        settings=settings,
        db=db,
        store=store,
        auth=auth,
        runtime=runtime,
        engines=engines,
        analysis=AnalysisService(engines, settings),
        games=GameService(db, settings),
        providers=providers,
        imports=GameImportService(db, settings, providers, store),
        reviews=reviews[0],
        stats=StatisticsService(db),
        explorer=ExplorerService(db),
        limiter=RateLimiter(settings.analysis_rate_per_minute),
        metrics=metrics,
        maintenance=MaintenanceTask(db, settings, auth),
        review_workers=reviews,
        http_clients=clients,
    )
    metrics.add_collector(_collector(container))
    return container


def start_workers(c: Container) -> None:
    c.imports.start()
    for worker in c.review_workers:
        worker.start()
    c.maintenance.start()
    c.workers_started = True


async def shutdown(c: Container) -> None:
    if c.workers_started:
        await c.imports.stop()
        for worker in c.review_workers:
            await worker.stop()
        await c.maintenance.stop()
    await c.engines.shutdown()
    c.runtime.stop()
    for client in c.http_clients:
        await client.aclose()
    c.db.dispose()


def describe(c: Container) -> dict[str, Any]:
    return {"version": APP_VERSION, "environment": c.settings.environment, "auth_mode": c.settings.auth_mode}
