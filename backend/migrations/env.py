"""Alembic environment.

The URL comes from ``config.attributes["database_url"]`` when migrations run
inside the app (see app/db/migrate.py), otherwise from ChessLab settings.
``render_as_batch`` lets future migrations ALTER tables on SQLite.
"""

from alembic import context

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import Settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("database_url")
    return url or Settings().resolved_database_url


def run_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    from app.db.migrate import migration_engine

    engine = migration_engine(_url())  # foreign keys off + transactional DDL on SQLite
    with engine.begin() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
