"""GameRepository: all SQL touching the ``games`` table lives here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from sqlalchemy import ColumnElement, Select, and_, case, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Game, GameReview
from app.services.chess.normalize import GameRecord

SortKey = Literal["played_desc", "played_asc", "imported_desc", "rating_desc", "length_desc"]


@dataclass
class GameFilters:
    q: str | None = None  # player name (either side), case-insensitive substring
    source: str | None = None
    owner: str | None = None
    color: str | None = None  # user's colour
    result: str | None = None  # user's result: win/loss/draw
    time_class: str | None = None
    rated: bool | None = None
    date_from: date | None = None
    date_to: date | None = None
    opening: str | None = None  # substring of opening name or ECO code
    min_rating: int | None = None  # user's rating at the time
    max_rating: int | None = None
    reviewed: bool | None = None
    ids: list[int] | None = None


def _user_rating_expr() -> ColumnElement[int | None]:
    return case((Game.user_color == "white", Game.white_elo), (Game.user_color == "black", Game.black_elo), else_=None)


def apply_filters(stmt: Select, f: GameFilters) -> Select:  # type: ignore[type-arg]
    conditions: list[ColumnElement[bool]] = []
    if f.ids:
        conditions.append(Game.id.in_(f.ids))
    if f.q:
        pattern = f"%{f.q.strip().lower()}%"
        conditions.append(or_(func.lower(Game.white).like(pattern), func.lower(Game.black).like(pattern)))
    if f.source:
        conditions.append(Game.source == f.source)
    if f.owner:
        conditions.append(Game.owner_username == f.owner.lower())
    if f.color:
        conditions.append(Game.user_color == f.color)
    if f.result:
        conditions.append(Game.user_result == f.result)
    if f.time_class:
        conditions.append(Game.time_class == f.time_class)
    if f.rated is not None:
        conditions.append(Game.rated.is_(f.rated))
    if f.date_from:
        conditions.append(Game.played_at >= datetime.combine(f.date_from, time.min, tzinfo=UTC))
    if f.date_to:
        conditions.append(Game.played_at < datetime.combine(f.date_to + timedelta(days=1), time.min, tzinfo=UTC))
    if f.opening:
        pattern = f"%{f.opening.strip().lower()}%"
        conditions.append(or_(func.lower(Game.opening).like(pattern), func.lower(Game.eco).like(pattern)))
    rating = _user_rating_expr()
    if f.min_rating is not None:
        conditions.append(rating >= f.min_rating)
    if f.max_rating is not None:
        conditions.append(rating <= f.max_rating)
    if f.reviewed is not None:
        has_review = (
            select(GameReview.id).where(GameReview.game_id == Game.id, GameReview.status == "completed").exists()
        )
        conditions.append(has_review if f.reviewed else ~has_review)
    return stmt.where(and_(*conditions)) if conditions else stmt


def _order(stmt: Select, sort: SortKey) -> Select:  # type: ignore[type-arg]
    if sort == "played_asc":
        return stmt.order_by(Game.played_at.asc().nulls_first(), Game.id.asc())
    if sort == "imported_desc":
        return stmt.order_by(Game.imported_at.desc(), Game.id.desc())
    if sort == "rating_desc":
        return stmt.order_by(_user_rating_expr().desc().nulls_last(), Game.id.desc())
    if sort == "length_desc":
        return stmt.order_by(Game.ply_count.desc(), Game.id.desc())
    return stmt.order_by(Game.played_at.desc().nulls_last(), Game.id.desc())


class GameRepository:
    """Every query is scoped to one user's library."""

    def __init__(self, session: Session, user_id: int) -> None:
        self.session = session
        self.user_id = user_id

    def _mine(self, stmt: Select) -> Select:  # type: ignore[type-arg]
        return stmt.where(Game.user_id == self.user_id)

    def exists(self, source: str, external_id: str) -> bool:
        stmt = self._mine(select(Game.id).where(Game.source == source, Game.external_id == external_id))
        return self.session.execute(stmt).first() is not None

    def insert(self, record: GameRecord, import_job_id: str | None = None) -> Game | None:
        """Insert a game unless ``(user, source, external_id)`` already exists.
        Returns None for duplicates. Uses a savepoint so a race on the unique
        constraint only rolls back this one row."""
        if self.exists(record.source, record.external_id):
            return None
        game = Game(**record.as_model_kwargs(), import_job_id=import_job_id, user_id=self.user_id)
        try:
            with self.session.begin_nested():
                self.session.add(game)
                self.session.flush()
        except IntegrityError:
            return None
        return game

    def get(self, game_id: int) -> Game | None:
        game = self.session.get(Game, game_id)
        return game if game is not None and game.user_id == self.user_id else None

    def page(self, f: GameFilters, *, sort: SortKey, offset: int, limit: int) -> tuple[list[Game], int]:
        total = self.session.execute(self._mine(apply_filters(select(func.count(Game.id)), f))).scalar_one()
        stmt = _order(self._mine(apply_filters(select(Game), f)), sort).offset(offset).limit(limit)
        return list(self.session.execute(stmt).scalars()), int(total)

    def iterate(self, f: GameFilters, *, sort: SortKey = "played_asc", limit: int | None = None) -> list[Game]:
        stmt = _order(self._mine(apply_filters(select(Game), f)), sort)
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.execute(stmt).scalars())

    def delete(self, game_id: int) -> bool:
        result = self.session.execute(delete(Game).where(Game.id == game_id, Game.user_id == self.user_id))
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def delete_many(self, ids: list[int]) -> int:
        result = self.session.execute(delete(Game).where(Game.id.in_(ids), Game.user_id == self.user_id))
        return int(result.rowcount)  # type: ignore[attr-defined]

    def delete_all(self) -> int:
        result = self.session.execute(delete(Game).where(Game.user_id == self.user_id))
        return int(result.rowcount)  # type: ignore[attr-defined]

    def latest_played_at(self, source: str, owner: str) -> datetime | None:
        stmt = self._mine(
            select(func.max(Game.played_at)).where(Game.source == source, Game.owner_username == owner.lower())
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def count(self) -> int:
        return int(self.session.execute(self._mine(select(func.count(Game.id)))).scalar_one())

    def version_key(self) -> tuple[int, int, int, str]:
        """Changes whenever this user's games are added or removed (for in-memory caches)."""
        count, max_id, max_imported = self.session.execute(
            self._mine(select(func.count(Game.id), func.max(Game.id), func.max(Game.imported_at)))
        ).one()
        return self.user_id, int(count), int(max_id or 0), str(max_imported)

    def owners(self) -> list[tuple[str, str, int]]:
        stmt = (
            select(Game.source, Game.owner_username, func.count(Game.id))
            .where(Game.owner_username.is_not(None), Game.user_id == self.user_id)
            .group_by(Game.source, Game.owner_username)
            .order_by(func.count(Game.id).desc())
        )
        return [(s, o, int(c)) for s, o, c in self.session.execute(stmt).all() if o is not None]
