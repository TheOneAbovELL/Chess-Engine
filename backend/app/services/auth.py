"""Accounts and sessions.

``auth_mode=none`` (default, local use): there is no login; every request acts
as the built-in local user (id 1).

``auth_mode=password``: users register and log in with username + password.
The first account registered on an install that already has local data
*claims* the local user (id 1), so switching a personal install to accounts
keeps all existing games. The first account is also the administrator, who may
change server-wide engine resources.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, InvalidInputError
from app.core.security import (
    LoginThrottle,
    hash_password,
    new_session_token,
    password_problems,
    token_digest,
    verify_password,
)
from app.db.base import utcnow
from app.db.session import Database
from app.models import LOCAL_USER_ID, User, UserSession

log = logging.getLogger("chesslab.auth")
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,31}$")
SESSION_COOKIE = "chesslab_session"
TOUCH_INTERVAL = timedelta(minutes=5)


class AuthRequiredError(AppError):
    status_code = 401
    code = "auth_required"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    display_name: str
    is_admin: bool

    @classmethod
    def of(cls, user: User) -> CurrentUser:
        return cls(user.id, user.username, user.display_name, user.is_admin)


LOCAL_USER = CurrentUser(LOCAL_USER_ID, "local", "You", True)
_DUMMY: list[str] = []


def _dummy_hash() -> str:
    if not _DUMMY:
        _DUMMY.append(hash_password("timing-equaliser"))
    return _DUMMY[0]


class AuthService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self.throttle = LoginThrottle()

    # ------------------------------------------------------------- sessions
    def _new_session(self, session: object, user: User, user_agent: str | None) -> str:
        token = new_session_token()
        now = utcnow()
        session.add(  # type: ignore[attr-defined]
            UserSession(
                token_hash=token_digest(token),
                user_id=user.id,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(days=self.settings.session_days),
                user_agent=(user_agent or "")[:200] or None,
            )
        )
        return token

    def resolve(self, token: str | None) -> CurrentUser | None:
        if not token or len(token) > 128:
            return None
        with self.db.session() as session:
            row = session.get(UserSession, token_digest(token))
            if row is None:
                return None
            now = datetime.now(UTC)
            if row.expires_at <= now:
                session.delete(row)
                return None
            user = session.get(User, row.user_id)
            if user is None or user.disabled:
                return None
            if now - row.last_seen_at > TOUCH_INTERVAL:
                row.last_seen_at = now
            return CurrentUser.of(user)

    def logout(self, token: str | None) -> None:
        if token:
            with self.db.session() as session:
                session.execute(delete(UserSession).where(UserSession.token_hash == token_digest(token)))

    def purge_expired_sessions(self) -> int:
        with self.db.session() as session:
            result = session.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
            return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # -------------------------------------------------------------- accounts
    @staticmethod
    def normalize_username(username: str) -> str:
        name = username.strip().lower()
        if not USERNAME_RE.fullmatch(name):
            raise InvalidInputError(
                "Usernames are 3-32 characters: lowercase letters, digits, '_' or '-', "
                "starting with a letter or digit.",
                code="invalid_username",
            )
        return name

    def register(
        self, username: str, password: str, display_name: str | None, user_agent: str | None
    ) -> tuple[CurrentUser, str]:
        if not self.settings.multi_user:
            raise ConflictError("Accounts are disabled (CHESSLAB_AUTH_MODE=none).", code="auth_disabled")
        name = self.normalize_username(username)
        problems = password_problems(password, name)
        if problems:
            raise InvalidInputError(" ".join(problems), code="weak_password")
        with self.db.session() as session:
            if session.execute(select(User.id).where(User.username == name)).first():
                raise ConflictError("That username is taken.", code="username_taken")
            claimed = False
            local = session.get(User, LOCAL_USER_ID)
            registered = session.execute(
                select(func.count(User.id)).where(User.password_hash.is_not(None))
            ).scalar_one()
            if not self.settings.allow_registration and registered > 0:
                raise ForbiddenError("Registration is closed on this server.", code="registration_closed")
            if local is not None and local.password_hash is None and registered == 0:
                # First account on this install: take over the local user's data.
                user = local
                user.username, user.password_hash, user.is_admin = name, hash_password(password), True
                user.display_name = (display_name or name)[:64]
                claimed = True
            else:
                user = User(
                    username=name,
                    display_name=(display_name or name)[:64],
                    password_hash=hash_password(password),
                    is_admin=registered == 0,
                    disabled=False,
                )
                session.add(user)
                session.flush()
            user.last_login_at = utcnow()
            token = self._new_session(session, user, user_agent)
            result = CurrentUser.of(user)
        log.info("account registered", extra={"user": result.id, "claimed_local_data": claimed})
        return result, token

    def login(self, username: str, password: str, client: str, user_agent: str | None) -> tuple[CurrentUser, str]:
        if not self.settings.multi_user:
            raise ConflictError("Accounts are disabled (CHESSLAB_AUTH_MODE=none).", code="auth_disabled")
        name = username.strip().lower()[:64]
        keys = (f"user:{name}", f"client:{client}")
        if self.throttle.blocked(*keys):
            raise AppError(
                "Too many failed sign-in attempts. Try again in 15 minutes.", code="too_many_attempts", status_code=429
            )
        with self.db.session() as session:
            user = session.execute(select(User).where(User.username == name)).scalar_one_or_none()
            # Always run the hash check so timing does not reveal which usernames exist.
            valid = verify_password(password, user.password_hash if user else _dummy_hash())
            if user is None or not valid or user.disabled:
                self.throttle.fail(*keys)
                raise AppError("Wrong username or password.", code="invalid_credentials", status_code=401)
            self.throttle.reset(*keys)
            user.last_login_at = utcnow()
            token = self._new_session(session, user, user_agent)
            return CurrentUser.of(user), token

    def change_password(self, user: CurrentUser, current: str, new: str, keep_token: str | None) -> None:
        problems = password_problems(new, user.username)
        if problems:
            raise InvalidInputError(" ".join(problems), code="weak_password")
        with self.db.session() as session:
            row = session.get(User, user.id)
            if row is None or not verify_password(current, row.password_hash):
                raise AppError("The current password is wrong.", code="invalid_credentials", status_code=401)
            row.password_hash = hash_password(new)
            # Sign out every other device.
            keep = token_digest(keep_token) if keep_token else ""
            session.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.token_hash != keep))

    def delete_account(self, user: CurrentUser, password: str) -> None:
        """Delete the account and everything it owns (games, reviews, jobs, settings)."""
        with self.db.session() as session:
            row = session.get(User, user.id)
            if row is None or not verify_password(password, row.password_hash):
                raise AppError("The password is wrong.", code="invalid_credentials", status_code=401)
            session.delete(row)  # ON DELETE CASCADE removes the rest
        log.info("account deleted", extra={"user": user.id})

    def users_count(self) -> int:
        with self.db.session() as session:
            return int(session.execute(select(func.count(User.id)).where(User.password_hash.is_not(None))).scalar_one())

    def set_disabled(self, user_id: int, disabled: bool) -> None:
        with self.db.session() as session:
            session.execute(update(User).where(User.id == user_id).values(disabled=disabled))
            if disabled:
                session.execute(delete(UserSession).where(UserSession.user_id == user_id))
