"""Every PromQL query the Toolkit issues is built here (TRD §4, §10.3; IF-02, TH-09).

User input never becomes PromQL directly: service names, environments and windows are
validated against strict grammars and substituted into fixed templates.

Metric/label names follow the OpenTelemetry HTTP semantic conventions as translated by
the Collector's Prometheus remote-write exporter (``http.server.request.duration`` in
seconds → ``http_server_request_duration_seconds_*``; ``service.name`` →
``service_name``; ``deployment.environment.name`` → ``deployment_environment_name``).
They are confined to this module so UD-06 adjustments touch one file.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from toolkit.core.validators import ENVIRONMENT_RE, PROMQL_DURATION_RE, SERVICE_NAME_RE

DURATION_METRIC = "http_server_request_duration_seconds"
STATUS_LABEL = "http_response_status_code"
SERVICE_LABEL = "service_name"
ENV_LABEL = "deployment_environment_name"


class ChartMetric(StrEnum):
    REQUEST_RATE = "request_rate"
    ERROR_RATIO = "error_ratio"
    LATENCY_P50 = "latency_p50"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"


UNITS: dict[str, str] = {
    "request_rate": "requests_per_second",
    "error_ratio": "ratio",
    "latency_p50": "seconds",
    "latency_p95": "seconds",
    "latency_p99": "seconds",
    "data_absent": "boolean",
}

_QUANTILES = {"latency_p50": "0.5", "latency_p95": "0.95", "latency_p99": "0.99"}


class InvalidQueryParamError(ValueError):
    pass


_RE2_META = frozenset("\\.+*?()|[]{}^$")


def regex_literal(value: str) -> str:
    """Escape ``value`` for use inside a PromQL ``=~"…"`` string.

    Python's ``re.escape`` also escapes ``-``, which PromQL rejects as an unknown string escape.
    The backslash itself must be doubled: the string literal unescapes once, RE2 once more.
    """
    return "".join("\\\\" + c if c in _RE2_META else c for c in value)


@dataclass(frozen=True)
class Selector:
    service_name: str
    environment: str | None = None

    def __post_init__(self) -> None:
        if not SERVICE_NAME_RE.match(self.service_name):
            raise InvalidQueryParamError("invalid service_name")
        if self.environment is not None and not ENVIRONMENT_RE.match(self.environment):
            raise InvalidQueryParamError("invalid environment")

    def matchers(self, extra: str = "") -> str:
        parts = [f'{SERVICE_LABEL}="{self.service_name}"']
        if self.environment:
            # Matches series that carry the environment label or have none at all.
            parts.append(f'{ENV_LABEL}=~"{regex_literal(self.environment)}|"')
        if extra:
            parts.append(extra)
        return ",".join(parts)


def _window(window: str) -> str:
    if not PROMQL_DURATION_RE.match(window):
        raise InvalidQueryParamError("invalid window")
    return window


def request_rate(sel: Selector, window: str) -> str:
    w = _window(window)
    return f"sum(rate({DURATION_METRIC}_count{{{sel.matchers()}}}[{w}]))"


def error_ratio(sel: Selector, window: str) -> str:
    w = _window(window)
    five_xx = STATUS_LABEL + '=~"5.."'
    errors = f"sum(rate({DURATION_METRIC}_count{{{sel.matchers(five_xx)}}}[{w}]))"
    total = f"sum(rate({DURATION_METRIC}_count{{{sel.matchers()}}}[{w}]))"
    # "or (total * 0)" makes "traffic but no 5xx series" evaluate to 0 instead of empty,
    # while zero traffic still yields NaN/empty ("no traffic", never 100 % available).
    return f"({errors} or ({total} * 0)) / {total}"


def latency_quantile(sel: Selector, window: str, quantile_metric: str) -> str:
    q = _QUANTILES[quantile_metric]
    w = _window(window)
    return f"histogram_quantile({q}, sum by (le) (rate({DURATION_METRIC}_bucket{{{sel.matchers()}}}[{w}])))"


def data_absent(sel: Selector, stale_window: str) -> str:
    w = _window(stale_window)
    return f"absent_over_time({DURATION_METRIC}_count{{{sel.matchers()}}}[{w}])"


def metric_query(metric: str, sel: Selector, window: str) -> str:
    if metric == "request_rate":
        return request_rate(sel, window)
    if metric == "error_ratio":
        return error_ratio(sel, window)
    if metric in _QUANTILES:
        return latency_quantile(sel, window, metric)
    raise InvalidQueryParamError(f"unknown metric {metric!r}")


def total_requests(sel: Selector, window: str) -> str:
    """Request count over a window; used to tell 'no traffic' from 'no data'."""
    w = _window(window)
    return f"sum(increase({DURATION_METRIC}_count{{{sel.matchers()}}}[{w}]))"


def series_present(sel: Selector) -> str:
    return f"count({DURATION_METRIC}_count{{{sel.matchers()}}})"


def last_sample_batch(service_names: list[str]) -> str:
    """Latest sample timestamp per service for all targets in one query (scales with targets)."""
    for name in service_names:
        if not SERVICE_NAME_RE.match(name):
            raise InvalidQueryParamError("invalid service_name")
    alternatives = "|".join(regex_literal(n) for n in sorted(set(service_names)))
    return (
        f'max by ({SERVICE_LABEL}, {ENV_LABEL}) (timestamp({{{SERVICE_LABEL}=~"{alternatives}",'
        f'__name__=~"{DURATION_METRIC}_count|target_info"}}))'
    )


def seconds_to_promql(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"
