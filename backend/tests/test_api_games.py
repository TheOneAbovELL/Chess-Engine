"""Game library API: PGN upload, listing/filtering/pagination, detail, export, delete, errors."""

from __future__ import annotations

from fastapi.testclient import TestClient

from .helpers import OPENINGS, SCHOLARS_MATE, make_pgn


def upload(client: TestClient, pgn: str, owner: str | None = None) -> dict:
    response = client.post("/api/v1/games/import-pgn", json={"pgn": pgn, "owner": owner})
    assert response.status_code == 200, response.text
    return response.json()


def library(n: int = 6) -> str:
    games = []
    for i in range(n):
        white, black = ("me", f"opp{i}") if i % 2 == 0 else (f"opp{i}", "me")
        result = ["1-0", "0-1", "1/2-1/2"][i % 3]
        games.append(
            make_pgn(
                OPENINGS[i % 4],
                {
                    "White": white,
                    "Black": black,
                    "Result": result,
                    "Date": f"2026.0{1 + i}.15",
                    "TimeControl": "600+0" if i < 3 else "180+0",
                    "WhiteElo": str(1400 + 10 * i),
                    "BlackElo": "1450",
                },
            )
        )
    return "\n\n".join(games)


def test_upload_multi_game_pgn_with_duplicates_and_errors(client: TestClient) -> None:
    text = library(4) + "\n\n" + '[Event "broken"]\n\n1. e4 e5 2. Ke3 *' + "\n\n" + library(1)
    summary = upload(client, text, owner="me")
    assert (summary["total"], summary["imported"], summary["duplicates"], summary["failed"]) == (6, 4, 1, 1)
    assert summary["errors"][0]["index"] == 4
    again = upload(client, library(4), owner="me")
    assert again["duplicates"] == 4 and again["imported"] == 0


def test_empty_and_oversized_uploads(client: TestClient) -> None:
    response = client.post("/api/v1/games/import-pgn", json={"pgn": "nothing here"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_pgn"
    huge = client.post(
        "/api/v1/games/import-pgn",
        content=b'{"pgn": "' + b"x" * (7 * 1024 * 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert huge.status_code == 413
    assert huge.json()["error"]["code"] == "payload_too_large"


def test_list_filter_sort_paginate(client: TestClient) -> None:
    upload(client, library(6), owner="me")
    page = client.get("/api/v1/games", params={"page_size": 4}).json()
    assert page["total"] == 6 and len(page["items"]) == 4
    dates = [g["played_at"] for g in page["items"]]
    assert dates == sorted(dates, reverse=True)
    page2 = client.get("/api/v1/games", params={"page_size": 4, "page": 2}).json()
    assert len(page2["items"]) == 2

    assert client.get("/api/v1/games", params={"color": "white"}).json()["total"] == 3
    assert client.get("/api/v1/games", params={"result": "win"}).json()["total"] == 2
    assert client.get("/api/v1/games", params={"time_class": "rapid"}).json()["total"] == 3
    assert client.get("/api/v1/games", params={"q": "OPP3"}).json()["total"] == 1
    assert client.get("/api/v1/games", params={"date_from": "2026-03-01", "date_to": "2026-04-30"}).json()["total"] == 2
    assert client.get("/api/v1/games", params={"min_rating": 1420}).json()["total"] >= 1
    rating_sorted = client.get("/api/v1/games", params={"sort": "rating_desc", "color": "white"}).json()["items"]
    assert rating_sorted[0]["user_rating"] == max(g["user_rating"] for g in rating_sorted)
    assert client.get("/api/v1/games", params={"page_size": 500}).status_code == 422
    assert client.get("/api/v1/games", params={"color": "purple"}).status_code == 422


def test_detail_pgn_export_and_delete(client: TestClient) -> None:
    upload(client, make_pgn(SCHOLARS_MATE, {"White": "me", "Black": "you", "Date": "2026.05.01"}), owner="me")
    game = client.get("/api/v1/games").json()["items"][0]
    detail = client.get(f"/api/v1/games/{game['id']}").json()
    assert [m["san"] for m in detail["moves"]] == SCHOLARS_MATE
    assert detail["moves"][-1]["fen"].startswith("r1bqkb1r/pppp1Qpp")
    assert detail["result"] == "1-0" and detail["user_result"] == "win"

    pgn = client.get(f"/api/v1/games/{game['id']}/pgn")
    assert pgn.headers["content-type"].startswith("application/x-chess-pgn")
    assert "attachment" in pgn.headers["content-disposition"] and "Qxf7#" in pgn.text

    export = client.get("/api/v1/games/export.pgn")
    assert export.text.count("[Event") == 1

    assert client.delete(f"/api/v1/games/{game['id']}").status_code == 204
    missing = client.get(f"/api/v1/games/{game['id']}")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.delete(f"/api/v1/games/{game['id']}").status_code == 404


def test_bulk_delete_and_delete_all_requires_confirmation(client: TestClient) -> None:
    upload(client, library(4))
    ids = [g["id"] for g in client.get("/api/v1/games").json()["items"]]
    assert client.post("/api/v1/games/delete", json={"ids": ids[:2]}).json() == {"deleted": 2}
    assert client.delete("/api/v1/data/games", params={"confirm": "yes"}).status_code == 422
    assert client.delete("/api/v1/data/games", params={"confirm": "DELETE"}).json() == {"deleted": 2}


def test_save_local_game(client: TestClient) -> None:
    pgn = make_pgn(["e4", "e5"], {"White": "You", "Black": "Stockfish"})
    first = client.post("/api/v1/games/save", json={"pgn": pgn, "owner": "You"})
    second = client.post("/api/v1/games/save", json={"pgn": pgn, "owner": "You"})
    assert first.status_code == 201 and second.json()["imported"] == 1  # each save is a new game
    games = client.get("/api/v1/games", params={"source": "local"}).json()
    assert games["total"] == 2 and games["items"][0]["played_at"] is not None


def test_pgn_parse_and_validate_endpoints(client: TestClient) -> None:
    parsed = client.post("/api/v1/pgn/parse", json={"pgn": "1. e4 e5 (1... c5) 2. Nf3 *"}).json()
    assert parsed["games_in_text"] == 1 and len(parsed["nodes"]) == 5
    bad = client.post("/api/v1/pgn/parse", json={"pgn": "1. e4 e4 *"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_pgn"
    report = client.post("/api/v1/pgn/validate", json={"pgn": library(2) + "\n\n1. e4 e4 *"}).json()
    assert report == {"valid_games": 2, "invalid_games": 1, "errors": report["errors"]}


def test_validation_error_envelope(client: TestClient) -> None:
    response = client.post("/api/v1/positions/validate", json={"fen": 5})
    assert response.status_code == 422
    body = response.json()["error"]
    assert body["code"] == "validation_error" and body["details"][0]["loc"][-1] == "fen"
    assert client.get("/api/v1/nope").json()["error"]["code"] == "not_found"


def test_security_headers_and_cors(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    evil = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_health_config_and_data_info(client: TestClient) -> None:
    health = client.get("/api/v1/health").json()
    assert health["status"] == "ok" and health["database"] == "ok"
    config = client.get("/api/v1/config").json()
    assert config["limits"]["max_multipv"] == 5
    assert "path" not in str(config).lower()  # no filesystem paths exposed
    info = client.get("/api/v1/data/info").json()
    assert info["games"] == 0
    backup = client.post("/api/v1/data/backup").json()
    assert backup["name"].startswith("chesslab-") and backup["bytes"] > 0
    assert any(b["name"] == backup["name"] for b in client.get("/api/v1/data/info").json()["backups"])


def test_settings_validation(client: TestClient) -> None:
    engine = client.get("/api/v1/settings/engine").json()
    engine["stockfish_threads"] = 999
    response = client.put("/api/v1/settings/engine", json=engine)
    assert response.status_code == 422 and response.json()["error"]["code"] == "settings_out_of_range"
    bad_thresholds = client.put(
        "/api/v1/settings/classification", json={"excellent": 0.3, "good": 0.1, "inaccuracy": 0.2, "mistake": 0.4}
    )
    assert bad_thresholds.status_code == 422
    ok = client.put(
        "/api/v1/settings/classification", json={"excellent": 0.01, "good": 0.04, "inaccuracy": 0.09, "mistake": 0.18}
    )
    assert ok.json()["mistake"] == 0.18


def test_statistics_and_explorer(client: TestClient) -> None:
    empty = client.get("/api/v1/stats/summary").json()
    assert empty["totals"]["games"] == 0 and empty["insights"] == []
    upload(client, library(6), owner="me")
    stats = client.get("/api/v1/stats/summary").json()
    assert stats["totals"]["games"] == 6
    assert stats["by_color"]["white"]["games"] == 3
    white_only = client.get("/api/v1/stats/summary", params={"color": "white"}).json()
    assert white_only["totals"]["games"] == 3

    root = client.get("/api/v1/explorer").json()
    assert root["total_games"] == 6
    first_moves = {m["san"]: m["games"] for m in root["moves"]}
    assert first_moves == {"e4": 3, "d4": 2, "c4": 1}
    after_e4 = client.get("/api/v1/explorer", params=[("moves", "e2e4")]).json()
    assert {m["san"] for m in after_e4["moves"]} == {"e5", "c5"}
    assert client.get("/api/v1/explorer", params=[("moves", "e2e5")]).status_code == 422
