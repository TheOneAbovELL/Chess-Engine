"""Search for the ChessLab engine.

Implemented techniques (each switchable through :class:`SearchConfig`):

* Negamax alpha-beta with principal-variation search (PVS)
* Iterative deepening with a triangular PV table
* Quiescence search over captures and promotions (with delta pruning)
* Transposition table with mate-score ply adjustment
* Move ordering: TT move, MVV-LVA captures, promotions, killer moves, history
* Null-move pruning (R = 2, disabled in check / pawn-only endgames)
* Late-move reductions for quiet moves searched late
* Check extension
* Mate-distance pruning
* Draw detection: repetition, fifty-move rule, insufficient material
* MultiPV at the root (excluding previously found root moves)
* Cooperative cancellation (``stop_event``) and time management

Legal move generation is delegated to python-chess, a well-tested rules library;
writing our own bitboard generator is part of the "faster engine" roadmap.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import chess
import chess.polyglot

from .evaluation import Evaluator
from .pst import ORDER_VALUE
from .tt import EXACT, LOWER, UPPER, TranspositionTable

INF = 1_000_000
MATE = 100_000
MATE_BOUND = MATE - 1_000  # scores beyond this are mate scores
MAX_PLY = 96
CHECK_EVERY = 1024  # nodes between clock / stop-flag checks


class SearchAborted(Exception):
    """Raised inside the tree when the search must stop immediately."""


@dataclass
class SearchConfig:
    quiescence: bool = True
    transposition_table: bool = True
    null_move: bool = True
    killer_moves: bool = True
    history_heuristic: bool = True
    late_move_reductions: bool = True
    check_extension: bool = True


@dataclass
class SearchLimits:
    depth: int | None = None
    nodes: int | None = None
    movetime_ms: int | None = None
    # Clock-based limits (UCI "go wtime btime winc binc movestogo").
    wtime_ms: int | None = None
    btime_ms: int | None = None
    winc_ms: int = 0
    binc_ms: int = 0
    movestogo: int | None = None
    infinite: bool = False


@dataclass
class PVLine:
    multipv: int
    score: int  # side-to-move POV centipawns, or mate-encoded (see is_mate_score)
    pv: list[chess.Move]


@dataclass
class IterationInfo:
    depth: int
    seldepth: int
    nodes: int
    time_ms: int
    nps: int
    hashfull: int
    lines: list[PVLine] = field(default_factory=list)


@dataclass
class SearchResult:
    best_move: chess.Move | None
    ponder: chess.Move | None
    score: int | None
    depth: int
    nodes: int
    time_ms: int
    lines: list[PVLine]


def is_mate_score(score: int) -> bool:
    return abs(score) >= MATE_BOUND


def mate_in(score: int) -> int:
    """Convert an internal mate score into UCI "mate N" (moves, signed)."""
    plies = MATE - abs(score)
    moves = (plies + 1) // 2
    return moves if score > 0 else -moves


def compute_time_budget(limits: SearchLimits, turn: chess.Color) -> tuple[float | None, float | None]:
    """Return (soft, hard) budgets in seconds.

    * ``soft``: do not *start* a new iteration after this much time.
    * ``hard``: abort the current iteration at this point.
    """
    if limits.infinite:
        return None, None
    if limits.movetime_ms is not None:
        t = max(0.01, limits.movetime_ms / 1000)
        return t, t
    remaining = limits.wtime_ms if turn == chess.WHITE else limits.btime_ms
    if remaining is None:
        return None, None
    inc = (limits.winc_ms if turn == chess.WHITE else limits.binc_ms) / 1000
    remaining_s = max(0.0, remaining / 1000 - 0.05)  # keep a small safety margin
    moves_left = limits.movestogo if limits.movestogo else 30
    base = remaining_s / max(1, moves_left) + inc * 0.8
    hard = min(remaining_s * 0.5, base * 3)
    soft = min(hard, base)
    return max(0.01, soft), max(0.02, hard)


class Searcher:
    def __init__(
        self,
        evaluator: Evaluator | None = None,
        config: SearchConfig | None = None,
        tt: TranspositionTable | None = None,
    ) -> None:
        self.evaluator = evaluator or Evaluator()
        self.config = config or SearchConfig()
        self.tt = tt or TranspositionTable()
        self.stop_event = threading.Event()
        self.reset_heuristics()
        self._reset_counters()

    # ------------------------------------------------------------------ setup
    def reset_heuristics(self) -> None:
        self.killers: list[list[chess.Move | None]] = [[None, None] for _ in range(MAX_PLY + 8)]
        self.history: list[list[int]] = [[0] * 4096 for _ in range(2)]

    def new_game(self) -> None:
        self.tt.clear()
        self.reset_heuristics()

    def _reset_counters(self) -> None:
        self.nodes = 0
        self.seldepth = 0
        self.start_time = time.perf_counter()
        self.hard_deadline: float | None = None
        self.node_limit: int | None = None
        self.pv_table: list[list[chess.Move]] = [[] for _ in range(MAX_PLY + 8)]

    # ------------------------------------------------------------ public API
    def search(
        self,
        board: chess.Board,
        limits: SearchLimits | None = None,
        multipv: int = 1,
        on_iteration: Callable[[IterationInfo], None] | None = None,
    ) -> SearchResult:
        """Run iterative deepening on a *copy* of ``board``."""
        limits = limits or SearchLimits()
        board = board.copy()
        self._reset_counters()
        self.stop_event.clear()
        soft, hard = compute_time_budget(limits, board.turn)
        self.hard_deadline = self.start_time + hard if hard is not None else None
        self.node_limit = limits.nodes
        max_depth = min(limits.depth or MAX_PLY - 1, MAX_PLY - 1)

        legal = list(board.legal_moves)
        if not legal:
            score = -MATE if board.is_check() else 0
            return SearchResult(None, None, score, 0, 0, 0, [])

        multipv = max(1, min(multipv, len(legal)))
        completed: list[PVLine] = []
        completed_depth = 0

        for depth in range(1, max_depth + 1):
            try:
                lines = self._search_root(board, depth, multipv)
            except SearchAborted:
                break
            completed = lines
            completed_depth = depth
            if on_iteration is not None:
                on_iteration(self._iteration_info(depth, lines))
            mate_fully_searched = (
                bool(lines) and is_mate_score(lines[0].score) and depth >= MATE - abs(lines[0].score) + 1
            )
            if mate_fully_searched and not limits.infinite:
                break  # a forced mate found and fully searched: deeper search cannot improve it
            if soft is not None and time.perf_counter() - self.start_time >= soft:
                break
            if self.stop_event.is_set():
                break

        if not completed:
            # Not even depth 1 completed (stopped instantly): play an ordered legal move.
            fallback = self._order_moves(board, legal, None, 0)[0]
            completed = [PVLine(1, 0, [fallback])]

        best = completed[0]
        elapsed = self._elapsed_ms()
        return SearchResult(
            best_move=best.pv[0],
            ponder=best.pv[1] if len(best.pv) > 1 else None,
            score=best.score,
            depth=completed_depth,
            nodes=self.nodes,
            time_ms=elapsed,
            lines=completed,
        )

    def stop(self) -> None:
        self.stop_event.set()

    # --------------------------------------------------------------- helpers
    def _elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.start_time) * 1000)

    def _iteration_info(self, depth: int, lines: list[PVLine]) -> IterationInfo:
        elapsed = self._elapsed_ms()
        nps = int(self.nodes * 1000 / elapsed) if elapsed > 0 else self.nodes * 1000
        return IterationInfo(depth, self.seldepth, self.nodes, elapsed, nps, self.tt.hashfull(), lines)

    def _check_limits(self) -> None:
        if self.stop_event.is_set():
            raise SearchAborted
        if self.hard_deadline is not None and time.perf_counter() >= self.hard_deadline:
            raise SearchAborted
        if self.node_limit is not None and self.nodes >= self.node_limit:
            raise SearchAborted

    @staticmethod
    def _key(board: chess.Board) -> int:
        return chess.polyglot.zobrist_hash(board)

    def _is_draw(self, board: chess.Board) -> bool:
        return board.halfmove_clock >= 100 or board.is_insufficient_material() or board.is_repetition(2)

    # ----------------------------------------------------------- move order
    def _order_moves(
        self, board: chess.Board, moves: list[chess.Move], tt_move: chess.Move | None, ply: int
    ) -> list[chess.Move]:
        killers = self.killers[ply] if self.config.killer_moves else (None, None)
        history = self.history[board.turn] if self.config.history_heuristic else None

        def score(move: chess.Move) -> int:
            if move == tt_move:
                return 10_000_000
            if board.is_capture(move):
                victim = board.piece_type_at(move.to_square) or chess.PAWN  # en passant
                attacker = board.piece_type_at(move.from_square) or chess.PAWN
                return 1_000_000 + ORDER_VALUE[victim] * 10 - ORDER_VALUE[attacker] // 10
            if move.promotion:
                return 900_000 + ORDER_VALUE[move.promotion]
            if move == killers[0]:
                return 800_000
            if move == killers[1]:
                return 790_000
            if history is not None:
                return history[move.from_square * 64 + move.to_square]
            return 0

        return sorted(moves, key=score, reverse=True)

    def _update_quiet_heuristics(self, board: chess.Board, move: chess.Move, depth: int, ply: int) -> None:
        if self.config.killer_moves and self.killers[ply][0] != move:
            self.killers[ply][1] = self.killers[ply][0]
            self.killers[ply][0] = move
        if self.config.history_heuristic:
            table = self.history[board.turn]
            idx = move.from_square * 64 + move.to_square
            table[idx] += depth * depth
            if table[idx] > 700_000:  # keep below killer scores; age everything
                self.history[board.turn] = [v // 2 for v in table]

    # ----------------------------------------------------------------- root
    def _search_root(self, board: chess.Board, depth: int, multipv: int) -> list[PVLine]:
        lines: list[PVLine] = []
        excluded: set[chess.Move] = set()
        for index in range(multipv):
            score, pv = self._root(board, depth, excluded)
            if not pv:
                break
            lines.append(PVLine(index + 1, score, pv))
            excluded.add(pv[0])
        lines.sort(key=lambda line: line.score, reverse=True)
        for i, line in enumerate(lines):
            line.multipv = i + 1
        return lines

    def _root(self, board: chess.Board, depth: int, excluded: set[chess.Move]) -> tuple[int, list[chess.Move]]:
        alpha, beta = -INF, INF
        tt_move = None
        if self.config.transposition_table and not excluded:
            entry = self.tt.get(self._key(board))
            tt_move = entry.move if entry else None
        moves = [m for m in board.legal_moves if m not in excluded]
        if not moves:
            return -INF, []
        best_score = -INF
        best_pv: list[chess.Move] = []
        for i, move in enumerate(self._order_moves(board, moves, tt_move, 0)):
            board.push(move)
            if i == 0:
                score = -self._negamax(board, depth - 1, -beta, -alpha, 1, True)
            else:
                score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, 1, True)
                if alpha < score < beta:
                    score = -self._negamax(board, depth - 1, -beta, -alpha, 1, True)
            board.pop()
            if score > best_score:
                best_score = score
                best_pv = [move, *self.pv_table[1]]
                if score > alpha:
                    alpha = score
        if self.config.transposition_table and not excluded and best_pv:
            self.tt.store(self._key(board), depth, best_score, EXACT, best_pv[0])
        return best_score, best_pv

    # ----------------------------------------------------------- main search
    def _negamax(self, board: chess.Board, depth: int, alpha: int, beta: int, ply: int, allow_null: bool) -> int:
        self.pv_table[ply] = []
        self.nodes += 1
        if self.nodes % CHECK_EVERY == 0:
            self._check_limits()
        if ply > self.seldepth:
            self.seldepth = ply

        if self._is_draw(board):
            return 0
        if ply >= MAX_PLY:
            return self.evaluator.evaluate(board)

        # Mate-distance pruning: no line from here can beat a shorter mate.
        alpha = max(alpha, -MATE + ply)
        beta = min(beta, MATE - ply - 1)
        if alpha >= beta:
            return alpha

        in_check = board.is_check()
        if in_check and self.config.check_extension:
            depth += 1

        if depth <= 0:
            return (
                self._quiescence(board, alpha, beta, ply) if self.config.quiescence else self.evaluator.evaluate(board)
            )

        pv_node = beta - alpha > 1
        alpha_orig = alpha
        key = 0
        tt_move = None
        if self.config.transposition_table:
            key = self._key(board)
            entry = self.tt.get(key)
            if entry is not None:
                tt_move = entry.move
                if entry.depth >= depth and not pv_node:
                    score = self._score_from_tt(entry.score, ply)
                    if entry.flag == EXACT:
                        return score
                    if entry.flag == LOWER and score >= beta:
                        return score
                    if entry.flag == UPPER and score <= alpha:
                        return score

        # Null-move pruning: if passing still fails high, the position is good enough.
        if (
            self.config.null_move
            and allow_null
            and not in_check
            and not pv_node
            and depth >= 3
            and self._has_non_pawn_material(board, board.turn)
            and self.evaluator.evaluate(board) >= beta
        ):
            board.push(chess.Move.null())
            score = -self._negamax(board, depth - 3, -beta, -beta + 1, ply + 1, False)
            board.pop()
            if score >= beta and not is_mate_score(score):
                return beta

        moves = list(board.legal_moves)
        if not moves:
            return -MATE + ply if in_check else 0

        best_score = -INF
        best_move: chess.Move | None = None
        for i, move in enumerate(self._order_moves(board, moves, tt_move, ply)):
            is_quiet = not board.is_capture(move) and not move.promotion
            board.push(move)
            gives_check = board.is_check()
            if i == 0:
                score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1, True)
            else:
                reduction = 0
                if (
                    self.config.late_move_reductions
                    and depth >= 3
                    and i >= 3
                    and is_quiet
                    and not in_check
                    and not gives_check
                ):
                    reduction = 1 if i < 8 else 2
                score = -self._negamax(board, depth - 1 - reduction, -alpha - 1, -alpha, ply + 1, True)
                if reduction and score > alpha:
                    score = -self._negamax(board, depth - 1, -alpha - 1, -alpha, ply + 1, True)
                if alpha < score < beta:
                    score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1, True)
            board.pop()

            if score > best_score:
                best_score = score
                best_move = move
                if score > alpha:
                    alpha = score
                    self.pv_table[ply] = [move, *self.pv_table[ply + 1]]
                    if alpha >= beta:
                        if is_quiet:
                            self._update_quiet_heuristics(board, move, depth, ply)
                        break

        if self.config.transposition_table:
            flag = UPPER if best_score <= alpha_orig else LOWER if best_score >= beta else EXACT
            self.tt.store(key, depth, self._score_to_tt(best_score, ply), flag, best_move)
        return best_score

    def _quiescence(self, board: chess.Board, alpha: int, beta: int, ply: int) -> int:
        self.pv_table[ply] = []
        self.nodes += 1
        if self.nodes % CHECK_EVERY == 0:
            self._check_limits()
        if ply > self.seldepth:
            self.seldepth = ply
        if ply >= MAX_PLY:
            return self.evaluator.evaluate(board)

        in_check = board.is_check()
        if in_check:
            # No stand-pat in check: every evasion must be considered.
            moves = list(board.legal_moves)
            if not moves:
                return -MATE + ply
            best = -INF
        else:
            stand_pat = self.evaluator.evaluate(board)
            if stand_pat >= beta:
                return stand_pat
            if stand_pat > alpha:
                alpha = stand_pat
            best = stand_pat
            moves = list(board.generate_legal_captures())
            promo_rank = chess.BB_RANK_8 if board.turn == chess.WHITE else chess.BB_RANK_1
            moves.extend(
                m
                for m in board.generate_legal_moves(
                    board.pawns & board.occupied_co[board.turn], promo_rank & ~board.occupied
                )
                if m.promotion == chess.QUEEN
            )

        for move in self._order_moves(board, moves, None, min(ply, MAX_PLY)):
            if not in_check and board.is_capture(move) and not move.promotion:
                # Delta pruning: even winning this piece cannot lift us to alpha.
                victim = board.piece_type_at(move.to_square) or chess.PAWN
                if best + ORDER_VALUE[victim] + 200 < alpha:
                    continue
            board.push(move)
            score = -self._quiescence(board, -beta, -alpha, ply + 1)
            board.pop()
            if score > best:
                best = score
                if score > alpha:
                    alpha = score
                    self.pv_table[ply] = [move, *self.pv_table[ply + 1]]
                    if alpha >= beta:
                        break
        return best

    @staticmethod
    def _has_non_pawn_material(board: chess.Board, color: chess.Color) -> bool:
        return bool((board.knights | board.bishops | board.rooks | board.queens) & board.occupied_co[color])

    @staticmethod
    def _score_to_tt(score: int, ply: int) -> int:
        if score >= MATE_BOUND:
            return score + ply
        if score <= -MATE_BOUND:
            return score - ply
        return score

    @staticmethod
    def _score_from_tt(score: int, ply: int) -> int:
        if score >= MATE_BOUND:
            return score - ply
        if score <= -MATE_BOUND:
            return score + ply
        return score
