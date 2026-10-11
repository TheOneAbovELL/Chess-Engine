"""Sign-in, registration and account management (``auth_mode=password``).

Sessions are opaque random tokens in an HttpOnly, SameSite=Lax cookie; only a
SHA-256 digest is stored server-side. Unsafe requests are additionally
protected by the Origin check in :class:`app.main.OriginCheckMiddleware`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import client_key, container, current_user, optional_user
from app.core.container import Container
from app.core.errors import ConflictError
from app.services.auth import SESSION_COOKIE, CurrentUser

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class Registration(Credentials):
    display_name: str | None = Field(None, max_length=64)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class PasswordConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _user_out(user: CurrentUser | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "is_admin": user.is_admin}


def _set_cookie(response: Response, c: Container, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=c.settings.session_days * 86400,
        httponly=True,
        secure=c.settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_cookie(response: Response, c: Container) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=c.settings.cookie_secure, httponly=True, samesite="lax")


def _require_accounts(c: Container) -> None:
    if not c.settings.multi_user:
        raise ConflictError("Accounts are turned off on this install (single-user mode).", code="auth_disabled")


@router.get("/session", summary="Who is signed in, and how this server handles accounts")
def session(c: Container = Depends(container), user: CurrentUser | None = Depends(optional_user)) -> dict[str, Any]:
    registered = c.auth.users_count() if c.settings.multi_user else 0
    return {
        "auth_mode": c.settings.auth_mode,
        "user": _user_out(user),
        "registration_open": c.settings.multi_user and (c.settings.allow_registration or registered == 0),
        "needs_setup": c.settings.multi_user and registered == 0,
    }


@router.post("/register", summary="Create an account and sign in")
def register(
    body: Registration, request: Request, response: Response, c: Container = Depends(container)
) -> dict[str, Any]:
    _require_accounts(c)
    c.lookup_limiter.check(f"register:{client_key(request)}")
    user, token = c.auth.register(body.username, body.password, body.display_name, request.headers.get("user-agent"))
    _set_cookie(response, c, token)
    return {"user": _user_out(user)}


@router.post("/login", summary="Sign in")
def login(body: Credentials, request: Request, response: Response, c: Container = Depends(container)) -> dict[str, Any]:
    _require_accounts(c)
    user, token = c.auth.login(body.username, body.password, client_key(request), request.headers.get("user-agent"))
    _set_cookie(response, c, token)
    return {"user": _user_out(user)}


@router.post("/logout", summary="Sign out on this device")
def logout(request: Request, response: Response, c: Container = Depends(container)) -> dict[str, bool]:
    c.auth.logout(request.cookies.get(SESSION_COOKIE))
    _clear_cookie(response, c)
    return {"ok": True}


@router.post("/password", summary="Change password (signs out your other devices)")
def change_password(
    body: PasswordChange,
    request: Request,
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, bool]:
    _require_accounts(c)
    c.auth.change_password(user, body.current_password, body.new_password, request.cookies.get(SESSION_COOKIE))
    return {"ok": True}


@router.post("/delete-account", summary="Permanently delete your account and all of its data")
def delete_account(
    body: PasswordConfirm,
    response: Response,
    c: Container = Depends(container),
    user: CurrentUser = Depends(current_user),
) -> dict[str, bool]:
    _require_accounts(c)
    c.auth.delete_account(user, body.password)
    _clear_cookie(response, c)
    return {"ok": True}
