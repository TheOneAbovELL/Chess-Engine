"""Application configuration.

All settings come from environment variables prefixed with ``CHESSLAB_`` (or a
``.env`` file in the repository root / backend directory). See ``.env.example``.

Data location
-------------
By default user data (the SQLite database, backups and logs) lives *outside*
the repository, in the per-user application-data directory:

* Windows: ``%LOCALAPPDATA%\\ChessLab``
* Linux/macOS: ``$XDG_DATA_HOME/chesslab`` or ``~/.local/share/chesslab``

This keeps personal game history out of Git and out of cloud-synced project
folders (e.g. OneDrive), which also corrupt SQLite files while they are open.
"""

from __future__ import annotations

import os
import sys
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = PROJECT_ROOT / "backend"
APP_VERSION = "0.1.0"


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "ChessLab"
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg) / "chesslab" if xdg else Path.home() / ".local" / "share" / "chesslab"


def _cpu_count() -> int:
    return os.cpu_count() or 2


def default_engine_threads() -> int:
    """A modest share of the CPU so the machine stays responsive (2 on 8 threads, 3 on 12)."""
    return max(1, min(4, _cpu_count() // 4))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHESSLAB_",
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "production", "test"] = "development"
    host: str = "127.0.0.1"
    port: int = Field(8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False

    data_dir: Path = Field(default_factory=default_data_dir)
    database_url: str | None = None  # default: sqlite file inside data_dir

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    serve_frontend: bool = True
    frontend_dist: Path = PROJECT_ROOT / "frontend" / "dist"

    # ---- Engines ------------------------------------------------------------
    # Only configurable through the environment, never through the API.
    stockfish_path: Path | None = None
    engines_dir: Path = PROJECT_ROOT / "engines"
    custom_engine_enabled: bool = True
    engine_start_timeout_s: float = Field(20.0, gt=0)
    engine_idle_shutdown_s: float = Field(600.0, ge=30)
    # Run engines at below-normal OS priority (Windows). Keeps the desktop snappy
    # on an idle machine, but other CPU-heavy programs can then starve the engine.
    engine_low_priority: bool = False

    # Hard ceilings that user-editable engine settings are validated against.
    max_engine_threads: int = Field(default_factory=lambda: max(1, _cpu_count() - 2), ge=1, le=64)
    max_engine_hash_mb: int = Field(1024, ge=16, le=8192)
    max_search_depth: int = Field(40, ge=1, le=99)
    max_multipv: int = Field(5, ge=1, le=10)
    max_analysis_seconds: float = Field(60.0, gt=0)  # one-shot REST analysis / best move
    max_live_analysis_seconds: float = Field(180.0, gt=0)  # infinite analysis auto-stops
    max_review_movetime_ms: int = Field(10_000, ge=100)

    # ---- Requests & imports ---------------------------------------------------
    max_request_bytes: int = Field(6 * 1024 * 1024, ge=1024)
    max_pgn_bytes: int = Field(5 * 1024 * 1024, ge=1024)
    max_pgn_games_per_upload: int = Field(2000, ge=1)
    max_import_games: int = Field(5000, ge=1)
    max_batch_review_games: int = Field(100, ge=1)
    analysis_rate_per_minute: int = Field(120, ge=1)

    # ---- External public APIs --------------------------------------------------
    http_timeout_s: float = Field(30.0, gt=0)
    http_max_retries: int = Field(3, ge=0, le=10)
    http_contact: str | None = None  # optional contact info appended to the User-Agent
    chesscom_base_url: str = "https://api.chess.com/pub"
    lichess_base_url: str = "https://lichess.org"

    @field_validator("data_dir", "engines_dir", "frontend_dist", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @cached_property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'chesslab.db').as_posix()}"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def user_agent(self) -> str:
        # Both Chess.com and Lichess ask for an identifying User-Agent. Lichess
        # answers anonymous requests without one with a misleading 404.
        contact = f"; contact: {self.http_contact}" if self.http_contact else ""
        return f"ChessLab/{APP_VERSION} (local-first personal chess analysis app{contact})"

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.backups_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
