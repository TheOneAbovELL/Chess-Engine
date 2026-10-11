"""Health, configuration, engines and settings."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import chess
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from app.api.deps import admin_user, client_key, container, current_user
from app.core.config import APP_VERSION
from app.core.container import Container
from app.core.errors import EngineUnavailableError, InvalidInputError
from app.models import WorkerHeartbeat
from app.services.auth import CurrentUser
from app.services.chess.positions import parse_fen
from app.services.engine.types import EngineDescriptor
from app.services.settings_store import ClassificationThresholds, EngineSettings, InterfacePrefs, Preferences

router = APIRouter()
client_log = logging.getLogger("chesslab.client")


def _database_ok(c: Container) -> bool:
    try:
        with c.db.session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


def _workers(c: Container) -> dict[str, Any]:
    """Background workers seen recently, in this or any other process."""
    cutoff = datetime.now(UTC) - timedelta(seconds=c.settings.job_stale_after_s)
    with c.db.session() as session:
        rows = session.execute(
            select(WorkerHeartbeat.kind, func.count(WorkerHeartbeat.worker_id))
            .where(WorkerHeartbeat.seen_at >= cutoff)
            .group_by(WorkerHeartbeat.kind)
        ).all()
    alive = {kind: int(n) for kind, n in rows}
    return {"imports": alive.get("imports", 0), "reviews": alive.get("reviews", 0), "in_process": c.workers_started}


@router.get("/health", summary="Overall status (database, engines, workers)")
def health(c: Container = Depends(container)) -> dict[str, Any]:
    db_ok = _database_ok(c)
    engines = {e.id: e.status if e.available else "unavailable" for e in c.engines.describe()}
    return {
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "database": "ok" if db_ok else "error",
        "engines": engines,
        "workers": _workers(c) if db_ok else None,
    }


@router.get("/health/live", summary="Liveness probe (the process is serving requests)")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe (the database is reachable)")
def ready(c: Container = Depends(container)) -> Any:
    if _database_ok(c):
        return {"status": "ok"}
    return JSONResponse({"status": "unavailable"}, status_code=503)


@router.get("/config", summary="Limits and features the frontend should respect")
def config(c: Container = Depends(container)) -> dict[str, Any]:
    s = c.settings
    return {
        "version": APP_VERSION,
        "auth_mode": s.auth_mode,
        "limits": {
            "max_engine_threads": s.max_engine_threads,
            "max_engine_hash_mb": s.max_engine_hash_mb,
            "max_search_depth": s.max_search_depth,
            "max_multipv": s.max_multipv,
            "max_analysis_seconds": s.max_analysis_seconds,
            "max_live_analysis_seconds": s.max_live_analysis_seconds,
            "max_review_movetime_ms": s.max_review_movetime_ms,
            "max_pgn_bytes": s.max_pgn_bytes,
            "max_import_games": s.max_import_games,
            "max_batch_review_games": s.max_batch_review_games,
            "max_games_per_user": s.max_games_per_user,
            "max_reviews_per_day": s.max_reviews_per_day,
        },
        "interactive_engine_pool": s.interactive_engine_pool,
        "providers": [{"id": p.name, "name": p.display_name} for p in c.providers.values()],
    }


@router.get("/engines", response_model=list[EngineDescriptor], summary="Available engines and their status")
def engines(c: Container = Depends(container)) -> list[EngineDescriptor]:
    return c.engines.describe()


@router.get("/engines/levels", summary="Play-strength levels per engine")
def engine_levels(c: Container = Depends(container)) -> dict[str, Any]:
    return c.analysis.levels()


@router.post("/engines/{engine_id}/stop", summary="Stop your current search on this engine")
def stop_engine(
    engine_id: str, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> dict[str, bool]:
    pool = c.engines.pools().get(engine_id)
    return {"stopped": pool.stop(user.id) if pool is not None else False}


@router.get("/engines/custom/evaluate", summary="Static evaluation breakdown from ChessLab's engine")
def custom_evaluate(fen: str = Query(chess.STARTING_FEN, max_length=100)) -> dict[str, Any]:
    board = parse_fen(fen)
    try:
        from chesslab_engine.evaluation import Evaluator
    except ImportError as exc:  # pragma: no cover - depends on installation
        raise EngineUnavailableError("The ChessLab engine package is not installed.") from exc
    breakdown: dict[str, Any] = Evaluator().breakdown(board)
    breakdown["perspective"] = "white"
    return breakdown


@router.get("/settings/engine", response_model=EngineSettings)
def get_engine_settings(c: Container = Depends(container)) -> EngineSettings:
    return c.store.engine()


@router.put("/settings/engine", response_model=EngineSettings, summary="Server-wide engine resources (administrator)")
async def put_engine_settings(
    body: EngineSettings, c: Container = Depends(container), _admin: CurrentUser = Depends(admin_user)
) -> EngineSettings:
    if body.default_engine and not c.engines.is_available(body.default_engine):
        raise InvalidInputError("The selected default engine is not available.", code="engine_unavailable")
    saved = c.store.set_engine(body)
    await c.engines.apply_settings(saved.clamp(c.settings))
    return saved


@router.get("/settings/classification", response_model=ClassificationThresholds)
def get_thresholds(
    c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> ClassificationThresholds:
    return c.store.thresholds(user.id)


@router.put("/settings/classification", response_model=ClassificationThresholds)
def put_thresholds(
    body: ClassificationThresholds, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> ClassificationThresholds:
    return c.store.set_thresholds(user.id, body)


@router.get("/settings/preferences", response_model=Preferences)
def get_preferences(c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> Preferences:
    return c.store.preferences(user.id)


@router.put("/settings/preferences", response_model=Preferences)
def put_preferences(
    body: Preferences, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> Preferences:
    return c.store.set_preferences(user.id, body)


@router.get("/settings/interface", response_model=InterfacePrefs, summary="Theme, feature switches, board look")
def get_interface(c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> InterfacePrefs:
    return c.store.interface(user.id)


@router.put("/settings/interface", response_model=InterfacePrefs)
def put_interface(
    body: InterfacePrefs, c: Container = Depends(container), user: CurrentUser = Depends(current_user)
) -> InterfacePrefs:
    return c.store.set_interface(user.id, body)


class ClientError(BaseModel):
    message: str = Field(max_length=500)
    stack: str | None = Field(None, max_length=4000)
    url: str | None = Field(None, max_length=300)
    component: str | None = Field(None, max_length=2000)


@router.post("/client-errors", status_code=202, summary="Record a crash in the web app (kept in the server log)")
def client_error(body: ClientError, request: Request, c: Container = Depends(container)) -> dict[str, bool]:
    # Written to this server's own log only; never forwarded to any third party.
    c.lookup_limiter.check(f"client-error:{client_key(request)}")
    c.metrics.client_errors.inc()
    client_log.warning(
        "web client error: %s",
        body.message,
        extra={"page": body.url, "component": (body.component or "")[:500], "stack": (body.stack or "")[:4000]},
    )
    return {"recorded": True}
