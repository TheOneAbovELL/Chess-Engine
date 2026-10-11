"""Password hashing and session tokens (standard library only).

* Passwords: scrypt (memory-hard) with a per-password random salt, encoded as
  ``scrypt$n$r$p$salt_b64$hash_b64`` so parameters can be raised later.
* Sessions: 32 random bytes sent to the browser in an HttpOnly cookie; only
  their SHA-256 digest is stored server-side.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
SCRYPT_MAXMEM = 64 * 1024 * 1024
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, maxmem=SCRYPT_MAXMEM
    )
    b64 = base64.urlsafe_b64encode
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if algorithm != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_b64)
        expected = base64.urlsafe_b64decode(hash_b64)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), maxmem=SCRYPT_MAXMEM)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# Frequent entries (8+ characters) of public breached-password top lists.
COMMON_PASSWORDS = frozenset(
    """
    password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword 12345678 123456789
    1234567890 0987654321 87654321 11111111 00000000 12341234 12121212 11223344 qwertyui qwerty123 qwertyuiop
    1q2w3e4r 1qaz2wsx zaq12wsx asdfghjk asdfasdf zxcvbnm1 iloveyou iloveyou1 sunshine princess football
    football1 baseball welcome welcome1 letmein1 trustno1 superman batman123 starwars whatever dragon12
    monkey12 abc12345 abcd1234 aa123456 changeme computer internet master12 michael1 jennifer shadow12
    chesslab chess123 chessmaster checkmate grandmaster magnus123 stockfish lichess1 chesscom
    """.split()
)


def password_problems(password: str, username: str) -> list[str]:
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"Use at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 256:
        problems.append("Use at most 256 characters.")
    if password.lower() == username.lower():
        problems.append("The password must differ from the username.")
    if password.lower() in COMMON_PASSWORDS or len(set(password)) <= 2:
        problems.append("This password is too common or too easy to guess.")
    return problems


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LoginThrottle:
    """Slows down password guessing: after ``limit`` failures for the same
    username or client within ``window_s`` further attempts are refused."""

    def __init__(self, limit: int = 8, window_s: float = 900.0) -> None:
        self.limit = limit
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._failures.setdefault(key, deque())
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        return hits

    def blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(len(self._prune(k, now)) >= self.limit for k in keys)

    def fail(self, *keys: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._prune(key, now).append(now)
            if len(self._failures) > 50_000:
                self._failures = {k: v for k, v in self._failures.items() if v}

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
