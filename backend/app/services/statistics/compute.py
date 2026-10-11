"""Pure statistics over stored games and reviewed moves.

Everything here is a plain function of its inputs (no database, no I/O) so the
calculations can be verified against small hand-made datasets in tests.

*Measured* figures (counts, scores, averages) are reported as such. *Inferred*
observations ("insights") always carry their sample size and a confidence
level, and are worded as potential patterns, never as verdicts.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

ERROR_CLASSES = ("inaccuracy", "mistake", "blunder")
MOVE_CLASSES = ("best", "excellent", "good", "inaccuracy", "mistake", "blunder")


@dataclass(frozen=True)
class GameFact:
    id: int
    played_at: datetime | None
    source: str
    user_color: str | None
    user_result: str | None
    user_rating: int | None
    opponent_rating: int | None
    time_class: str
    opening: str | None
    eco: str | None
    ply_count: int
    termination: str | None
    rated: bool | None


@dataclass(frozen=True)
class MoveFact:
    game_id: int
    ply: int
    classification: str
    win_loss: float
    phase: str  # opening / middlegame / endgame
    clock_s: float | None
    base_time_s: float | None  # initial clock of the game, if known
    missed_tactic: bool  # engine's best move was a capture/check/mate the player didn't play
    allowed_tactic: bool  # the opponent's best reply is a capture/check/mate


def _score(w: int, d: int, n: int) -> float | None:
    return round((w + 0.5 * d) / n, 4) if n else None


def wdl(games: list[GameFact]) -> dict[str, Any]:
    known = [g for g in games if g.user_result in ("win", "loss", "draw")]
    w = sum(g.user_result == "win" for g in known)
    d = sum(g.user_result == "draw" for g in known)
    losses = sum(g.user_result == "loss" for g in known)
    return {"games": len(known), "wins": w, "draws": d, "losses": losses, "score": _score(w, d, len(known))}


def opening_family(name: str | None) -> str | None:
    """Group opening names into families.

    Lichess: "Sicilian Defense: Najdorf Variation" -> "Sicilian Defense".
    Chess.com slugs: "Sicilian Defense Najdorf Variation" -> words up to the
    first family keyword (Defense, Opening, Game, Gambit, Attack, System...).
    This is a heuristic; unusual names fall back to their first three words.
    """
    if not name:
        return None
    base = re.split(r"[:,]", name)[0].strip()
    words = base.replace("-", " ").split()
    keywords = {"defense", "defence", "opening", "game", "gambit", "attack", "system", "countergambit"}
    for i, word in enumerate(words):
        if word.lower() in keywords:
            return " ".join(words[: i + 1])
    return " ".join(words[:3]) or None


def _family_key(name: str) -> str:
    return name.lower().replace("'", "").replace("-", " ")


TERMINATION_PATTERNS = [
    ("timeout", re.compile(r"time|timeout|flag", re.I)),
    ("checkmate", re.compile(r"checkmate|mate\b", re.I)),
    ("resignation", re.compile(r"resign", re.I)),
    ("abandoned", re.compile(r"abandon", re.I)),
    ("draw", re.compile(r"draw|stalemate|repetition|agreement|insufficient|50|fifty", re.I)),
]


def termination_kind(text: str | None) -> str:
    if not text:
        return "unknown"
    for kind, pattern in TERMINATION_PATTERNS:
        if pattern.search(text):
            return kind
    return "other"  # e.g. Lichess "Normal" (mate or resignation, not distinguishable)


def confidence(n: int) -> str:
    return "high" if n >= 100 else "medium" if n >= 30 else "low"


def compute_summary(games: list[GameFact], moves: list[MoveFact]) -> dict[str, Any]:
    ordered = sorted(games, key=lambda g: (g.played_at is None, g.played_at or datetime.min))
    perspective = [g for g in ordered if g.user_color]

    by_color = {color: wdl([g for g in perspective if g.user_color == color]) for color in ("white", "black")}

    tc_groups: dict[str, list[GameFact]] = defaultdict(list)
    for g in perspective:
        tc_groups[g.time_class].append(g)
    by_time_class = sorted(
        ({"time_class": tc, **wdl(gs)} for tc, gs in tc_groups.items()), key=lambda r: r["games"], reverse=True
    )

    # Rating trend per time class: the user's own rating as recorded in each game.
    rating_trend: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for g in perspective:
        if g.user_rating and g.played_at:
            rating_trend[g.time_class].append({"date": g.played_at, "rating": g.user_rating, "game_id": g.id})
    for tc, points in rating_trend.items():
        if len(points) > 400:  # keep payloads small; keep first/last exact
            step = len(points) / 400
            rating_trend[tc] = [points[int(i * step)] for i in range(400)] + [points[-1]]

    families: dict[str, dict[str, Any]] = {}
    for g in perspective:
        family = opening_family(g.opening)
        if not family:
            continue
        entry = families.setdefault(_family_key(family), {"name": family, "games": []})
        entry["games"].append(g)
    openings = []
    for entry in families.values():
        stats = wdl(entry["games"])
        as_white = wdl([g for g in entry["games"] if g.user_color == "white"])
        as_black = wdl([g for g in entry["games"] if g.user_color == "black"])
        openings.append({"name": entry["name"], **stats, "as_white": as_white, "as_black": as_black})
    openings.sort(key=lambda r: r["games"], reverse=True)

    lengths = [g.ply_count for g in perspective if g.ply_count]
    length_by_result = {}
    for result in ("win", "draw", "loss"):
        values = [g.ply_count for g in perspective if g.user_result == result and g.ply_count]
        length_by_result[result] = round(sum(values) / len(values) / 2, 1) if values else None

    endings: dict[str, dict[str, int]] = defaultdict(lambda: {"win": 0, "loss": 0, "draw": 0})
    for g in perspective:
        if g.user_result:
            endings[termination_kind(g.termination)][g.user_result] += 1

    recent = perspective[-20:]
    previous = perspective[-40:-20]

    move_counts = {c: sum(1 for m in moves if m.classification == c) for c in MOVE_CLASSES}
    move_total = sum(move_counts.values())

    return {
        "totals": {
            **wdl(perspective),
            "all_games": len(games),
            "without_perspective": len(games) - len(perspective),
            "first_game": ordered[0].played_at if ordered else None,
            "last_game": ordered[-1].played_at if ordered else None,
        },
        "by_color": by_color,
        "by_time_class": by_time_class,
        "rating_trend": dict(rating_trend),
        "openings": openings[:20],
        "game_length": {
            "average_moves": round(sum(lengths) / len(lengths) / 2, 1) if lengths else None,
            "by_result": length_by_result,
        },
        "endings": dict(endings),
        "recent": {"last_20": wdl(recent), "previous_20": wdl(previous)},
        "move_quality": {
            "reviewed_games": len({m.game_id for m in moves}),
            "moves": move_total,
            "counts": move_counts,
            "by_phase": _errors_by_phase(moves),
        },
        "insights": insights(perspective, moves, by_color, openings, endings, by_time_class),
    }


def _errors_by_phase(moves: list[MoveFact]) -> dict[str, Any]:
    result = {}
    for phase in ("opening", "middlegame", "endgame"):
        phase_moves = [m for m in moves if m.phase == phase]
        errors = [m for m in phase_moves if m.classification in ("mistake", "blunder")]
        result[phase] = {
            "moves": len(phase_moves),
            "mistakes_and_blunders": len(errors),
            "rate": round(len(errors) / len(phase_moves), 4) if phase_moves else None,
        }
    return result


def insights(
    games: list[GameFact],
    moves: list[MoveFact],
    by_color: dict[str, dict[str, Any]],
    openings: list[dict[str, Any]],
    endings: dict[str, dict[str, int]],
    by_time_class: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Potential patterns, each with its evidence. Thresholds are deliberately
    conservative and every item states its sample size."""
    found: list[dict[str, Any]] = []

    def add(kind: str, title: str, detail: str, n: int) -> None:
        found.append({"kind": kind, "title": title, "detail": detail, "sample_size": n, "confidence": confidence(n)})

    w, b = by_color["white"], by_color["black"]
    if w["games"] >= 10 and b["games"] >= 10 and w["score"] is not None and b["score"] is not None:
        gap = w["score"] - b["score"]
        if abs(gap) >= 0.15:
            weaker = "Black" if gap > 0 else "White"
            add(
                "color",
                f"Results are noticeably weaker with {weaker}",
                f"Score {w['score']:.0%} with White vs {b['score']:.0%} with Black.",
                w["games"] + b["games"],
            )

    for opening in openings:
        if opening["games"] >= 5 and opening["score"] is not None and opening["score"] <= 0.35:
            add(
                "opening",
                f"Low score in the {opening['name']}",
                f"{opening['score']:.0%} over {opening['games']} games "
                f"({opening['wins']}W {opening['draws']}D {opening['losses']}L).",
                opening["games"],
            )

    total_losses = sum(e["loss"] for e in endings.values())
    timeouts = endings.get("timeout", {}).get("loss", 0)
    if total_losses >= 10 and timeouts / total_losses >= 0.3:
        add(
            "time",
            "Many losses come from running out of time",
            f"{timeouts} of {total_losses} losses ({timeouts / total_losses:.0%}) ended on time.",
            total_losses,
        )

    rated_tc = [r for r in by_time_class if r["games"] >= 10 and r["score"] is not None]
    if len(rated_tc) >= 2:
        worst = min(rated_tc, key=lambda r: r["score"])
        best = max(rated_tc, key=lambda r: r["score"])
        if best["score"] - worst["score"] >= 0.15:
            add(
                "time_control",
                f"{worst['time_class'].title()} is your weakest time control",
                f"{worst['score']:.0%} in {worst['time_class']} vs {best['score']:.0%} in {best['time_class']}.",
                worst["games"] + best["games"],
            )

    if moves:
        phase_rates = _errors_by_phase(moves)
        rated = {p: v for p, v in phase_rates.items() if v["moves"] >= 50 and v["rate"] is not None}
        if len(rated) >= 2:
            worst_phase = max(rated, key=lambda p: rated[p]["rate"])
            others = [v["rate"] for p, v in rated.items() if p != worst_phase]
            if rated[worst_phase]["rate"] >= 1.5 * max(others) and rated[worst_phase]["mistakes_and_blunders"] >= 5:
                add(
                    "phase",
                    f"Mistakes cluster in the {worst_phase}",
                    f"{rated[worst_phase]['rate']:.1%} of {worst_phase} moves were mistakes or blunders "
                    f"(other phases: {', '.join(f'{r:.1%}' for r in others)}).",
                    rated[worst_phase]["moves"],
                )

        errors = [m for m in moves if m.classification in ("mistake", "blunder")]
        if len(errors) >= 10:
            allowed = sum(m.allowed_tactic for m in errors)
            missed = sum(m.missed_tactic for m in errors)
            if allowed / len(errors) >= 0.5:
                add(
                    "tactics",
                    "Errors often allow a forcing reply",
                    f"In {allowed} of {len(errors)} mistakes/blunders the opponent's best answer "
                    "was a capture, check or mate. "
                    "Checking the opponent's forcing moves before moving may help.",
                    len(errors),
                )
            if missed / len(errors) >= 0.4:
                add(
                    "tactics",
                    "Forcing moves are sometimes missed",
                    f"In {missed} of {len(errors)} mistakes/blunders the engine's choice was a capture, check or mate.",
                    len(errors),
                )

        timed = [m for m in moves if m.clock_s is not None and m.base_time_s]
        if len(timed) >= 100:
            low = [m for m in timed if m.clock_s is not None and m.base_time_s and m.clock_s < 0.1 * m.base_time_s]
            normal = [m for m in timed if m not in low]
            if len(low) >= 20 and normal:
                low_rate = sum(m.classification in ("mistake", "blunder") for m in low) / len(low)
                normal_rate = sum(m.classification in ("mistake", "blunder") for m in normal) / len(normal)
                if low_rate >= 2 * normal_rate and low_rate >= 0.1:
                    add(
                        "time_pressure",
                        "Accuracy drops under time pressure",
                        f"With under 10% of the clock left, {low_rate:.0%} of moves were mistakes/blunders "
                        f"vs {normal_rate:.0%} otherwise.",
                        len(low),
                    )
    return found
