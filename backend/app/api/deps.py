from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import Query, Request

from app.core.container import Container
from app.repositories.games import GameFilters


def container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def game_filters(
    q: str | None = Query(None, max_length=64, description="Player name (either side)"),
    source: Literal["chesscom", "lichess", "pgn", "local"] | None = None,
    owner: str | None = Query(None, max_length=64, description="Imported account username"),
    color: Literal["white", "black"] | None = None,
    result: Literal["win", "loss", "draw"] | None = None,
    time_class: Literal["ultrabullet", "bullet", "blitz", "rapid", "classical", "correspondence", "unknown"]
    | None = None,
    rated: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    opening: str | None = Query(None, max_length=80),
    min_rating: int | None = Query(None, ge=0, le=4000),
    max_rating: int | None = Query(None, ge=0, le=4000),
    reviewed: bool | None = None,
) -> GameFilters:
    return GameFilters(
        q=q,
        source=source,
        owner=owner,
        color=color,
        result=result,
        time_class=time_class,
        rated=rated,
        date_from=date_from,
        date_to=date_to,
        opening=opening,
        min_rating=min_rating,
        max_rating=max_rating,
        reviewed=reviewed,
    )
