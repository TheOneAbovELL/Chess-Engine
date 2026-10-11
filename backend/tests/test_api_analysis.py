"""Analysis API: REST analysis, play, comparison, limits, rate limiting and the live WebSocket."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app

from .conftest import SleepRecorder, make_settings, provider_factory
from .test_engines import needs_stockfish


def test_validate_position(client: TestClient) -> None:
    info = client.post(
        "/api/v1/positions/validate", json={"moves": ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"]}
    ).json()
    assert info["is_game_over"] and info["outcome"] == "checkmate" and info["result"] == "1-0"
    assert info["legal_moves"] == []
    start = client.post("/api/v1/positions/validate", json={}).json()
    assert start["turn"] == "white" and len(start["legal_moves"]) == 20
    bad = client.post("/api/v1/positions/validate", json={"moves": ["e2e4", "e2e4"]})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "illegal_move"
    pattern = client.post("/api/v1/positions/validate", json={"moves": ["e2e4; rm -rf /"]})
    assert pattern.status_code == 422


def test_rest_analysis_with_custom_engine(client: TestClient) -> None:
    snap = client.post(
        "/api/v1/analysis", json={"engine": "custom", "depth": 3, "multipv": 2, "moves": ["e2e4"]}
    ).json()
    assert snap["final"] and snap["depth"] == 3 and len(snap["lines"]) == 2
    assert snap["fen"].startswith("rnbqkbnr/pppppppp/8/8/4P3")
    assert snap["lines"][0]["pv_san"][0] in {"e5", "c5", "e6", "d5", "Nf6", "Nc6", "d6", "c6", "g6"}


def test_limits_are_enforced(client: TestClient) -> None:
    too_deep = client.post("/api/v1/analysis", json={"engine": "custom", "depth": 80})
    assert too_deep.status_code == 422 and too_deep.json()["error"]["code"] == "limit_too_high"
    too_long = client.post("/api/v1/analysis", json={"engine": "custom", "movetime_ms": 600_000})
    assert too_long.status_code == 422
    too_many_lines = client.post("/api/v1/analysis", json={"engine": "custom", "multipv": 9})
    assert too_many_lines.status_code == 422
    unknown = client.post("/api/v1/analysis", json={"engine": "komodo"})
    assert unknown.status_code == 422


def test_best_move_and_levels(client: TestClient) -> None:
    levels = client.get("/api/v1/engines/levels").json()
    assert len(levels["stockfish"]) == 10 and len(levels["custom"]) == 6
    move = client.post("/api/v1/analysis/best-move", json={"engine": "custom", "level": 1, "moves": ["e2e4"]}).json()
    assert move["best_move"] and move["best_move_san"]
    over = client.post(
        "/api/v1/analysis/best-move", json={"engine": "custom", "moves": ["f2f3", "e7e5", "g2g4", "d8h4"]}
    )
    assert over.status_code == 422 and over.json()["error"]["code"] == "game_over"
    bad_level = client.post("/api/v1/analysis/best-move", json={"engine": "custom", "level": 9})
    assert bad_level.status_code == 422


def test_compare_reports_each_engine(client: TestClient) -> None:
    results = client.post("/api/v1/analysis/compare", json={"engines": ["custom"], "depth": 2}).json()
    assert results[0]["engine_id"] == "custom" and results[0]["snapshot"]["depth"] == 2


def test_evaluation_breakdown(client: TestClient) -> None:
    data = client.get("/api/v1/engines/custom/evaluate", params={"fen": "4k3/8/8/3P4/8/8/8/4K3 w - - 0 1"}).json()
    assert data["perspective"] == "white" and data["components"]["passed_pawns"] > 0
    assert client.get("/api/v1/engines/custom/evaluate", params={"fen": "bad"}).status_code == 422


def test_rate_limit(tmp_path: Path, sleeps: SleepRecorder) -> None:
    settings = make_settings(tmp_path, analysis_rate_per_minute=2)
    with TestClient(create_app(settings, provider_factory=provider_factory(sleeps))) as client:
        for _ in range(2):
            assert client.post("/api/v1/analysis", json={"engine": "custom", "depth": 1}).status_code == 200
        limited = client.post("/api/v1/analysis", json={"engine": "custom", "depth": 1})
        assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"


def test_stockfish_unavailable_is_reported(tmp_path: Path, sleeps: SleepRecorder) -> None:
    settings = make_settings(tmp_path, stockfish_path=tmp_path / "missing" / "stockfish.exe")
    with TestClient(create_app(settings, provider_factory=provider_factory(sleeps))) as client:
        response = client.post("/api/v1/analysis", json={"engine": "stockfish", "depth": 5})
        assert response.status_code == 503 and response.json()["error"]["code"] == "engine_unavailable"
        assert "install_stockfish" in response.json()["error"]["message"]
        engines = {e["id"]: e for e in client.get("/api/v1/engines").json()}
        assert engines["stockfish"]["available"] is False and "missing" not in (engines["stockfish"]["detail"] or "")


# ------------------------------------------------------------------ WebSocket


def test_live_analysis_stream(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/analysis/live") as ws:
        ws.send_json({"type": "start", "request_id": "r1", "engine": "custom", "depth": 4, "multipv": 2})
        messages = []
        while True:
            message = ws.receive_json()
            messages.append(message)
            if message["type"] in ("done", "error"):
                break
    assert messages[-1]["type"] == "done", messages[-1]
    assert all(m["request_id"] == "r1" for m in messages)
    final = messages[-1]["snapshot"]
    assert final["final"] and final["depth"] == 4 and len(final["lines"]) == 2
    updates = [m for m in messages if m["type"] == "update"]
    assert updates and all(not u["snapshot"]["final"] for u in updates)


def test_live_analysis_stop_and_restart(client: TestClient) -> None:
    kiwipete = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
    with client.websocket_connect("/api/v1/analysis/live") as ws:
        ws.send_json({"type": "start", "request_id": "long", "engine": "custom", "fen": kiwipete})
        first = ws.receive_json()
        assert first["request_id"] == "long"
        # Starting a new analysis stops the old one; its "done" arrives first.
        ws.send_json({"type": "start", "request_id": "short", "engine": "custom", "depth": 2})
        seen: dict[str, dict] = {}
        while "short" not in seen:
            message = ws.receive_json()
            if message["type"] == "done":
                seen[message["request_id"]] = message["snapshot"]
        assert seen["long"]["stop_reason"] == "stopped"
        assert seen["short"]["depth"] == 2

        ws.send_json({"type": "start", "request_id": "again", "engine": "custom", "fen": kiwipete})
        ws.receive_json()
        ws.send_json({"type": "stop"})
        while True:
            message = ws.receive_json()
            if message["type"] == "done":
                assert message["request_id"] == "again" and message["snapshot"]["stop_reason"] == "stopped"
                break


def test_live_analysis_errors(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/analysis/live") as ws:
        ws.send_text("not json")
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "start", "request_id": "x", "fen": "garbage", "engine": "custom"})
        error = ws.receive_json()
        assert error["type"] == "error" and error["code"] == "invalid_fen" and error["request_id"] == "x"
        ws.send_json({"type": "start", "request_id": "y", "depth": 500})
        assert ws.receive_json()["code"] == "validation_error"


def test_live_analysis_rejects_foreign_origin(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/analysis/live", headers={"Origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()


@needs_stockfish
@pytest.mark.stockfish
def test_live_stockfish_analysis(client: TestClient) -> None:
    with client.websocket_connect("/api/v1/analysis/live") as ws:
        ws.send_json(
            {
                "type": "start",
                "request_id": "sf",
                "engine": "stockfish",
                "depth": 14,
                "multipv": 3,
                "moves": ["e2e4", "e7e5"],
            }
        )
        while True:
            message = ws.receive_json()
            if message["type"] == "done":
                break
    snap = message["snapshot"]
    assert snap["engine_name"].startswith("Stockfish") and snap["depth"] >= 14 and len(snap["lines"]) == 3
