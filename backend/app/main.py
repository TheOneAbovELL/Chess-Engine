"""ChessLab API application factory.

Run locally:  ``uvicorn app.main:app --reload`` (from ``backend/``) or use
``scripts/dev.ps1`` from the repository root.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import certifi
import httpx
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1 import analysis, games, imports, insights, system
from app.core.config import APP_VERSION, Settings
from app.core.container import Container
from app.core.errors import error_body, install_error_handlers
from app.core.logging import configure_logging
from app.core.ratelimit import RateLimiter
from app.db.migrate import run_migrations
from app.db.session import Database
from app.services.analysis import AnalysisService
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
ProviderFactory = Any  # Callable[[Settings], tuple[dict[str, ChessHistoryProvider], list[httpx.AsyncClient]]]


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


class BodySizeLimitMiddleware:
    """Reject request bodies above ``max_bytes`` (413) even without Content-Length."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > self.max_bytes:
                await self._reject(scope, receive, send)
                return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(error_body("payload_too_large", "The request body is too large."), status_code=413)
        await response(scope, receive, send)


class _TooLarge(Exception):
    pass


class SecurityHeadersMiddleware:
    CSP = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'"
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        is_docs = scope.get("path", "").startswith("/api/docs") or scope.get("path", "").startswith("/api/redoc")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                ]
                if not is_docs:  # Swagger UI loads its assets from a CDN
                    headers.append((b"content-security-policy", self.CSP.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(settings: Settings | None = None, *, provider_factory: ProviderFactory | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings)
    settings.ensure_directories()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.resolved_database_url)
        await asyncio.to_thread(run_migrations, db, settings)
        store = SettingsStore(db, settings)
        runtime = EngineRuntime()
        runtime.start()
        engines = EngineManager(settings, runtime, await asyncio.to_thread(store.engine))
        engines.start()
        providers, clients = (provider_factory or default_providers)(settings)
        import_service = GameImportService(db, settings, providers, store)
        review_service = GameReviewService(db, settings, engines, store)
        app.state.container = Container(
            settings=settings,
            db=db,
            store=store,
            runtime=runtime,
            engines=engines,
            analysis=AnalysisService(engines, settings),
            games=GameService(db, settings),
            providers=providers,
            imports=import_service,
            reviews=review_service,
            stats=StatisticsService(db),
            explorer=ExplorerService(db),
            limiter=RateLimiter(settings.analysis_rate_per_minute),
            http_clients=clients,
        )
        import_service.start()
        review_service.start()
        log.info("ChessLab started", extra={"version": APP_VERSION, "environment": settings.environment})
        try:
            yield
        finally:
            await import_service.stop()
            await review_service.stop()
            await engines.shutdown()
            runtime.stop()
            for http_client in clients:
                await http_client.aclose()
            db.dispose()
            log.info("ChessLab stopped")

    app = FastAPI(
        title="ChessLab API",
        version=APP_VERSION,
        description=(
            "Local-first chess analysis: Stockfish and a custom engine, Chess.com/Lichess imports, game review."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    api = APIRouter(prefix="/api/v1")
    for module in (system, analysis, games, imports, insights):
        api.include_router(module.router)
    app.include_router(api)

    dist = settings.frontend_dist
    if settings.serve_frontend and (dist / "index.html").is_file():
        index = dist / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Any:
            if path.startswith("api/"):
                return JSONResponse(error_body("not_found", "Not found."), status_code=404)
            candidate = (dist / path).resolve()
            # Serve real files inside dist only (no path traversal); otherwise the SPA shell.
            if path and candidate.is_file() and candidate.is_relative_to(dist):
                return FileResponse(candidate)
            return FileResponse(index)

    return app


app = create_app()
