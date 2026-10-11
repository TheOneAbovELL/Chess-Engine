"""Persistent background-job workers that are safe to run in several processes.

Jobs live in the database (``import_jobs`` / ``game_reviews``):

* **Claiming** uses a conditional ``UPDATE … WHERE status = 'queued'``; only one
  worker's update can succeed for a given job, on SQLite and Postgres alike.
* **Heartbeats**: while a job runs, its worker refreshes ``heartbeat_at``
  every few seconds and its own row in ``worker_heartbeats``.
* **Recovery**: any worker re-queues running jobs whose heartbeat is older
  than ``job_stale_after_s`` (their process crashed or was stopped). Imports are
  idempotent and reviews resume from stored positions, so retrying is safe.

API handlers call :meth:`BackgroundWorker.notify` after enqueuing (when the
worker runs in the same process); otherwise workers poll.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar

from sqlalchemy import func, or_, select, update

from app.db.session import Database
from app.models import WorkerHeartbeat
from app.models.jobs import QUEUED, RUNNING

T = TypeVar("T")
log = logging.getLogger("chesslab.jobs")


def new_worker_id(kind: str, index: int = 0) -> str:
    return f"{socket.gethostname()[:40]}:{os.getpid()}:{kind}:{index}:{uuid.uuid4().hex[:6]}"


def claim(db: Database, model: Any, order_column: Any, worker_id: str, extra_where: Any = None) -> Any | None:
    """Atomically move the oldest queued job to running for this worker."""
    now = datetime.now(UTC)
    with db.session() as session:
        stmt = select(model.id).where(model.status == QUEUED)
        if extra_where is not None:
            stmt = stmt.where(extra_where)
        candidates = session.execute(stmt.order_by(order_column.asc()).limit(5)).scalars().all()
        for job_id in candidates:
            result = session.execute(
                update(model)
                .where(model.id == job_id, model.status == QUEUED)
                .values(
                    status=RUNNING,
                    worker_id=worker_id,
                    heartbeat_at=now,
                    started_at=func.coalesce(model.started_at, now),
                    attempts=model.attempts + 1,
                )
            )
            if result.rowcount == 1:  # type: ignore[attr-defined]
                return job_id
    return None


def requeue_stale(db: Database, model: Any, stale_after_s: float) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_s)
    with db.session() as session:
        result = session.execute(
            update(model)
            .where(model.status == RUNNING, or_(model.heartbeat_at.is_(None), model.heartbeat_at < cutoff))
            .values(status=QUEUED, worker_id=None)
        )
        count = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if count:
        log.warning("re-queued stalled jobs", extra={"table": model.__tablename__, "count": count})
    return count


def touch(db: Database, model: Any, job_id: Any, worker_id: str) -> None:
    with db.session() as session:
        session.execute(
            update(model)
            .where(model.id == job_id, model.worker_id == worker_id, model.status == RUNNING)
            .values(heartbeat_at=datetime.now(UTC))
        )


class BackgroundWorker(ABC, Generic[T]):
    name = "worker"
    kind = "worker"
    poll_interval_s = 5.0
    heartbeat_interval_s = 10.0

    def __init__(self, db: Database, stale_after_s: float = 60.0, index: int = 0) -> None:
        self.db = db
        self.stale_after_s = stale_after_s
        self.index = index
        self.worker_id = new_worker_id(self.kind, index)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._heartbeat: asyncio.Task[None] | None = None
        self._stopping = False
        self.current: T | None = None
        self.peers: list[BackgroundWorker[T]] = []  # same-kind workers in this process

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        self._task = self._loop.create_task(self._run(), name=f"{self.name}-{self.index}")
        self._heartbeat = self._loop.create_task(self._beat(), name=f"{self.name}-{self.index}-heartbeat")

    def notify(self) -> None:
        """Wake the worker (and its peers in this process); safe from any thread."""
        for worker in (self, *self.peers):
            if worker._loop is not None and worker._wake is not None and not worker._loop.is_closed():
                worker._loop.call_soon_threadsafe(worker._wake.set)

    async def stop(self) -> None:
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        for task in (self._task, self._heartbeat):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._task = self._heartbeat = None
        with contextlib.suppress(Exception):
            await asyncio.to_thread(self._forget_heartbeat)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------ heartbeat
    def _record_heartbeat(self) -> None:
        now = datetime.now(UTC)
        with self.db.session() as session:
            row = session.get(WorkerHeartbeat, self.worker_id)
            if row is None:
                session.add(WorkerHeartbeat(worker_id=self.worker_id, kind=self.kind, started_at=now, seen_at=now))
            else:
                row.seen_at = now

    def _forget_heartbeat(self) -> None:
        with self.db.session() as session:
            row = session.get(WorkerHeartbeat, self.worker_id)
            if row is not None:
                session.delete(row)

    async def _beat(self) -> None:
        while not self._stopping:
            try:
                await asyncio.to_thread(self._record_heartbeat)
                if self.current is not None:
                    await asyncio.to_thread(self.touch_job, self.current)
                await asyncio.to_thread(self.renew)
            except Exception:
                log.exception("heartbeat failed", extra={"worker": self.worker_id})
            await asyncio.sleep(self.heartbeat_interval_s)

    # ----------------------------------------------------------------- loop
    async def _run(self) -> None:
        assert self._wake is not None
        while not self._stopping:
            try:
                await asyncio.to_thread(self.requeue)
                job = await asyncio.to_thread(self.claim_next)
            except Exception:
                log.exception("job polling failed", extra={"worker": self.worker_id})
                job = None
            if job is None:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval_s)
                continue
            self.current = job
            try:
                await self.process(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job crashed", extra={"worker": self.name})
                await asyncio.to_thread(self.mark_crashed, job)
            finally:
                self.current = None
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(self.after_job, job)

    # ------------------------------------------------------------ overrides
    @abstractmethod
    def requeue(self) -> None:
        """Re-queue jobs whose worker stopped sending heartbeats."""

    @abstractmethod
    def claim_next(self) -> T | None:
        """Atomically pick the next queued job and mark it running."""

    @abstractmethod
    async def process(self, job: T) -> None: ...

    @abstractmethod
    def mark_crashed(self, job: T) -> None: ...

    @abstractmethod
    def touch_job(self, job: T) -> None: ...

    def renew(self) -> None:
        """Renew leases held while working (optional)."""

    def after_job(self, job: T) -> None:
        """Release per-job resources such as leases (optional)."""
