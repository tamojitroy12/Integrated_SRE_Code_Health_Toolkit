"""Read-side monitoring queries for the API: charts and current values."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from toolkit.db.models import MonitoringTarget
from toolkit.monitoring import queries as Q
from toolkit.monitoring.prometheus import PrometheusClient, PrometheusUnavailable

RANGE_SECONDS = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400}
MAX_POINTS = 300
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="promql")


def selector_for(target: MonitoringTarget) -> Q.Selector:
    return Q.Selector(target.service_name, target.environment)


def default_step(range_key: str) -> int:
    seconds = RANGE_SECONDS[range_key]
    step = math.ceil(seconds / MAX_POINTS)
    return max(15, math.ceil(step / 15) * 15)


def rate_window_for_step(step: int) -> str:
    # At least four scrape/export intervals so rate() always has two samples.
    return Q.seconds_to_promql(max(60, step * 2))


@dataclass
class ChartResult:
    metric: str
    unit: str
    range: str
    step_seconds: int
    status: str  # ok | no_data | no_traffic
    series: list[dict[str, object]] = field(default_factory=list)


def chart(
    client: PrometheusClient, target: MonitoringTarget, metric: str, range_key: str, step: int | None, now: datetime
) -> ChartResult:
    step_s = step or default_step(range_key)
    seconds = RANGE_SECONDS[range_key]
    if seconds / step_s > 11_000:  # Prometheus' own resolution limit
        step_s = math.ceil(seconds / 11_000)
    sel = selector_for(target)
    start = now - timedelta(seconds=seconds)
    promql = Q.metric_query(metric, sel, rate_window_for_step(step_s))
    series = client.query_range(promql, start, now, step_s)
    total = client.query_scalar(Q.total_requests(sel, Q.seconds_to_promql(seconds)), now)
    if total is None:
        status = "no_data"
    elif total == 0 or math.isnan(total):
        status = "no_traffic"
    else:
        status = "ok"
    points: list[dict[str, object]] = []
    if series:
        for t, v in series[0].points:
            points.append({"t": t, "v": None if math.isnan(v) or math.isinf(v) else round(v, 6)})
    return ChartResult(metric, Q.UNITS[metric], range_key, step_s, status, points)


def _current(client: PrometheusClient, target: MonitoringTarget) -> dict[str, float | None]:
    sel = selector_for(target)
    out: dict[str, float | None] = {}
    for key, metric in (
        ("request_rate", "request_rate"),
        ("error_ratio", "error_ratio"),
        ("latency_p95_seconds", "latency_p95"),
    ):
        value = client.query_scalar(Q.metric_query(metric, sel, "5m"))
        out[key] = None if value is None or math.isnan(value) or math.isinf(value) else round(value, 6)
    if out["request_rate"] is None and out["error_ratio"] is None:
        return out
    if out["request_rate"] is None:
        out["request_rate"] = 0.0
    return out


def current_values(client: PrometheusClient, targets: list[MonitoringTarget]) -> dict[str, dict[str, float | None]]:
    """Current request rate, error ratio and p95 per target, queried concurrently.

    Raises PrometheusUnavailable if the store cannot be reached.
    """
    futures = {str(t.id): _pool.submit(_current, client, t) for t in targets}
    results: dict[str, dict[str, float | None]] = {}
    for tid, fut in futures.items():
        results[tid] = fut.result()
    return results


__all__ = ["RANGE_SECONDS", "ChartResult", "PrometheusUnavailable", "chart", "current_values", "default_step"]
