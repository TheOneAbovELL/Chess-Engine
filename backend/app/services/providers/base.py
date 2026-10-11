"""ChessHistoryProvider: the interface for public game-history sources.

To add a platform, implement :class:`ChessHistoryProvider` and register it in
``app/main.py``. The import service handles persistence, deduplication,
progress, cancellation and error reporting for every provider.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,29}$")
ImportMode = Literal["recent", "all", "refresh"]
TIME_CLASS_FILTERS = ("ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence")


def validate_username(value: str) -> str:
    value = value.strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("Usernames are 2-30 characters: letters, digits, '_' or '-'.")
    return value


class ImportParams(BaseModel):
    provider: Literal["chesscom", "lichess"]
    username: str
    mode: ImportMode = "recent"
    max_games: int = Field(50, ge=1)
    since: date | None = None
    until: date | None = None
    time_classes: list[Literal["ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence"]] = Field(
        default_factory=list, max_length=6
    )
    color: Literal["white", "black"] | None = None
    rated: bool | None = None

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        return validate_username(value)

    @model_validator(mode="after")
    def _dates(self) -> ImportParams:
        if self.since and self.until and self.since > self.until:
            raise ValueError("'since' must be on or before 'until'.")
        return self


class ProviderError(Exception):
    """A failure talking to a provider, with a message safe to show users."""

    def __init__(self, kind: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind  # not_found | closed | rate_limited | network | server | bad_response | gone
        self.message = message
        self.status = status


@dataclass
class ProviderUser:
    provider: str
    username: str
    exists: bool
    url: str | None = None
    display_name: str | None = None
    status: str | None = None  # e.g. "closed", "basic", "premium"
    closed: bool = False
    joined: datetime | None = None
    last_online: datetime | None = None
    game_counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class RawGame:
    """One game as delivered by a provider, before normalisation."""

    pgn: str
    source: str
    external_id: str | None
    ref: str  # URL or id used in error reports
    overrides: dict[str, Any] = field(default_factory=dict)
    skip_reason: str | None = None  # set when the provider already knows it cannot be imported


@dataclass
class BatchStats:
    imported: int = 0
    duplicates: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class ProviderBatch:
    games: list[RawGame]
    label: str  # e.g. "2026-10" or "games 1-25"
    # Called after every game in the batch was processed without failures.
    on_complete: Callable[[], Awaitable[None]] | None = None
    # Filled in by the import service before the provider resumes.
    stats: BatchStats = field(default_factory=BatchStats)


class ImportContext(ABC):
    """Services the import job offers to providers."""

    @abstractmethod
    async def cache_validators(self, url: str) -> tuple[str | None, str | None]: ...

    @abstractmethod
    async def store_validators(self, url: str, etag: str | None, last_modified: str | None) -> None: ...

    @abstractmethod
    async def latest_played_at(self, source: str, owner: str) -> datetime | None: ...

    @abstractmethod
    async def set_phase(self, phase: str) -> None: ...

    @abstractmethod
    async def cancel_requested(self) -> bool: ...


class ChessHistoryProvider(ABC):
    name: str
    display_name: str

    @abstractmethod
    async def lookup_user(self, username: str) -> ProviderUser:
        """Check that a public account exists. Raises ProviderError."""

    @abstractmethod
    def fetch(self, params: ImportParams, ctx: ImportContext, max_games: int) -> AsyncIterator[ProviderBatch]:
        """Yield batches of games, newest first, honouring ``params``."""

    @abstractmethod
    async def preview(self, username: str, limit: int) -> list[dict[str, Any]]:
        """A few recent games' metadata (no import)."""
