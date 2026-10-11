# syntax=docker/dockerfile:1
# ChessLab: one container serving the API and the built frontend on port 8000.
# Data (SQLite database, backups, logs) lives in the /data volume.

# ---- 1. Build the frontend ---------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---- 2. Runtime --------------------------------------------------------------
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CHESSLAB_ENVIRONMENT=production \
    CHESSLAB_DATA_DIR=/data \
    CHESSLAB_HOST=0.0.0.0 \
    CHESSLAB_PORT=8000 \
    CHESSLAB_LOG_JSON=true \
    CHESSLAB_STOCKFISH_PATH=/usr/games/stockfish

# Debian's Stockfish package (GPLv3). It is older than the latest release;
# mount a newer binary and point CHESSLAB_STOCKFISH_PATH at it if you prefer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/ backend/
COPY engine-lab/ engine-lab/
# Editable installs keep the source layout the app uses to find migrations.
RUN pip install -e ./backend -e ./engine-lab
COPY --from=frontend /src/frontend/dist frontend/dist

RUN useradd --create-home --uid 10001 chesslab \
    && mkdir -p /data \
    && chown chesslab:chesslab /data
USER chesslab
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
