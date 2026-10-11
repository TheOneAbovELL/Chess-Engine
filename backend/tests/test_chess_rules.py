"""Chess correctness: validation, rules, terminal states, FEN/PGN parsing and normalisation."""

from __future__ import annotations

import io

import chess
import chess.pgn
import pytest

from app.core.errors import InvalidInputError
from app.services.chess.normalize import (
    UnsupportedGameError,
    detect_source,
    normalize_game,
    opening_from_eco_url,
    time_class_from_control,
    user_perspective,
)
from app.services.chess.pgn import (
    MalformedGameError,
    ParseFailure,
    clean_comment,
    game_tree,
    iter_pgn_games,
    parse_single_game,
)
from app.services.chess.positions import board_from_request, parse_fen, position_status, pv_to_san, terminal_reason

from .helpers import SCHOLARS_MATE, make_pgn


def legal_ucis(fen: str | None = None, moves: list[str] | None = None) -> set[str]:
    return {m.uci() for m in board_from_request(fen, moves).legal_moves}


# --------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("fen", "code"),
    [
        ("not a fen", "invalid_fen"),
        ("8/8/8/8/8/8/8/8 w - - 0 1", "illegal_position"),  # no kings
        ("4k3/8/8/8/8/8/8/4K2R b K - 0 1", None),  # valid
        ("4k3/8/8/8/8/8/8/4K3 w KQ - 0 1", "illegal_position"),  # castling rights without rooks
        ("4k2R/8/8/8/8/8/8/4K3 w - - 0 1", "illegal_position"),  # side not to move in check
        ("P3k3/8/8/8/8/8/8/4K3 w - - 0 1", "illegal_position"),  # pawn on back rank
        ("x" * 120, "invalid_fen"),
    ],
)
def test_fen_validation(fen: str, code: str | None) -> None:
    if code is None:
        assert parse_fen(fen).fen().startswith("4k3")
        return
    with pytest.raises(InvalidInputError) as info:
        parse_fen(fen)
    assert info.value.code == code


def test_illegal_and_malformed_moves_are_rejected() -> None:
    with pytest.raises(InvalidInputError) as info:
        board_from_request(None, ["e2e5"])
    assert info.value.code == "illegal_move"
    with pytest.raises(InvalidInputError) as info:
        board_from_request(None, ["zz99"])
    assert info.value.code == "invalid_move"
    with pytest.raises(InvalidInputError):
        board_from_request(None, ["e2e4", "e2e4"])  # square now empty


# ------------------------------------------------------------- chess rules


def test_start_position_has_twenty_moves() -> None:
    assert len(legal_ucis()) == 20


def test_castling_both_sides_and_through_check() -> None:
    fen = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    assert {"e1g1", "e1c1"} <= legal_ucis(fen)
    # A black rook on f8... attacks f1: kingside castling through check is illegal.
    attacked = "4kr2/8/8/8/8/8/8/R3K2R w KQ - 0 1"
    moves = legal_ucis(attacked)
    assert "e1g1" not in moves and "e1c1" in moves
    # Castling out of check is illegal.
    in_check = "4k3/4r3/8/8/8/8/8/R3K2R w KQ - 0 1"
    assert not {"e1g1", "e1c1"} & legal_ucis(in_check)


def test_en_passant() -> None:
    moves = legal_ucis(None, ["e2e4", "a7a6", "e4e5", "d7d5"])
    assert "e5d6" in moves
    board = board_from_request(None, ["e2e4", "a7a6", "e4e5", "d7d5", "e5d6"])
    assert board.piece_at(chess.D5) is None  # captured pawn removed
    # Only immediately after the double step.
    assert "e5d6" not in legal_ucis(None, ["e2e4", "a7a6", "e4e5", "d7d5", "h2h3", "h7h6"])


def test_promotion_to_every_piece() -> None:
    moves = legal_ucis("8/P6k/8/8/8/8/8/K7 w - - 0 1")
    assert {"a7a8q", "a7a8r", "a7a8b", "a7a8n"} <= moves
    assert "a7a8" not in moves  # promotion piece is required
    board = board_from_request("8/P6k/8/8/8/8/8/K7 w - - 0 1", ["a7a8n"])
    assert board.piece_at(chess.A8) == chess.Piece(chess.KNIGHT, chess.WHITE)


def test_pinned_piece_cannot_move() -> None:
    assert not any(m.startswith("e2") for m in legal_ucis("4r1k1/8/8/8/8/8/4N3/4K3 w - - 0 1"))


def test_check_and_checkmate() -> None:
    board = board_from_request(None, ["e2e4", "e7e5", "f1c4", "b8c6", "d1h5", "g8f6", "h5f7"])
    status = position_status(board)
    assert status.is_check and status.is_game_over
    assert status.outcome == "checkmate" and status.result == "1-0"
    assert terminal_reason(board) == "checkmate"


def test_stalemate() -> None:
    board = parse_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    status = position_status(board)
    assert not status.is_check and status.outcome == "stalemate" and status.result == "1/2-1/2"


@pytest.mark.parametrize(
    "fen",
    ["8/8/4k3/8/8/4K3/8/8 w - - 0 1", "8/8/4k3/8/8/4K3/4N3/8 w - - 0 1", "8/8/4k3/8/8/4KB2/8/8 w - - 0 1"],
)
def test_insufficient_material(fen: str) -> None:
    status = position_status(parse_fen(fen))
    assert status.outcome == "insufficient_material" and status.result == "1/2-1/2"


def test_fifty_move_and_threefold_claims() -> None:
    fifty = parse_fen("4k3/8/8/8/8/8/4P3/4K2R w - - 100 80")
    status = position_status(fifty)
    assert status.can_claim_draw and not status.is_game_over  # claimable, not automatic
    assert terminal_reason(parse_fen("4k3/8/8/8/8/8/4P3/4K2R w - - 150 120")) == "seventyfive_moves"

    shuffle = ["g1f3", "g8f6", "f3g1", "f6g8"] * 2
    board = board_from_request(None, shuffle)
    assert position_status(board).can_claim_draw  # threefold repetition can be claimed
    assert terminal_reason(board) is None
    board = board_from_request(None, shuffle * 2)
    assert terminal_reason(board) == "fivefold_repetition"


def test_pv_to_san_stops_at_illegal_move() -> None:
    board = chess.Board()
    moves = [chess.Move.from_uci(u) for u in ("e2e4", "e7e5", "e2e4")]
    assert pv_to_san(board, moves) == ["e4", "e5"]


# ------------------------------------------------------------------- PGN


def test_pgn_with_variations_and_comments() -> None:
    text = '[Event "Test"]\n[Result "*"]\n\n1. e4 {[%clk 0:05:00] best by test} e5 (1... c5 2. Nf3) 2. Nf3 $1 *'
    game, count = parse_single_game(text)
    assert count == 1
    nodes = game_tree(game)
    root = nodes[0]
    assert root["fen"] == chess.STARTING_FEN and root["san"] is None
    e4 = nodes[root["children"][0]]
    assert e4["san"] == "e4" and e4["comment"] == "best by test" and e4["clock"] == 300
    assert [nodes[i]["san"] for i in e4["children"]] == ["e5", "c5"]
    nf3 = nodes[nodes[e4["children"][0]]["children"][0]]
    assert nf3["san"] == "Nf3" and nf3["nags"] == [1]


def test_malformed_pgn_is_reported_not_truncated() -> None:
    items = list(iter_pgn_games('[Event "x"]\n\n1. e4 e5 2. Ke3 Nf6 *\n\n[Event "ok"]\n\n1. d4 d5 *', 10))
    assert isinstance(items[0], ParseFailure) and "Invalid game" in items[0].error
    assert not isinstance(items[1], ParseFailure)
    with pytest.raises(InvalidInputError):
        parse_single_game("this is not pgn at all")


def test_clean_comment() -> None:
    assert clean_comment("[%clk 0:01:00] [%eval 0.3] nice") == "nice"


# ------------------------------------------------------------ normalisation


def _game(pgn: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None
    return game


def test_normalize_detects_chesscom_and_lichess_links() -> None:
    cc = _game(make_pgn(SCHOLARS_MATE, {"White": "a", "Black": "b", "Link": "https://www.chess.com/game/live/123456"}))
    record = normalize_game(cc, owner="A")
    assert (record.source, record.external_id) == ("chesscom", "live/123456")
    assert record.result == "1-0" and record.ply_count == 7
    assert record.user_color == "white" and record.user_result == "win"
    li = _game(make_pgn(["e4"], {"White": "x", "Black": "y", "Site": "https://lichess.org/AbCdEfGh"}))
    assert detect_source(li.headers) == ("lichess", "AbCdEfGh")


def test_normalize_fingerprint_is_stable_for_plain_pgn() -> None:
    pgn = make_pgn(["d4", "d5"], {"White": "A", "Black": "B", "Date": "2024.01.02", "Result": "*"})
    first = normalize_game(_game(pgn))
    second = normalize_game(_game(pgn))
    assert first.source == "pgn" and first.external_id == second.external_id
    other = normalize_game(
        _game(make_pgn(["d4", "Nf6"], {"White": "A", "Black": "B", "Date": "2024.01.02", "Result": "*"}))
    )
    assert other.external_id != first.external_id


def test_normalize_rejects_variants_and_keeps_setup_positions() -> None:
    with pytest.raises(UnsupportedGameError):
        normalize_game(_game('[Variant "Crazyhouse"]\n\n1. e4 *'))
    setup = _game('[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"]\n\n1. e4 *')
    record = normalize_game(setup)
    assert record.initial_fen == "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"


def test_normalize_raises_on_illegal_moves() -> None:
    with pytest.raises(MalformedGameError):
        normalize_game(_game("1. e4 e5 2. Ke3 *"))


@pytest.mark.parametrize(
    ("control", "expected"),
    [
        ("15+0", "ultrabullet"),
        ("60+0", "bullet"),
        ("180+2", "blitz"),
        ("600+0", "rapid"),
        ("1800+20", "classical"),
        ("-", "correspondence"),
        ("1/259200", "correspondence"),
        (None, "unknown"),
        ("weird", "unknown"),
    ],
)
def test_time_class(control: str | None, expected: str) -> None:
    assert time_class_from_control(control) == expected


def test_opening_from_eco_url() -> None:
    assert (
        opening_from_eco_url(
            "https://www.chess.com/openings/Closed-Sicilian-Defense-Fianchetto-Variation...6.exd5-exd5"
        )
        == "Closed Sicilian Defense Fianchetto Variation"
    )
    assert opening_from_eco_url("https://www.chess.com/openings/Queens-Pawn-Opening-2.Nf3") == "Queens Pawn Opening"
    assert opening_from_eco_url(None) is None


def test_user_perspective() -> None:
    assert user_perspective("Alice", "Bob", "0-1", "bob") == ("black", "win")
    assert user_perspective("Alice", "Bob", "1/2-1/2", "ALICE") == ("white", "draw")
    assert user_perspective("Alice", "Bob", "1-0", "carol") == (None, None)
    assert user_perspective("Alice", "Bob", "*", "alice") == ("white", None)
