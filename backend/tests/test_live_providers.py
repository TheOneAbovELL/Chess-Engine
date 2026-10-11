"""Optional live checks against the real public APIs.

Not part of the default run (``-m "not live"`` in pytest config). Run with:

    pytest -m live

They import a handful of games from long-standing public accounts (Chess.com's
"erik" and Lichess's "thibault"), so they need internet access and may fail
if those services are down or rate-limit the network you are on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import make_settings, wait_for

pytestmark = pytest.mark.live


@pytest.fixture()
def live_client(tmp_path: Path) -> Any:
    with TestClient(create_app(make_settings(tmp_path))) as client:  # real providers, real HTTP
        yield client


def run(client: TestClient, **body: Any) -> dict[str, Any]:
    job_id = client.post("/api/v1/imports", json=body).json()["id"]
    return wait_for(
        lambda: (j := client.get(f"/api/v1/imports/{job_id}").json())["status"] not in ("queued", "running") and j,
        timeout=120,
    )


@pytest.mark.parametrize(("provider", "username"), [("chesscom", "erik"), ("lichess", "thibault")])
def test_live_import_and_refresh(live_client: TestClient, provider: str, username: str) -> None:
    lookup = live_client.get(f"/api/v1/providers/{provider}/users/{username}")
    assert lookup.status_code == 200 and lookup.json()["exists"]

    job = run(live_client, provider=provider, username=username, mode="recent", max_games=5)
    assert job["status"] in ("completed", "partial"), job
    assert job["imported"] + job["skipped"] >= 1
    games = live_client.get("/api/v1/games", params={"source": provider}).json()
    assert games["total"] == job["imported"]
    detail = live_client.get(f"/api/v1/games/{games['items'][0]['id']}").json()
    assert detail["moves"] and detail["user_color"] in ("white", "black")

    again = run(live_client, provider=provider, username=username, mode="recent", max_games=5)
    assert again["imported"] == 0 and again["duplicates"] == job["imported"]
    refresh = run(live_client, provider=provider, username=username, mode="refresh", max_games=50)
    assert refresh["status"] in ("completed", "partial")
    assert (
        live_client.get("/api/v1/games", params={"source": provider}).json()["total"]
        == job["imported"] + refresh["imported"]
    )


def test_live_unknown_user(live_client: TestClient) -> None:
    name = "zz-chesslab-no-such-user-9"
    assert live_client.get(f"/api/v1/providers/chesscom/users/{name}").status_code == 404
    assert live_client.get(f"/api/v1/providers/lichess/users/{name}").status_code == 404
