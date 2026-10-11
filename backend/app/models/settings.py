from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow


class AppSetting(Base):
    """Small key/value store for user-editable settings (validated by Pydantic
    schemas before they are written)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class HttpCacheEntry(Base):
    """Validators (ETag / Last-Modified) for conditional requests.

    Only stored after a Chess.com monthly archive has been *fully* processed,
    so a ``304 Not Modified`` reliably means "nothing new to import here".
    """

    __tablename__ = "http_cache"

    url: Mapped[str] = mapped_column(String(255), primary_key=True)
    etag: Mapped[str | None] = mapped_column(String(160))
    last_modified: Mapped[str | None] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
