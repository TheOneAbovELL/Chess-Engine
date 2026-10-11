"""Move-quality classification (pure functions, fully unit tested).

Algorithm (see docs/game-review.md)
-----------------------------------
For the move played in position P (mover M) leading to position Q:

1. ``best``  = engine evaluation of P (its top line), from M's point of view.
2. ``after`` = engine evaluation of Q, from M's point of view. Both searches
   use the same engine settings, so the comparison is like-for-like.
3. Convert both to *expected score* (0..1, see ``scoring.expected_score``) and
   compute ``loss = max(0, E(best) - E(after))``.
4. Categories:

   * ``forced``     - the only legal move (excluded from statistics)
   * ``best``       - the move is the engine's top choice
   * ``excellent``  - loss <  thresholds.excellent  (default 0.02)
   * ``good``       - loss <  thresholds.good       (default 0.05)
   * ``inaccuracy`` - loss <  thresholds.inaccuracy (default 0.10)
   * ``mistake``    - loss <  thresholds.mistake    (default 0.20)
   * ``blunder``    - otherwise

Expected score handles mates naturally: allowing a forced mate drops it to 0,
and a move that keeps a +9 position at +6 loses almost nothing. These labels
are ChessLab's own; they do not reproduce any other site's classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import chess

from app.services.chess.scoring import centipawns_for_loss, expected_score
from app.services.engine.types import Evaluation
from app.services.settings_store import ClassificationThresholds

CATEGORIES = ("best", "excellent", "good", "inaccuracy", "mistake", "blunder", "forced")
ERROR_CATEGORIES = ("inaccuracy", "mistake", "blunder")


@dataclass(frozen=True)
class MoveVerdict:
    classification: str
    win_loss: float  # expected-score loss for the mover, 0..1
    cp_loss: int  # centipawn loss for the mover (capped, for ACPL)


def classify_move(
    before: Evaluation,
    after: Evaluation,
    mover: chess.Color,
    *,
    played_uci: str,
    best_uci: str | None,
    legal_move_count: int,
    thresholds: ClassificationThresholds,
) -> MoveVerdict:
    e_before = expected_score(before, mover)  # White's expected score, mover to move
    e_after = expected_score(after, not mover)  # White's expected score, opponent to move
    if mover == chess.BLACK:
        e_before, e_after = 1 - e_before, 1 - e_after
    loss = max(0.0, e_before - e_after)

    cp_before = centipawns_for_loss(before, mover)
    cp_after = centipawns_for_loss(after, not mover)
    if mover == chess.BLACK:
        cp_before, cp_after = -cp_before, -cp_after
    cp_loss = max(0, cp_before - cp_after)

    if legal_move_count == 1:
        label = "forced"
    elif best_uci is not None and played_uci == best_uci:
        label = "best"
    elif loss < thresholds.excellent:
        label = "excellent"
    elif loss < thresholds.good:
        label = "good"
    elif loss < thresholds.inaccuracy:
        label = "inaccuracy"
    elif loss < thresholds.mistake:
        label = "mistake"
    else:
        label = "blunder"
    return MoveVerdict(label, round(loss, 4), cp_loss)


def summarize(verdicts: list[tuple[chess.Color, MoveVerdict]]) -> dict[str, Any]:
    """Per-colour counts, average centipawn loss and average expected-score loss."""
    summary: dict[str, Any] = {}
    for color, name in ((chess.WHITE, "white"), (chess.BLACK, "black")):
        mine = [v for c, v in verdicts if c == color]
        counted = [v for v in mine if v.classification != "forced"]
        counts = {category: sum(1 for v in mine if v.classification == category) for category in CATEGORIES}
        summary[name] = {
            "moves": len(mine),
            "counts": counts,
            "acpl": round(sum(v.cp_loss for v in counted) / len(counted), 1) if counted else None,
            "avg_win_loss": round(sum(v.win_loss for v in counted) / len(counted), 4) if counted else None,
        }
    return summary
