"""Tiny in-memory sliding-window rate limiter.

Adequate for a local, single-process app. A multi-instance deployment would
need a shared store (e.g. Redis); see docs/deployment.md.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from .errors import RateLimitedError


class RateLimiter:
    def __init__(self, limit: int, window_s: float = 60.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] > self.window_s:
                hits.popleft()
            if len(hits) >= self.limit:
                raise RateLimitedError("Too many analysis requests. Please slow down for a moment.")
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory if many distinct clients appear
                self._hits = {k: v for k, v in self._hits.items() if v}
