"""Standalone background worker: imports, game reviews and maintenance.

    python -m app.worker

Use it when the web processes run with ``CHESSLAB_RUN_WORKERS=false`` (for
example several web replicas behind a proxy). Any number of worker processes
may run against the same database: jobs are claimed atomically, crashed
workers' jobs are re-queued after ``CHESSLAB_JOB_STALE_AFTER_S``, and provider
imports stay one-at-a-time cluster-wide through a database lease.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.core.bootstrap import build_container, shutdown, start_workers
from app.core.config import APP_VERSION, Settings
from app.core.logging import configure_logging

log = logging.getLogger("chesslab.worker")


async def run(settings: Settings, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    container = await build_container(settings)
    start_workers(container)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, stop.set)  # not available on Windows; Ctrl+C still works
    log.info(
        "ChessLab worker started",
        extra={"version": APP_VERSION, "review_workers": settings.review_workers},
    )
    try:
        await stop.wait()
    finally:
        await shutdown(container)
        log.info("ChessLab worker stopped")


def main() -> None:
    settings = Settings()
    configure_logging(settings)
    settings.ensure_directories()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run(settings))


if __name__ == "__main__":
    main()
