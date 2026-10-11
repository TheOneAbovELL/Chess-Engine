# Architecture

ChessLab is a **modular monolith**: one FastAPI process (plus engine subprocesses) and one React single-page app. Boundaries are clear enough that a piece could be split out later, but nothing here needs microservices, a message broker or a cloud service.

## Repository layout

```
backend/                 FastAPI application (Python 3.11+)
  app/main.py            app factory: lifespan wiring, middleware, routers, SPA serving
  app/core/              settings, logging, error envelope, rate limiter, service container
  app/db/                SQLAlchemy engine/session, Alembic runner with pre-migration backups
  app/models/            ORM tables: games, import_jobs, game_reviews, position_evaluations, app_settings, http_cache
  app/repositories/      SQL for games (filters, pagination, dedupe insert)
  app/services/
    chess/               positions (validation), pgn (defensive parsing, trees), normalize (GameRecord), scoring
    engine/              ChessEngine interface, UCI adapter, Stockfish/Custom engines, runtime thread, manager
    providers/           ChessHistoryProvider interface, polite HTTP client, Chess.com, Lichess
    review/              classification (pure) and the review worker
    statistics/          pure statistics + DB loader, personal opening explorer
    analysis.py games.py imports.py settings_store.py
  app/api/v1/            thin routers + Pydantic schemas
  app/jobs/worker.py     persistent background-worker base
  migrations/            Alembic migrations
  tests/                 pytest suite (unit, integration, live)
engine-lab/              the ChessLab engine (UCI), tests, benchmarks
frontend/                React 19 + TypeScript (strict) + Vite + Tailwind
  src/features/<area>/   one folder per screen (analysis, play, games, review, imports, dashboard, explorer, engine-lab, settings, board)
  src/lib/               API client, move tree + PGN export, evaluation and chess helpers
  src/stores/            small zustand stores (analysis board, preferences, toasts)
  e2e/                   Playwright tests against the real stack
scripts/                 setup, Stockfish install, dev/start, checks, backup/restore
docs/                    this documentation
```

## Request flow

1. The browser talks to `/api/v1` (REST) and `/api/v1/analysis/live` (WebSocket). In development Vite proxies both to `127.0.0.1:8000`; in "start"/Docker mode FastAPI serves the built SPA itself, so there is one origin.
2. Routers validate input with Pydantic and call a service. DB-bound handlers are plain functions (FastAPI runs them in a thread pool); engine handlers are `async`.
3. Services own business rules; repositories own SQL; models are plain tables.
4. Every FEN and move list is re-validated with python-chess on the server (`services/chess/positions.py`). The frontend uses chess.js only for instant feedback.

## Engines

```
           main event loop (uvicorn)                    engine runtime thread (ProactorEventLoop on Windows)
 ┌───────────────────────────────────────┐          ┌───────────────────────────────────────────────┐
 │ AnalysisService / GameReviewService   │  call()  │ python-chess UciProtocol objects              │
 │   └─ EngineManager.slot(id, purpose)  │ ───────► │   ├─ Stockfish process  (interactive)          │
 │        └─ EngineSlot.use() -> Lease   │ ◄─────── │   ├─ ChessLab engine    (interactive)          │
 │             (lock, preemption, stop)  │ updates  │   └─ review engine      (one, either kind)     │
 └───────────────────────────────────────┘          └───────────────────────────────────────────────┘
```

* **`ChessEngine`** (`services/engine/base.py`) is the interface: `start`, `close`, `configure`, `analyse(board, limits, multipv, on_update, stop)`, `play(board, limits, options)`, `capabilities`, `identity`. Callers never see UCI details; they receive normalised `AnalysisSnapshot`s.
* **`UciEngine`** implements it for any UCI engine; `StockfishEngine` and `CustomChessEngine` only add their command line, options and capabilities. Adding Leela or another UCI engine is a small subclass plus a manager entry.
* **Why a separate thread and loop?** On Windows, uvicorn's `--reload` mode runs a `SelectorEventLoop`, which cannot spawn subprocesses. Engines therefore live on their own thread with a `ProactorEventLoop`; `EngineRuntime.call()` bridges loops, and cancellation propagates.
* **Bounded processes.** The `EngineManager` keeps at most one process per *(engine, purpose)* slot, so never more than three. Each slot serialises work with a lock. Interactive slots are *preemptive*: a new request stops the running search (via a `StopSignal` wired to UCI `stop`) and takes over, so clicking through positions never builds a queue. Processes start lazily, restart after crashes and stop after `ENGINE_IDLE_SHUTDOWN_S` idle.
* **Every search is capped** by time even when only a depth is requested; "infinite" live analysis stops after `MAX_LIVE_ANALYSIS_SECONDS`.
* **The custom engine runs out of process** (`python -m chesslab_engine`), so its CPU-heavy Python search never holds the web server's GIL, and it shares the exact lifecycle, cancellation and test path of Stockfish.

## Background jobs

Imports and reviews are rows in the database (`import_jobs`, `game_reviews`), processed by two `BackgroundWorker`s started in the app lifespan. Each worker handles one job at a time (bounding network and CPU use), is woken immediately when a job is queued and polls as a fallback. On startup, jobs left `running` by a crash or shutdown are re-queued:

* **Imports** are idempotent (games deduplicated by `(source, external_id)`), so resuming cannot create duplicates; each batch is committed with the job counters, so counters always match the database.
* **Reviews** store results position by position and skip already-stored plies when resumed.

A separate broker (Redis + RQ/Celery) would only be justified for multiple backend instances or many concurrent users; see [deployment.md](deployment.md).

## Data model

| Table | Purpose |
| --- | --- |
| `games` | One row per game: players, ratings, result, time class, opening, `played_at`, PGN, mainline UCI moves (for fast explorer/statistics), `owner_username` and the user's colour/result. Unique `(source, external_id)`. |
| `import_jobs` | Persistent import jobs: params, status, counters, phase, bounded error list. |
| `game_reviews` | Review job + result header: engine, settings, thresholds used, progress, summary. |
| `position_evaluations` | Per-position evaluation (White POV), best move, MultiPV alternatives, terminal state, and for the move that led there: classification, expected-score loss, centipawn loss, clock. Unique `(review_id, ply)`. |
| `app_settings` | Validated JSON settings (engine, thresholds, linked accounts). |
| `http_cache` | ETag / Last-Modified of Chess.com monthly archives that were fully imported. Cleared whenever games are deleted. |

SQLite runs in WAL mode with foreign keys on and a busy timeout. Migrations are Alembic (`render_as_batch` for SQLite); startup backs up an existing database before upgrading and refuses to touch an unversioned database that already has tables.

## Design decisions

| Decision | Reason |
| --- | --- |
| python-chess for rules, PGN and UCI | Mature, thoroughly tested; writing move legality from scratch adds risk without value here. |
| react-chessboard for rendering | Maintained, accessible-enough base with drag & drop; ChessLab adds click-to-move, legality, promotion UI and a screen-reader position description. |
| Expected-score (logistic) classification | Treats a 300 cp swing in a level position very differently from one in a won position, and handles mates naturally ([game-review.md](game-review.md)). |
| Data outside the repository by default | Keeps personal data out of Git and out of cloud-synced folders (OneDrive can corrupt open SQLite files). |
| No authentication | Single-user local app; adding accounts would add attack surface without benefit locally. Required before any public hosting. |
| Polling for job progress, WebSocket for analysis | Progress changes about once a second (polling is simple and robust); analysis updates are frequent and need cancellation (WebSocket). |
