# Deployment

ChessLab is designed and verified as a **local, single-user** application. This page explains what changes if you host it, and what you must add first. Nothing in the repository deploys or uploads anything automatically.

## Before exposing it to a network

* **There are no user accounts.** Anyone who can reach the server can import, delete and analyse games and use your CPU. Put it behind authentication (e.g. a reverse proxy with OAuth/SSO or HTTP basic auth over TLS), or implement accounts as a separate layer before any public deployment.
* Bind to `127.0.0.1` (the default) unless you have a reason not to; in Docker the compose file publishes to localhost only.
* Serve over **HTTPS** (WebSockets then use `wss://`).
* Set `CHESSLAB_CORS_ORIGINS` to exactly your frontend origin(s). Same-origin hosting (backend serving the built frontend) needs no CORS at all.
* Keep the resource ceilings (`CHESSLAB_MAX_*`, `CHESSLAB_ANALYSIS_RATE_PER_MINUTE`) conservative. The rate limiter is in-memory and per process.

## Shapes that work

| Option | Notes |
| --- | --- |
| **Same machine, single process** (`scripts/start.ps1` or the Dockerfile) | Simplest. FastAPI serves the SPA and API on one port. |
| **VM / VPS with Docker** | `docker compose up -d`; persist the `/data` volume; put Caddy/nginx/Traefik in front for TLS and authentication. |
| **Separate static frontend + API host** | Build `frontend/dist` and host it on any static host; point the API URL at the backend by serving both under one domain (recommended, avoids CORS) or set CORS origins. |

**Unsuitable:** serverless/edge functions. Engines are long-running native processes that need dedicated CPU, the live analysis uses WebSockets, and background jobs run inside the server process.

## Sizing

| Load | CPU | RAM |
| --- | --- | --- |
| One user, defaults | 2–4 cores | ~400 MB (backend ~150 MB, Stockfish ~100 MB network + hash) |
| Higher depth/threads | as configured | hash size + ~150 MB per Stockfish process (max 2 Stockfish processes) |

Stockfish binaries are CPU-specific: use the "universal" build, or an x86-64 build that matches the host's instruction set (AVX2/BMI2). Debian's packaged Stockfish works anywhere but is older.

## Operations checklist

* **Persistence:** the SQLite file in `CHESSLAB_DATA_DIR` (Docker volume `/data`). SQLite suits a single process; for several backend replicas you would move to PostgreSQL (SQLAlchemy models are portable; a migration test pass is required) and a shared job queue.
* **Background jobs:** run in-process, one import and one review at a time; jobs survive restarts. Several replicas would each run workers, so you would need a broker (Redis + RQ/Celery) or a single dedicated worker process.
* **Health checks:** `GET /api/v1/health` (200 with `status: ok`); the Docker image defines a `HEALTHCHECK`.
* **Logging:** JSON lines on stdout (`CHESSLAB_LOG_JSON=true`, default in Docker) and a rotating file in `<data dir>/logs`. No telemetry is sent anywhere.
* **Backups:** see [operations.md](operations.md). Back up the volume or call `POST /api/v1/data/backup` on a schedule.
* **Environment variables:** see `.env.example`. ChessLab needs no secrets.

## Updating and rolling back

1. Back up the database (`scripts/db_tool.py backup` or the Settings page).
2. Deploy the new version. On startup, pending Alembic migrations run automatically, **after** an automatic `pre-migration-<rev>-<time>.db` backup.
3. To roll back: stop the new version, restore the pre-migration backup (`scripts/db_tool.py restore <file>`), start the previous version. Downgrade migrations exist but restoring the backup is the safer path.

## Licensing when distributing

If you distribute ChessLab with python-chess and/or Stockfish (for example a Docker image), the GPL-3.0 terms of those components apply to that distribution: provide the corresponding source (including Stockfish's) and licence texts. See [third-party-licenses.md](third-party-licenses.md).
