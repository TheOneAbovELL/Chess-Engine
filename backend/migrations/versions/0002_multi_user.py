"""multi-user accounts, worker heartbeats, leases

Every existing row is assigned to the implicit local user (id 1), so a
single-user installation keeps all its games, reviews and settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import app.db.base

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UTC_DT = app.db.base.UTCDateTime()
SERVER_WIDE_KEYS = ("engine",)


def _now() -> datetime:
    return datetime.now(UTC)


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTC_DT, nullable=False),
        sa.Column("last_login_at", UTC_DT, nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.bulk_insert(
        users,
        [{"id": 1, "username": "local", "display_name": "You", "password_hash": None, "is_admin": True, "disabled": False, "created_at": _now(), "last_login_at": None}],
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", UTC_DT, nullable=False),
        sa.Column("expires_at", UTC_DT, nullable=False),
        sa.Column("last_seen_at", UTC_DT, nullable=False),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])
    op.create_table(
        "leases",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("holder", sa.String(length=128), nullable=False),
        sa.Column("expires_at", UTC_DT, nullable=False),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_leases")),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("started_at", UTC_DT, nullable=False),
        sa.Column("seen_at", UTC_DT, nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_worker_heartbeats")),
    )

    # --- games: owner, per-user dedupe, opening-book version -------------------
    with op.batch_alter_table("games") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("opening_version", sa.Integer(), nullable=True))
        batch.drop_index("ix_games_owner_played")
        batch.drop_index("ix_games_source_owner")
        batch.drop_constraint("uq_games_source_external_id", type_="unique")
        batch.create_unique_constraint(op.f("uq_games_user_id_source_external_id"), ["user_id", "source", "external_id"])
        batch.create_index("ix_games_user_played", ["user_id", "played_at"])
        batch.create_index("ix_games_user_owner", ["user_id", "source", "owner_username"])
        batch.create_foreign_key(op.f("fk_games_user_id_users"), "users", ["user_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("games") as batch:
        batch.alter_column("user_id", server_default=None)

    # --- jobs: owner + heartbeat ---------------------------------------------------
    with op.batch_alter_table("import_jobs") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("worker_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", UTC_DT, nullable=True))
        batch.create_index(op.f("ix_import_jobs_user_id"), ["user_id"])
        batch.create_foreign_key(op.f("fk_import_jobs_user_id_users"), "users", ["user_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("import_jobs") as batch:
        batch.alter_column("user_id", server_default=None)
        batch.alter_column("attempts", server_default=None)

    with op.batch_alter_table("game_reviews") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("worker_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", UTC_DT, nullable=True))
        batch.create_index(op.f("ix_game_reviews_user_id"), ["user_id"])
        batch.create_foreign_key(op.f("fk_game_reviews_user_id_users"), "users", ["user_id"], ["id"], ondelete="CASCADE")
    with op.batch_alter_table("game_reviews") as batch:
        batch.alter_column("user_id", server_default=None)

    # --- settings: rebuild with a surrogate key and (user_id, key) uniqueness ----
    bind = op.get_bind()
    old_settings = bind.execute(sa.text("SELECT key, value, updated_at FROM app_settings")).all()
    op.drop_table("app_settings")
    settings = op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", UTC_DT, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_app_settings_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_settings")),
        sa.UniqueConstraint("user_id", "key", name=op.f("uq_app_settings_user_id_key")),
    )
    op.create_index(op.f("ix_app_settings_user_id"), "app_settings", ["user_id"])
    if old_settings:
        import json

        rows = []
        for key, value, updated_at in old_settings:
            parsed = json.loads(value) if isinstance(value, str) else value
            rows.append(
                {"user_id": None if key in SERVER_WIDE_KEYS else 1, "key": key, "value": parsed, "updated_at": _now()}
            )
        op.bulk_insert(settings, rows)

    # --- http cache: per-user validators (cache contents are disposable) ---------
    op.drop_table("http_cache")
    op.create_table(
        "http_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=255), nullable=False),
        sa.Column("etag", sa.String(length=160), nullable=True),
        sa.Column("last_modified", sa.String(length=80), nullable=True),
        sa.Column("updated_at", UTC_DT, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_http_cache_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_http_cache")),
        sa.UniqueConstraint("user_id", "url", name=op.f("uq_http_cache_user_id_url")),
    )
    op.create_index(op.f("ix_http_cache_user_id"), "http_cache", ["user_id"])


def downgrade() -> None:
    """Back to single-user. Rows of users other than id 1 are deleted, because
    the old schema cannot tell owners apart (back up first)."""
    bind = op.get_bind()
    for table in ("game_reviews", "import_jobs", "games"):
        bind.execute(sa.text(f"DELETE FROM {table} WHERE user_id <> 1"))  # noqa: S608 - fixed table names

    op.drop_table("http_cache")
    op.create_table(
        "http_cache",
        sa.Column("url", sa.String(length=255), nullable=False),
        sa.Column("etag", sa.String(length=160), nullable=True),
        sa.Column("last_modified", sa.String(length=80), nullable=True),
        sa.Column("updated_at", UTC_DT, nullable=False),
        sa.PrimaryKeyConstraint("url", name=op.f("pk_http_cache")),
    )
    rows = bind.execute(sa.text("SELECT key, value, updated_at FROM app_settings WHERE user_id IS NULL OR user_id = 1")).all()
    op.drop_table("app_settings")
    settings = op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", UTC_DT, nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_app_settings")),
    )
    if rows:
        import json

        op.bulk_insert(settings, [{"key": k, "value": json.loads(v) if isinstance(v, str) else v, "updated_at": _now()} for k, v, _u in rows])

    with op.batch_alter_table("game_reviews") as batch:
        batch.drop_constraint(op.f("fk_game_reviews_user_id_users"), type_="foreignkey")
        batch.drop_index(op.f("ix_game_reviews_user_id"))
        batch.drop_column("heartbeat_at")
        batch.drop_column("worker_id")
        batch.drop_column("user_id")
    with op.batch_alter_table("import_jobs") as batch:
        batch.drop_constraint(op.f("fk_import_jobs_user_id_users"), type_="foreignkey")
        batch.drop_index(op.f("ix_import_jobs_user_id"))
        batch.drop_column("heartbeat_at")
        batch.drop_column("worker_id")
        batch.drop_column("attempts")
        batch.drop_column("user_id")
    with op.batch_alter_table("games") as batch:
        batch.drop_constraint(op.f("fk_games_user_id_users"), type_="foreignkey")
        batch.drop_index("ix_games_user_owner")
        batch.drop_index("ix_games_user_played")
        batch.drop_constraint(op.f("uq_games_user_id_source_external_id"), type_="unique")
        batch.create_unique_constraint("uq_games_source_external_id", ["source", "external_id"])
        batch.create_index("ix_games_source_owner", ["source", "owner_username"])
        batch.create_index("ix_games_owner_played", ["owner_username", "played_at"])
        batch.drop_column("opening_version")
        batch.drop_column("user_id")

    op.drop_table("worker_heartbeats")
    op.drop_table("leases")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
