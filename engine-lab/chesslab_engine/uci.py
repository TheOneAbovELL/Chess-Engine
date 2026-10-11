"""Universal Chess Interface (UCI) front end.

Run with ``python -m chesslab_engine``. The engine can then be used by the
ChessLab backend (through the same UCI adapter that drives Stockfish) or by any
UCI GUI such as Arena, Cute Chess or En Croissant.

The search runs on a worker thread so that ``stop``, ``isready`` and ``quit``
are processed while the engine is thinking, as the UCI protocol requires.
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from typing import TextIO

import chess

from . import ENGINE_AUTHOR, ENGINE_NAME, __version__
from .evaluation import EvalConfig, Evaluator
from .search import (
    IterationInfo,
    SearchConfig,
    Searcher,
    SearchLimits,
    is_mate_score,
    mate_in,
)
from .tt import TranspositionTable

# UCI check options -> (config object attribute owner, attribute name)
SEARCH_OPTIONS = {
    "UseQuiescence": "quiescence",
    "UseTranspositionTable": "transposition_table",
    "UseNullMove": "null_move",
    "UseKillerMoves": "killer_moves",
    "UseHistoryHeuristic": "history_heuristic",
    "UseLateMoveReductions": "late_move_reductions",
    "UseCheckExtension": "check_extension",
}
EVAL_OPTIONS = {
    "EvalMobility": "mobility",
    "EvalKingSafety": "king_safety",
    "EvalPawnStructure": "pawn_structure",
    "EvalPassedPawns": "passed_pawns",
    "EvalPieceActivity": "piece_activity",
    "EvalEndgame": "endgame",
}
MAX_HASH_MB = 1024
MAX_MULTIPV = 5


def format_score(score: int) -> str:
    if is_mate_score(score):
        return f"mate {mate_in(score)}"
    return f"cp {score}"


class UciEngine:
    def __init__(self, out: TextIO = sys.stdout) -> None:
        self.out = out
        self.write_lock = threading.Lock()
        self.board = chess.Board()
        self.hash_mb = 32
        self.multipv = 1
        self.search_config = SearchConfig()
        self.eval_config = EvalConfig()
        self.searcher = Searcher(Evaluator(self.eval_config), self.search_config, TranspositionTable(self.hash_mb))
        self.thread: threading.Thread | None = None

    # ------------------------------------------------------------- output
    def send(self, line: str) -> None:
        with self.write_lock:
            self.out.write(line + "\n")
            self.out.flush()

    # ------------------------------------------------------------- commands
    def handle(self, line: str) -> bool:
        """Process one command. Returns False when the engine should exit."""
        tokens = line.strip().split()
        if not tokens:
            return True
        cmd, args = tokens[0], tokens[1:]
        handler: Callable[[list[str]], None] | None = {
            "uci": self.cmd_uci,
            "isready": lambda _a: self.send("readyok"),
            "ucinewgame": self.cmd_newgame,
            "setoption": self.cmd_setoption,
            "position": self.cmd_position,
            "go": self.cmd_go,
            "stop": lambda _a: self.stop_search(),
            "ponderhit": lambda _a: None,
            "d": lambda _a: self.send(str(self.board) + "\nFen: " + self.board.fen()),
        }.get(cmd)
        if cmd == "quit":
            self.stop_search()
            return False
        if handler is None:
            self.send(f"info string unknown command: {cmd}")
            return True
        try:
            handler(args)
        except (ValueError, IndexError) as exc:  # malformed input must never crash the engine
            self.send(f"info string error: {exc}")
        return True

    def cmd_uci(self, _args: list[str]) -> None:
        self.send(f"id name {ENGINE_NAME} {__version__}")
        self.send(f"id author {ENGINE_AUTHOR}")
        self.send(f"option name Hash type spin default 32 min 1 max {MAX_HASH_MB}")
        self.send(f"option name MultiPV type spin default 1 min 1 max {MAX_MULTIPV}")
        self.send("option name Clear Hash type button")
        for name in [*SEARCH_OPTIONS, *EVAL_OPTIONS]:
            self.send(f"option name {name} type check default true")
        self.send("uciok")

    def cmd_newgame(self, _args: list[str]) -> None:
        self.stop_search()
        self.searcher.new_game()
        self.board = chess.Board()

    def cmd_setoption(self, args: list[str]) -> None:
        # setoption name <id> [value <x>]; names may contain spaces.
        if "name" not in args:
            raise ValueError("setoption requires 'name'")
        name_start = args.index("name") + 1
        if "value" in args:
            v = args.index("value")
            name = " ".join(args[name_start:v])
            value = " ".join(args[v + 1 :])
        else:
            name, value = " ".join(args[name_start:]), ""
        self.stop_search()
        lname = name.lower()
        if lname == "hash":
            self.hash_mb = max(1, min(MAX_HASH_MB, int(value)))
            self.searcher.tt.resize(self.hash_mb)
        elif lname == "multipv":
            self.multipv = max(1, min(MAX_MULTIPV, int(value)))
        elif lname == "clear hash":
            self.searcher.tt.clear()
        else:
            for opt, attr in SEARCH_OPTIONS.items():
                if opt.lower() == lname:
                    setattr(self.search_config, attr, value.lower() == "true")
                    return
            for opt, attr in EVAL_OPTIONS.items():
                if opt.lower() == lname:
                    setattr(self.eval_config, attr, value.lower() == "true")
                    return
            self.send(f"info string unknown option: {name}")

    def cmd_position(self, args: list[str]) -> None:
        self.stop_search()
        if not args:
            raise ValueError("position requires arguments")
        moves: list[str] = []
        if "moves" in args:
            m = args.index("moves")
            moves = args[m + 1 :]
            args = args[:m]
        if args[0] == "startpos":
            board = chess.Board()
        elif args[0] == "fen":
            board = chess.Board(" ".join(args[1:]))
        else:
            raise ValueError(f"unknown position type {args[0]}")
        for uci in moves:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                raise ValueError(f"illegal move {uci}")
            board.push(move)
        self.board = board

    def cmd_go(self, args: list[str]) -> None:
        self.stop_search()
        limits = SearchLimits()
        int_args = {
            "depth": "depth",
            "nodes": "nodes",
            "movetime": "movetime_ms",
            "wtime": "wtime_ms",
            "btime": "btime_ms",
            "winc": "winc_ms",
            "binc": "binc_ms",
            "movestogo": "movestogo",
        }
        i = 0
        while i < len(args):
            tok = args[i]
            if tok in int_args and i + 1 < len(args):
                setattr(limits, int_args[tok], max(0, int(args[i + 1])))
                i += 2
                continue
            if tok == "infinite":
                limits.infinite = True
            i += 1
        if limits.depth is not None:
            limits.depth = max(1, limits.depth)
        board = self.board.copy()
        self.thread = threading.Thread(target=self._run_search, args=(board, limits), daemon=True)
        self.thread.start()

    def stop_search(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            self.searcher.stop()
            self.thread.join()
        self.thread = None

    # ------------------------------------------------------------- search
    def _report(self, info: IterationInfo) -> None:
        for line in info.lines:
            pv = " ".join(m.uci() for m in line.pv)
            self.send(
                f"info depth {info.depth} seldepth {info.seldepth} multipv {line.multipv} "
                f"score {format_score(line.score)} nodes {info.nodes} nps {info.nps} "
                f"hashfull {info.hashfull} time {info.time_ms} pv {pv}"
            )

    def _run_search(self, board: chess.Board, limits: SearchLimits) -> None:
        try:
            result = self.searcher.search(board, limits, self.multipv, self._report)
        except Exception as exc:  # pragma: no cover - last-resort safety net
            self.send(f"info string search error: {exc!r}")
            legal = list(board.legal_moves)
            self.send(f"bestmove {legal[0].uci() if legal else '0000'}")
            return
        if result.best_move is None:
            self.send("bestmove 0000")
        elif result.ponder is not None:
            self.send(f"bestmove {result.best_move.uci()} ponder {result.ponder.uci()}")
        else:
            self.send(f"bestmove {result.best_move.uci()}")


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    engine = UciEngine(stdout)
    for raw in stdin:
        if not engine.handle(raw):
            break
    engine.stop_search()
