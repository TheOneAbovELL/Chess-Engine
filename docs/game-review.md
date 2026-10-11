# Game review: how moves are evaluated and classified

## Pipeline

1. The stored PGN is parsed and every position of the main line is rebuilt (with move history, so repetitions are visible to the engine).
2. Each position is searched with **the same limits**: a depth (default 14) with a per-position time cap (default 1 s), on a dedicated review engine process (Stockfish by default). Terminal positions (mate, stalemate, insufficient material, 75-move rule, fivefold repetition) are scored exactly without the engine.
3. Results are stored per position as they are produced, so an interrupted review resumes where it stopped.
4. When all positions are done, each move is classified from the evaluations of the position before and after it. Changing thresholds later only re-labels moves (`/reviews/{id}/reclassify`); the engine is not re-run.

## Evaluation conventions

* All scores are from **White's point of view**: `cp` in centipawns (+ favours White), `mate` in moves (+ White mates, − Black mates, 0 = the side to move is checkmated).
* **Expected score** converts an evaluation into White's chance of scoring, using the logistic curve that Lichess publishes for its "winning chances":

  `E(cp) = 1 / (1 + exp(−0.00368208 · cp))`

  E(0) = 50 %, E(+100) ≈ 59 %, E(+300) ≈ 75 %, E(+1000) ≈ 97.5 %. A forced mate for White is 100 %, for Black 0 %.

## Classification

For a move by player **M** from position **P** to position **Q**:

* `best` = the engine's evaluation of **P** (its top line), from M's point of view.
* `after` = the engine's evaluation of **Q**, from M's point of view.
* `loss = max(0, E(best) − E(after))`, the expected score M gave away.

| Label | Rule (default thresholds, configurable in Settings) |
| --- | --- |
| **Forced** | The only legal move (excluded from statistics). |
| **Best** | The move is the engine's top choice. |
| **Excellent** | loss < 2 % |
| **Good** | loss < 5 % |
| **Inaccuracy** | loss < 10 % |
| **Mistake** | loss < 20 % |
| **Blunder** | loss ≥ 20 % |

Examples with the defaults: from an equal position (+0.30), a move to −0.50 loses ≈ 7 % (inaccuracy); to −1.30 ≈ 15 % (mistake); to −4.00 ≈ 34 % (blunder). The same three-pawn drop matters far less when the game is already decided: +10 → +7 loses ≈ 4.6 % (good), while +1.50 → −1.50 loses ≈ 27 % (blunder). Allowing a forced mate loses nearly everything (blunder).

**Average centipawn loss (ACPL)** is also reported per side, with mates and large values capped at ±1000 cp, excluding forced moves.

## Limitations (please read)

* These labels are **ChessLab's own**. They are not, and do not try to reproduce, Chess.com's or Lichess's proprietary classifications or accuracy scores.
* Evaluations are **engine estimates** at a finite depth. A deeper search can change them, especially in sharp tactical positions or long endgames.
* `before` and `after` come from two searches of the same depth, one ply apart. Search instability (horizon effects) can occasionally make a good move look slightly worse or better than it is. This is why playing the engine's top move is always classified *best*, regardless of the measured loss.
* One threshold set cannot be perfect for every position. That is why thresholds are configurable and reclassification is cheap.
* Time pressure, practical chances and human-likeness are not modelled.

## Statistics built on reviews

The dashboard aggregates *your* moves (by colour from the game's owner) in reviewed games. It reports the class distribution, mistake rates per phase (opening = first 20 plies, endgame = at most 6 minor/major pieces left, otherwise middlegame), and **potential patterns** only above minimum sample sizes. Each pattern shows its evidence, sample size and a confidence level (low < 30, medium < 100, high ≥ 100). Examples: errors that allowed a forcing reply, missed forcing moves, accuracy under time pressure (when clock data exists), weak openings (≥ 5 games, ≤ 35 % score), colour or time-control gaps (≥ 10 games each, ≥ 15 % difference). They are prompts for study, not verdicts.
