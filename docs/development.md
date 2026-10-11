# Development and testing

## Everyday commands

| Task | Command (Windows; use `.venv/bin/python` elsewhere) |
| --- | --- |
| Start dev servers | `scripts\dev.ps1` |
| All checks | `scripts\check.ps1` (`-E2E`, `-Live` for more) |
| Backend tests | `cd backend; .venv\Scripts\python -m pytest -p no:warnings` |
| Only Stockfish tests | `… -m pytest -m stockfish` |
| Live API tests | `… -m pytest -m live` (real Chess.com/Lichess, network required) |
| Backend lint/format/types | `ruff check app tests`, `ruff format app tests`, `mypy app` (strict) |
| Engine tests | `cd engine-lab; ..\backend\.venv\Scripts\python -m pytest` |
| Engine bench | `python engine-lab\benchmarks\bench.py --depth 4 --compare engine-lab\benchmarks\results\baseline.json` |
| Frontend | `cd frontend; npx tsc -b; npx eslint .; npx vitest run; npm run build` |
| Browser E2E | `cd frontend; npm run build; npx playwright test` (uses installed Edge; `PLAYWRIGHT_CHANNEL=chrome` elsewhere) |
| New migration | `cd backend; .venv\Scripts\python -m alembic revision --autogenerate -m "describe change"` (review it!) |

## Test suites and what they prove

| Suite | Scope | External dependencies |
| --- | --- | --- |
| `backend/tests/test_chess_rules.py` | FEN validation, legal/illegal moves, check/mate, stalemate, castling, en passant, promotion, draws (insufficient, 50/75-move, threefold/fivefold), PGN trees, malformed PGN, normalisation | none |
| `test_review_logic.py`, `test_statistics.py` | Evaluation conventions, classification thresholds, summaries, statistics on hand-computed datasets | none |
| `test_engines.py` | Real engine processes: streaming, White-POV scores, stop/preemption, time limits, terminal positions, crash recovery, missing executable, clean shutdown, completed-iteration snapshots | custom engine (always); **Stockfish tests skip if not installed** |
| `test_api_analysis.py` | REST analysis, limits, rate limiting, best move, compare, live WebSocket (stream, stop, restart, errors, origin check) | custom engine; Stockfish test skips if absent |
| `test_api_games.py` | Upload (multi-game, duplicates, malformed, oversized → 413), filters, pagination, detail, export, delete, error envelope, security headers, CORS, backups, settings validation, statistics, explorer | none |
| `test_imports_chesscom.py`, `test_imports_lichess.py` | Full import jobs with **mocked HTTP** (respx): success, newest-first selection, duplicates, conditional refresh/304, validators cleared on delete, unknown user, empty archive, malformed PGN, variants, 404/410/500, 429 + backoff, network errors/timeouts, bad formats, filters, cancel/retry, interrupted-job resume, persistence across restarts | none |
| `test_reviews.py` | Review jobs end to end with the real custom engine; resume after interruption; cancel/retry; reclassify; cascade delete; Stockfish review (skips if absent) | custom engine; Stockfish |
| `test_migrations.py` | Fresh DB, backup before upgrade, refusal of unversioned DBs, backup API | none |
| `test_live_providers.py` (`-m live`) | Real imports from Chess.com (`erik`) and Lichess (`thibault`), dedupe, refresh, unknown users | internet |
| `engine-lab/tests` | Evaluation symmetry and components, mates in 1/2, terminal positions, legality on random positions, stop/time/node limits, MultiPV, draws, UCI protocol in-process and as a subprocess | none |
| `frontend/src/**/*.test.ts(x)` | Move tree and PGN export, evaluation/format helpers, chess helpers, EvalBar, MoveInput, MoveTree, EngineLines, keyboard hook, dialogs | none |
| `frontend/e2e` | Real stack in Edge: welcome state, analysis with live engine, PGN import → history → Stockfish review → dashboard, play vs engine, client + server validation | Edge/Chrome; Stockfish step skips if absent |

Mocked tests and live tests are deliberately separate. A mocked test never counts as proof that a live integration works; `-m live` does that.

## Dependency management

* **Python:** exact pins in `backend/pyproject.toml` and `engine-lab/pyproject.toml`. To upgrade: bump a pin, reinstall, run `scripts\check.ps1 -Live`, commit.
* **Node:** exact versions in `frontend/package.json`, locked by `package-lock.json`; install with `npm ci`. Upgrade with `npm install <pkg>@<version> -E`, then run the checks.
* **Audits:** `pip-audit` (install separately) for Python and `npm audit` for Node. Neither ran in this environment.
* TypeScript is pinned to 5.9 because typescript-eslint 8.x supports TypeScript < 6.1; react-router stays on v7 for API stability.

## Extending ChessLab

* **New history provider** (e.g. another chess site): implement `ChessHistoryProvider` (`lookup_user`, `fetch` yielding `ProviderBatch`es of `RawGame`, `preview`) in `backend/app/services/providers/`, register it in `default_providers()` (`app/main.py`), and add its id to the `ImportParams.provider` literal and the frontend provider list. Dedupe, progress, cancellation, persistence and error reporting come for free.
* **New engine** (e.g. Leela/Lc0): subclass `UciEngine` with its command, options and capabilities; extend `EngineManager.is_available/_create`; add the id to `EngineId` (backend types and `frontend/src/types/api.ts`).
* **New statistic:** add a pure function in `services/statistics/compute.py` with a dataset test, then expose it in `compute_summary`.

## Code style

* Python: ruff (lint + format, line length 120), mypy strict on `app/`; services hold logic, routers stay thin.
* TypeScript: `strict`, `noUncheckedIndexedAccess`; ESLint with React Hooks v7 rules (no state syncing in effects, derived state preferred); Tailwind tokens from `src/styles/index.css`.
