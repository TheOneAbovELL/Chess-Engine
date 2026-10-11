"""Named, expiring locks stored in the database (works on SQLite and Postgres).

Used to make some work cluster-wide singletons, e.g. only one import talks to
Chess.com/Lichess at a time no matter how many worker processes run, and only
one process performs maintenance (backups, session cleanup).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Lease


def acquire(session: Session, name: str, holder: str, ttl_s: float) -> bool:
    """Take (or renew) the lease. Returns False if someone else holds it."""
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=ttl_s)
    result = session.execute(
        update(Lease)
        .where(Lease.name == name, or_(Lease.holder == holder, Lease.expires_at < now))
        .values(holder=holder, expires_at=expires)
    )
    if result.rowcount:  # type: ignore[attr-defined]
        return True
    if session.get(Lease, name) is not None:
        return False
    try:
        with session.begin_nested():
            session.add(Lease(name=name, holder=holder, expires_at=expires))
            session.flush()
    except IntegrityError:
        return False  # another process created it first
    return True


def release(session: Session, name: str, holder: str) -> None:
    session.execute(delete(Lease).where(Lease.name == name, Lease.holder == holder))
