"""Play a controlled match between two UCI engine configurations.

Every opening in ``openings.txt`` is played twice with colours swapped, so both
sides get the same positions. Games longer than ``--max-plies`` are adjudicated
as draws (reported separately).

The Elo difference printed at the end is a *statistical estimate from this
match only*. It depends on the opponents, time control, openings and number of
games, and is not a rating on any public scale. With few games the 95%
interval is very wide; the script says so rather than hiding it.

Examples (from the repository root, backend virtualenv active):

    # Does null-move pruning help? Same engine, one feature off.
    python engine-lab/benchmarks/match.py --options2 UseNullMove=false --movetime 200

    # Custom engine vs strength-limited Stockfish
    python engine-lab/benchmarks/match.py --engine2 engines/stockfish/stockfish/stockfish-windows-x86-64-universal.exe \
        --options2 UCI_LimitStrength=true --options2 UCI_Elo=1350 --movetime 200
"""

from __future__ import annotations

import argparse
import json
import math
import shlex
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import chess
import chess.engine
import chess.pgn

HERE = Path(__file__).resolve().parent
DEFAULT_ENGINE = f'"{sys.executable}" -m chesslab_engine'


@dataclass
class Tally:
    wins: int = 0
    draws: int = 0
    losses: int = 0
    adjudicated: int = 0
    games: list[dict[str, str]] = field(default_factory=list)

    @property
    def n(self) -> int:
        return self.wins + self.draws + self.losses

    @property
    def score(self) -> float:
        return (self.wins + 0.5 * self.draws) / self.n if self.n else 0.0


def split_command(command: str) -> list[str]:
    """Split an engine command line. On Windows ``shlex`` keeps quote characters
    in non-POSIX mode, so strip them from each token afterwards."""
    if sys.platform == "win32":
        return [token.strip('"') for token in shlex.split(command, posix=False)]
    return shlex.split(command)


def elo_estimate(t: Tally) -> tuple[float | None, float | None, float | None]:
    """Elo difference with a 95% confidence interval (normal approximation)."""
    if t.n == 0:
        return None, None, None
    s = t.score
    if s in (0.0, 1.0):
        return (math.inf if s == 1 else -math.inf), None, None
    elo = -400 * math.log10(1 / s - 1)
    variance = (t.wins * (1 - s) ** 2 + t.draws * (0.5 - s) ** 2 + t.losses * (0 - s) ** 2) / t.n
    if variance == 0:  # e.g. every game drawn: no spread to build an interval from
        return elo + 0.0, None, None
    stderr = math.sqrt(variance / t.n)
    lo, hi = max(1e-6, s - 1.96 * stderr), min(1 - 1e-6, s + 1.96 * stderr)
    return elo, -400 * math.log10(1 / lo - 1), -400 * math.log10(1 / hi - 1)


def parse_options(pairs: list[str]) -> dict[str, str | int | bool]:
    options: dict[str, str | int | bool] = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        low = value.lower()
        options[name] = (
            True if low == "true" else False if low == "false" else int(value) if value.lstrip("-").isdigit() else value
        )
    return options


def load_openings(path: Path) -> list[list[str]]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            board = chess.Board()
            for uci in line.split():
                board.push_uci(uci)  # validates legality
            lines.append(line.split())
    return lines


def play_game(
    white: chess.engine.SimpleEngine,
    black: chess.engine.SimpleEngine,
    opening: list[str],
    limit: chess.engine.Limit,
    max_plies: int,
    game_key: object,
) -> tuple[str, bool, chess.pgn.Game]:
    board = chess.Board()
    for uci in opening:
        board.push_uci(uci)
    engines = {chess.WHITE: white, chess.BLACK: black}
    adjudicated = False
    while not board.is_game_over(claim_draw=True):
        if board.ply() >= max_plies:
            adjudicated = True
            break
        # A new ``game`` key makes python-chess send ``ucinewgame`` (fresh hash tables).
        result = engines[board.turn].play(board, limit, game=game_key)
        if result.move is None or result.move not in board.legal_moves:
            raise RuntimeError(f"engine returned illegal move {result.move} in {board.fen()}")
        board.push(result.move)
    outcome = "1/2-1/2" if adjudicated else board.result(claim_draw=True)
    game = chess.pgn.Game.from_board(board)
    game.headers["Result"] = outcome
    return outcome, adjudicated, game


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine1", default=DEFAULT_ENGINE)
    parser.add_argument("--engine2", default=DEFAULT_ENGINE)
    parser.add_argument("--options1", action="append", default=[], metavar="Name=value")
    parser.add_argument("--options2", action="append", default=[], metavar="Name=value")
    parser.add_argument("--movetime", type=int, default=200, help="milliseconds per move (default 200)")
    parser.add_argument("--depth", type=int, help="fixed depth per move instead of movetime")
    parser.add_argument("--openings", type=Path, default=HERE / "openings.txt")
    parser.add_argument("--rounds", type=int, default=1, help="times to repeat the opening suite")
    parser.add_argument("--max-plies", type=int, default=200)
    parser.add_argument("--pgn", type=Path, help="write all games to this PGN file")
    parser.add_argument("--save", type=Path, help="write a JSON summary")
    args = parser.parse_args()

    limit = chess.engine.Limit(depth=args.depth) if args.depth else chess.engine.Limit(time=args.movetime / 1000)
    openings = load_openings(args.openings) * args.rounds
    e1 = chess.engine.SimpleEngine.popen_uci(split_command(args.engine1))
    e2 = chess.engine.SimpleEngine.popen_uci(split_command(args.engine2))
    try:
        e1.configure(parse_options(args.options1))
        e2.configure(parse_options(args.options2))
        name1 = f"{e1.id.get('name', 'engine1')} {args.options1 or ''}".strip()
        name2 = f"{e2.id.get('name', 'engine2')} {args.options2 or ''}".strip()
        tally = Tally()
        pgn_out = []
        started = time.perf_counter()
        game_no = 0
        for opening in openings:
            for engine1_white in (True, False):
                game_no += 1
                white, black = (e1, e2) if engine1_white else (e2, e1)
                result, adjudicated, game = play_game(white, black, opening, limit, args.max_plies, object())
                game.headers["White"] = name1 if engine1_white else name2
                game.headers["Black"] = name2 if engine1_white else name1
                game.headers["Round"] = str(game_no)
                pgn_out.append(str(game))
                tally.adjudicated += adjudicated
                if result == "1/2-1/2":
                    tally.draws += 1
                elif (result == "1-0") == engine1_white:
                    tally.wins += 1
                else:
                    tally.losses += 1
                tally.games.append(
                    {"round": str(game_no), "result": result, "engine1": "white" if engine1_white else "black"}
                )
                print(
                    f"game {game_no:>3}: {result:<7} (engine1 {'white' if engine1_white else 'black'})  running +{tally.wins} ={tally.draws} -{tally.losses}",
                    flush=True,
                )
    finally:
        e1.quit()
        e2.quit()

    elo, lo, hi = elo_estimate(tally)
    print(f"\nengine1: {name1}\nengine2: {name2}")
    print(
        f"Result for engine1: +{tally.wins} ={tally.draws} -{tally.losses}  score {tally.score:.1%} over {tally.n} games ({tally.adjudicated} adjudicated at {args.max_plies} plies)"
    )
    if elo is not None and lo is not None and hi is not None:
        print(f"Elo difference estimate: {elo:+.0f}  (95% CI {lo:+.0f} .. {hi:+.0f})")
    elif elo is not None and math.isinf(elo):
        print("Elo difference estimate: unbounded (one side scored 100%); play more games.")
    elif elo is not None:
        print(f"Elo difference estimate: {elo:+.0f}, no confidence interval (all results identical); play more games.")
    if tally.n < 100:
        print("Note: fewer than 100 games; treat the estimate as a rough indication only.")
    print(f"Wall time {time.perf_counter() - started:.0f}s")

    if args.pgn:
        args.pgn.write_text("\n\n".join(pgn_out) + "\n", encoding="utf-8")
    if args.save:
        args.save.write_text(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
                    "engine1": name1,
                    "engine2": name2,
                    "limit": {"movetime_ms": None if args.depth else args.movetime, "depth": args.depth},
                    "wins": tally.wins,
                    "draws": tally.draws,
                    "losses": tally.losses,
                    "adjudicated": tally.adjudicated,
                    "score": tally.score,
                    "elo_estimate": elo,
                    "elo_ci95": [lo, hi],
                    "games": tally.games,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
