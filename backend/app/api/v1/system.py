"""Health, configuration, engines and settings."""

from __future__ import annotations

from typing import Any

import chess
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.api.deps import container
from app.core.config import APP_VERSION
from app.core.container import Container
from app.core.errors import EngineUnavailableError, InvalidInputError
from app.services.chess.positions import parse_fen
from app.services.engine.types import EngineDescriptor
from app.services.settings_store import ClassificationThresholds, EngineSettings, Preferences

router = APIRouter()


@router.get("/health", summary="Liveness and dependency status")
def health(c: Container = Depends(container)) -> dict[str, Any]:
    db_ok = True
    try:
        with c.db.session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    engines = {e.id: e.status if e.available else "unavailable" for e in c.engines.describe()}
    return {
        "status": "ok" if db_ok else "degraded",
        "version": APP_VERSION,
        "database": "ok" if db_ok else "error",
        "engines": engines,
        "workers": {"imports": c.imports.current is not None, "reviews": c.reviews.current is not None},
    }


@router.get("/config", summary="Limits and features the frontend should respect")
def config(c: Container = Depends(container)) -> dict[str, Any]:
    s = c.settings
    return {
        "version": APP_VERSION,
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
        },
        "providers": [{"id": p.name, "name": p.display_name} for p in c.providers.values()],
    }


@router.get("/engines", response_model=list[EngineDescriptor], summary="Available engines and their status")
def engines(c: Container = Depends(container)) -> list[EngineDescriptor]:
    return c.engines.describe()


@router.get("/engines/levels", summary="Play-strength levels per engine")
def engine_levels(c: Container = Depends(container)) -> dict[str, Any]:
    return c.analysis.levels()


@router.post("/engines/{engine_id}/stop", summary="Stop the engine's current interactive search")
def stop_engine(engine_id: str, c: Container = Depends(container)) -> dict[str, bool]:
    try:
        slot = c.engines.slot(engine_id)
    except EngineUnavailableError:
        return {"stopped": False}
    if slot.current_stop is not None:
        slot.current_stop.request()
        return {"stopped": True}
    return {"stopped": False}


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


@router.put("/settings/engine", response_model=EngineSettings)
async def put_engine_settings(body: EngineSettings, c: Container = Depends(container)) -> EngineSettings:
    if body.default_engine and not c.engines.is_available(body.default_engine):
        raise InvalidInputError("The selected default engine is not available.", code="engine_unavailable")
    saved = c.store.set_engine(body)
    await c.engines.apply_settings(saved.clamp(c.settings))
    return saved


@router.get("/settings/classification", response_model=ClassificationThresholds)
def get_thresholds(c: Container = Depends(container)) -> ClassificationThresholds:
    return c.store.thresholds()


@router.put("/settings/classification", response_model=ClassificationThresholds)
def put_thresholds(body: ClassificationThresholds, c: Container = Depends(container)) -> ClassificationThresholds:
    return c.store.set_thresholds(body)


@router.get("/settings/preferences", response_model=Preferences)
def get_preferences(c: Container = Depends(container)) -> Preferences:
    return c.store.preferences()


@router.put("/settings/preferences", response_model=Preferences)
def put_preferences(body: Preferences, c: Container = Depends(container)) -> Preferences:
    return c.store.set_preferences(body)
