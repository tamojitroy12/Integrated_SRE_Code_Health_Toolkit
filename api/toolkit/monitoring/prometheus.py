"""Minimal Prometheus HTTP API client (IF-02)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from toolkit.core.config import get_settings

# Overridable in tests / embedding (e.g. httpx.MockTransport); None uses the network.
DEFAULT_TRANSPORT: httpx.BaseTransport | None = None


class PrometheusUnavailable(Exception):  # noqa: N818
    pass


@dataclass(frozen=True)
class Sample:
    labels: dict[str, str]
    t: datetime
    v: float


@dataclass(frozen=True)
class Series:
    labels: dict[str, str]
    points: list[tuple[datetime, float]]


def _to_float(raw: str) -> float:
    try:
        return float(raw)
    except ValueError:
        return math.nan


class PrometheusClient:
    def __init__(
        self, base_url: str | None = None, *, timeout: float | None = None, transport: httpx.BaseTransport | None = None
    ) -> None:
        s = get_settings()
        self.base_url = (base_url or s.prometheus_url).rstrip("/")
        self._client = httpx.Client(
            timeout=timeout or s.prometheus_timeout_seconds,
            transport=transport or DEFAULT_TRANSPORT,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            resp = self._client.get(f"{self.base_url}{path}", params=params)
        except httpx.HTTPError as exc:
            raise PrometheusUnavailable(str(type(exc).__name__)) from exc
        if resp.status_code >= 500:
            raise PrometheusUnavailable(f"HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise PrometheusUnavailable("invalid JSON") from exc
        if body.get("status") != "success":
            raise PrometheusUnavailable(str(body.get("error", "query failed"))[:200])
        return body["data"]

    def query(self, promql: str, at: datetime | None = None) -> list[Sample]:
        params: dict[str, Any] = {"query": promql}
        if at is not None:
            params["time"] = f"{at.timestamp():.3f}"
        data = self._get("/api/v1/query", params)
        if data.get("resultType") == "scalar":
            ts, val = data["result"]
            return [Sample({}, datetime.fromtimestamp(float(ts), UTC), _to_float(val))]
        out: list[Sample] = []
        for item in data.get("result", []):
            ts, val = item["value"]
            out.append(Sample(item.get("metric", {}), datetime.fromtimestamp(float(ts), UTC), _to_float(val)))
        return out

    def query_scalar(self, promql: str, at: datetime | None = None) -> float | None:
        """First sample value, or None for an empty result. NaN is returned as NaN."""
        samples = self.query(promql, at)
        return samples[0].v if samples else None

    def query_range(self, promql: str, start: datetime, end: datetime, step_seconds: int) -> list[Series]:
        data = self._get(
            "/api/v1/query_range",
            {
                "query": promql,
                "start": f"{start.timestamp():.3f}",
                "end": f"{end.timestamp():.3f}",
                "step": str(step_seconds),
            },
        )
        series: list[Series] = []
        for item in data.get("result", []):
            pts = [(datetime.fromtimestamp(float(t), UTC), _to_float(v)) for t, v in item.get("values", [])]
            series.append(Series(item.get("metric", {}), pts))
        return series

    def ready(self) -> bool:
        try:
            return self._client.get(f"{self.base_url}/-/ready").status_code == 200
        except httpx.HTTPError:
            return False
