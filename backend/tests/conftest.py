"""Shared fixtures.

Every test app gets its own temporary data directory and SQLite database, so
tests never touch the real user database. HTTP providers use a no-op sleep so
retry/backoff paths run instantly; respx intercepts all outgoing HTTP.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

# Must happen before ``app.main`` is imported (it builds a default app at import).
_SESSION_DIR = tempfile.mkdtemp(prefix="chesslab-tests-")
os.environ["CHESSLAB_ENVIRONMENT"] = "test"
os.environ["CHESSLAB_DATA_DIR"] = _SESSION_DIR
os.environ["CHESSLAB_SERVE_FRONTEND"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.providers.base import ChessHistoryProvider  # noqa: E402
from app.services.providers.chesscom import ChessComProvider  # noqa: E402
from app.services.providers.http import PoliteClient  # noqa: E402
from app.services.providers.lichess import LichessProvider  # noqa: E402

CHESSCOM = "https://api.chess.com/pub"
LICHESS = "https://lichess.org"
FIXTURES = Path(__file__).parent / "fixtures"


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture()
def sleeps() -> SleepRecorder:
    return SleepRecorder()


def make_settings(data_dir: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "data_dir": data_dir,
        "serve_frontend": False,
        "http_max_retries": 2,
        "engine_idle_shutdown_s": 600,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture()
def settings(data_dir: Path) -> Settings:
    return make_settings(data_dir)


def provider_factory(
    sleeps: SleepRecorder,
) -> Callable[[Settings], tuple[dict[str, ChessHistoryProvider], list[httpx.AsyncClient]]]:
    def factory(settings: Settings) -> tuple[dict[str, ChessHistoryProvider], list[httpx.AsyncClient]]:
        a = httpx.AsyncClient(headers={"User-Agent": settings.user_agent}, timeout=5)
        b = httpx.AsyncClient(headers={"User-Agent": settings.user_agent}, timeout=5)
        providers: dict[str, ChessHistoryProvider] = {
            "chesscom": ChessComProvider(
                PoliteClient(
                    a,
                    provider_name="Chess.com",
                    max_retries=settings.http_max_retries,
                    rate_limit_wait_s=10,
                    sleep=sleeps,
                ),
                settings.chesscom_base_url,
            ),
            "lichess": LichessProvider(
                PoliteClient(
                    b,
                    provider_name="Lichess",
                    max_retries=settings.http_max_retries,
                    rate_limit_wait_s=60,
                    sleep=sleeps,
                ),
                settings.lichess_base_url,
            ),
        }
        return providers, [a, b]

    return factory


@pytest.fixture()
def client(settings: Settings, sleeps: SleepRecorder) -> Iterator[TestClient]:
    app = create_app(settings, provider_factory=provider_factory(sleeps))
    with TestClient(app) as test_client:
        yield test_client


def wait_for(predicate: Callable[[], Any], timeout: float = 30.0, interval: float = 0.1) -> Any:
    """Poll until ``predicate()`` is truthy (background jobs run on the app loop)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met within timeout")


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
