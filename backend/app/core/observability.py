"""Request IDs, access logging and a small Prometheus-compatible metrics registry.

Metrics stay inside the process: they are only *exposed* at ``/metrics`` for a
scraper the operator runs (optionally protected by a bearer token). Nothing is
ever pushed anywhere.
"""

from __future__ import annotations

import contextvars
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
access_log = logging.getLogger("chesslab.access")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdFilter(logging.Filter):
    """Adds ``request_id`` to every record logged while handling a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = request_id_var.get()
        if rid and not hasattr(record, "request_id"):
            record.request_id = rid
        return True


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(names: tuple[str, ...], values: tuple[str, ...]) -> str:
    if not names:
        return ""
    return "{" + ",".join(f'{n}="{_escape(v)}"' for n, v in zip(names, values, strict=True)) + "}"


class Counter:
    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()) -> None:
        self.name, self.help, self.label_names = name, help_text, labels
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, *labels: str, amount: float = 1.0) -> None:
        with self._lock:
            self._values[labels] = self._values.get(labels, 0.0) + amount

    def value(self, *labels: str) -> float:
        return self._values.get(labels, 0.0)

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        with self._lock:
            for labels, value in sorted(self._values.items()):
                yield f"{self.name}{_labels(self.label_names, labels)} {value}"


class Histogram:
    BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

    def __init__(self, name: str, help_text: str, labels: tuple[str, ...] = ()) -> None:
        self.name, self.help, self.label_names = name, help_text, labels
        self._data: dict[tuple[str, ...], tuple[list[int], float, int]] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, *labels: str) -> None:
        with self._lock:
            buckets, total, count = self._data.get(labels, ([0] * len(self.BUCKETS), 0.0, 0))
            for i, bound in enumerate(self.BUCKETS):
                if value <= bound:
                    buckets[i] += 1
            self._data[labels] = (buckets, total + value, count + 1)

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} histogram"
        with self._lock:
            for labels, (buckets, total, count) in sorted(self._data.items()):
                for bound, n in zip(self.BUCKETS, buckets, strict=True):
                    lbl = _labels((*self.label_names, "le"), (*labels, str(bound)))
                    yield f"{self.name}_bucket{lbl} {n}"
                yield f"{self.name}_bucket{_labels((*self.label_names, 'le'), (*labels, '+Inf'))} {count}"
                yield f"{self.name}_sum{_labels(self.label_names, labels)} {total}"
                yield f"{self.name}_count{_labels(self.label_names, labels)} {count}"


GaugeCollector = Callable[[], Iterable[tuple[str, str, dict[str, str], float]]]


class Metrics:
    def __init__(self) -> None:
        self.requests = Counter("chesslab_http_requests_total", "HTTP requests", ("method", "route", "status"))
        self.latency = Histogram("chesslab_http_request_seconds", "HTTP request latency", ("route",))
        self.client_errors = Counter("chesslab_client_errors_total", "Errors reported by the web client")
        self._collectors: list[GaugeCollector] = []

    def add_collector(self, collector: GaugeCollector) -> None:
        self._collectors.append(collector)

    def render(self) -> str:
        lines: list[str] = []
        for metric in (self.requests, self.latency, self.client_errors):
            lines.extend(metric.render())
        seen: set[str] = set()
        for collector in self._collectors:
            try:
                samples = list(collector())
            except Exception:  # a broken collector must not break scraping
                logging.getLogger("chesslab.metrics").exception("metrics collector failed")
                continue
            for name, help_text, labels, value in samples:
                if name not in seen:
                    seen.add(name)
                    lines += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
                names = tuple(labels)
                lines.append(f"{name}{_labels(names, tuple(labels[n] for n in names))} {value}")
        return "\n".join(lines) + "\n"


def route_template(scope: Scope) -> str:
    """The matched route pattern (``/api/v1/games/{game_id}``), never the raw
    path, so metrics have bounded cardinality and contain no identifiers."""
    raw = str(scope.get("path", ""))
    route = getattr(scope.get("route"), "path", None)
    if not isinstance(route, str) or ":path" in route:
        return "/api/other" if raw.startswith("/api/") else "/static"
    # Nested routers report the path relative to their prefix; API path
    # parameters are single segments, so the prefix is the leading remainder.
    segments = [p for p in raw.split("/") if p]
    relative = [p for p in route.split("/") if p]
    prefix = segments[: max(0, len(segments) - len(relative))]
    return "/" + "/".join([*prefix, *relative])


class RequestContextMiddleware:
    """Assigns/propagates ``X-Request-ID``, logs one access line per request
    and records request metrics."""

    def __init__(self, app: ASGIApp, metrics: Metrics | None = None) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"x-request-id"), "")
        rid = incoming if _SAFE_ID.fullmatch(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                message["headers"] = [*message.get("headers", []), (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            elapsed = time.perf_counter() - started
            route = route_template(scope)
            if self.metrics is not None:
                self.metrics.requests.inc(scope.get("method", "GET"), route, str(status))
                self.metrics.latency.observe(elapsed, route)
            path = str(scope.get("path", ""))
            if path.startswith("/api/") and not path.startswith("/api/v1/health"):
                access_log.info(
                    "%s %s %s",
                    scope.get("method"),
                    route,
                    status,
                    extra={"status": status, "ms": round(elapsed * 1000, 1)},
                )
            request_id_var.reset(token)


def install_request_id_logging() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
            handler.addFilter(RequestIdFilter())
