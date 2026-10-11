from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow


class Game(Base):
    """One stored game.

    ``(source, external_id)`` is the deduplication key:

    * ``chesscom``: ``live/<id>`` or ``daily/<id>`` from the game URL
    * ``lichess``: the 8-character game id
    * ``pgn``: a SHA-256 fingerprint of players, date, result and moves
    * ``local``: a random UUID for games played in ChessLab

    ``moves_uci`` duplicates information in ``pgn`` on purpose: replaying UCI
    moves is far cheaper than re-parsing PGN, which keeps the opening explorer
    and statistics fast.
    """

    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("source", "external_id"),
        Index("ix_games_owner_played", "owner_username", "played_at"),
        Index("ix_games_source_owner", "source", "owner_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    owner_username: Mapped[str | None] = mapped_column(String(64))  # lower-cased account name
    user_color: Mapped[str | None] = mapped_column(String(5))  # "white" | "black"
    user_result: Mapped[str | None] = mapped_column(String(4))  # "win" | "loss" | "draw"

    white: Mapped[str] = mapped_column(String(64))
    black: Mapped[str] = mapped_column(String(64))
    white_elo: Mapped[int | None] = mapped_column(Integer)
    black_elo: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(7))  # "1-0" | "0-1" | "1/2-1/2" | "*"
    termination: Mapped[str | None] = mapped_column(String(160))

    time_control: Mapped[str | None] = mapped_column(String(32))
    time_class: Mapped[str] = mapped_column(String(16), index=True, default="unknown")
    rated: Mapped[bool | None] = mapped_column(Boolean)
    variant: Mapped[str] = mapped_column(String(32), default="standard")
    eco: Mapped[str | None] = mapped_column(String(8))
    opening: Mapped[str | None] = mapped_column(String(200))
    event: Mapped[str | None] = mapped_column(String(160))
    url: Mapped[str | None] = mapped_column(String(255))

    played_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    ply_count: Mapped[int] = mapped_column(Integer, default=0)
    initial_fen: Mapped[str | None] = mapped_column(String(100))  # None = standard start
    moves_uci: Mapped[str] = mapped_column(Text, default="")
    pgn: Mapped[str] = mapped_column(Text)

    import_job_id: Mapped[str | None] = mapped_column(String(36))
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
