"""User-editable settings, validated by Pydantic and persisted in ``app_settings``.

Server-side ceilings (``Settings.max_*``) always win: a stored value above a
ceiling (e.g. after lowering ``CHESSLAB_MAX_ENGINE_THREADS``) is clamped when
read, so a settings row can never make the engine exceed configured limits.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.core.config import Settings, default_engine_threads
from app.core.errors import InvalidInputError
from app.db.session import Database
from app.models import AppSetting


class EngineSettings(BaseModel):
    default_engine: Literal["stockfish", "custom"] = "stockfish"
    stockfish_threads: int = Field(default_factory=default_engine_threads, ge=1)
    stockfish_hash_mb: int = Field(128, ge=16)
    custom_hash_mb: int = Field(64, ge=8, le=512)
    analysis_multipv: int = Field(3, ge=1)
    analysis_depth: int | None = Field(None, ge=1)  # None: until stopped or time cap
    analysis_movetime_ms: int | None = Field(None, ge=100)
    review_engine: Literal["stockfish", "custom"] = "stockfish"
    review_depth: int = Field(14, ge=4, le=30)
    review_movetime_ms: int = Field(1000, ge=100)
    review_multipv: int = Field(2, ge=1, le=3)
    review_threads: int = Field(default_factory=default_engine_threads, ge=1)

    def clamp(self, settings: Settings) -> EngineSettings:
        data = self.model_dump()
        data["stockfish_threads"] = min(self.stockfish_threads, settings.max_engine_threads)
        data["review_threads"] = min(self.review_threads, settings.max_engine_threads)
        data["stockfish_hash_mb"] = min(self.stockfish_hash_mb, settings.max_engine_hash_mb)
        data["analysis_multipv"] = min(self.analysis_multipv, settings.max_multipv)
        if self.analysis_depth is not None:
            data["analysis_depth"] = min(self.analysis_depth, settings.max_search_depth)
        if self.analysis_movetime_ms is not None:
            data["analysis_movetime_ms"] = min(
                self.analysis_movetime_ms, int(settings.max_live_analysis_seconds * 1000)
            )
        data["review_movetime_ms"] = min(self.review_movetime_ms, settings.max_review_movetime_ms)
        return EngineSettings(**data)

    def check_limits(self, settings: Settings) -> None:
        """Reject (rather than silently clamp) out-of-range values on update."""
        problems = []
        if self.stockfish_threads > settings.max_engine_threads or self.review_threads > settings.max_engine_threads:
            problems.append(f"threads must be at most {settings.max_engine_threads}")
        if self.stockfish_hash_mb > settings.max_engine_hash_mb:
            problems.append(f"hash must be at most {settings.max_engine_hash_mb} MB")
        if self.analysis_multipv > settings.max_multipv:
            problems.append(f"candidate lines must be at most {settings.max_multipv}")
        if self.analysis_depth is not None and self.analysis_depth > settings.max_search_depth:
            problems.append(f"depth must be at most {settings.max_search_depth}")
        if self.review_movetime_ms > settings.max_review_movetime_ms:
            problems.append(f"review time per move must be at most {settings.max_review_movetime_ms} ms")
        if problems:
            raise InvalidInputError("; ".join(problems).capitalize() + ".", code="settings_out_of_range")


class ClassificationThresholds(BaseModel):
    """Upper bounds of expected-score loss (0..1) for each move category.

    loss < excellent -> excellent, < good -> good, < inaccuracy -> inaccuracy,
    < mistake -> mistake, otherwise blunder. Playing the engine's top move is
    always "best". See docs/game-review.md.
    """

    excellent: float = Field(0.02, gt=0, lt=1)
    good: float = Field(0.05, gt=0, lt=1)
    inaccuracy: float = Field(0.10, gt=0, lt=1)
    mistake: float = Field(0.20, gt=0, lt=1)

    @model_validator(mode="after")
    def _ascending(self) -> ClassificationThresholds:
        if not (self.excellent < self.good < self.inaccuracy < self.mistake):
            raise ValueError("thresholds must increase: excellent < good < inaccuracy < mistake")
        return self


class LinkedAccount(BaseModel):
    provider: Literal["chesscom", "lichess"]
    username: str = Field(min_length=2, max_length=30, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class Preferences(BaseModel):
    accounts: list[LinkedAccount] = Field(default_factory=list, max_length=10)


_MODELS: dict[str, type[BaseModel]] = {
    "engine": EngineSettings,
    "classification": ClassificationThresholds,
    "preferences": Preferences,
}


class SettingsStore:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def _read(self, session: Session, key: str) -> BaseModel:
        model = _MODELS[key]
        row = session.get(AppSetting, key)
        if row is None:
            return model()
        try:
            return model.model_validate(row.value)
        except ValidationError:
            # A stored value from an older version that no longer validates:
            # fall back to defaults instead of breaking the app.
            return model()

    def _write(self, key: str, value: BaseModel) -> None:
        with self.db.session() as session:
            row = session.get(AppSetting, key)
            payload: dict[str, Any] = value.model_dump(mode="json")
            if row is None:
                session.add(AppSetting(key=key, value=payload))
            else:
                row.value = payload

    def engine(self) -> EngineSettings:
        with self.db.session() as session:
            value = self._read(session, "engine")
        assert isinstance(value, EngineSettings)
        return value.clamp(self.settings)

    def set_engine(self, value: EngineSettings) -> EngineSettings:
        value.check_limits(self.settings)
        self._write("engine", value)
        return value

    def thresholds(self) -> ClassificationThresholds:
        with self.db.session() as session:
            value = self._read(session, "classification")
        assert isinstance(value, ClassificationThresholds)
        return value

    def set_thresholds(self, value: ClassificationThresholds) -> ClassificationThresholds:
        self._write("classification", value)
        return value

    def preferences(self) -> Preferences:
        with self.db.session() as session:
            value = self._read(session, "preferences")
        assert isinstance(value, Preferences)
        return value

    def set_preferences(self, value: Preferences) -> Preferences:
        self._write("preferences", value)
        return value

    def remember_account(self, provider: str, username: str) -> None:
        prefs = self.preferences()
        if any(a.provider == provider and a.username.lower() == username.lower() for a in prefs.accounts):
            return
        prefs.accounts.append(LinkedAccount(provider=provider, username=username))  # type: ignore[arg-type]
        prefs.accounts = prefs.accounts[-10:]
        self.set_preferences(prefs)
