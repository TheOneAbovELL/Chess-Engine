"""Lichess imports end to end (mocked HTTP)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient

from .conftest import LICHESS, SleepRecorder, wait_for
from .helpers import lichess_pgn

USER = "Bob"
EXPORT = f"{LICHESS}/api/games/user/{USER}"
WHEN = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
GAMES = [
    lichess_pgn("AAAAAAAA", "Bob", "Zed", "1-0", WHEN + timedelta(hours=3)),
    lichess_pgn("BBBBBBBB", "Yan", "Bob", "1/2-1/2", WHEN + timedelta(hours=2), event="casual rapid game"),
    lichess_pgn("CCCCCCCC", "Bob", "Xia", "0-1", WHEN + timedelta(hours=1), event="rated bullet game"),
]


def user(router: respx.Router, **extra: Any) -> respx.Route:
    body = {
        "id": "bob",
        "username": USER,
        "url": f"https://lichess.org/@/{USER}",
        "perfs": {"blitz": {"games": 3, "rating": 1700}},
        "count": {"all": 3},
        "createdAt": 1_600_000_000_000,
        **extra,
    }
    return router.get(f"{LICHESS}/api/user/{USER}").mock(return_value=httpx.Response(200, json=body))


def stream(chunks: list[str]) -> httpx.Response:
    async def body() -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield chunk.encode()

    return httpx.Response(200, content=body(), headers={"Content-Type": "application/x-chess-pgn"})


def start(client: TestClient, **params: Any) -> dict[str, Any]:
    body = {"provider": "lichess", "username": USER, "mode": "recent", "max_games": 25, **params}
    response = client.post("/api/v1/imports", json=body)
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    return wait_for(
        lambda: (j := client.get(f"/api/v1/imports/{job_id}").json())["status"] not in ("queued", "running") and j
    )


@respx.mock(assert_all_called=False)
def test_streamed_import_split_across_chunks(client: TestClient, respx_mock: respx.Router) -> None:
    user(respx_mock)
    text = "\n\n".join(GAMES)
    cut1, cut2 = len(GAMES[0]) // 2, len(GAMES[0]) + 10  # chunk borders inside games
    route = respx_mock.get(EXPORT).mock(return_value=stream([text[:cut1], text[cut1:cut2], text[cut2:]]))
    job = start(client, max_games=25)
    assert job["status"] == "completed", job
    assert job["imported"] == 3

    request = route.calls[0].request
    assert request.headers["Accept"] == "application/x-chess-pgn"
    assert "ChessLab" in request.headers["User-Agent"]  # Lichess requires an identifying UA
    assert request.url.params["max"] == "25" and request.url.params["clocks"] == "true"

    items = {g["external_id"]: g for g in client.get("/api/v1/games", params={"source": "lichess"}).json()["items"]}
    assert items["AAAAAAAA"]["user_result"] == "win" and items["AAAAAAAA"]["time_class"] == "blitz"
    assert items["BBBBBBBB"]["rated"] is False and items["BBBBBBBB"]["time_class"] == "rapid"
    assert (
        items["CCCCCCCC"]["user_result"] == "loss"
        and items["CCCCCCCC"]["opening"] == "Sicilian Defense: Najdorf Variation"
    )


@respx.mock(assert_all_called=False)
def test_refresh_requests_only_newer_games(client: TestClient, respx_mock: respx.Router) -> None:
    user(respx_mock)
    route = respx_mock.get(EXPORT).mock(return_value=stream(["\n\n".join(GAMES)]))
    start(client)
    route.mock(return_value=stream([GAMES[0]]))  # the API would only send newer games
    job = start(client, mode="refresh")
    since = int(route.calls[-1].request.url.params["since"])
    newest = WHEN + timedelta(hours=3)
    assert since == int(newest.timestamp() * 1000) + 1
    assert (job["imported"], job["duplicates"]) == (0, 1)


@respx.mock(assert_all_called=False)
def test_filters_are_passed_to_lichess(client: TestClient, respx_mock: respx.Router) -> None:
    user(respx_mock)
    route = respx_mock.get(EXPORT).mock(return_value=stream([GAMES[2]]))
    start(
        client,
        time_classes=["bullet", "ultrabullet"],
        color="white",
        rated=True,
        since="2026-09-01",
        until="2026-10-31",
    )
    params = route.calls[0].request.url.params
    assert params["perfType"] == "bullet,ultraBullet"
    assert params["color"] == "white" and params["rated"] == "true"
    assert int(params["since"]) == int(datetime(2026, 9, 1, tzinfo=UTC).timestamp() * 1000)
    assert int(params["until"]) == int(datetime(2026, 11, 1, tzinfo=UTC).timestamp() * 1000) - 1


@respx.mock(assert_all_called=False)
def test_unknown_and_closed_accounts(client: TestClient, respx_mock: respx.Router) -> None:
    respx_mock.get(f"{LICHESS}/api/user/{USER}").mock(return_value=httpx.Response(404, json={"error": "Not found"}))
    job = start(client)
    assert job["status"] == "failed" and "no player named" in job["message"]

    user(respx_mock, disabled=True)
    job = start(client)
    assert job["status"] == "failed" and "closed" in job["message"]


@respx.mock(assert_all_called=False)
def test_export_404_and_variants(client: TestClient, respx_mock: respx.Router) -> None:
    user(respx_mock)
    respx_mock.get(EXPORT).mock(return_value=httpx.Response(404, text="<html>Page not found</html>"))
    job = start(client)
    assert job["status"] == "failed" and "HTTP 404" in job["message"]

    variant = lichess_pgn("DDDDDDDD", "Bob", "Zed", "1-0", WHEN, variant="Chess960")
    broken = GAMES[0].replace("AAAAAAAA", "EEEEEEEE").replace("1. e4", "1. Ke3")
    respx_mock.get(EXPORT).mock(return_value=stream(["\n\n".join([GAMES[1], variant, broken])]))
    job = start(client)
    assert job["status"] == "partial"
    assert (job["imported"], job["skipped"], job["failed"]) == (1, 1, 1)


@respx.mock(assert_all_called=False)
def test_429_waits_a_full_minute(client: TestClient, respx_mock: respx.Router, sleeps: SleepRecorder) -> None:
    user(respx_mock)
    respx_mock.get(EXPORT).mock(side_effect=[httpx.Response(429), stream([GAMES[0]])])
    job = start(client)
    assert job["status"] == "completed" and job["imported"] == 1
    assert 60 in sleeps.calls


@respx.mock(assert_all_called=False)
def test_lookup_reports_counts_and_notes(client: TestClient, respx_mock: respx.Router) -> None:
    user(respx_mock, tosViolation=True)
    data = client.get(f"/api/v1/providers/lichess/users/{USER}").json()
    assert data["exists"] and data["game_counts"]["all"] == 3
    assert any("terms-of-service" in note for note in data["notes"])
