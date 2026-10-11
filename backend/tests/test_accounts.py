"""Accounts (auth_mode=password): registration, sessions, isolation between users,
claiming local data, password changes, account deletion and data export."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password, password_problems, verify_password
from app.main import create_app
from app.services.auth import SESSION_COOKIE

from .conftest import SleepRecorder, make_settings, provider_factory
from .test_api_games import library, upload

PASSWORD = "correct horse battery"


@pytest.fixture()
def accounts(tmp_path: Path, sleeps: SleepRecorder) -> Iterator[TestClient]:
    settings = make_settings(tmp_path / "data", auth_mode="password", run_workers=False)
    with TestClient(create_app(settings, provider_factory=provider_factory(sleeps))) as client:
        yield client


def register(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    client.cookies.clear()
    response = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def login(client: TestClient, username: str, password: str = PASSWORD) -> None:
    client.cookies.clear()
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def test_password_hashing() -> None:
    stored = hash_password("s3cret-enough")
    assert stored.startswith("scrypt$") and "s3cret-enough" not in stored
    assert verify_password("s3cret-enough", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "garbage")
    assert hash_password("same") != hash_password("same")  # salted
    assert password_problems("short", "bob")
    assert password_problems("password123", "bob")  # common
    assert password_problems("alice-alice", "alice-alice")
    assert password_problems(PASSWORD, "alice") == []


def test_everything_requires_sign_in(accounts: TestClient) -> None:
    session = accounts.get("/api/v1/auth/session").json()
    assert session == {"auth_mode": "password", "user": None, "registration_open": True, "needs_setup": True}
    for method, path in [
        ("get", "/api/v1/games"),
        ("get", "/api/v1/stats/summary"),
        ("get", "/api/v1/imports"),
        ("get", "/api/v1/settings/interface"),
        ("post", "/api/v1/analysis"),
        ("get", "/api/v1/account/export"),
    ]:
        response = getattr(accounts, method)(path, **({"json": {}} if method == "post" else {}))
        assert response.status_code == 401, (path, response.text)
        assert response.json()["error"]["code"] == "auth_required"
    # Public endpoints stay public.
    assert accounts.get("/api/v1/health").status_code == 200
    assert accounts.get("/api/v1/config").status_code == 200


def test_register_login_logout_and_session_cookie(accounts: TestClient) -> None:
    user = register(accounts, "Alice")
    assert user["username"] == "alice" and user["is_admin"] is True  # first account administers
    cookie = accounts.cookies.get(SESSION_COOKIE)
    assert cookie and len(cookie) > 30
    assert accounts.get("/api/v1/auth/session").json()["user"]["username"] == "alice"

    assert accounts.post("/api/v1/auth/logout").json() == {"ok": True}
    accounts.cookies.clear()
    assert accounts.get("/api/v1/auth/session").json()["user"] is None
    # The old token no longer works even if replayed.
    accounts.cookies.set(SESSION_COOKIE, cookie)
    assert accounts.get("/api/v1/games").status_code == 401

    bad = accounts.post("/api/v1/auth/login", json={"username": "alice", "password": "nope-nope-nope"})
    unknown = accounts.post("/api/v1/auth/login", json={"username": "nobody", "password": "nope-nope-nope"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()  # does not reveal which usernames exist
    login(accounts, "ALICE")
    assert accounts.get("/api/v1/games").status_code == 200


def test_registration_rules(accounts: TestClient) -> None:
    register(accounts, "alice")
    accounts.cookies.clear()
    taken = accounts.post("/api/v1/auth/register", json={"username": "Alice", "password": PASSWORD})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "username_taken"
    weak = accounts.post("/api/v1/auth/register", json={"username": "bob", "password": "12345678"})
    assert weak.status_code == 422 and weak.json()["error"]["code"] == "weak_password"
    invalid = accounts.post("/api/v1/auth/register", json={"username": "a b", "password": PASSWORD})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_username"
    second = register(accounts, "bob")
    assert second["is_admin"] is False


def test_failed_logins_are_throttled(accounts: TestClient) -> None:
    register(accounts, "alice")
    accounts.cookies.clear()
    codes = [
        accounts.post("/api/v1/auth/login", json={"username": "alice", "password": f"wrong-{i}-pass"}).status_code
        for i in range(10)
    ]
    assert codes[:8] == [401] * 8 and codes[-1] == 429
    # Even the right password is refused while throttled.
    assert accounts.post("/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}).status_code == 429


def test_users_only_see_their_own_data(accounts: TestClient) -> None:
    register(accounts, "alice")
    upload(accounts, library(4))
    alice_games = accounts.get("/api/v1/games").json()
    assert alice_games["total"] == 4
    game_id = alice_games["items"][0]["id"]
    accounts.put("/api/v1/settings/interface", json={"theme": "light", "experience": "simple"})

    register(accounts, "bob")
    assert accounts.get("/api/v1/games").json()["total"] == 0
    assert accounts.get("/api/v1/stats/summary").json()["totals"]["games"] == 0
    assert accounts.get(f"/api/v1/games/{game_id}").status_code == 404
    assert accounts.get(f"/api/v1/games/{game_id}/pgn").status_code == 404
    assert accounts.delete(f"/api/v1/games/{game_id}").status_code == 404
    assert accounts.post(f"/api/v1/games/{game_id}/review", json={}).status_code == 404
    assert accounts.post("/api/v1/games/delete", json={"ids": [game_id]}).json() == {"deleted": 0}
    assert accounts.delete("/api/v1/data/games", params={"confirm": "DELETE"}).json() == {"deleted": 0}
    assert accounts.get("/api/v1/settings/interface").json()["theme"] == "system"  # bob's own defaults
    # The same PGN can be stored by both users (uniqueness is per user).
    assert upload(accounts, library(4))["imported"] == 4

    login(accounts, "alice")
    assert accounts.get("/api/v1/games").json()["total"] == 4
    assert accounts.get("/api/v1/settings/interface").json()["theme"] == "light"


def test_reviews_and_imports_are_private(accounts: TestClient) -> None:
    register(accounts, "alice")
    upload(accounts, library(2))
    game_id = accounts.get("/api/v1/games").json()["items"][0]["id"]
    review = accounts.post(f"/api/v1/games/{game_id}/review", json={"engine": "custom", "depth": 4}).json()
    job = accounts.post("/api/v1/imports", json={"provider": "lichess", "username": "someone"}).json()

    register(accounts, "bob")
    assert accounts.get(f"/api/v1/reviews/{review['id']}").status_code == 404
    assert accounts.post(f"/api/v1/reviews/{review['id']}/cancel").status_code == 404
    assert accounts.get("/api/v1/reviews/queue").json() == []
    assert accounts.get(f"/api/v1/imports/{job['id']}").status_code == 404
    assert accounts.post(f"/api/v1/imports/{job['id']}/cancel").status_code == 404
    assert accounts.get("/api/v1/imports").json() == []


def test_only_the_admin_changes_engine_resources(accounts: TestClient) -> None:
    register(accounts, "alice")
    current = accounts.get("/api/v1/settings/engine").json()
    assert accounts.put("/api/v1/settings/engine", json=current).status_code == 200
    register(accounts, "bob")
    denied = accounts.put("/api/v1/settings/engine", json=current)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "forbidden"
    assert accounts.post("/api/v1/data/backup").status_code == 403
    info = accounts.get("/api/v1/data/info").json()
    assert info["database_bytes"] is None and info["backups"] == [] and info["can_backup"] is False


def test_change_password_signs_out_other_devices(accounts: TestClient) -> None:
    register(accounts, "alice")
    other_device = accounts.cookies.get(SESSION_COOKIE)
    login(accounts, "alice")
    this_device = accounts.cookies.get(SESSION_COOKIE)
    wrong = accounts.post("/api/v1/auth/password", json={"current_password": "nope", "new_password": "new pass 2026!"})
    assert wrong.status_code == 401
    ok = accounts.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "new pass 2026!"})
    assert ok.status_code == 200
    assert accounts.get("/api/v1/games").status_code == 200  # this device stays signed in
    accounts.cookies.clear()
    accounts.cookies.set(SESSION_COOKIE, other_device)
    assert accounts.get("/api/v1/games").status_code == 401
    assert this_device != other_device
    login(accounts, "alice", "new pass 2026!")


def test_delete_account_removes_all_its_data(accounts: TestClient) -> None:
    register(accounts, "alice")
    upload(accounts, library(3))
    register(accounts, "bob")
    upload(accounts, library(2))
    refused = accounts.post("/api/v1/auth/delete-account", json={"password": "wrong password"})
    assert refused.status_code == 401
    assert accounts.post("/api/v1/auth/delete-account", json={"password": PASSWORD}).status_code == 200
    accounts.cookies.clear()
    assert accounts.post("/api/v1/auth/login", json={"username": "bob", "password": PASSWORD}).status_code == 401

    container = accounts.app.state.container  # type: ignore[attr-defined]
    with container.db.session() as session:
        from sqlalchemy import func, select

        from app.models import Game

        assert session.execute(select(func.count(Game.id))).scalar_one() == 3  # only alice's remain
    login(accounts, "alice")
    assert accounts.get("/api/v1/games").json()["total"] == 3


def test_account_export_zip(accounts: TestClient) -> None:
    register(accounts, "alice")
    upload(accounts, library(3))
    response = accounts.get("/api/v1/account/export")
    assert response.status_code == 200 and response.headers["content-type"] == "application/zip"
    assert "chesslab-alice-" in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert set(archive.namelist()) == {"README.txt", "games.pgn", "reviews.json", "settings.json", "account.json"}
    assert archive.read("games.pgn").decode().count("[Event ") == 3
    assert b"scrypt" not in b"".join(archive.read(n) for n in archive.namelist())  # no password hashes


def test_first_account_claims_existing_local_data(tmp_path: Path, sleeps: SleepRecorder) -> None:
    data = tmp_path / "data"
    with TestClient(create_app(make_settings(data), provider_factory=provider_factory(sleeps))) as local:
        upload(local, library(5))  # single-user mode, no login
    settings = make_settings(data, auth_mode="password", run_workers=False)
    with TestClient(create_app(settings, provider_factory=provider_factory(sleeps))) as client:
        assert client.get("/api/v1/auth/session").json()["needs_setup"] is True
        register(client, "owner")
        assert client.get("/api/v1/games").json()["total"] == 5  # the local library is now owner's
        register(client, "guest")
        assert client.get("/api/v1/games").json()["total"] == 0


def test_registration_can_be_closed(tmp_path: Path, sleeps: SleepRecorder) -> None:
    settings = make_settings(tmp_path / "data", auth_mode="password", allow_registration=False, run_workers=False)
    with TestClient(create_app(settings, provider_factory=provider_factory(sleeps))) as client:
        register(client, "admin")  # the very first account is always allowed
        client.cookies.clear()
        assert client.get("/api/v1/auth/session").json()["registration_open"] is False
        closed = client.post("/api/v1/auth/register", json={"username": "stranger", "password": PASSWORD})
        assert closed.status_code == 403 and closed.json()["error"]["code"] == "registration_closed"


def test_auth_routes_disabled_in_single_user_mode(client: TestClient) -> None:
    assert client.get("/api/v1/auth/session").json()["user"]["username"] == "local"
    response = client.post("/api/v1/auth/register", json={"username": "x-user", "password": PASSWORD})
    assert response.status_code == 409 and response.json()["error"]["code"] == "auth_disabled"
