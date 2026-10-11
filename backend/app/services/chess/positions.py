"""Position validation and status reporting.

The backend never trusts the client's idea of a position: every FEN and move
list is re-validated here with python-chess before it reaches an engine.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess

from app.core.errors import InvalidInputError

MAX_FEN_LENGTH = 100
MAX_HISTORY_MOVES = 1000

_STATUS_MESSAGES = {
    chess.STATUS_NO_WHITE_KING: "White has no king.",
    chess.STATUS_NO_BLACK_KING: "Black has no king.",
    chess.STATUS_TOO_MANY_KINGS: "There are too many kings.",
    chess.STATUS_TOO_MANY_WHITE_PAWNS: "White has more than 8 pawns.",
    chess.STATUS_TOO_MANY_BLACK_PAWNS: "Black has more than 8 pawns.",
    chess.STATUS_PAWNS_ON_BACKRANK: "Pawns cannot stand on the first or last rank.",
    chess.STATUS_TOO_MANY_WHITE_PIECES: "White has more than 16 pieces.",
    chess.STATUS_TOO_MANY_BLACK_PIECES: "Black has more than 16 pieces.",
    chess.STATUS_BAD_CASTLING_RIGHTS: "Castling rights do not match the king and rook placement.",
    chess.STATUS_INVALID_EP_SQUARE: "The en-passant square is not possible in this position.",
    chess.STATUS_OPPOSITE_CHECK: "The side not to move is in check.",
    chess.STATUS_EMPTY: "The board is empty.",
    chess.STATUS_RACE_CHECK: "Both kings are in check.",
    chess.STATUS_RACE_OVER: "Invalid race position.",
    chess.STATUS_RACE_MATERIAL: "Invalid race material.",
    chess.STATUS_TOO_MANY_CHECKERS: "The king is attacked by too many pieces at once.",
    chess.STATUS_IMPOSSIBLE_CHECK: "This check could not arise in a legal game.",
}


def parse_fen(fen: str) -> chess.Board:
    """Parse and fully validate a FEN, raising a user-friendly error."""
    fen = fen.strip()
    if not fen or len(fen) > MAX_FEN_LENGTH:
        raise InvalidInputError("FEN must be between 1 and 100 characters.", code="invalid_fen")
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        raise InvalidInputError(f"Malformed FEN: {exc}", code="invalid_fen") from exc
    status = board.status()
    if status != chess.STATUS_VALID:
        problems = [msg for flag, msg in _STATUS_MESSAGES.items() if status & flag]
        raise InvalidInputError(
            "Illegal position: " + " ".join(problems or ["the position is not valid."]),
            code="illegal_position",
            details={"problems": problems},
        )
    return board


def board_from_request(fen: str | None, moves: list[str] | None) -> chess.Board:
    """Build a board from a start FEN plus UCI moves. Keeping the move history
    lets engines see repetitions, which a bare FEN cannot express."""
    board = parse_fen(fen) if fen else chess.Board()
    for index, uci in enumerate(moves or []):
        if index >= MAX_HISTORY_MOVES:
            raise InvalidInputError("Too many moves in history.", code="too_many_moves")
        try:
            move = chess.Move.from_uci(uci)
        except ValueError as exc:
            raise InvalidInputError(f"Invalid move notation '{uci}'.", code="invalid_move") from exc
        if move not in board.legal_moves:
            raise InvalidInputError(f"Illegal move '{uci}' at ply {index + 1}.", code="illegal_move")
        board.push(move)
    return board


@dataclass(frozen=True)
class PositionStatus:
    is_check: bool
    is_game_over: bool
    outcome: str | None  # "checkmate", "stalemate", "insufficient_material", ...
    result: str | None  # "1-0", "0-1", "1/2-1/2"
    can_claim_draw: bool


def position_status(board: chess.Board) -> PositionStatus:
    outcome = board.outcome(claim_draw=False)
    claim = board.can_claim_fifty_moves() or board.can_claim_threefold_repetition()
    return PositionStatus(
        is_check=board.is_check(),
        is_game_over=outcome is not None,
        outcome=outcome.termination.name.lower() if outcome else None,
        result=outcome.result() if outcome else None,
        can_claim_draw=claim,
    )


def terminal_reason(board: chess.Board) -> str | None:
    """Reason a position ends the game (no engine search needed), else None."""
    if board.is_checkmate():
        return "checkmate"
    if board.is_stalemate():
        return "stalemate"
    if board.is_insufficient_material():
        return "insufficient_material"
    if board.is_seventyfive_moves():
        return "seventyfive_moves"
    if board.is_fivefold_repetition():
        return "fivefold_repetition"
    return None


def pv_to_san(board: chess.Board, moves: list[chess.Move]) -> list[str]:
    """SAN for a principal variation; stops at the first illegal move."""
    temp = board.copy(stack=False)
    sans: list[str] = []
    for move in moves:
        if move not in temp.legal_moves:
            break
        sans.append(temp.san(move))
        temp.push(move)
    return sans
