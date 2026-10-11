from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import Depends, Query, Request

from app.core.container import Container
from app.repositories.games import GameFilters
from app.services.auth import LOCAL_USER, SESSION_COOKIE, AuthRequiredError, CurrentUser, ForbiddenError


def container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def optional_user(request: Request, c: Container = Depends(container)) -> CurrentUser | None:
    """The signed-in user, the built-in local user (``auth_mode=none``), or None."""
    if not c.settings.multi_user:
        return LOCAL_USER
    cached = getattr(request.state, "user", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]
    user = c.auth.resolve(request.cookies.get(SESSION_COOKIE))
    request.state.user = user
    return user


def current_user(user: CurrentUser | None = Depends(optional_user)) -> CurrentUser:
    if user is None:
        raise AuthRequiredError("Please sign in.")
    return user


def admin_user(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise ForbiddenError("Only the administrator can change this.")
    return user


def rate_key(request: Request, user: CurrentUser) -> str:
    """Rate-limit per account when accounts exist, otherwise per client address."""
    return f"user:{user.id}" if user is not LOCAL_USER else f"ip:{client_key(request)}"


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
