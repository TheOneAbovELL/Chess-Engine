from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow


class AppSetting(Base):
    """Small key/value store for settings (validated by Pydantic before writing).

    ``user_id`` is NULL for server-wide settings (engine resources) and set for
    per-user settings (review thresholds, linked accounts, interface).
    """

    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("user_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class HttpCacheEntry(Base):
    """Validators (ETag / Last-Modified) for conditional requests.

    Only stored after a Chess.com monthly archive has been *fully* imported for
    this user, so a ``304 Not Modified`` reliably means "nothing new here".
    """

    __tablename__ = "http_cache"
    __table_args__ = (UniqueConstraint("user_id", "url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(255))
    etag: Mapped[str | None] = mapped_column(String(160))
    last_modified: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
