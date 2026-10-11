"""LichessProvider: Lichess public API (free, no token needed for public games).

Docs: https://lichess.org/api

* ``GET /api/user/{username}`` - public profile (404 if unknown)
* ``GET /api/games/user/{username}`` with ``Accept: application/x-chess-pgn``
  - streamed PGN export, newest first; anonymous throughput is about 20 games/s

Lichess requires an identifying ``User-Agent``; without one the export
endpoint answers with a generic 404 page (lichess-org/api issue #667). One
request at a time; on HTTP 429 wait a full minute before retrying.

Refresh mode asks only for games played after the newest stored game
(``since``), so no history is downloaded twice.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, time, timedelta
from typing import Any

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

NAME = "Lichess"
BATCH_SIZE = 25
GAME_SPLIT_RE = re.compile(r"\n\s*\n(?=\[Event )")
HEADER_RE = re.compile(r'^\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]\s*$', re.MULTILINE)
SPEED_RE = re.compile(r"\b(ultrabullet|bullet|blitz|rapid|classical|correspondence)\b", re.IGNORECASE)
PERF_TYPES = {
    "ultrabullet": "ultraBullet",
    "bullet": "bullet",
    "blitz": "blitz",
    "rapid": "rapid",
    "classical": "classical",
    "correspondence": "correspondence",
}
STANDARD = {"", "standard", "from position"}


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _from_ms(value: Any) -> datetime | None:
    if isinstance(value, int | float) and value > 0:
        return datetime.fromtimestamp(value / 1000, UTC)
    return None


def parse_headers(pgn: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in HEADER_RE.finditer(pgn.split("\n\n", 1)[0])}


class LichessProvider(ChessHistoryProvider):
    name = "lichess"
    display_name = NAME

    def __init__(self, http: PoliteClient, base_url: str) -> None:
        self.http = http
        self.base_url = base_url.rstrip("/")

    async def lookup_user(self, username: str) -> ProviderUser:
        response = await self.http.get(f"{self.base_url}/api/user/{username}")
        if response.status_code == 404:
            raise ProviderError(
                "not_found", f"Lichess has no player named '{username}'. Check the spelling.", status=404
            )
        if response.status_code != 200:
            raise ProviderError(
                "bad_response", f"Lichess answered with HTTP {response.status_code}.", status=response.status_code
            )
        data = json_or_error(response, NAME)
        if not isinstance(data, dict) or "id" not in data:
            raise ProviderError("bad_response", "Lichess returned an unexpected profile format.")
        raw_perfs = data.get("perfs")
        perfs: dict[str, Any] = raw_perfs if isinstance(raw_perfs, dict) else {}
        counts = {
            name: int(perf.get("games", 0))
            for name, perf in perfs.items()
            if isinstance(perf, dict) and isinstance(perf.get("games"), int) and perf.get("games")
        }
        total = data.get("count", {}).get("all") if isinstance(data.get("count"), dict) else None
        if isinstance(total, int):
            counts["all"] = total
        user = ProviderUser(
            provider=self.name,
            username=str(data.get("username", username)),
            exists=True,
            url=data.get("url"),
            closed=bool(data.get("disabled") or data.get("closed")),
            status="closed" if (data.get("disabled") or data.get("closed")) else None,
            joined=_from_ms(data.get("createdAt")),
            last_online=_from_ms(data.get("seenAt")),
            game_counts=counts,
        )
        if user.closed:
            user.notes.append("This Lichess account is closed; its games are not available for export.")
        if data.get("tosViolation"):
            user.notes.append("This account is marked for a terms-of-service violation; some games may be unavailable.")
        return user

    def to_raw(self, pgn: str) -> RawGame:
        headers = parse_headers(pgn)
        site = headers.get("Site", "")
        game_id = headers.get("GameId") or (site.rstrip("/").rsplit("/", 1)[-1] if "lichess.org/" in site else "")
        external_id = game_id if re.fullmatch(r"[A-Za-z0-9]{8}", game_id or "") else None
        variant = headers.get("Variant", "").strip().lower()
        skip = (
            None
            if variant in STANDARD
            else f"Variant '{headers.get('Variant')}' is not supported (standard chess only)."
        )
        event = headers.get("Event", "")
        speed = SPEED_RE.search(event)
        overrides: dict[str, Any] = {
            "time_class": speed.group(1).lower() if speed else None,
            "rated": True
            if event.lower().startswith("rated")
            else False
            if event.lower().startswith("casual")
            else None,
        }
        return RawGame(
            pgn=pgn,
            source=self.name,
            external_id=external_id,
            ref=site or game_id or "lichess game",
            overrides=overrides,
            skip_reason=skip,
        )

    def _query(self, params: ImportParams, max_games: int, since: datetime | None) -> dict[str, Any]:
        query: dict[str, Any] = {
            "max": max_games,
            "clocks": "true",
            "opening": "true",
            "moves": "true",
            "tags": "true",
            "sort": "dateDesc",
            "finished": "true",
        }
        lower = since
        if params.since:
            explicit = datetime.combine(params.since, time.min, tzinfo=UTC)
            lower = max(lower, explicit) if lower else explicit
        if lower:
            query["since"] = _ms(lower)
        if params.until:
            query["until"] = _ms(datetime.combine(params.until + timedelta(days=1), time.min, tzinfo=UTC)) - 1
        if params.time_classes:
            query["perfType"] = ",".join(PERF_TYPES[t] for t in params.time_classes)
        if params.color:
            query["color"] = params.color
        if params.rated is not None:
            query["rated"] = "true" if params.rated else "false"
        return query

    async def fetch(self, params: ImportParams, ctx: ImportContext, max_games: int) -> AsyncIterator[ProviderBatch]:
        username = params.username
        await ctx.set_phase("Checking the Lichess account")
        user = await self.lookup_user(username)
        if user.closed:
            raise ProviderError("closed", f"The Lichess account '{username}' is closed; its games cannot be exported.")
        since = None
        if params.mode == "refresh":
            latest = await ctx.latest_played_at(self.name, username)
            if latest is not None:
                since = latest + timedelta(milliseconds=1)
        query = self._query(params, max_games, since)
        await ctx.set_phase("Downloading games from Lichess")
        url = f"{self.base_url}/api/games/user/{username}"
        async with self.http.stream(url, params=query, headers={"Accept": "application/x-chess-pgn"}) as response:
            if response.status_code == 404:
                raise ProviderError(
                    "not_found",
                    "Lichess did not return games for this account (HTTP 404). "
                    "The account may be closed or its games hidden.",
                    status=404,
                )
            if response.status_code != 200:
                raise ProviderError(
                    "bad_response", f"Lichess answered with HTTP {response.status_code}.", status=response.status_code
                )
            buffer = ""
            batch: list[RawGame] = []
            count = 0
            async for chunk in response.aiter_text():
                buffer += chunk
                parts = GAME_SPLIT_RE.split(buffer)
                buffer = parts.pop()
                for part in parts:
                    if part.strip():
                        batch.append(self.to_raw(part.strip() + "\n"))
                        count += 1
                if len(batch) >= BATCH_SIZE:
                    yield ProviderBatch(batch, label=f"games {count - len(batch) + 1}-{count}")
                    batch = []
                    await ctx.set_phase(f"Downloaded {count} games")
                    if await ctx.cancel_requested():
                        return
            if buffer.strip():
                batch.append(self.to_raw(buffer.strip() + "\n"))
                count += 1
            if batch:
                yield ProviderBatch(batch, label=f"games {count - len(batch) + 1}-{count}")

    async def preview(self, username: str, limit: int) -> list[dict[str, Any]]:
        url = f"{self.base_url}/api/games/user/{username}"
        response = await self.http.get(
            url,
            params={"max": limit, "moves": "false", "opening": "true"},
            headers={"Accept": "application/x-chess-pgn"},
        )
        if response.status_code == 404:
            raise ProviderError("not_found", f"Lichess has no games for '{username}'.", status=404)
        if response.status_code != 200:
            raise ProviderError("bad_response", f"Lichess answered with HTTP {response.status_code}.")
        result = []
        for part in GAME_SPLIT_RE.split(response.text):
            if not part.strip():
                continue
            h = parse_headers(part)
            speed = SPEED_RE.search(h.get("Event", ""))
            played = None
            if h.get("UTCDate") and h.get("UTCTime"):
                try:
                    played = datetime.strptime(f"{h['UTCDate']} {h['UTCTime']}", "%Y.%m.%d %H:%M:%S").replace(
                        tzinfo=UTC
                    )
                except ValueError:
                    played = None
            result.append(
                {
                    "url": h.get("Site"),
                    "white": h.get("White"),
                    "black": h.get("Black"),
                    "white_rating": int(h["WhiteElo"]) if h.get("WhiteElo", "").isdigit() else None,
                    "black_rating": int(h["BlackElo"]) if h.get("BlackElo", "").isdigit() else None,
                    "time_class": speed.group(1).lower() if speed else "unknown",
                    "played_at": played,
                    "rules": h.get("Variant", "Standard"),
                }
            )
        return result[:limit]
