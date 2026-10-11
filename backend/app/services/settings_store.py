"""User-editable settings, validated by Pydantic and persisted in ``app_settings``.

Server-side ceilings (``Settings.max_*``) always win: a stored value above a
ceiling (e.g. after lowering ``CHESSLAB_MAX_ENGINE_THREADS``) is clamped when
read, so a settings row can never make the engine exceed configured limits.
"""

from __future__ import annotations

from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
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


class InterfacePrefs(BaseModel):
    """Per-user interface settings, synced across devices.

    ``experience`` is a preset the UI applies to the feature switches below;
    every switch can still be changed individually.
    """

    model_config = ConfigDict(extra="ignore")

    theme: Literal["system", "dark", "light"] = "system"
    experience: Literal["simple", "standard", "advanced"] = "standard"
    board_theme: Literal["walnut", "slate", "emerald", "midnight"] = "walnut"
    coordinates: bool = True
    animations: bool = True
    move_sounds: bool = True
    show_eval_bar: bool = True
    show_best_arrow: bool = True
    show_classifications: bool = True
    show_opening_names: bool = True
    show_explorer: bool = True
    show_engine_lab: bool = False
    show_insights: bool = True
    analysis_lines: int = Field(1, ge=1, le=5)
    preferred_engine: Literal["auto", "stockfish", "custom", "browser"] = "auto"
    onboarded: bool = False


_SERVER_WIDE = {"engine"}
_MODELS: dict[str, type[BaseModel]] = {
    "engine": EngineSettings,
    "classification": ClassificationThresholds,
    "preferences": Preferences,
    "interface": InterfacePrefs,
}
M = TypeVar("M", bound=BaseModel)


class SettingsStore:
    """Reads/writes validated settings. ``engine`` is server-wide; the rest
    are stored per user."""

    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    @staticmethod
    def _owner(key: str, user_id: int | None) -> int | None:
        return None if key in _SERVER_WIDE else user_id

    def _row(self, session: Session, key: str, user_id: int | None) -> AppSetting | None:
        owner = self._owner(key, user_id)
        stmt = select(AppSetting).where(AppSetting.key == key)
        stmt = stmt.where(AppSetting.user_id.is_(None)) if owner is None else stmt.where(AppSetting.user_id == owner)
        return session.execute(stmt).scalar_one_or_none()

    def _read(self, key: str, model: type[M], user_id: int | None) -> M:
        with self.db.session() as session:
            row = self._row(session, key, user_id)
            if row is None:
                return model()
            try:
                return model.model_validate(row.value)
            except ValidationError:
                # A stored value from an older version that no longer validates:
                # fall back to defaults instead of breaking the app.
                return model()

    def _write(self, key: str, value: BaseModel, user_id: int | None) -> None:
        payload: dict[str, Any] = value.model_dump(mode="json")
        with self.db.session() as session:
            row = self._row(session, key, user_id)
            if row is None:
                session.add(AppSetting(key=key, value=payload, user_id=self._owner(key, user_id)))
            else:
                row.value = payload

    # Server-wide
    def engine(self) -> EngineSettings:
        return self._read("engine", EngineSettings, None).clamp(self.settings)

    def set_engine(self, value: EngineSettings) -> EngineSettings:
        value.check_limits(self.settings)
        self._write("engine", value, None)
        return value

    # Per user
    def thresholds(self, user_id: int) -> ClassificationThresholds:
        return self._read("classification", ClassificationThresholds, user_id)

    def set_thresholds(self, user_id: int, value: ClassificationThresholds) -> ClassificationThresholds:
        self._write("classification", value, user_id)
        return value

    def preferences(self, user_id: int) -> Preferences:
        return self._read("preferences", Preferences, user_id)

    def set_preferences(self, user_id: int, value: Preferences) -> Preferences:
        self._write("preferences", value, user_id)
        return value

    def interface(self, user_id: int) -> InterfacePrefs:
        return self._read("interface", InterfacePrefs, user_id)

    def set_interface(self, user_id: int, value: InterfacePrefs) -> InterfacePrefs:
        self._write("interface", value, user_id)
        return value

    def remember_account(self, user_id: int, provider: str, username: str) -> None:
        prefs = self.preferences(user_id)
        if any(a.provider == provider and a.username.lower() == username.lower() for a in prefs.accounts):
            return
        prefs.accounts.append(LinkedAccount(provider=provider, username=username))  # type: ignore[arg-type]
        prefs.accounts = prefs.accounts[-10:]
        self.set_preferences(user_id, prefs)

    def export(self, user_id: int) -> dict[str, Any]:
        return {
            "classification": self.thresholds(user_id).model_dump(mode="json"),
            "preferences": self.preferences(user_id).model_dump(mode="json"),
            "interface": self.interface(user_id).model_dump(mode="json"),
        }
