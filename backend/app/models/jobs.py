from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow

# Shared job status vocabulary (imports and reviews).
QUEUED, RUNNING, COMPLETED, PARTIAL, FAILED, CANCELLED = (
    "queued",
    "running",
    "completed",
    "partial",
    "failed",
    "cancelled",
)
ACTIVE_STATUSES = (QUEUED, RUNNING)


class ImportJob(Base):
    """A persistent game-history import from a public provider.

    Jobs survive restarts: a job that was running when the app stopped is put
    back in the queue on startup. Imports are idempotent (deduplicated by
    ``(source, external_id)``), so resuming never creates duplicates.
    """

    __tablename__ = "import_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    username: Mapped[str] = mapped_column(String(64), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), index=True, default=QUEUED)
    cancel_requested: Mapped[bool] = mapped_column(default=False)

    discovered: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    phase: Mapped[str | None] = mapped_column(String(160))
    message: Mapped[str | None] = mapped_column(Text)
    errors: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
