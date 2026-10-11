"""Logging setup: readable console output, optional JSON lines, rotating file."""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from typing import Any

from .config import Settings

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class KeyValueFormatter(logging.Formatter):
    """``2026-10-11 12:00:00 INFO  chesslab.imports  message  key=value ...``"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = [f"{k}={v}" for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS and not k.startswith("_")]
        return f"{base}  {' '.join(extras)}" if extras else base


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(settings.log_level)
    for handler in list(root.handlers):
        if getattr(handler, "_chesslab", False):
            root.removeHandler(handler)

    formatter: logging.Formatter = (
        JsonFormatter() if settings.log_json else KeyValueFormatter("%(asctime)s %(levelname)-7s %(name)s  %(message)s")
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._chesslab = True  # type: ignore[attr-defined]
    root.addHandler(console)

    if settings.environment != "test":
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            settings.logs_dir / "chesslab.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter())
        file_handler._chesslab = True  # type: ignore[attr-defined]
        root.addHandler(file_handler)

    # python-chess logs every UCI line at DEBUG; keep it quiet unless asked.
    logging.getLogger("chess.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
