# ChessLab Engine

An educational UCI chess engine in Python: alpha-beta/PVS with iterative deepening,
quiescence, transposition table, killer/history ordering, null-move pruning, LMR,
MultiPV, and a tapered PeSTO-based evaluation with mobility, king safety, pawn
structure, passed pawns, piece activity and mop-up terms. Every technique can be
toggled through UCI options so its value can be measured.

    python -m chesslab_engine            # speak UCI on stdin/stdout
    python -m pytest                     # tests (from this folder)
    python benchmarks/bench.py --depth 4 --compare benchmarks/results/baseline.json
    python benchmarks/match.py --options2 UseNullMove=false --movetime 200

Design, implemented techniques, benchmarking method and next steps:
[../docs/engine-design.md](../docs/engine-design.md).

Legal move generation, board representation and UCI client utilities come from
python-chess (GPL-3.0-or-later); see ../docs/third-party-licenses.md.
