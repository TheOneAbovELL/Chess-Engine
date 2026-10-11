"""Static evaluation for the ChessLab engine.

Design
------
The evaluation is a sum of independent *components*. Every component returns a
``(mg, eg)`` pair from **White's point of view**. The evaluator tapers the
totals between middlegame and endgame by the remaining non-pawn material
(``phase``) and finally converts to the side-to-move perspective that negamax
search needs.

Keeping components separate makes each one unit-testable, lets the engine
switch terms on and off through UCI options (to *measure* their value in
matches), and powers the evaluation breakdown shown in the Engine Lab UI.

All weights are hand-chosen starting points, not tuned values. Tuning them
(e.g. with Texel's method) is listed as future work in docs/engine-design.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields

import chess

from .pst import EG_TABLE, MAX_PHASE, MG_TABLE, PHASE_INC

Score = tuple[int, int]  # (middlegame, endgame), White's point of view

WHITE, BLACK = chess.WHITE, chess.BLACK
FILE_MASKS = [chess.BB_FILES[f] for f in range(8)]
ADJACENT_FILES = [
    (FILE_MASKS[f - 1] if f > 0 else 0) | (FILE_MASKS[f + 1] if f < 7 else 0) for f in range(8)
]

TEMPO_BONUS = 10

# Mobility: (mg, eg) per reachable square above a typical baseline count.
MOBILITY_WEIGHT = {
    chess.KNIGHT: (4, 4),
    chess.BISHOP: (5, 5),
    chess.ROOK: (2, 4),
    chess.QUEEN: (1, 2),
}
MOBILITY_BASELINE = {chess.KNIGHT: 4, chess.BISHOP: 6, chess.ROOK: 7, chess.QUEEN: 13}

DOUBLED_PAWN: Score = (-10, -20)
ISOLATED_PAWN: Score = (-12, -15)
CONNECTED_PAWN: Score = (5, 7)

# Passed-pawn bonus by *relative* rank (0 = own back rank, 7 = promotion rank).
PASSED_MG = [0, 5, 10, 15, 25, 40, 60, 0]
PASSED_EG = [0, 10, 20, 35, 60, 95, 140, 0]

BISHOP_PAIR: Score = (30, 50)
ROOK_OPEN_FILE: Score = (20, 10)
ROOK_SEMI_OPEN_FILE: Score = (10, 5)
ROOK_ON_SEVENTH: Score = (10, 20)

SHIELD_MISSING_PENALTY = 15  # mg, per missing pawn in front of a castled king
KING_OPEN_FILE_PENALTY = 20  # mg, per (semi-)open file next to the king
KING_ATTACK_WEIGHT = {chess.KNIGHT: 8, chess.BISHOP: 8, chess.ROOK: 12, chess.QUEEN: 20}


@dataclass
class EvalConfig:
    """Feature switches. Exposed as UCI options (EvalMobility, ...)."""

    mobility: bool = True
    king_safety: bool = True
    pawn_structure: bool = True
    passed_pawns: bool = True
    piece_activity: bool = True
    endgame: bool = True

    @classmethod
    def names(cls) -> list[str]:
        return [f.name for f in fields(cls)]


# --------------------------------------------------------------------------- #
# Components                                                                   #
# --------------------------------------------------------------------------- #


def _bits(bb: int) -> list[int]:
    """Square indices of the set bits of ``bb``. A plain loop that builds a list
    is noticeably faster in CPython than python-chess's generator."""
    out = []
    while bb:
        lsb = bb & -bb
        out.append(lsb.bit_length() - 1)
        bb ^= lsb
    return out


def material_pst(board: chess.Board) -> tuple[Score, int]:
    """Material + piece-square tables. Also returns the game phase (0..24)."""
    mg = eg = 0
    phase = 0
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        mg_tab = MG_TABLE[color]
        eg_tab = EG_TABLE[color]
        occ = board.occupied_co[color]
        for piece_type, bb in (
            (chess.PAWN, board.pawns),
            (chess.KNIGHT, board.knights),
            (chess.BISHOP, board.bishops),
            (chess.ROOK, board.rooks),
            (chess.QUEEN, board.queens),
            (chess.KING, board.kings),
        ):
            mg_row = mg_tab[piece_type]
            eg_row = eg_tab[piece_type]
            for sq in _bits(bb & occ):
                mg += sign * mg_row[sq]
                eg += sign * eg_row[sq]
                phase += PHASE_INC[piece_type]
    return (mg, eg), min(phase, MAX_PHASE)


def _pawn_attacks(pawns: int, color: chess.Color) -> int:
    if color == WHITE:
        return ((pawns << 7) & ~chess.BB_FILE_H & chess.BB_ALL) | (
            (pawns << 9) & ~chess.BB_FILE_A & chess.BB_ALL
        )
    return (pawns >> 9) & ~chess.BB_FILE_H | (pawns >> 7) & ~chess.BB_FILE_A


def mobility(board: chess.Board) -> Score:
    """Pseudo-legal reach of minor/major pieces, excluding squares occupied by own
    pieces or attacked by enemy pawns (those squares are rarely useful)."""
    mg = eg = 0
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        own = board.occupied_co[color]
        enemy_pawn_attacks = _pawn_attacks(board.pawns & board.occupied_co[not color], not color)
        allowed = ~own & ~enemy_pawn_attacks & chess.BB_ALL
        for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            w_mg, w_eg = MOBILITY_WEIGHT[piece_type]
            base = MOBILITY_BASELINE[piece_type]
            for sq in _bits(board.pieces_mask(piece_type, color)):
                count = chess.popcount(board.attacks_mask(sq) & allowed) - base
                mg += sign * w_mg * count
                eg += sign * w_eg * count
    return mg, eg


def pawn_structure(board: chess.Board) -> Score:
    """Doubled, isolated and connected (phalanx/supported) pawns."""
    mg = eg = 0
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        pawns = board.pawns & board.occupied_co[color]
        support = _pawn_attacks(pawns, color)
        for f in range(8):
            on_file = chess.popcount(pawns & FILE_MASKS[f])
            if on_file == 0:
                continue
            if on_file > 1:
                mg += sign * DOUBLED_PAWN[0] * (on_file - 1)
                eg += sign * DOUBLED_PAWN[1] * (on_file - 1)
            if not pawns & ADJACENT_FILES[f]:
                mg += sign * ISOLATED_PAWN[0] * on_file
                eg += sign * ISOLATED_PAWN[1] * on_file
        for sq in _bits(pawns):
            rank_neighbors = chess.BB_RANKS[chess.square_rank(sq)] & ADJACENT_FILES[chess.square_file(sq)]
            if (pawns & rank_neighbors) or (support & chess.BB_SQUARES[sq]):
                mg += sign * CONNECTED_PAWN[0]
                eg += sign * CONNECTED_PAWN[1]
    return mg, eg


def _front_span(sq: chess.Square, color: chess.Color) -> int:
    """Squares in front of ``sq`` on its own and adjacent files (towards promotion)."""
    file_ = chess.square_file(sq)
    rank = chess.square_rank(sq)
    files = FILE_MASKS[file_] | ADJACENT_FILES[file_]
    rank_range = range(rank + 1, 8) if color == WHITE else range(0, rank)
    ranks = 0
    for r in rank_range:
        ranks |= chess.BB_RANKS[r]
    return files & ranks


# PASSED_MASK[color][sq]: enemy pawns on these squares stop a pawn on sq from being passed.
PASSED_MASK = [[_front_span(sq, color) for sq in chess.SQUARES] for color in (BLACK, WHITE)]


def is_passed_pawn(board: chess.Board, sq: chess.Square, color: chess.Color) -> bool:
    enemy_pawns = board.pawns & board.occupied_co[not color]
    return not (enemy_pawns & PASSED_MASK[color][sq])


def passed_pawns(board: chess.Board) -> Score:
    mg = eg = 0
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        enemy_pawns = board.pawns & board.occupied_co[not color]
        masks = PASSED_MASK[color]
        for sq in _bits(board.pawns & board.occupied_co[color]):
            if not enemy_pawns & masks[sq]:
                rel_rank = chess.square_rank(sq) if color == WHITE else 7 - chess.square_rank(sq)
                mg += sign * PASSED_MG[rel_rank]
                eg += sign * PASSED_EG[rel_rank]
    return mg, eg


def piece_activity(board: chess.Board) -> Score:
    """Bishop pair, rooks on (semi-)open files and on the seventh rank."""
    mg = eg = 0
    all_pawns = board.pawns
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        own_pawns = all_pawns & board.occupied_co[color]
        if chess.popcount(board.pieces_mask(chess.BISHOP, color)) >= 2:
            mg += sign * BISHOP_PAIR[0]
            eg += sign * BISHOP_PAIR[1]
        seventh = chess.BB_RANK_7 if color == WHITE else chess.BB_RANK_2
        for sq in _bits(board.pieces_mask(chess.ROOK, color)):
            file_mask = FILE_MASKS[chess.square_file(sq)]
            if not all_pawns & file_mask:
                mg += sign * ROOK_OPEN_FILE[0]
                eg += sign * ROOK_OPEN_FILE[1]
            elif not own_pawns & file_mask:
                mg += sign * ROOK_SEMI_OPEN_FILE[0]
                eg += sign * ROOK_SEMI_OPEN_FILE[1]
            if chess.BB_SQUARES[sq] & seventh:
                mg += sign * ROOK_ON_SEVENTH[0]
                eg += sign * ROOK_ON_SEVENTH[1]
    return mg, eg


def king_safety(board: chess.Board) -> Score:
    """Middlegame-only: pawn shield, open files near the king, and pressure on the
    king zone. The endgame term is 0 because an active king is good there."""
    mg = 0
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        king_sq = board.king(color)
        if king_sq is None:
            continue
        own_pawns = board.pawns & board.occupied_co[color]
        all_pawns = board.pawns
        kf = chess.square_file(king_sq)
        kr = chess.square_rank(king_sq)

        # Pawn shield only matters for a king tucked away on the wings.
        if kf <= 2 or kf >= 5:
            forward = 1 if color == WHITE else -1
            for f in range(max(0, kf - 1), min(7, kf + 1) + 1):
                shield = 0
                for step in (1, 2):
                    r = kr + forward * step
                    if 0 <= r <= 7:
                        shield |= chess.BB_SQUARES[chess.square(f, r)]
                if not own_pawns & shield:
                    mg -= sign * SHIELD_MISSING_PENALTY

        for f in range(max(0, kf - 1), min(7, kf + 1) + 1):
            if not own_pawns & FILE_MASKS[f]:
                mg -= sign * (KING_OPEN_FILE_PENALTY if not all_pawns & FILE_MASKS[f] else KING_OPEN_FILE_PENALTY // 2)

        zone = board.attacks_mask(king_sq) | chess.BB_SQUARES[king_sq]
        pressure = 0
        attackers = 0
        enemy = not color
        for piece_type, weight in KING_ATTACK_WEIGHT.items():
            for sq in _bits(board.pieces_mask(piece_type, enemy)):
                hits = chess.popcount(board.attacks_mask(sq) & zone)
                if hits:
                    attackers += 1
                    pressure += weight * hits
        # A single attacker is rarely dangerous; scale pressure with attacker count.
        if attackers >= 2:
            mg -= sign * (pressure * min(attackers, 4) // 4)
    return mg, 0


CENTER_DISTANCE = [
    max(3 - min(chess.square_file(s), 7 - chess.square_file(s)), 3 - min(chess.square_rank(s), 7 - chess.square_rank(s)))
    for s in chess.SQUARES
]


def endgame(board: chess.Board) -> Score:
    """Mop-up evaluation: when one side has a decisive material edge and the
    other has no pawns, drive the losing king to the edge and bring the winning
    king closer. This lets a shallow search convert K+Q/K+R vs K."""
    eg = 0
    material = [0, 0]
    for color in (WHITE, BLACK):
        material[color] = (
            320 * chess.popcount(board.pieces_mask(chess.KNIGHT, color))
            + 330 * chess.popcount(board.pieces_mask(chess.BISHOP, color))
            + 500 * chess.popcount(board.pieces_mask(chess.ROOK, color))
            + 900 * chess.popcount(board.pieces_mask(chess.QUEEN, color))
        )
    for strong in (WHITE, BLACK):
        weak = not strong
        weak_pawns = board.pawns & board.occupied_co[weak]
        if weak_pawns or material[strong] - material[weak] < 500:
            continue
        ks, kw = board.king(strong), board.king(weak)
        if ks is None or kw is None:
            continue
        sign = 1 if strong == WHITE else -1
        bonus = 10 * CENTER_DISTANCE[kw] + 4 * (14 - chess.square_manhattan_distance(ks, kw))
        eg += sign * bonus
    return 0, eg


COMPONENTS: dict[str, Callable[[chess.Board], Score]] = {
    "mobility": mobility,
    "king_safety": king_safety,
    "pawn_structure": pawn_structure,
    "passed_pawns": passed_pawns,
    "piece_activity": piece_activity,
    "endgame": endgame,
}


# --------------------------------------------------------------------------- #
# Evaluator                                                                    #
# --------------------------------------------------------------------------- #


def taper(score: Score, phase: int) -> int:
    """Blend mg/eg by phase. Truncates toward zero (not floor) so that a position
    and its colour-mirrored twin get exactly opposite scores."""
    mg, eg = score
    return int((mg * phase + eg * (MAX_PHASE - phase)) / MAX_PHASE)


PAWN_ONLY_COMPONENTS = ("pawn_structure", "passed_pawns")
PAWN_HASH_LIMIT = 65_536


class Evaluator:
    """Combines the enabled components.

    Pawn-only terms (structure and passed pawns) depend solely on the two pawn
    bitboards, which change on few moves. They are cached in a small *pawn hash
    table*, a classic engine optimisation that removes most of their cost.
    """

    def __init__(self, config: EvalConfig | None = None) -> None:
        self.config = config or EvalConfig()
        self.pawn_cache: dict[tuple[int, int, bool, bool], Score] = {}

    def _pawn_terms(self, board: chess.Board) -> Score:
        use_structure = self.config.pawn_structure
        use_passed = self.config.passed_pawns
        if not (use_structure or use_passed):
            return 0, 0
        white_pawns = board.pawns & board.occupied_co[WHITE]
        key = (white_pawns, board.pawns ^ white_pawns, use_structure, use_passed)
        cached = self.pawn_cache.get(key)
        if cached is not None:
            return cached
        mg = eg = 0
        if use_structure:
            a, b = pawn_structure(board)
            mg += a
            eg += b
        if use_passed:
            a, b = passed_pawns(board)
            mg += a
            eg += b
        if len(self.pawn_cache) >= PAWN_HASH_LIMIT:
            self.pawn_cache.clear()
        self.pawn_cache[key] = (mg, eg)
        return mg, eg

    def evaluate(self, board: chess.Board) -> int:
        """Centipawn score from the side to move's perspective."""
        (mg, eg), phase = material_pst(board)
        p_mg, p_eg = self._pawn_terms(board)
        mg += p_mg
        eg += p_eg
        config = self.config
        for name, fn in COMPONENTS.items():
            if name in PAWN_ONLY_COMPONENTS or not getattr(config, name):
                continue
            c_mg, c_eg = fn(board)
            mg += c_mg
            eg += c_eg
        white_pov = taper((mg, eg), phase)
        score = white_pov if board.turn == WHITE else -white_pov
        return score + TEMPO_BONUS

    def breakdown(self, board: chess.Board) -> dict[str, object]:
        """Per-component contributions (White's POV, tapered) for display."""
        (mg, eg), phase = material_pst(board)
        parts: dict[str, int] = {"material_pst": taper((mg, eg), phase)}
        total_mg, total_eg = mg, eg
        for name, fn in COMPONENTS.items():
            if not getattr(self.config, name):
                continue
            c_mg, c_eg = fn(board)
            parts[name] = taper((c_mg, c_eg), phase)
            total_mg += c_mg
            total_eg += c_eg
        tempo = TEMPO_BONUS if board.turn == WHITE else -TEMPO_BONUS
        parts["tempo"] = tempo
        return {
            "phase": phase,
            "max_phase": MAX_PHASE,
            "components": parts,
            "total_white_pov": taper((total_mg, total_eg), phase) + tempo,
        }
