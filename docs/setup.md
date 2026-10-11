# Setup

## Requirements

| | Minimum | Notes |
| --- | --- | --- |
| OS | Windows 10/11, Linux, macOS | Developed and verified on Windows 11 |
| Python | 3.11 | 3.13 used for development |
| Node.js | 20 | 22 LTS recommended; the jsdom test dependency prefers ≥ 22.22 or 24 (warning only) |
| CPU / RAM | 2 cores / 4 GB | Defaults use a quarter of your threads and 128 MB hash; no GPU needed |
| Disk | ~1 GB | Python + Node dependencies; Stockfish adds ~200 MB unpacked |

## Windows (scripted)

```powershell
git clone <your copy> ChessLab
cd ChessLab
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1              # venv + packages + npm + .env
powershell -ExecutionPolicy Bypass -File scripts\install_stockfish.ps1  # official Stockfish into engines\
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1                # backend :8000 + frontend :5173
```

`install_stockfish.ps1 -DryRun` shows what it would download; `-Tag sf_17.1` picks a specific release.

## Manual setup (any OS)

```bash
# Backend + engine (Linux/macOS: .venv/bin/python; Windows: .venv\Scripts\python.exe)
python -m venv backend/.venv
backend/.venv/bin/python -m pip install -e "backend[dev]" -e engine-lab

# Frontend
cd frontend && npm ci && cd ..

# Configuration (optional; every setting has a default)
cp .env.example .env

# Stockfish: Debian/Ubuntu `sudo apt install stockfish`, macOS `brew install stockfish`,
# or download from https://stockfishchess.org/download/ and set CHESSLAB_STOCKFISH_PATH.

# Run (two terminals)
cd backend && .venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
cd frontend && npm run dev          # http://127.0.0.1:5173
```

Single-server mode (production build served by FastAPI on :8000):

```bash
cd frontend && npm run build && cd ../backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Docker

```bash
docker compose up --build      # http://127.0.0.1:8000, data in the "chesslab-data" volume
```

The image builds the frontend, installs Debian's Stockfish package (an older release; mount a newer binary and set `CHESSLAB_STOCKFISH_PATH` to use it) and runs as an unprivileged user. Docker was not available in the development environment, so the image is provided but **untested**.

## Where things are stored

| What | Default location | Setting |
| --- | --- | --- |
| Database | `%LOCALAPPDATA%\ChessLab\chesslab.db` (Windows), `~/.local/share/chesslab/` (Linux/macOS) | `CHESSLAB_DATA_DIR`, `CHESSLAB_DATABASE_URL` |
| Backups | `<data dir>\backups\` | via data dir |
| Logs | `<data dir>\logs\chesslab.log` (rotating, 3 × 5 MB, JSON lines) | `CHESSLAB_LOG_LEVEL`, `CHESSLAB_LOG_JSON` |
| Stockfish | `engines\` (ignored by Git), PATH, or explicit path | `CHESSLAB_STOCKFISH_PATH` |
| Display preferences | browser `localStorage` | Settings → Board & display |

> **OneDrive note.** If the project folder is inside OneDrive (as on the development machine), OneDrive will try to sync `node_modules` and `backend\.venv` (tens of thousands of files). It does no harm, but you may prefer to mark the folder "Always keep on this device" or move the project out of OneDrive. The database is deliberately stored *outside* the project folder for this reason.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Stockfish not found" in the sidebar | Run `scripts\install_stockfish.ps1` or set `CHESSLAB_STOCKFISH_PATH`, then restart the backend. |
| Frontend shows "Server offline" | Start the backend; check that port 8000 is free (`netstat -ano | findstr :8000`). |
| Lichess import returns HTTP 404 for every user | Make sure nothing strips the `User-Agent` header (proxies). Lichess rejects anonymous requests without one. |
| Analysis is slow while other programs run | Lower Stockfish threads in Settings, or set `CHESSLAB_ENGINE_LOW_PRIORITY=true` to favour other programs. |
| "Port 5173 is already in use" | Another Vite instance is running; close it (the dev server uses a fixed port so the proxy and CORS match). |
| PowerShell refuses to run scripts | Use `powershell -ExecutionPolicy Bypass -File scripts\<name>.ps1` as shown. |
