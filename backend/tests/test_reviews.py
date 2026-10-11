"""Game review jobs end to end, using the real custom engine at low depth."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.models import GameReview, PositionEvaluation
from app.models.jobs import RUNNING

from .conftest import wait_for
from .helpers import SCHOLARS_MATE, make_pgn
from .test_engines import needs_stockfish

# Black blunders with 3...Nf6?? allowing Qxf7#.
GAME = make_pgn(SCHOLARS_MATE, {"White": "me", "Black": "them", "Date": "2026.10.01"}, clocks=["0:05:00", "0:04:50"])


def imported_game(client: TestClient) -> int:
    summary = client.post("/api/v1/games/import-pgn", json={"pgn": GAME, "owner": "me"}).json()
    return int(summary["game_ids"][0])


def run_review(client: TestClient, game_id: int, **body: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/games/{game_id}/review", json={"engine": "custom", "depth": 4, "movetime_ms": 3000, **body}
    )
    assert response.status_code == 202, response.text
    review_id = response.json()["id"]
    return wait_for(
        lambda: (
            (r := client.get(f"/api/v1/reviews/{review_id}").json())["status"] in ("completed", "failed", "cancelled")
            and r
        ),
        timeout=120,
    )


def test_full_review(client: TestClient) -> None:
    game_id = imported_game(client)
    review = run_review(client, game_id)
    assert review["status"] == "completed", review
    assert review["progress_done"] == review["progress_total"] == len(SCHOLARS_MATE) + 1

    full = client.get(f"/api/v1/games/{game_id}/review").json()
    positions = full["positions"]
    assert [p["ply"] for p in positions] == list(range(len(SCHOLARS_MATE) + 1))
    assert positions[0]["move_uci"] is None and positions[1]["move_san"] == "e4"
    assert positions[1]["clock_s"] == 300
    final = positions[-1]
    assert final["terminal"] == "checkmate" and final["eval"] == {"cp": None, "mate": 0}
    blunder = positions[6]  # 3...Nf6?? allows mate in one
    assert blunder["move_san"] == "Nf6" and blunder["classification"] == "blunder"
    assert positions[6]["best_move_uci"] == "h7h6" or positions[6]["eval"]["mate"] == 1
    assert positions[7]["classification"] == "best"  # Qxf7# is the engine's choice
    assert review["summary"]["black"]["counts"]["blunder"] >= 1
    assert all(p["lines"] for p in positions[:-1])

    listed = client.get("/api/v1/games", params={"reviewed": True}).json()
    assert listed["total"] == 1 and listed["items"][0]["review"]["status"] == "completed"

    stats = client.get("/api/v1/stats/summary").json()
    assert stats["move_quality"]["reviewed_games"] == 1
    assert stats["move_quality"]["moves"] > 0  # only "me" (White) moves are counted


def test_review_is_reused_unless_forced(client: TestClient) -> None:
    game_id = imported_game(client)
    first = run_review(client, game_id)
    again = client.post(f"/api/v1/games/{game_id}/review", json={"engine": "custom", "depth": 4}).json()
    assert again["id"] == first["id"]
    forced = run_review(client, game_id, force=True)
    assert forced["id"] != first["id"] and forced["status"] == "completed"


def test_reclassify_with_new_thresholds(client: TestClient) -> None:
    game_id = imported_game(client)
    review = run_review(client, game_id)
    client.put(
        "/api/v1/settings/classification", json={"excellent": 0.3, "good": 0.5, "inaccuracy": 0.8, "mistake": 0.99}
    )
    updated = client.post(f"/api/v1/reviews/{review['id']}/reclassify").json()
    assert updated["thresholds"]["mistake"] == 0.99
    assert all(
        p["classification"] != "blunder"
        for p in updated["positions"]
        if p["win_loss"] is not None and p["win_loss"] < 0.99
    )


def test_resume_after_interruption(client: TestClient) -> None:
    container = client.app.state.container
    game_id = imported_game(client)
    client.portal.call(container.reviews.stop)  # simulate the app going down mid-review
    queued = client.post(f"/api/v1/games/{game_id}/review", json={"engine": "custom", "depth": 4}).json()
    with container.db.session() as session:
        review = session.get(GameReview, queued["id"])
        assert review is not None
        review.status = RUNNING
        session.add(
            PositionEvaluation(
                review_id=review.id,
                ply=0,
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                cp=17,
                mate=None,
                best_move_uci="e2e4",
                best_move_san="e4",
                lines=[],
            )
        )
        review.progress_done = 1
    client.portal.call(container.reviews.start)  # restart: recover() re-queues the running review
    done = wait_for(
        lambda: (r := client.get(f"/api/v1/reviews/{queued['id']}").json())["status"] == "completed" and r, timeout=120
    )
    assert done["progress_done"] == len(SCHOLARS_MATE) + 1
    positions = client.get(f"/api/v1/reviews/{queued['id']}", params={"positions": True}).json()["positions"]
    assert positions[0]["eval"]["cp"] == 17  # the stored row was kept, not recomputed


def test_cancel_queued_review_and_retry(client: TestClient) -> None:
    container = client.app.state.container
    game_id = imported_game(client)
    client.portal.call(container.reviews.stop)
    queued = client.post(f"/api/v1/games/{game_id}/review", json={"engine": "custom", "depth": 4}).json()
    assert [r["id"] for r in client.get("/api/v1/reviews/queue").json()] == [queued["id"]]
    cancelled = client.post(f"/api/v1/reviews/{queued['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    retried = client.post(f"/api/v1/reviews/{queued['id']}/retry").json()
    assert retried["status"] == "queued"
    client.portal.call(container.reviews.start)
    done = wait_for(
        lambda: (r := client.get(f"/api/v1/reviews/{queued['id']}").json())["status"] == "completed" and r, timeout=120
    )
    assert done["summary"] is not None


def test_batch_review_and_validation(client: TestClient) -> None:
    game_id = imported_game(client)
    results = client.post(
        "/api/v1/reviews/batch", json={"game_ids": [game_id, 99999], "engine": "custom", "depth": 4}
    ).json()
    assert results[0]["game_id"] == game_id and "error" in results[1]
    assert client.post(f"/api/v1/games/{game_id}/review", json={"depth": 100}).status_code == 422
    assert client.post("/api/v1/games/424242/review", json={}).status_code == 404


def test_deleting_a_game_removes_its_reviews(client: TestClient) -> None:
    game_id = imported_game(client)
    review = run_review(client, game_id)
    client.delete(f"/api/v1/games/{game_id}")
    assert client.get(f"/api/v1/reviews/{review['id']}").status_code == 404


@needs_stockfish
def test_stockfish_review(client: TestClient) -> None:
    game_id = imported_game(client)
    review = run_review(client, game_id, engine="stockfish", depth=10, movetime_ms=1000)
    assert review["status"] == "completed" and review["engine_name"].startswith("Stockfish")
    positions = client.get(f"/api/v1/games/{game_id}/review").json()["positions"]
    assert positions[6]["classification"] == "blunder"
    assert positions[6]["eval"]["mate"] == 1  # after 3...Nf6, White mates in one
