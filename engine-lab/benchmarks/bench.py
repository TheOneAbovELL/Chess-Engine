"""Fixed-depth benchmark for the ChessLab engine.

Searches every position in ``positions.epd`` to a fixed depth with a fresh
engine and reports nodes, time, nodes/second and the chosen move.

Because the search is single-threaded and deterministic, the *total node count*
is a reproducible signature of the search: a change that alters it changed the
search tree. Time and NPS depend on the machine and on background load.

Usage (from the repository root, with the backend virtualenv active):

    python engine-lab/benchmarks/bench.py --depth 4
    python engine-lab/benchmarks/bench.py --depth 4 --save results/my-run.json
    python engine-lab/benchmarks/bench.py --depth 4 --compare engine-lab/benchmarks/results/baseline.json
    python engine-lab/benchmarks/bench.py --depth 4 --set UseNullMove=false
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import chess

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from chesslab_engine import __version__  # noqa: E402
from chesslab_engine.evaluation import EvalConfig, Evaluator  # noqa: E402
from chesslab_engine.search import SearchConfig, Searcher, SearchLimits  # noqa: E402
from chesslab_engine.uci import EVAL_OPTIONS, SEARCH_OPTIONS  # noqa: E402


def load_positions(path: Path) -> list[tuple[str, str]]:
    positions = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        fen, _, ident = line.partition(";")
        board = chess.Board(fen.strip())  # validates the FEN
        positions.append((board.fen(), ident.strip() or board.fen()))
    return positions


def apply_settings(pairs: list[str], search: SearchConfig, evaluation: EvalConfig) -> dict[str, bool]:
    applied: dict[str, bool] = {}
    for pair in pairs:
        name, _, value = pair.partition("=")
        flag = value.strip().lower() in {"1", "true", "yes", "on"}
        if name in SEARCH_OPTIONS:
            setattr(search, SEARCH_OPTIONS[name], flag)
        elif name in EVAL_OPTIONS:
            setattr(evaluation, EVAL_OPTIONS[name], flag)
        else:
            raise SystemExit(f"unknown option {name!r}; choose from {[*SEARCH_OPTIONS, *EVAL_OPTIONS]}")
        applied[name] = flag
    return applied


def run(depth: int, positions: list[tuple[str, str]], settings: list[str]) -> dict[str, object]:
    rows = []
    total_nodes = 0
    total_time = 0.0
    search_cfg, eval_cfg = SearchConfig(), EvalConfig()
    applied = apply_settings(settings, search_cfg, eval_cfg)
    for fen, ident in positions:
        searcher = Searcher(Evaluator(eval_cfg), search_cfg)  # fresh TT: reproducible
        start = time.perf_counter()
        result = searcher.search(chess.Board(fen), SearchLimits(depth=depth))
        elapsed = time.perf_counter() - start
        total_nodes += result.nodes
        total_time += elapsed
        rows.append(
            {
                "id": ident,
                "fen": fen,
                "best_move": result.best_move.uci() if result.best_move else None,
                "score": result.score,
                "nodes": result.nodes,
                "seconds": round(elapsed, 3),
                "nps": int(result.nodes / elapsed) if elapsed else 0,
            }
        )
        print(f"{ident:<22} {rows[-1]['best_move']!s:<7} nodes {result.nodes:>9,}  {elapsed:7.2f}s  {rows[-1]['nps']:>7,} nps", flush=True)
    return {
        "engine_version": __version__,
        "depth": depth,
        "settings": applied,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": {"python": platform.python_version(), "platform": platform.platform(), "processor": platform.processor()},
        "total_nodes": total_nodes,
        "total_seconds": round(total_time, 3),
        "nps": int(total_nodes / total_time) if total_time else 0,
        "positions": rows,
    }


def compare(current: dict[str, object], baseline_path: Path) -> None:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if baseline.get("depth") != current["depth"]:
        print(f"\n(baseline depth {baseline.get('depth')} != current depth {current['depth']}: node counts are not comparable)")
        return
    base_rows = {row["id"]: row for row in baseline["positions"]}
    changed = 0
    print(f"\nComparison with {baseline_path.name} (engine {baseline.get('engine_version')}):")
    for row in current["positions"]:  # type: ignore[union-attr]
        base = base_rows.get(row["id"])
        if not base:
            continue
        same = base["best_move"] == row["best_move"]
        changed += not same
        delta = (row["nodes"] - base["nodes"]) / base["nodes"] * 100 if base["nodes"] else 0.0
        print(f"  {row['id']:<22} move {'same' if same else base['best_move'] + ' -> ' + str(row['best_move']):<16} nodes {delta:+6.1f}%")
    total_delta = (current["total_nodes"] - baseline["total_nodes"]) / baseline["total_nodes"] * 100  # type: ignore[operator]
    print(f"  total nodes {total_delta:+.1f}%, best-move changes: {changed}/{len(current['positions'])}")  # type: ignore[arg-type]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--depth", type=int, default=4)
    parser.add_argument("--positions", type=Path, default=HERE / "positions.epd")
    parser.add_argument("--save", type=Path, help="write results JSON to this path")
    parser.add_argument("--compare", type=Path, help="compare against a saved results JSON")
    parser.add_argument("--set", action="append", default=[], metavar="Option=bool", help="toggle a UCI feature option")
    args = parser.parse_args()

    result = run(args.depth, load_positions(args.positions), args.set)
    print(f"\nTotal: {result['total_nodes']:,} nodes in {result['total_seconds']}s ({result['nps']:,} nps) at depth {args.depth}")
    if args.compare:
        compare(result, args.compare)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Saved {args.save}")


if __name__ == "__main__":
    main()
