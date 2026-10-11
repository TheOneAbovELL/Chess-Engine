from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow

LOCAL_USER_ID = 1  # the implicit user of single-user (auth_mode=none) installs


class User(Base):
    """An account. In single-user mode there is exactly one, id 1 ("local"),
    with no password; every row in the database belongs to some user."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)  # stored lower-case
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class UserSession(Base):
    """Server-side login session. Only a SHA-256 hash of the cookie token is
    stored, so a database leak does not leak usable sessions."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user_agent: Mapped[str | None] = mapped_column(String(200))


class Lease(Base):
    """A named, expiring lock shared by every process using the database
    (e.g. "only one import talks to Chess.com/Lichess at a time")."""

    __tablename__ = "leases"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    holder: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class WorkerHeartbeat(Base):
    """Liveness of background-worker processes (used by readiness checks)."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
