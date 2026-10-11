import chess
import pytest

from chesslab_engine.evaluation import (
    TEMPO_BONUS,
    EvalConfig,
    Evaluator,
    endgame,
    is_passed_pawn,
    king_safety,
    material_pst,
    passed_pawns,
    pawn_structure,
    piece_activity,
)

POSITIONS = [
    chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N1PN2/PP3PPP/R2QKB1R w KQ - 0 8",
    "6k1/5ppp/8/8/8/8/5PPP/3R2K1 b - - 0 1",
]


@pytest.mark.parametrize("fen", POSITIONS)
def test_evaluation_is_color_symmetric(fen: str) -> None:
    """Mirroring the board (and swapping colours) must not change the score
    from the side to move's perspective. This catches sign and table-flip bugs."""
    evaluator = Evaluator()
    board = chess.Board(fen)
    assert evaluator.evaluate(board) == evaluator.evaluate(board.mirror())


def test_start_position_is_balanced() -> None:
    evaluator = Evaluator()
    assert evaluator.evaluate(chess.Board()) == TEMPO_BONUS


def test_extra_queen_is_strongly_positive() -> None:
    board = chess.Board("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
    assert Evaluator().evaluate(board) > 800
    board.turn = chess.BLACK
    assert Evaluator().evaluate(board) < -800


def test_material_pst_phase() -> None:
    _, phase = material_pst(chess.Board())
    assert phase == 24
    _, phase = material_pst(chess.Board("4k3/pppppppp/8/8/8/8/PPPPPPPP/4K3 w - - 0 1"))
    assert phase == 0


def test_passed_pawn_detection() -> None:
    board = chess.Board("4k3/8/8/3P4/8/8/2p5/4K3 w - - 0 1")
    assert is_passed_pawn(board, chess.D5, chess.WHITE)
    assert is_passed_pawn(board, chess.C2, chess.BLACK)
    blocked = chess.Board("4k3/4p3/8/3P4/8/8/8/4K3 w - - 0 1")
    assert not is_passed_pawn(blocked, chess.D5, chess.WHITE)  # e7 pawn covers d6


def test_advanced_passed_pawn_scores_higher() -> None:
    low = passed_pawns(chess.Board("4k3/8/8/8/8/3P4/8/4K3 w - - 0 1"))
    high = passed_pawns(chess.Board("4k3/8/3P4/8/8/8/8/4K3 w - - 0 1"))
    assert high[1] > low[1] > 0


def test_doubled_and_isolated_pawns_are_penalised() -> None:
    healthy = pawn_structure(chess.Board("4k3/8/8/8/8/8/2PPP3/4K3 w - - 0 1"))
    doubled = pawn_structure(chess.Board("4k3/8/8/8/8/3P4/3PP3/4K3 w - - 0 1"))
    isolated = pawn_structure(chess.Board("4k3/8/8/8/8/8/P3P3/4K3 w - - 0 1"))
    assert doubled[1] < healthy[1]
    assert isolated[1] < healthy[1]


def test_bishop_pair_and_open_file_rook() -> None:
    pair = piece_activity(chess.Board("4k3/8/8/8/8/8/8/2B1KB2 w - - 0 1"))
    single = piece_activity(chess.Board("4k3/8/8/8/8/8/8/2B1K3 w - - 0 1"))
    assert pair[0] > single[0]
    open_rook = piece_activity(chess.Board("4k3/pppp1ppp/8/8/8/8/PPPP1PPP/4RK2 w - - 0 1"))
    closed_rook = piece_activity(chess.Board("4k3/pppppppp/8/8/8/8/PPPPPPPP/4RK2 w - - 0 1"))
    assert open_rook[0] > closed_rook[0]


def test_king_safety_prefers_intact_shield() -> None:
    shielded = king_safety(chess.Board("6k1/5ppp/8/8/8/8/5PPP/6K1 w - - 0 1"))
    exposed = king_safety(chess.Board("6k1/5ppp/8/8/8/8/8/6K1 w - - 0 1"))
    assert shielded[0] > exposed[0]
    assert shielded[1] == 0  # king safety is a middlegame-only term


def test_mop_up_drives_lone_king_to_edge() -> None:
    center = endgame(chess.Board("8/8/8/3k4/8/8/8/4K2Q w - - 0 1"))
    corner = endgame(chess.Board("k7/8/8/8/8/8/8/4K2Q w - - 0 1"))
    assert corner[1] > center[1] > 0


def test_breakdown_sums_to_total() -> None:
    board = chess.Board(POSITIONS[1])
    evaluator = Evaluator()
    info = evaluator.breakdown(board)
    parts = info["components"]
    assert isinstance(parts, dict)
    # Tapering each part separately can differ from tapering the sum by rounding.
    assert abs(sum(parts.values()) - info["total_white_pov"]) <= len(parts)
    side_to_move = info["total_white_pov"] if board.turn == chess.WHITE else -info["total_white_pov"]
    assert abs(side_to_move - evaluator.evaluate(board)) <= 1


def test_disabled_components_change_result() -> None:
    board = chess.Board(POSITIONS[1])
    full = Evaluator().evaluate(board)
    bare = Evaluator(EvalConfig(False, False, False, False, False, False)).evaluate(board)
    assert full != bare
    assert set(Evaluator(EvalConfig(mobility=False)).breakdown(board)["components"]) == {  # type: ignore[arg-type]
        "material_pst",
        "king_safety",
        "pawn_structure",
        "passed_pawns",
        "piece_activity",
        "endgame",
        "tempo",
    }


def test_pawn_cache_respects_config_changes() -> None:
    board = chess.Board("4k3/8/8/3P4/8/8/8/4K3 w - - 0 1")
    evaluator = Evaluator()
    with_passed = evaluator.evaluate(board)
    evaluator.config.passed_pawns = False
    assert evaluator.evaluate(board) < with_passed
