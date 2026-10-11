"""Minimal persistent background-job worker.

Jobs live in the database (``import_jobs`` / ``game_reviews``), so they survive
restarts. Each worker processes one job at a time, which also bounds engine and
network usage. API handlers call :meth:`BackgroundWorker.notify` (thread-safe)
after enqueuing; the worker also polls periodically as a fallback.

A separate broker (Redis + RQ/Celery) is unnecessary for a single-user local
app; docs/architecture.md explains when that would change.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")
log = logging.getLogger("chesslab.jobs")


class BackgroundWorker(ABC, Generic[T]):
    name = "worker"
    poll_interval_s = 5.0

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self.current: T | None = None

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        self._task = self._loop.create_task(self._run(), name=self.name)

    def notify(self) -> None:
        """Wake the worker; safe to call from any thread."""
        if self._loop is not None and self._wake is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._wake.set)

    async def stop(self) -> None:
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None

    async def _run(self) -> None:
        assert self._wake is not None
        await asyncio.to_thread(self.recover)
        while not self._stopping:
            job = await asyncio.to_thread(self.claim_next)
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

    @abstractmethod
    def recover(self) -> None:
        """On startup, re-queue jobs that were running when the app stopped."""

    @abstractmethod
    def claim_next(self) -> T | None:
        """Atomically pick the next queued job and mark it running."""

    @abstractmethod
    async def process(self, job: T) -> None: ...

    @abstractmethod
    def mark_crashed(self, job: T) -> None: ...
