"""Outbound HTTP client used by every integration adapter (TRD §10.1).

Provides timeouts, bounded retries with exponential backoff on transient failures,
no redirects by default and typed errors. Hosts are limited to an allowlist (CON-09).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

TRANSIENT_STATUS = {408, 425, 429, 500, 502, 503, 504}
USER_AGENT = "sre-code-health-toolkit/1.0"


class UpstreamError(Exception):
    """An upstream call failed. ``status`` is None for network-level failures."""

    def __init__(self, message: str, *, status: int | None = None, transient: bool = False) -> None:
        self.status = status
        self.transient = transient
        super().__init__(message)


class HostNotAllowedError(UpstreamError):
    pass


class HttpClient:
    def __init__(
        self,
        *,
        allowed_hosts: Iterable[str],
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": USER_AGENT, **(headers or {})},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _check_host(self, url: str) -> None:
        host = (urlsplit(url).hostname or "").lower()
        if host not in self.allowed_hosts:
            raise HostNotAllowedError(f"host {host!r} is not in the outbound allowlist")

    def request(
        self,
        method: str,
        url: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        ok_statuses: Iterable[int] = (200,),
        retry: bool = True,
    ) -> httpx.Response:
        self._check_host(url)
        ok = set(ok_statuses)
        attempts = self.max_retries + 1 if retry else 1
        last_exc: UpstreamError | None = None
        for attempt in range(attempts):
            try:
                resp = self._client.request(method, url, json=json, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                last_exc = UpstreamError(f"timeout calling {urlsplit(url).hostname}", transient=True)
                last_exc.__cause__ = exc
            except httpx.HTTPError as exc:
                last_exc = UpstreamError(f"network error calling {urlsplit(url).hostname}", transient=True)
                last_exc.__cause__ = exc
            else:
                if resp.status_code in ok:
                    return resp
                transient = resp.status_code in TRANSIENT_STATUS
                last_exc = UpstreamError(
                    f"{urlsplit(url).hostname} returned HTTP {resp.status_code}",
                    status=resp.status_code,
                    transient=transient,
                )
                if not transient:
                    raise last_exc
                retry_after = _retry_after(resp)
                if retry_after is not None and attempt + 1 < attempts:
                    self._sleep(min(retry_after, 30.0))
                    continue
            if attempt + 1 < attempts:
                delay = self.backoff_base * (2**attempt) * (0.5 + random.random())  # noqa: S311
                self._sleep(delay)
        assert last_exc is not None
        raise last_exc

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.request("GET", url, **kwargs).json()

    def post_json(self, url: str, body: Any, **kwargs: Any) -> Any:
        return self.request("POST", url, json=body, **kwargs).json()


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()
