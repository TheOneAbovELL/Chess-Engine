"""Statistics verified against small hand-computed datasets."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.statistics.compute import (
    GameFact,
    MoveFact,
    compute_summary,
    confidence,
    opening_family,
    termination_kind,
    wdl,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def game(
    i: int,
    color: str | None,
    result: str | None,
    *,
    tc: str = "blitz",
    opening: str | None = "Italian Game",
    rating: int | None = 1500,
    termination: str = "won by resignation",
    plies: int = 60,
) -> GameFact:
    return GameFact(
        i,
        START + timedelta(days=i),
        "chesscom",
        color,
        result,
        rating,
        1500,
        tc,
        opening,
        "C50",
        plies,
        termination,
        True,
    )


def test_wdl_and_score() -> None:
    games = [game(1, "white", "win"), game(2, "white", "draw"), game(3, "black", "loss"), game(4, None, None)]
    assert wdl(games) == {"games": 3, "wins": 1, "draws": 1, "losses": 1, "score": 0.5}
    assert wdl([])["score"] is None


@pytest.mark.parametrize(
    ("name", "family"),
    [
        ("Sicilian Defense: Najdorf Variation", "Sicilian Defense"),
        ("Sicilian Defense Najdorf Variation", "Sicilian Defense"),
        ("Queen's Gambit Declined: Orthodox", "Queen's Gambit"),
        ("Caro-Kann Defense: Advance Variation", "Caro Kann Defense"),
        ("Ruy Lopez Opening Morphy Defense", "Ruy Lopez Opening"),
        ("Bongcloud", "Bongcloud"),
        (None, None),
    ],
)
def test_opening_family(name: str | None, family: str | None) -> None:
    assert opening_family(name) == family


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("erik won on time", "timeout"),
        ("Time forfeit", "timeout"),
        ("won by checkmate", "checkmate"),
        ("won by resignation", "resignation"),
        ("Game drawn by repetition", "draw"),
        ("Normal", "other"),
        (None, "unknown"),
    ],
)
def test_termination_kind(text: str | None, kind: str) -> None:
    assert termination_kind(text) == kind


def test_confidence_levels() -> None:
    assert [confidence(n) for n in (5, 30, 100)] == ["low", "medium", "high"]


def test_summary_on_known_dataset() -> None:
    games = (
        [game(i, "white", "win") for i in range(6)]
        + [game(10 + i, "white", "loss", tc="bullet") for i in range(2)]
        + [game(20 + i, "black", "draw", opening="Sicilian Defense: Najdorf Variation") for i in range(2)]
        + [
            game(30 + i, "black", "loss", opening="Sicilian Defense: Dragon", termination="lost on time")
            for i in range(3)
        ]
        + [game(40, None, None)]
    )
    summary = compute_summary(games, [])
    totals = summary["totals"]
    assert totals["games"] == 13 and totals["all_games"] == 14 and totals["without_perspective"] == 1
    assert (totals["wins"], totals["draws"], totals["losses"]) == (6, 2, 5)
    assert totals["score"] == pytest.approx(7 / 13, abs=1e-4)
    assert summary["by_color"]["white"]["score"] == 0.75
    assert summary["by_color"]["black"]["score"] == 0.2
    tcs = {r["time_class"]: r for r in summary["by_time_class"]}
    assert tcs["bullet"]["losses"] == 2 and tcs["blitz"]["games"] == 11
    sicilian = next(o for o in summary["openings"] if o["name"] == "Sicilian Defense")
    assert sicilian["games"] == 5 and sicilian["score"] == 0.2  # Najdorf + Dragon grouped
    assert summary["endings"]["timeout"]["loss"] == 3
    assert summary["game_length"]["average_moves"] == 30.0
    kinds = {i["kind"] for i in summary["insights"]}
    assert "opening" in kinds  # 5 games at 20% in the Sicilian
    assert "color" not in kinds  # fewer than 10 games per colour: no colour claim


def test_insights_require_enough_data() -> None:
    few = [game(i, "black", "loss", opening="Dutch Defense") for i in range(4)]
    assert compute_summary(few, [])["insights"] == []


def test_color_insight_and_rating_trend() -> None:
    games = [game(i, "white", "win", rating=1500 + i) for i in range(10)] + [
        game(20 + i, "black", "loss") for i in range(10)
    ]
    summary = compute_summary(games, [])
    color = [i for i in summary["insights"] if i["kind"] == "color"]
    assert color and "Black" in color[0]["title"] and color[0]["sample_size"] == 20
    trend = summary["rating_trend"]["blitz"]
    assert trend[0]["rating"] == 1500 and len(trend) == 20


def test_move_quality_and_phase_insight() -> None:
    def mv(i: int, cls: str, phase: str, *, allowed: bool = False) -> MoveFact:
        return MoveFact(1, i, cls, 0.0, phase, None, None, False, allowed)

    moves = (
        [mv(i, "good", "opening") for i in range(60)]
        + [mv(i, "good", "middlegame") for i in range(55)]
        + [mv(i, "blunder", "endgame", allowed=True) for i in range(12)]
        + [mv(i, "good", "endgame") for i in range(48)]
    )
    summary = compute_summary([game(1, "white", "loss")], moves)
    quality = summary["move_quality"]
    assert quality["moves"] == 175 and quality["counts"]["blunder"] == 12
    assert quality["by_phase"]["endgame"]["rate"] == 0.2
    kinds = {i["kind"] for i in summary["insights"]}
    assert "phase" in kinds and "tactics" in kinds
