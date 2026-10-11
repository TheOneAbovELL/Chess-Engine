"""ChessComProvider: Chess.com Published-Data API (free, public, no key).

Docs: https://www.chess.com/news/view/published-data-api

* ``GET /pub/player/{username}`` - profile (404 if the player does not exist)
* ``GET /pub/player/{username}/games/archives`` - monthly archive URLs, oldest first
* ``GET /pub/player/{username}/games/{YYYY}/{MM}`` - that month's games (JSON, PGN inside)

Requests are serial (the API only rate-limits parallel access). In refresh
mode, ``If-None-Match`` / ``If-Modified-Since`` validators from the last
complete import of a month are sent, so unchanged months cost a 304 and no
parsing.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from typing import Any

from app.services.chess.normalize import CHESSCOM_LINK_RE

from .base import (
    ChessHistoryProvider,
    ImportContext,
    ImportParams,
    ProviderBatch,
    ProviderError,
    ProviderUser,
    RawGame,
)
from .http import PoliteClient, json_or_error

MONTH_RE = re.compile(r"/games/(\d{4})/(\d{2})/?$")
TIME_CLASS_MAP = {"bullet": "bullet", "blitz": "blitz", "rapid": "rapid", "daily": "correspondence"}
NAME = "Chess.com"


def _epoch(value: Any) -> datetime | None:
    if isinstance(value, int | float) and value > 0:
        return datetime.fromtimestamp(value, UTC)
    return None


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1)
    return start, end


class ChessComProvider(ChessHistoryProvider):
    name = "chesscom"
    display_name = NAME

    def __init__(self, http: PoliteClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    def _player_url(self, username: str) -> str:
        return f"{self.base_url}/player/{username.lower()}"

    async def lookup_user(self, username: str) -> ProviderUser:
        response = await self.http.get(self._player_url(username))
        if response.status_code in (404, 410):
            raise ProviderError(
                "not_found", f"Chess.com has no public player named '{username}'. Check the spelling.", status=404
            )
        if response.status_code != 200:
            raise ProviderError(
                "bad_response", f"Chess.com answered with HTTP {response.status_code}.", status=response.status_code
            )
        data = json_or_error(response, NAME)
        if not isinstance(data, dict) or "username" not in data:
            raise ProviderError("bad_response", "Chess.com returned an unexpected profile format.")
        status = str(data.get("status") or "")
        user = ProviderUser(
            provider=self.name,
            username=str(data.get("username")),
            exists=True,
            url=data.get("url"),
            display_name=data.get("name"),
            status=status or None,
            closed=status.startswith("closed"),
            joined=_epoch(data.get("joined")),
            last_online=_epoch(data.get("last_online")),
        )
        if user.closed:
            user.notes.append("This Chess.com account is closed; its public archive may be incomplete or unavailable.")
        return user

    async def _archives(self, username: str) -> list[str]:
        response = await self.http.get(f"{self._player_url(username)}/games/archives")
        if response.status_code in (404, 410):
            raise ProviderError("not_found", f"Chess.com has no public game archive for '{username}'.", status=404)
        if response.status_code != 200:
            raise ProviderError(
                "bad_response", f"Chess.com answered with HTTP {response.status_code}.", status=response.status_code
            )
        data = json_or_error(response, NAME)
        archives = data.get("archives") if isinstance(data, dict) else None
        if not isinstance(archives, list) or not all(isinstance(a, str) for a in archives):
            raise ProviderError("bad_response", "Chess.com returned an unexpected archive list format.")
        return [a for a in archives if MONTH_RE.search(a)]

    def to_raw(self, game: dict[str, Any]) -> RawGame:
        url = game.get("url") if isinstance(game.get("url"), str) else None
        match = CHESSCOM_LINK_RE.search(url or "")
        external_id = f"{match.group(1).lower()}/{match.group(2)}" if match else (game.get("uuid") or None)
        ref = url or str(game.get("uuid") or "unknown game")
        pgn = game.get("pgn")
        rules = game.get("rules", "chess")
        skip = None
        if rules != "chess":
            skip = f"Variant '{rules}' is not supported (standard chess only)."
        elif not isinstance(pgn, str) or not pgn.strip():
            skip = "Chess.com provided no PGN for this game."
        overrides: dict[str, Any] = {
            "time_class": TIME_CLASS_MAP.get(str(game.get("time_class"))),
            "rated": game.get("rated") if isinstance(game.get("rated"), bool) else None,
            "played_at": _epoch(game.get("end_time")),
            "url": url,
        }
        return RawGame(
            pgn=pgn or "", source=self.name, external_id=external_id, ref=ref, overrides=overrides, skip_reason=skip
        )

    @staticmethod
    def _matches(game: dict[str, Any], params: ImportParams, username: str) -> bool:
        played = _epoch(game.get("end_time"))
        if params.since and played and played.date() < params.since:
            return False
        if params.until and played and played.date() > params.until:
            return False
        if params.time_classes:
            tc = TIME_CLASS_MAP.get(str(game.get("time_class")), "unknown")
            if tc not in params.time_classes:
                return False
        if params.rated is not None and game.get("rated") is not params.rated:
            return False
        if params.color:
            side = game.get(params.color)
            if not isinstance(side, dict) or str(side.get("username", "")).lower() != username.lower():
                return False
        return True

    async def fetch(self, params: ImportParams, ctx: ImportContext, max_games: int) -> AsyncIterator[ProviderBatch]:
        username = params.username
        await ctx.set_phase("Reading the list of monthly archives")
        months = list(reversed(await self._archives(username)))  # newest first
        filtered = bool(params.time_classes or params.color or params.rated is not None or params.since or params.until)
        remaining = max_games
        for url in months:
            if remaining <= 0 or await ctx.cancel_requested():
                return
            m = MONTH_RE.search(url)
            assert m is not None
            year, month = int(m.group(1)), int(m.group(2))
            start, end = _month_bounds(year, month)
            if params.until and start > params.until:
                continue
            if params.since and end <= params.since:
                break  # months are newest first: everything further is older
            label = f"{year}-{month:02d}"
            await ctx.set_phase(f"Downloading {label}")

            headers: dict[str, str] = {}
            if params.mode == "refresh":
                etag, last_modified = await ctx.cache_validators(url)
                if etag:
                    headers["If-None-Match"] = etag
                if last_modified:
                    headers["If-Modified-Since"] = last_modified
            response = await self.http.get(url, headers=headers)
            if response.status_code == 304:
                # Unchanged since this month was last fully imported. In refresh
                # mode older months are unchanged too, so we are done.
                if params.mode == "refresh":
                    return
                continue
            if response.status_code in (404, 410):
                continue
            if response.status_code != 200:
                raise ProviderError("bad_response", f"Chess.com answered with HTTP {response.status_code} for {label}.")
            data = json_or_error(response, NAME)
            games = data.get("games") if isinstance(data, dict) else None
            if not isinstance(games, list):
                raise ProviderError("bad_response", f"Chess.com returned an unexpected format for {label}.")

            candidates = [g for g in games if isinstance(g, dict) and self._matches(g, params, username)]
            candidates.sort(key=lambda g: g.get("end_time") or 0, reverse=True)
            truncated = len(candidates) > remaining
            selected = [self.to_raw(g) for g in candidates[:remaining]]
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")

            async def remember(
                url: str = url, etag: str | None = etag, last_modified: str | None = last_modified
            ) -> None:
                await ctx.store_validators(url, etag, last_modified)

            # Validators mean "every game of this month is stored", so only keep
            # them when nothing was filtered out or cut off.
            batch = ProviderBatch(selected, label=label, on_complete=None if (truncated or filtered) else remember)
            yield batch
            remaining -= len(selected)
            if params.mode == "refresh" and selected and batch.stats.imported == 0 and batch.stats.failed == 0:
                return  # reached games we already have

    async def preview(self, username: str, limit: int) -> list[dict[str, Any]]:
        months = await self._archives(username)
        result: list[dict[str, Any]] = []
        for url in reversed(months):
            response = await self.http.get(url)
            if response.status_code != 200:
                continue
            data = json_or_error(response, NAME)
            games = sorted(
                (g for g in data.get("games", []) if isinstance(g, dict)),
                key=lambda g: g.get("end_time") or 0,
                reverse=True,
            )
            for g in games:
                white, black = g.get("white") or {}, g.get("black") or {}
                result.append(
                    {
                        "url": g.get("url"),
                        "white": white.get("username"),
                        "black": black.get("username"),
                        "white_rating": white.get("rating"),
                        "black_rating": black.get("rating"),
                        "time_class": TIME_CLASS_MAP.get(str(g.get("time_class")), "unknown"),
                        "played_at": _epoch(g.get("end_time")),
                        "rules": g.get("rules"),
                    }
                )
                if len(result) >= limit:
                    return result
        return result
