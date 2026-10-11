"""Evaluation conventions shared across the application.

**All scores leaving the backend are from White's point of view.**

* ``cp``: centipawns, positive = White is better.
* ``mate``: moves to mate, positive = White mates, negative = Black mates.
  ``mate == 0`` means the side to move in that position is already checkmated.

Expected score
--------------
To compare positions fairly (a 300cp swing matters at +0.5 but hardly at +9),
the review uses the *expected score* of a centipawn evaluation:

    E(cp) = 1 / (1 + exp(-0.00368208 * cp))

This logistic curve is the one Lichess publishes for its "winning chances"
(``2 * E - 1``). It maps 0cp to 0.5, +100cp to about 0.59 and +300cp to 0.75.
It is a convention, not a law; see docs/game-review.md.
"""

from __future__ import annotations

import math

import chess
import chess.engine

from app.services.engine.types import Evaluation

LOGISTIC_K = 0.00368208
CP_CAP = 1000  # centipawn losses are capped here when averaging (ACPL)


def from_pov_score(score: chess.engine.PovScore) -> Evaluation:
    white = score.white()
    mate = white.mate()
    if mate is not None:
        return Evaluation(cp=None, mate=mate)
    return Evaluation(cp=white.score(), mate=None)


def expected_score(evaluation: Evaluation, turn: chess.Color) -> float:
    """Expected score for White (0..1) of the position with ``turn`` to move."""
    if evaluation.mate is not None:
        if evaluation.mate > 0:
            return 1.0
        if evaluation.mate < 0:
            return 0.0
        return 0.0 if turn == chess.WHITE else 1.0  # side to move is checkmated
    cp = evaluation.cp or 0
    return 1.0 / (1.0 + math.exp(-LOGISTIC_K * cp))


def centipawns_for_loss(evaluation: Evaluation, turn: chess.Color) -> int:
    """White-POV centipawns with mates mapped to +-CP_CAP (for ACPL only)."""
    if evaluation.mate is not None:
        if evaluation.mate > 0:
            return CP_CAP
        if evaluation.mate < 0:
            return -CP_CAP
        return -CP_CAP if turn == chess.WHITE else CP_CAP
    return max(-CP_CAP, min(CP_CAP, evaluation.cp or 0))


def terminal_evaluation(board: chess.Board) -> Evaluation:
    if board.is_checkmate():
        return Evaluation(cp=None, mate=0)
    return Evaluation(cp=0, mate=None)
