# ChessLab

**A local-first chess analysis laboratory.** Play and analyse with Stockfish, import your public games from Chess.com and Lichess, get every game reviewed move by move, see where your results come from — and study (or improve) a chess engine written from scratch in Python.

Everything runs on your own computer. No accounts, no API keys, no paid services, no telemetry. Your games stay in a local SQLite database.

---

## Features

| Area | What you get |
| --- | --- |
| **Analysis** | Interactive board (drag or click, legal-move hints, promotion picker, typed moves), live Stockfish analysis over WebSocket with 1–5 candidate lines, evaluation bar, best-move arrow, depth/nodes/speed, a variation tree with undo/redo, FEN set-up, PGN load/export. |
| **Play** | Ten Stockfish strength levels (skill-limited and Elo-limited) plus the custom engine; takebacks, resign, optional "engine reasoning" panel, save the game, open it in analysis. |
| **Import** | Chess.com (official Published-Data API) and Lichess (official games export) by username — presets (25/50/100/custom/all), date/time-control/colour/rated filters, live progress, cancel/retry, "only new games" refresh, duplicate-safe re-imports. PGN file upload too. |
| **Game history** | Search, filter (result, colour, time control, account, source, dates, opening, reviewed), sort, paginate, export PGN, bulk review or delete. |
| **Game review** | Background engine review of every position, resumable after restarts; best vs played move, alternatives, expected-score loss, centipawn loss, documented move classifications (best → blunder), clickable evaluation graph, per-side summary. |
| **Dashboard** | Real statistics only: results by colour and time control, rating over time, opening families, game length, how games end, move quality by phase, and *inferred* patterns that always show their sample size and confidence. |
| **Opening explorer** | Your personal opening tree built from your own games, with your results per move. |
| **Engine Lab** | Stockfish vs the ChessLab engine on the same position, the custom engine's evaluation broken down by term, and the list of search/evaluation techniques it implements. |
| **Custom engine** | `engine-lab/`: an educational UCI engine (alpha-beta/PVS, iterative deepening, quiescence, TT, killers/history, null-move, LMR, MultiPV, PeSTO-based tapered evaluation) with reproducible benchmarks and a match runner. |

Screenshots are not included yet; run the app to see the interface.

## Architecture in one picture

```
 Browser (React + TypeScript, Vite)            ChessLab backend (FastAPI, Python)              Local resources
 ┌──────────────────────────────┐   REST /api/v1   ┌──────────────────────────────────────┐   ┌──────────────────┐
 │ Analysis · Play · History    │ ───────────────► │ API routers (thin)                   │   │ SQLite (WAL)     │
 │ Review · Dashboard · Lab     │   WebSocket      │ Services: analysis, games, imports,  │──►│ %LOCALAPPDATA%\  │
 │ chess.js for instant UI      │ ◄──────────────► │ review, statistics, explorer         │   │ ChessLab         │
 └──────────────────────────────┘  live analysis   │ Engine manager ─ engine thread ──────┼──►│ Stockfish (UCI)  │
                                                    │ Background workers (imports, reviews)│   │ ChessLab engine  │
                                                    │ Providers ── httpx (polite) ─────────┼──►│ (UCI subprocess) │
                                                    └──────────────────────────────────────┘   └──────────────────┘
                                                                   │ public data only
                                                                   ▼
                                                     api.chess.com/pub · lichess.org/api
```

The backend validates every position and move it receives; the frontend never has the final word. Details: [docs/architecture.md](docs/architecture.md).

## Quick start (Windows)

Requirements: **Python 3.11+** (3.13 tested), **Node.js 22 LTS** (or newer), Git. About 1 GB of disk for dependencies. No GPU needed.

```powershell
# 1. One-time setup: virtualenv, Python packages, npm packages, .env
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 2. Stockfish (downloads the official release from GitHub into engines\, ~80 MB)
powershell -ExecutionPolicy Bypass -File scripts\install_stockfish.ps1

# 3. Run backend + frontend (opens http://127.0.0.1:5173)
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Or as one server with the production build on http://127.0.0.1:8000:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Linux/macOS, manual steps and Docker: [docs/setup.md](docs/setup.md).

## Configuring Stockfish

ChessLab finds Stockfish in this order: `CHESSLAB_STOCKFISH_PATH` (in `.env`), `stockfish` on your `PATH`, then any `stockfish*` executable under `engines/`. The engine path can only be set on the server, never through the web UI. Threads, hash size, candidate lines and review depth are adjustable in **Settings**, within ceilings set by the server (defaults: a quarter of your CPU threads, 128 MB hash). Without Stockfish the app still works using the much weaker ChessLab engine.

## Importing your Chess.com or Lichess games

1. Open **Import Games**, choose Chess.com or Lichess, type your username, optionally **Check account**.
2. Pick *Latest 25/50/100*, a custom number or *All history* (optional filters: dates, time controls, colour, rated).
3. **Start import** and watch the progress card: found / imported / already had / skipped / failed.
4. Later, **Only new games since last import** (or **Refresh all linked accounts**) fetches just what is new.

No password or API key is involved; only public games are available. Details, limits and rate-limit behaviour: [docs/imports.md](docs/imports.md).

## Reviewing a game

Open a game from **Game History** → **Review this game**. Positions are analysed in the background (about a minute for a 40-move game at depth 14 on a laptop), and the review survives restarts. Then step through with ← → or by clicking the evaluation graph; each move shows its classification, what the engine preferred and the lines it considered. How classifications are computed (and their limits): [docs/game-review.md](docs/game-review.md).

## Running the tests

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1          # lint, types, unit/integration tests, build
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -E2E     # + Playwright browser tests (uses Edge)
powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Live    # + real Chess.com/Lichess API calls
```

Backend tests use mocked HTTP for providers and the **real** custom engine and **real** Stockfish (Stockfish tests are skipped, and reported as skipped, when it is not installed). See [docs/development.md](docs/development.md).

## Deployment

ChessLab is built to run locally. It can be containerised (`docker compose up --build`) or hosted on a VM, but it has **no user accounts**: do not expose it to the internet without adding authentication in front of it. Engines need a long-running process and real CPU, so serverless platforms are unsuitable. See [docs/deployment.md](docs/deployment.md).

## Current limitations

* Standard chess only (Chess960 and other variants are skipped on import, with a reason shown).
* Single user, no authentication; not intended to be internet-facing as is.
* Opening names come from the source (Lichess `Opening` header, Chess.com ECO URL); plain PGNs without them show no opening.
* The custom engine is a pure-Python educational engine (~10k nodes/s): it plays legal, sensible chess but is far weaker than Stockfish. No absolute Elo is claimed.
* Move classifications are ChessLab's own, based on documented thresholds; they are not Chess.com's or Lichess's.
* Docker and CI configuration are provided but were not executed in the development environment (no Docker; nothing was pushed).
* Full list and verification evidence: [docs/status.md](docs/status.md).

## Roadmap ideas

Opening preparation from the explorer, puzzles generated from your own blunders, Lichess cloud-eval/tablebase lookups (opt-in), additional engines (Leela via UCI), a faster custom engine core (bitboards in Rust or C via a Python extension), Texel-tuned evaluation, and optional authentication for multi-user hosting.

## Documentation

[Architecture](docs/architecture.md) · [Setup](docs/setup.md) · [API](docs/api.md) · [Imports](docs/imports.md) · [Game review](docs/game-review.md) · [Engine design](docs/engine-design.md) · [Development & testing](docs/development.md) · [Operations, backup & restore](docs/operations.md) · [Deployment](docs/deployment.md) · [Third-party licences](docs/third-party-licenses.md) · [Status & verification](docs/status.md)

## Licence

ChessLab's own source code is released under the [MIT License](LICENSE). It depends on **python-chess (GPL-3.0-or-later)** and runs **Stockfish (GPL-3.0)** as a separate program; if you *distribute* ChessLab together with those components (for example as a Docker image or an installer), the GPL's terms apply to that distribution. See [docs/third-party-licenses.md](docs/third-party-licenses.md).

## Acknowledgements

[Stockfish](https://stockfishchess.org/) and its developers · [python-chess](https://github.com/niklasf/python-chess) by Niklas Fiekas · [chess.js](https://github.com/jhlywa/chess.js) · [react-chessboard](https://github.com/Clariity/react-chessboard) · Ronald Friederich's PeSTO evaluation tables via the [Chess Programming Wiki](https://www.chessprogramming.org/PeSTO%27s_Evaluation_Function) · the public APIs of [Chess.com](https://www.chess.com/news/view/published-data-api) and [Lichess](https://lichess.org/api).
