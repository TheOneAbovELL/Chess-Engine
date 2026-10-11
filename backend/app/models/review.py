from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow

from .jobs import QUEUED


class GameReview(Base):
    """An engine review of one game; doubles as the background job record."""

    __tablename__ = "game_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default=QUEUED)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    engine_id: Mapped[str] = mapped_column(String(16))
    engine_name: Mapped[str | None] = mapped_column(String(80))
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # depth, movetime_ms, multipv
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    positions: Mapped[list[PositionEvaluation]] = relationship(
        back_populates="review", cascade="all, delete-orphan", passive_deletes=True, order_by="PositionEvaluation.ply"
    )


class PositionEvaluation(Base):
    """Engine evaluation of the position *after* ``ply`` half-moves.

    Scores are always from White's point of view. ``mate`` follows UCI sign
    conventions (positive: White mates); ``mate == 0`` means the side to move
    is checkmated in this position.

    For ``ply >= 1`` the row also describes the move that produced the
    position (``move_uci``/``move_san``) and its classification, computed from
    this row and the previous one.
    """

    __tablename__ = "position_evaluations"
    __table_args__ = (UniqueConstraint("review_id", "ply"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("game_reviews.id", ondelete="CASCADE"), index=True)
    ply: Mapped[int] = mapped_column(Integer)
    fen: Mapped[str] = mapped_column(String(100))

    cp: Mapped[int | None] = mapped_column(Integer)
    mate: Mapped[int | None] = mapped_column(Integer)
    depth: Mapped[int | None] = mapped_column(Integer)
    nodes: Mapped[int | None] = mapped_column(Integer)
    best_move_uci: Mapped[str | None] = mapped_column(String(8))
    best_move_san: Mapped[str | None] = mapped_column(String(12))
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # multipv alternatives
    terminal: Mapped[str | None] = mapped_column(String(24))  # checkmate / stalemate / draw reason

    move_uci: Mapped[str | None] = mapped_column(String(8))
    move_san: Mapped[str | None] = mapped_column(String(12))
    classification: Mapped[str | None] = mapped_column(String(16), index=True)
    cp_loss: Mapped[int | None] = mapped_column(Integer)
    win_loss: Mapped[float | None] = mapped_column(Float)  # expected-score loss, 0..1
    clock_s: Mapped[float | None] = mapped_column(Float)  # mover's remaining clock after the move, if recorded

    review: Mapped[GameReview] = relationship(back_populates="positions")
