"""Polite HTTP access to public chess APIs.

* One request at a time per provider (both providers ask for this).
* An identifying User-Agent on every request.
* Timeouts on every request; bounded retries with exponential backoff for
  network errors and 5xx responses.
* HTTP 429: wait (``Retry-After`` if given, else the provider's documented
  pause) and retry a bounded number of times, then report rate limiting.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx

from .base import ProviderError

log = logging.getLogger("chesslab.providers")
Sleep = Callable[[float], Awaitable[None]]


class PoliteClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        provider_name: str,
        max_retries: int = 3,
        rate_limit_wait_s: float = 60.0,
        backoff_base_s: float = 1.0,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.client = client
        self.provider_name = provider_name
        self.max_retries = max_retries
        self.rate_limit_wait_s = rate_limit_wait_s
        self.backoff_base_s = backoff_base_s
        self.sleep = sleep
        self._lock = asyncio.Lock()

    def _retry_after(self, response: httpx.Response) -> float:
        value = response.headers.get("Retry-After")
        if value and value.isdigit():
            return min(float(value), 300.0)
        return self.rate_limit_wait_s

    async def _attempts(self, send: Callable[[], Awaitable[httpx.Response]]) -> httpx.Response:
        attempt = 0
        while True:
            try:
                response = await send()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                if attempt >= self.max_retries:
                    raise ProviderError(
                        "network",
                        f"Could not reach {self.provider_name} (network error or timeout). "
                        "Check your internet connection and try again.",
                    ) from exc
                delay = self.backoff_base_s * (3**attempt)
                log.info("network error, retrying", extra={"provider": self.provider_name, "delay": delay})
                await self.sleep(delay)
                attempt += 1
                continue
            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise ProviderError(
                        "rate_limited",
                        f"{self.provider_name} is rate-limiting requests. Wait a few minutes and retry; "
                        "games already imported are kept.",
                        status=429,
                    )
                delay = self._retry_after(response)
                log.warning("rate limited, waiting", extra={"provider": self.provider_name, "delay": delay})
                await self.sleep(delay)
                attempt += 1
                continue
            if response.status_code >= 500:
                if attempt >= self.max_retries:
                    raise ProviderError(
                        "server",
                        f"{self.provider_name} returned a server error (HTTP {response.status_code}). Try again later.",
                        status=response.status_code,
                    )
                await self.sleep(self.backoff_base_s * (3**attempt))
                attempt += 1
                continue
            return response

    async def get(
        self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        async with self._lock:
            return await self._attempts(lambda: self.client.get(url, params=params, headers=headers))

    @asynccontextmanager
    async def stream(
        self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> AsyncIterator[httpx.Response]:
        """Open a streaming GET. Retries apply only until the response starts;
        a failure mid-stream surfaces as a network ProviderError."""
        async with self._lock:
            request = self.client.build_request("GET", url, params=params, headers=headers)
            response = await self._attempts(lambda: self.client.send(request, stream=True))
            try:
                yield response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise ProviderError(
                    "network", f"The connection to {self.provider_name} was interrupted. Retry to continue."
                ) from exc
            finally:
                await response.aclose()


def json_or_error(response: httpx.Response, provider_name: str) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError("bad_response", f"{provider_name} returned data in an unexpected format.") from exc
