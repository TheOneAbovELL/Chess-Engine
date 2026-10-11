"""Periodic housekeeping, run by exactly one process at a time (a lease).

* removes expired login sessions;
* names openings of games stored before the current opening book (backfill);
* takes automatic SQLite backups and keeps the newest ``backup_keep``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select

from app.core.config import Settings
from app.db.migrate import backup_sqlite, sqlite_path
from app.db.session import Database
from app.jobs import leases
from app.jobs.worker import new_worker_id
from app.models import Game
from app.services.auth import AuthService
from app.services.chess.openings import BOOK_VERSION, book

log = logging.getLogger("chesslab.maintenance")
LEASE = "maintenance"
AUTO_PREFIX = "auto-"


class MaintenanceTask:
    interval_s = 600.0
    backfill_batch = 500

    def __init__(self, db: Database, settings: Settings, auth: AuthService) -> None:
        self.db = db
        self.settings = settings
        self.auth = auth
        self.holder = new_worker_id("maintenance")
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run(), name="maintenance")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(5)  # let startup finish first
        while True:
            try:
                await asyncio.to_thread(self.run_once)
            except Exception:
                log.exception("maintenance failed")
            await asyncio.sleep(self.interval_s)

    # ------------------------------------------------------------------ work
    def run_once(self) -> dict[str, int]:
        with self.db.session() as session:
            if not leases.acquire(session, LEASE, self.holder, self.interval_s * 2):
                return {}
        done = {"sessions_purged": self.auth.purge_expired_sessions()}
        done["openings_named"] = self.backfill_openings()
        done["backups"] = 1 if self.auto_backup() else 0
        if any(done.values()):
            log.info("maintenance done", extra=done)
        return done

    def backfill_openings(self, limit: int | None = None) -> int:
        """Re-name openings of games stored with an older (or no) book version."""
        total = 0
        remaining = limit
        while remaining is None or remaining > 0:
            batch = self.backfill_batch if remaining is None else min(self.backfill_batch, remaining)
            with self.db.session() as session:
                games = (
                    session.execute(
                        select(Game)
                        .where(or_(Game.opening_version.is_(None), Game.opening_version < BOOK_VERSION))
                        .order_by(Game.id)
                        .limit(batch)
                    )
                    .scalars()
                    .all()
                )
                for game in games:
                    opening = book.classify(game.initial_fen, game.moves_uci.split())
                    if opening is not None:
                        game.eco, game.opening = opening.eco, opening.name
                    game.opening_version = BOOK_VERSION
            total += len(games)
            if remaining is not None:
                remaining -= len(games)
            if len(games) < batch:
                break
        return total

    def auto_backup(self, now: datetime | None = None) -> Path | None:
        if self.settings.backup_interval_hours <= 0:
            return None
        source = sqlite_path(self.db.url)
        if source is None or not source.exists():
            return None  # Postgres: use pg_dump (see docs/deployment.md)
        now = now or datetime.now(UTC)
        directory = self.settings.backups_dir
        existing = sorted(directory.glob(f"{AUTO_PREFIX}*.db")) if directory.exists() else []
        if existing:
            newest = datetime.fromtimestamp(existing[-1].stat().st_mtime, UTC)
            if now - newest < timedelta(hours=self.settings.backup_interval_hours):
                return None
        target = backup_sqlite(source, directory / f"{AUTO_PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}.db")
        existing = sorted(directory.glob(f"{AUTO_PREFIX}*.db"))
        for old in existing[: max(0, len(existing) - self.settings.backup_keep)]:
            old.unlink(missing_ok=True)
        log.info("automatic backup created", extra={"backup": target.name})
        return target
