"""Apply database migrations safely at startup.

* A brand-new database is created by running all migrations.
* An existing database that is behind the latest revision is **backed up first**
  (``<data_dir>/backups/pre-migration-<rev>-<timestamp>.db``) and then upgraded.
* Nothing is ever dropped or recreated implicitly; startup never deletes data.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.core.config import BACKEND_ROOT, Settings

from .session import Database

log = logging.getLogger("chesslab.db")


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    cfg.attributes["database_url"] = database_url
    return cfg


def sqlite_path(database_url: str) -> Path | None:
    prefix = "sqlite:///"
    if database_url.startswith(prefix) and ":memory:" not in database_url:
        return Path(database_url[len(prefix) :])
    return None


def backup_sqlite(source: Path, destination: Path) -> Path:
    """Consistent online copy using SQLite's backup API (safe while in use)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    # closing(): a sqlite3 connection used as a context manager only commits;
    # it must be closed explicitly or the file (and its WAL) stays open.
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
    return destination


def run_migrations(db: Database, settings: Settings) -> None:
    cfg = alembic_config(db.url)
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with db.engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
        has_tables = bool(inspect(conn).get_table_names())

    if current == head:
        log.info("database schema up to date", extra={"revision": current})
        return

    path = sqlite_path(db.url)
    if current is not None and path is not None and path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = backup_sqlite(path, settings.backups_dir / f"pre-migration-{current}-{stamp}.db")
        log.info("backed up database before migration", extra={"backup": backup.name})
    elif current is None and has_tables:
        # Tables exist but Alembic never ran: refuse rather than risk damage.
        raise RuntimeError(
            "The database contains tables but no migration history. "
            "Back it up and point CHESSLAB_DATABASE_URL at a new file, or stamp it manually."
        )

    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    log.info("database migrated", extra={"from": current, "to": head})
