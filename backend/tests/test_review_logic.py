"""Evaluation conventions and move classification (pure logic)."""

from __future__ import annotations

import chess
import pytest
from pydantic import ValidationError

from app.services.chess.scoring import centipawns_for_loss, expected_score, from_pov_score, terminal_evaluation
from app.services.engine.types import Evaluation
from app.services.review.classification import MoveVerdict, classify_move, summarize
from app.services.settings_store import ClassificationThresholds

T = ClassificationThresholds()


def ev(cp: int | None = None, mate: int | None = None) -> Evaluation:
    return Evaluation(cp=cp, mate=mate)


def test_expected_score_curve() -> None:
    assert expected_score(ev(0), chess.WHITE) == pytest.approx(0.5)
    assert expected_score(ev(100), chess.WHITE) == pytest.approx(0.5910, abs=1e-4)
    assert expected_score(ev(-300), chess.BLACK) == pytest.approx(1 - expected_score(ev(300), chess.WHITE))
    assert expected_score(ev(mate=3), chess.BLACK) == 1.0
    assert expected_score(ev(mate=-2), chess.WHITE) == 0.0
    # mate == 0: the side to move is checkmated.
    assert expected_score(ev(mate=0), chess.WHITE) == 0.0
    assert expected_score(ev(mate=0), chess.BLACK) == 1.0


def test_pov_scores_are_normalised_to_white() -> None:
    import chess.engine

    black_winning = chess.engine.PovScore(chess.engine.Cp(250), chess.BLACK)
    assert from_pov_score(black_winning) == ev(cp=-250)
    assert from_pov_score(chess.engine.PovScore(chess.engine.Mate(2), chess.BLACK)) == ev(mate=-2)


def test_terminal_evaluation_and_cp_cap() -> None:
    assert terminal_evaluation(chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")) == ev(mate=0)
    assert terminal_evaluation(chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")) == ev(cp=0)
    assert centipawns_for_loss(ev(cp=5000), chess.WHITE) == 1000
    assert centipawns_for_loss(ev(mate=0), chess.WHITE) == -1000


def classify(
    before: Evaluation,
    after: Evaluation,
    mover: chess.Color = chess.WHITE,
    played: str = "e2e4",
    best: str | None = "d2d4",
    legal: int = 20,
) -> MoveVerdict:
    return classify_move(before, after, mover, played_uci=played, best_uci=best, legal_move_count=legal, thresholds=T)


def test_engine_move_is_best_and_forced_move_is_forced() -> None:
    assert classify(ev(30), ev(-200), played="d2d4").classification == "best"  # engine's own choice
    assert classify(ev(30), ev(-500), legal=1).classification == "forced"


@pytest.mark.parametrize(
    ("before", "after", "label"),
    [
        (30, 25, "excellent"),  # loss 0.005
        (30, -10, "good"),  # loss 0.037
        (30, -50, "inaccuracy"),  # loss 0.073
        (30, -130, "mistake"),  # loss 0.146
        (30, -400, "blunder"),  # loss 0.34
    ],
)
def test_white_thresholds(before: int, after: int, label: str) -> None:
    assert classify(ev(before), ev(after)).classification == label


def test_black_perspective_is_mirrored() -> None:
    # Black to move at -30 (good for Black), plays into +400 for White: a blunder.
    verdict = classify(ev(-30), ev(400), mover=chess.BLACK)
    assert verdict.classification == "blunder"
    assert verdict.cp_loss == 430
    # Black improving its position loses nothing.
    assert classify(ev(-30), ev(-60), mover=chess.BLACK).win_loss == 0


def test_mate_transitions() -> None:
    assert classify(ev(mate=2), ev(mate=-3)).classification == "blunder"  # turned a win into a loss
    assert classify(ev(50), ev(mate=-1)).classification == "blunder"  # allowed mate
    # Already completely winning: keeping a large advantage is not penalised much.
    assert classify(ev(900), ev(650)).classification in {"excellent", "good"}
    # Missing a mate but staying totally winning is at most an inaccuracy.
    assert classify(ev(mate=3), ev(1200)).classification in {"excellent", "good", "inaccuracy"}


def test_summary_counts_and_averages() -> None:
    verdicts = [
        (chess.WHITE, MoveVerdict("best", 0.0, 0)),
        (chess.WHITE, MoveVerdict("blunder", 0.3, 400)),
        (chess.WHITE, MoveVerdict("forced", 0.0, 0)),
        (chess.BLACK, MoveVerdict("good", 0.04, 30)),
    ]
    summary = summarize(verdicts)
    assert summary["white"]["moves"] == 3
    assert summary["white"]["counts"]["blunder"] == 1 and summary["white"]["counts"]["forced"] == 1
    assert summary["white"]["acpl"] == 200.0  # forced moves excluded
    assert summary["black"]["avg_win_loss"] == 0.04


def test_thresholds_must_increase() -> None:
    with pytest.raises(ValidationError):
        ClassificationThresholds(excellent=0.1, good=0.05, inaccuracy=0.2, mistake=0.3)
    ClassificationThresholds(excellent=0.01, good=0.03, inaccuracy=0.08, mistake=0.15)
