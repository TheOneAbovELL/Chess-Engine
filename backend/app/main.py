"""ChessLab API application factory.

Run locally:  ``uvicorn app.main:app --reload`` (from ``backend/``) or use
``scripts/dev.ps1`` from the repository root.
"""

from __future__ import annotations

import ipaddress
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.v1 import analysis, auth, games, imports, insights, system
from app.core.bootstrap import ProviderFactory, build_container, default_providers, shutdown, start_workers
from app.core.config import APP_VERSION, Settings
from app.core.container import Container
from app.core.errors import error_body, install_error_handlers
from app.core.logging import configure_logging
from app.core.observability import Metrics, RequestContextMiddleware, install_request_id_logging

__all__ = ["create_app", "default_providers"]
log = logging.getLogger("chesslab")
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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


class OriginCheckMiddleware:
    """CSRF protection for state-changing requests.

    Browsers attach ``Origin`` (or at least ``Sec-Fetch-Site``) to cross-site
    POST/PUT/DELETE requests, so a request is refused when it demonstrably comes
    from another site. Same-origin requests and non-browser clients (scripts,
    curl) pass. Together with SameSite=Lax session cookies this blocks
    cross-site request forgery - also against the account-less local mode,
    where any web page could otherwise POST to ``localhost``.
    """

    def __init__(self, app: ASGIApp, allowed: list[str]) -> None:
        self.app = app
        self.allowed = set(allowed)

    def _ok(self, scope: Scope) -> bool:
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])}
        origin = headers.get("origin")
        if not origin and headers.get("referer"):
            parsed = urlparse(headers["referer"])
            origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin and origin != "null":
            return origin in self.allowed or urlparse(origin).netloc == headers.get("host", "")
        if origin == "null":
            return False
        return headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") in UNSAFE_METHODS and not self._ok(scope):
            response = JSONResponse(
                error_body("cross_site_request", "Cross-site requests are not allowed."), status_code=403
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    # 'wasm-unsafe-eval' lets the optional in-browser Stockfish (WebAssembly) compile;
    # it does not allow JavaScript eval.
    CSP = (
        "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; "
        "img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
        "connect-src 'self' ws: wss:; manifest-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; object-src 'none'"
    )
    PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

    def __init__(self, app: ASGIApp, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        is_docs = path.startswith("/api/docs")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", self.PERMISSIONS.encode()),
                    (b"cross-origin-opener-policy", b"same-origin"),
                ]
                if self.hsts:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                if path.startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                if not is_docs:  # Swagger UI loads its assets from a CDN
                    headers.append((b"content-security-policy", self.CSP.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _private_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host in ("testclient", "localhost")
    return address.is_loopback or address.is_private


def create_app(settings: Settings | None = None, *, provider_factory: ProviderFactory | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings)
    install_request_id_logging()
    settings.ensure_directories()
    metrics = Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The metrics registry exists before startup: the request middleware records into it.
        container = await build_container(settings, provider_factory, metrics=metrics)
        app.state.container = container
        if settings.run_workers:
            start_workers(container)
        log.info(
            "ChessLab started",
            extra={
                "version": APP_VERSION,
                "environment": settings.environment,
                "auth_mode": settings.auth_mode,
                "workers": settings.run_workers,
            },
        )
        try:
            yield
        finally:
            await shutdown(container)
            log.info("ChessLab stopped")

    docs = settings.docs_enabled
    app = FastAPI(
        title="ChessLab API",
        version=APP_VERSION,
        description=(
            "Local-first chess analysis: Stockfish and a custom engine, Chess.com/Lichess imports, game review."
        ),
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    install_error_handlers(app)
    # Middleware runs outermost-last-added: request context wraps everything.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)
    app.add_middleware(OriginCheckMiddleware, allowed=settings.cors_origins)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
        allow_credentials=settings.multi_user,
    )
    app.add_middleware(RequestContextMiddleware, metrics=metrics)

    api = APIRouter(prefix="/api/v1")
    for module in (system, auth, analysis, games, imports, insights):
        api.include_router(module.router)
    app.include_router(api)

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics(request: Request) -> Any:
        if not settings.metrics_enabled:
            return JSONResponse(error_body("not_found", "Not found."), status_code=404)
        token = settings.metrics_token
        if token:
            supplied = request.headers.get("authorization", "")
            if not secrets.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
                return JSONResponse(error_body("unauthorized", "Metrics token required."), status_code=401)
        elif not _private_client(request):
            # Without a token, metrics are only served to the local machine/network.
            return JSONResponse(error_body("not_found", "Not found."), status_code=404)
        c: Container = request.app.state.container
        return PlainTextResponse(c.metrics.render(), media_type="text/plain; version=0.0.4")

    dist = settings.frontend_dist
    if settings.serve_frontend and (dist / "index.html").is_file():
        index = dist / "index.html"
        immutable = {"Cache-Control": "public, max-age=31536000, immutable"}

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Any:
            if path.startswith("api/"):
                return JSONResponse(error_body("not_found", "Not found."), status_code=404)
            candidate = (dist / path).resolve()
            # Serve real files inside dist only (no path traversal); otherwise the SPA shell.
            if path and candidate.is_file() and candidate.is_relative_to(dist):
                # Vite fingerprints everything under assets/, so it can be cached forever.
                headers = immutable if path.startswith("assets/") else {"Cache-Control": "no-cache"}
                return FileResponse(candidate, headers=headers)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
