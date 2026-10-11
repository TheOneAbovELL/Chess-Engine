"""Statistics, the personal opening explorer, and local data management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import container, game_filters
from app.core.container import Container
from app.core.errors import InvalidInputError
from app.db.migrate import backup_sqlite, sqlite_path
from app.models import Game, GameReview, ImportJob
from app.repositories.games import GameFilters

from .schemas import UciMove

router = APIRouter()


@router.get("/stats/summary", summary="Dashboard statistics for the filtered games")
def stats_summary(filters: GameFilters = Depends(game_filters), c: Container = Depends(container)) -> dict[str, Any]:
    return c.stats.summary(filters)


@router.get("/explorer", summary="Moves you (and opponents) played from a position, with your results")
def explorer(
    fen: str | None = Query(None, max_length=100),
    moves: list[UciMove] = Query(default_factory=list, max_length=60),
    filters: GameFilters = Depends(game_filters),
    c: Container = Depends(container),
) -> dict[str, Any]:
    return c.explorer.query(fen, moves, filters)


@router.get("/data/info", summary="What is stored locally")
def data_info(c: Container = Depends(container)) -> dict[str, Any]:
    with c.db.session() as session:
        games = session.execute(select(func.count(Game.id))).scalar_one()
        reviews = session.execute(
            select(func.count(GameReview.id)).where(GameReview.status == "completed")
        ).scalar_one()
        imports = session.execute(select(func.count(ImportJob.id))).scalar_one()
    path = sqlite_path(c.db.url)
    backups = sorted(c.settings.backups_dir.glob("*.db"), reverse=True) if c.settings.backups_dir.exists() else []
    return {
        "games": games,
        "completed_reviews": reviews,
        "import_jobs": imports,
        "database_bytes": path.stat().st_size if path and path.exists() else None,
        "storage": "Local SQLite database in your user data folder (never uploaded).",
        "backups": [{"name": b.name, "bytes": b.stat().st_size} for b in backups[:20]],
    }


@router.post("/data/backup", summary="Create a consistent copy of the local database")
def create_backup(c: Container = Depends(container)) -> dict[str, Any]:
    path = sqlite_path(c.db.url)
    if path is None or not path.exists():
        raise InvalidInputError("Backups are only available for the local SQLite database.", code="backup_unsupported")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_sqlite(path, c.settings.backups_dir / f"chesslab-{stamp}.db")
    return {"name": target.name, "bytes": target.stat().st_size}


@router.delete("/data/games", summary="Delete ALL stored games and reviews")
def delete_all_games(
    confirm: str = Query(..., description="Must be the word DELETE"), c: Container = Depends(container)
) -> dict[str, int]:
    if confirm != "DELETE":
        raise InvalidInputError("Pass confirm=DELETE to delete every stored game.", code="confirmation_required")
    return {"deleted": c.games.delete_all()}
