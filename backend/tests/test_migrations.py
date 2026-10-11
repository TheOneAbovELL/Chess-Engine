"""Database initialisation, safe upgrades and backups."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.util.exc import CommandError
from sqlalchemy import inspect

from app.db.migrate import alembic_config, backup_sqlite, run_migrations
from app.db.session import Database

from .conftest import make_settings


def test_fresh_database_is_created(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.ensure_directories()
    db = Database(settings.resolved_database_url)
    run_migrations(db, settings)
    tables = set(inspect(db.engine).get_table_names())
    assert {"games", "import_jobs", "game_reviews", "position_evaluations", "app_settings", "http_cache"} <= tables
    run_migrations(db, settings)  # idempotent
    assert list(settings.backups_dir.glob("*.db")) == []  # nothing to back up
    db.dispose()


def test_upgrade_backs_up_existing_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.ensure_directories()
    db = Database(settings.resolved_database_url)
    run_migrations(db, settings)
    with db.engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO app_settings (key, value, updated_at) VALUES ('marker', '{}', '2026-01-01 00:00:00')"
        )
        cfg = alembic_config(db.url)
        cfg.attributes["connection"] = conn
        command.downgrade(cfg, "base")  # pretend an older version of the schema
        conn.exec_driver_sql("CREATE TABLE app_settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        conn.exec_driver_sql("INSERT INTO app_settings VALUES ('marker', '{}', '2026-01-01')")
        conn.exec_driver_sql("DELETE FROM alembic_version")  # table survives a downgrade to base
        conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('0000_older')")
    db.dispose()
    db = Database(settings.resolved_database_url)
    with pytest.raises(CommandError):  # unknown revision: alembic refuses, nothing is deleted
        run_migrations(db, settings)
    backups = list(settings.backups_dir.glob("pre-migration-*.db"))
    assert backups, "a backup must be taken before attempting the upgrade"
    with sqlite3.connect(backups[0]) as conn:
        assert conn.execute("SELECT key FROM app_settings").fetchall() == [("marker",)]
    db.dispose()


def test_refuses_unversioned_database_with_tables(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    settings.ensure_directories()
    path = settings.data_dir / "chesslab.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE something (id INTEGER)")
    db = Database(settings.resolved_database_url)
    with pytest.raises(RuntimeError, match="no migration history"):
        run_migrations(db, settings)
    db.dispose()


def test_backup_sqlite_copy(tmp_path: Path) -> None:
    source = tmp_path / "a.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.execute("INSERT INTO t VALUES (42)")
    target = backup_sqlite(source, tmp_path / "backups" / "b.db")
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT x FROM t").fetchone() == (42,)
