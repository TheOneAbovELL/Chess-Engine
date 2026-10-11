# The ChessLab engine

`engine-lab/chesslab_engine` is an educational chess engine written in Python. It is meant to be **read, measured and improved**, not to rival Stockfish. It speaks UCI (`python -m chesslab_engine`), so it can also be used from GUIs such as Arena, Cute Chess or En Croissant.

## Structure

| File | Responsibility |
| --- | --- |
| `pst.py` | Material values and PeSTO piece-square tables (middlegame/endgame), precomputed per colour and square |
| `evaluation.py` | Independent evaluation components, the tapered `Evaluator`, a pawn hash table and a per-term breakdown |
| `search.py` | Iterative deepening, negamax alpha-beta (PVS), quiescence, move ordering, pruning, MultiPV, time management |
| `tt.py` | Transposition table (Zobrist keys, depth-preferred replacement, bounded size) |
| `uci.py` | UCI protocol front end; search on a worker thread so `stop`/`isready` are handled while thinking |

Legal move generation uses **python-chess**, a trusted rules library. That keeps the engine correct, and makes a hand-written bitboard generator a clear next step.

## Implemented techniques

Status legend: ✅ implemented and tested · ⏳ future work

### Phase 1: basics
* ✅ Legal moves via python-chess; terminal positions (mate/stalemate) return `bestmove 0000`
* ✅ Material and piece-square tables (tapered PeSTO)
* ✅ Minimax in negamax form with **alpha-beta pruning**, configurable depth, best-move selection

### Phase 2: search
* ✅ **Iterative deepening** with a triangular PV table (`info depth … pv …` each iteration)
* ✅ **Principal-variation search** (null-window re-searches)
* ✅ **Move ordering**: TT move, MVV-LVA captures, promotions, **killer moves** (2 per ply), **history heuristic**
* ✅ **Transposition table** keyed by **Zobrist** hashes (python-chess's polyglot Zobrist keys, recomputed per node), with mate-score ply correction
* ✅ **Quiescence search**: captures and queen promotions; all evasions when in check; delta pruning
* ✅ **Null-move pruning** (R = 2, not in check, not without pieces), **late-move reductions**, **check extension**, **mate-distance pruning**
* ✅ Draw detection: repetition, fifty-move rule, insufficient material
* ✅ **Cancellation** (`stop`), node limits, **time management** (`movetime`, or `wtime/btime/winc/binc/movestogo` with soft/hard budgets)
* ✅ **MultiPV** (root searched again excluding earlier best moves)
* ⏳ Incremental Zobrist hashing, aspiration windows, static exchange evaluation, futility/razoring, singular extensions

### Phase 3: evaluation
* ✅ Piece-square tables, tapered by game phase
* ✅ Mobility (squares not attacked by enemy pawns)
* ✅ King safety: pawn shield, open/semi-open files near the king, multi-attacker pressure on the king zone (middlegame only)
* ✅ Pawn structure: doubled, isolated, connected pawns (cached in a **pawn hash table**)
* ✅ Passed pawns by relative rank (precomputed masks)
* ✅ Piece activity: bishop pair, rooks on open/semi-open files and on the 7th rank
* ✅ Endgame: mop-up evaluation to convert K+Q/K+R vs K
* ✅ Tempo bonus; colour-symmetric evaluation (verified by a mirroring test)
* ⏳ Weight tuning (Texel), king-pawn tropism, outposts, space, endgame scaling for opposite bishops

Every search and evaluation term can be **switched off through UCI options** (`UseNullMove`, `UseQuiescence`, `EvalMobility`, …). That is what makes their value measurable.

## Measuring progress honestly

### Fixed-depth bench (speed and search-tree signature)

```powershell
backend\.venv\Scripts\python engine-lab\benchmarks\bench.py --depth 4
backend\.venv\Scripts\python engine-lab\benchmarks\bench.py --depth 4 --compare engine-lab\benchmarks\results\baseline.json
backend\.venv\Scripts\python engine-lab\benchmarks\bench.py --depth 4 --set UseNullMove=false
```

The search is single-threaded and deterministic, so the **total node count** at a fixed depth is a reproducible signature: if a change alters it, the search tree changed. Time and nodes/second depend on the machine and its load. The committed baseline (`results/baseline.json`, engine 0.3.0, depth 4) is **88,551 nodes**. On the development laptop (Ryzen, with other heavy processes running) that took about 8 s, roughly 10,700 nodes/s; expect 5–20k nodes/s depending on the position.

### Matches (playing strength)

```powershell
# Is null-move pruning worth it? Same engine, one feature disabled, colours alternated per opening.
backend\.venv\Scripts\python engine-lab\benchmarks\match.py --options2 UseNullMove=false --movetime 200 --rounds 5

# Against strength-limited Stockfish
backend\.venv\Scripts\python engine-lab\benchmarks\match.py --engine2 engines\stockfish\stockfish\stockfish-windows-x86-64-universal.exe --options2 UCI_LimitStrength=true --options2 UCI_Elo=1400 --movetime 200
```

Each opening in `openings.txt` is played twice with colours swapped. Games over `--max-plies` are adjudicated as draws and reported. The script prints W/D/L, the score, and an **Elo difference with a 95 % confidence interval for that match only**.

**No absolute Elo rating is claimed for this engine.** A strength estimate is only meaningful together with its opponents, time control, opening set and number of games, and with a few dozen games the confidence interval spans hundreds of Elo. Record those conditions with any result you publish.

## Next steps for a faster engine

1. Profile (`python -m cProfile`) and keep the bench signature as a regression guard.
2. Incremental Zobrist and incremental material/PST updates in `push`/`pop`.
3. Static exchange evaluation for capture ordering and quiescence pruning.
4. Move the core (board, move generation, search) to Rust or C behind a Python extension, keeping the Python evaluation as the reference implementation for testing.
5. Texel tuning of the evaluation weights against a labelled position set.
