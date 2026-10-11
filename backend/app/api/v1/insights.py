"""Statistics, the personal opening explorer, and data management."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import admin_user, container, current_user, game_filters
from app.core.container import Container
from app.core.errors import InvalidInputError
from app.db.migrate import backup_sqlite, sqlite_path
from app.repositories.games import GameFilters
from app.services.account import counts, export_archive
from app.services.auth import CurrentUser

from .schemas import UciMove

router = APIRouter()


@router.get("/stats/summary", summary="Dashboard statistics for the filtered games")
def stats_summary(
    filters: GameFilters = Depends(game_filters),
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    return c.stats.summary(user.id, filters)


@router.get("/explorer", summary="Moves you (and opponents) played from a position, with your results")
def explorer(
    fen: str | None = Query(None, max_length=100),
    moves: list[UciMove] = Query(default_factory=list, max_length=60),
    filters: GameFilters = Depends(game_filters),
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, Any]:
    return c.explorer.query(user.id, fen, moves, filters)


@router.get("/data/info", summary="What is stored for you")
def data_info(c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    path = sqlite_path(c.db.url)
    local = not c.settings.multi_user and path is not None
    info: dict[str, Any] = {
        **counts(c.db, user.id),
        "storage": (
            "Local SQLite database in your user data folder (never uploaded)."
            if local
            else "This ChessLab server's database. Only you can see your games."
        ),
        "database_bytes": None,
        "backups": [],
        "can_backup": user.is_admin and path is not None,
    }
    if user.is_admin:
        if path is not None and path.exists():
            info["database_bytes"] = path.stat().st_size
        backups_dir = c.settings.backups_dir
        backups = sorted(backups_dir.glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        info["backups"] = [{"name": b.name, "bytes": b.stat().st_size} for b in backups[:20]]
    return info


@router.post("/data/backup", summary="Create a consistent copy of the SQLite database (administrator)")
def create_backup(c: Container = Depends(container), _admin: CurrentUser = Depends(admin_user)) -> dict[str, Any]:
    path = sqlite_path(c.db.url)
    if path is None or not path.exists():
        raise InvalidInputError(
            "Built-in backups cover the SQLite database. Back up PostgreSQL with pg_dump.", code="backup_unsupported"
        )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_sqlite(path, c.settings.backups_dir / f"chesslab-{stamp}.db")
    return {"name": target.name, "bytes": target.stat().st_size}


@router.get("/account/export", summary="Download everything stored for you (zip)")
async def export_account(c: Container = Depends(container), user: CurrentUser = Depends(current_user)) -> Response:
    data = await asyncio.to_thread(export_archive, c.db, c.games, c.store, user)
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="chesslab-{user.username}-{stamp}.zip"'},
    )


@router.delete("/data/games", summary="Delete ALL of your stored games and reviews")
def delete_all_games(
    confirm: str = Query(..., description="Must be the word DELETE"),
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, int]:
    if confirm != "DELETE":
        raise InvalidInputError("Pass confirm=DELETE to delete every stored game.", code="confirmation_required")
    return {"deleted": c.games.delete_all(user.id)}
