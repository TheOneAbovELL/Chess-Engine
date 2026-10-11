"""A dedicated thread + event loop for engine subprocess I/O.

Why: on Windows, uvicorn runs a ``SelectorEventLoop`` when started with
``--reload``, and that loop cannot spawn subprocesses (``NotImplementedError``).
Running every engine on its own thread with a ``ProactorEventLoop`` makes the
engine layer independent of how the web server was started, and keeps engine
protocol work off the request-handling loop.

All python-chess protocol objects are created and used *only* on this loop.
Callers on other loops use :meth:`EngineRuntime.call`.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")
log = logging.getLogger("chesslab.engine")


class EngineRuntime:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("engine runtime not started")
        return self._loop

    def start(self) -> None:
        if self._thread is not None:
            return

        def run() -> None:
            loop: asyncio.AbstractEventLoop
            if sys.platform == "win32":
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            try:
                loop.run_forever()
            finally:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

        self._thread = threading.Thread(target=run, name="engine-runtime", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)

    async def call(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run ``coro`` on the engine loop and await its result from any loop.
        Cancelling the awaiting task cancels the coroutine on the engine loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return await asyncio.wrap_future(future)

    def call_soon(self, callback: Callable[..., Any], *args: Any) -> None:
        self.loop.call_soon_threadsafe(callback, *args)

    def stop(self) -> None:
        if self._loop is None or self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)
        self._thread = None
        self._loop = None
        self._ready.clear()


class StopSignal:
    """Thread-safe "please stop" flag for a running search.

    The engine side binds a callback once the search has started; requesting a
    stop before that point is remembered and applied as soon as it binds.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requested = False
        self._callback: Callable[[], None] | None = None

    @property
    def requested(self) -> bool:
        return self._requested

    def request(self) -> None:
        with self._lock:
            self._requested = True
            callback = self._callback
        if callback is not None:
            callback()

    def bind(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._callback = callback
            requested = self._requested
        if requested:
            callback()
