"""Chess.com imports end to end (mocked HTTP; see test_live_providers.py for real calls)."""

from __future__ import annotations

from typing import Any

import httpx
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.models import ImportJob
from app.models.jobs import RUNNING

from .conftest import CHESSCOM, SleepRecorder, provider_factory, wait_for
from .helpers import chesscom_game

USER = "Alice"
OCT = f"{CHESSCOM}/player/alice/games/2026/10"
SEP = f"{CHESSCOM}/player/alice/games/2026/09"
T_OCT = 1_791_000_000  # 2026-10
T_SEP = 1_789_000_000  # 2026-09


def profile(router: respx.Router, status: int = 200) -> respx.Route:
    body = {
        "username": "alice",
        "url": "https://www.chess.com/member/alice",
        "status": "basic",
        "joined": 1_600_000_000,
        "last_online": T_OCT,
    }
    return router.get(f"{CHESSCOM}/player/alice").mock(
        return_value=httpx.Response(status, json=body if status == 200 else {"message": "not found"})
    )


def archives(router: respx.Router, urls: list[str] | Any) -> respx.Route:
    return router.get(f"{CHESSCOM}/player/alice/games/archives").mock(
        return_value=httpx.Response(200, json={"archives": urls})
    )


def month(games: list[dict[str, Any]], etag: str = '"v1"') -> httpx.Response:
    return httpx.Response(
        200, json={"games": games}, headers={"ETag": etag, "Last-Modified": "Mon, 05 Oct 2026 11:37:56 GMT"}
    )


OCT_GAMES = [
    chesscom_game(101, "Alice", "Bob", "1-0", T_OCT + 300),
    chesscom_game(102, "Carol", "Alice", "0-1", T_OCT + 200),
    chesscom_game(103, "Alice", "Dave", "1/2-1/2", T_OCT + 100, time_class="rapid"),
]
SEP_GAMES = [
    chesscom_game(91, "Eve", "Alice", "1-0", T_SEP + 200),
    chesscom_game(92, "Alice", "Frank", "1-0", T_SEP + 100, time_class="bullet"),
]


def start(client: TestClient, **params: Any) -> dict[str, Any]:
    body = {"provider": "chesscom", "username": USER, "mode": "recent", "max_games": 50, **params}
    response = client.post("/api/v1/imports", json=body)
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    return wait_for(
        lambda: (j := client.get(f"/api/v1/imports/{job_id}").json())["status"] not in ("queued", "running") and j
    )


@respx.mock(assert_all_called=False)
def test_recent_import_newest_first(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [SEP, OCT])
    respx_mock.get(OCT).mock(return_value=month(OCT_GAMES))
    respx_mock.get(SEP).mock(return_value=month(SEP_GAMES))

    job = start(client, max_games=4)
    assert job["status"] == "completed", job
    assert (job["discovered"], job["imported"], job["duplicates"], job["failed"]) == (4, 4, 0, 0)

    games = client.get("/api/v1/games", params={"source": "chesscom"}).json()
    assert games["total"] == 4
    ids = {g["external_id"] for g in games["items"]}
    assert ids == {"live/101", "live/102", "live/103", "live/91"}  # newest four
    by_id = {g["external_id"]: g for g in games["items"]}
    assert by_id["live/102"]["user_color"] == "black" and by_id["live/102"]["user_result"] == "win"
    assert by_id["live/103"]["time_class"] == "rapid" and by_id["live/103"]["user_result"] == "draw"
    assert by_id["live/101"]["opening"] == "Ruy Lopez Opening Morphy Defense"
    # The request identified itself, as Chess.com asks.
    assert "ChessLab" in respx_mock.calls[0].request.headers["User-Agent"]

    again = start(client, max_games=4)
    assert again["status"] == "completed"
    assert (again["imported"], again["duplicates"]) == (0, 4)
    assert client.get("/api/v1/games").json()["total"] == 4


@respx.mock(assert_all_called=False)
def test_refresh_uses_conditional_requests(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [SEP, OCT])
    oct_route = respx_mock.get(OCT).mock(return_value=month(OCT_GAMES, etag='"oct1"'))
    respx_mock.get(SEP).mock(return_value=month(SEP_GAMES, etag='"sep1"'))
    assert start(client, max_games=10)["imported"] == 5

    # A new game appears in October; September is unchanged.
    def october(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("If-None-Match") == '"oct1"'
        return month([chesscom_game(104, "Alice", "Gina", "1-0", T_OCT + 400), *OCT_GAMES], etag='"oct2"')

    oct_route.mock(side_effect=october)
    respx_mock.get(SEP).mock(return_value=httpx.Response(304))
    job = start(client, mode="refresh", max_games=100)
    assert job["status"] == "completed", job
    assert job["imported"] == 1 and job["duplicates"] == 3

    # Nothing new at all: the first month answers 304 and the import stops there.
    oct_route.mock(return_value=httpx.Response(304))
    job = start(client, mode="refresh", max_games=100)
    assert (job["status"], job["imported"], job["discovered"]) == ("completed", 0, 0)


@respx.mock(assert_all_called=False)
def test_deleting_games_forgets_validators(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [OCT])
    route = respx_mock.get(OCT).mock(return_value=month(OCT_GAMES, etag='"oct1"'))
    start(client, max_games=10)
    game_id = client.get("/api/v1/games").json()["items"][0]["id"]
    assert client.delete(f"/api/v1/games/{game_id}").status_code == 204

    def october(request: httpx.Request) -> httpx.Response:
        assert "If-None-Match" not in request.headers  # validators were cleared
        return month(OCT_GAMES)

    route.mock(side_effect=october)
    job = start(client, mode="refresh", max_games=10)
    assert job["imported"] == 1  # the deleted game came back


@respx.mock(assert_all_called=False)
def test_unknown_user(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock, status=404)
    job = start(client)
    assert job["status"] == "failed"
    assert "no public player" in job["message"]
    lookup = client.get("/api/v1/providers/chesscom/users/alice")
    assert lookup.status_code == 404 and lookup.json()["error"]["code"] == "provider_not_found"


def test_invalid_username_is_rejected_before_any_request(client: TestClient) -> None:
    response = client.post("/api/v1/imports", json={"provider": "chesscom", "username": "../etc/passwd"})
    assert response.status_code == 422
    assert client.get("/api/v1/providers/chesscom/users/a b").status_code == 422


@respx.mock(assert_all_called=False)
def test_empty_archive(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [])
    job = start(client)
    assert job["status"] == "completed" and job["discovered"] == 0
    assert "No games" in job["message"]


@respx.mock(assert_all_called=False)
def test_malformed_pgn_variant_and_missing_month(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [SEP, OCT])
    broken = chesscom_game(105, "Alice", "Bob", "1-0", T_OCT + 50, pgn='[Event "x"]\n\n1. e4 e5 2. Ke3 *')
    variant = chesscom_game(106, "Alice", "Bob", "1-0", T_OCT + 40, rules="chess960")
    respx_mock.get(OCT).mock(return_value=month([OCT_GAMES[0], broken, variant]))
    respx_mock.get(SEP).mock(return_value=httpx.Response(410))  # gone: skipped, not fatal
    job = start(client)
    assert job["status"] == "partial", job
    assert (job["imported"], job["failed"], job["skipped"]) == (1, 1, 1)
    errors = " ".join(e["error"] for e in job["errors"])
    assert "chess960" in errors and "Could not parse" in errors


@respx.mock(assert_all_called=False)
def test_rate_limit_is_retried_with_backoff(
    client: TestClient, respx_mock: respx.Router, sleeps: SleepRecorder
) -> None:
    profile(respx_mock)
    archives(respx_mock, [OCT])
    respx_mock.get(OCT).mock(side_effect=[httpx.Response(429, headers={"Retry-After": "7"}), month(OCT_GAMES)])
    job = start(client)
    assert job["status"] == "completed" and job["imported"] == 3
    assert 7.0 in sleeps.calls


@respx.mock(assert_all_called=False)
def test_rate_limit_exhausted(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [OCT])
    respx_mock.get(OCT).mock(return_value=httpx.Response(429))
    job = start(client)
    assert job["status"] == "failed" and "rate-limiting" in job["message"]


@respx.mock(assert_all_called=False)
def test_network_errors_and_timeouts(client: TestClient, respx_mock: respx.Router, sleeps: SleepRecorder) -> None:
    respx_mock.get(f"{CHESSCOM}/player/alice").mock(side_effect=httpx.ConnectError("offline"))
    job = start(client)
    assert job["status"] == "failed" and "Could not reach Chess.com" in job["message"]
    assert len(sleeps.calls) == 2  # bounded retries with backoff

    profile(respx_mock)
    archives(respx_mock, [OCT])
    respx_mock.get(OCT).mock(side_effect=httpx.ReadTimeout("slow"))
    job = start(client)
    assert job["status"] == "failed" and "timeout" in job["message"]


@respx.mock(assert_all_called=False)
def test_partial_failure_keeps_imported_games(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [SEP, OCT])
    respx_mock.get(OCT).mock(return_value=month(OCT_GAMES))
    respx_mock.get(SEP).mock(return_value=httpx.Response(500))
    job = start(client)
    assert job["status"] == "partial" and job["imported"] == 3
    assert "3 new games were saved" in job["message"]
    assert client.get("/api/v1/games").json()["total"] == 3


@respx.mock(assert_all_called=False)
def test_unexpected_format(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, "not-a-list")
    job = start(client)
    assert job["status"] == "failed" and "unexpected" in job["message"]


@respx.mock(assert_all_called=False)
def test_filters_and_date_range(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [SEP, OCT])
    respx_mock.get(OCT).mock(return_value=month(OCT_GAMES))
    respx_mock.get(SEP).mock(return_value=month(SEP_GAMES))
    job = start(client, time_classes=["bullet"])
    assert job["imported"] == 1
    job = start(client, color="white", since="2026-10-01")
    assert job["imported"] == 2  # 101 and 103: Alice had White in October


def test_cancel_and_conflicting_jobs(client: TestClient) -> None:
    container = client.app.state.container
    client.portal.call(container.imports.stop)  # keep jobs queued
    first = client.post("/api/v1/imports", json={"provider": "chesscom", "username": USER}).json()
    duplicate = client.post("/api/v1/imports", json={"provider": "chesscom", "username": "ALICE"})
    assert duplicate.status_code == 409
    cancelled = client.post(f"/api/v1/imports/{first['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    retry = client.post(f"/api/v1/imports/{first['id']}/retry")
    assert retry.status_code == 202 and retry.json()["status"] == "queued"


@respx.mock(assert_all_called=False)
def test_interrupted_job_resumes_without_duplicates(client: TestClient, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [OCT])
    respx_mock.get(OCT).mock(return_value=month(OCT_GAMES))
    start(client, max_games=1)  # one game already stored by an earlier run
    container = client.app.state.container
    with container.db.session() as session:
        session.add(
            ImportJob(
                id="interrupted-1",
                provider="chesscom",
                username="alice",
                params={"provider": "chesscom", "username": USER, "mode": "recent", "max_games": 50},
                status=RUNNING,
                errors=[],
            )
        )
    container.imports.recover()  # what happens at startup
    container.imports.notify()
    job = wait_for(lambda: (j := client.get("/api/v1/imports/interrupted-1").json())["status"] == "completed" and j)
    assert (job["imported"], job["duplicates"]) == (2, 1)


@respx.mock(assert_all_called=False)
def test_games_persist_across_restarts(settings: Settings, sleeps: SleepRecorder, respx_mock: respx.Router) -> None:
    profile(respx_mock)
    archives(respx_mock, [OCT])
    respx_mock.get(OCT).mock(return_value=month(OCT_GAMES))
    with TestClient(create_app(settings, provider_factory=provider_factory(sleeps))) as first:
        assert start(first)["imported"] == 3
    with TestClient(create_app(settings, provider_factory=provider_factory(sleeps))) as second:
        assert second.get("/api/v1/games").json()["total"] == 3
        prefs = second.get("/api/v1/settings/preferences").json()
        assert prefs["accounts"] == [{"provider": "chesscom", "username": USER}]


def test_pgn_with_chesscom_link_deduplicates_against_api_import(client: TestClient) -> None:
    pgn = OCT_GAMES[0]["pgn"]
    first = client.post("/api/v1/games/import-pgn", json={"pgn": pgn}).json()
    second = client.post("/api/v1/games/import-pgn", json={"pgn": pgn}).json()
    assert (first["imported"], second["duplicates"]) == (1, 1)
    game = client.get("/api/v1/games").json()["items"][0]
    assert game["source"] == "chesscom" and game["external_id"] == "live/101"


def test_unknown_provider(client: TestClient) -> None:
    assert client.get("/api/v1/providers/nope/users/alice").status_code == 404
    assert client.post("/api/v1/imports", json={"provider": "nope", "username": "alice"}).status_code == 422


@respx.mock(assert_all_called=False)
def test_preview_lists_recent_games_without_importing(client: TestClient, respx_mock: respx.Router) -> None:
    archives(respx_mock, [SEP, OCT])
    respx_mock.get(OCT).mock(return_value=month(OCT_GAMES))
    preview = client.get("/api/v1/providers/chesscom/users/alice/preview", params={"limit": 2}).json()
    assert [p["url"].rsplit("/", 1)[1] for p in preview] == ["101", "102"]
    assert client.get("/api/v1/games").json()["total"] == 0
