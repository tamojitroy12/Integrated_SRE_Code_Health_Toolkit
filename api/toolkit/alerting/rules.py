"""Alert rule validation (FR-ALR-01, API_SPEC §6) and lifecycle transitions (FR-ALR-02)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode

THRESHOLD_METRICS = {"error_ratio", "latency_p95", "request_rate"}
ANOMALY_METRICS = {"request_rate", "latency_p95"}
WINDOWS = {"1m", "5m", "15m"}
DEFAULT_ANOMALY_PARAMS = {"baseline_points": 60, "z_threshold": 3.0, "consecutive": 3}


@dataclass
class RuleSpec:
    type: str
    metric: str
    comparator: str | None
    threshold: float | None
    window: str | None
    duration_seconds: int | None
    resolve_after: int
    params: dict[str, Any]


def _err(field: str, issue: str) -> dict[str, str]:
    return {"field": field, "issue": issue}


def validate_rule(spec: RuleSpec) -> RuleSpec:
    """Validate and normalise a rule; raises 422 VALIDATION_ERROR listing every problem."""
    s = get_settings()
    errors: list[dict[str, str]] = []
    eval_s = s.alert_eval_interval_seconds
    if spec.resolve_after < 1 or spec.resolve_after > 100:
        errors.append(_err("resolve_after", "must be between 1 and 100"))

    if spec.type == "threshold":
        if spec.metric not in THRESHOLD_METRICS:
            errors.append(_err("metric", f"threshold rules support {sorted(THRESHOLD_METRICS)}"))
        if spec.comparator not in ("gt", "lt"):
            errors.append(_err("comparator", "must be gt or lt"))
        if spec.window not in WINDOWS:
            errors.append(_err("window", "must be one of 1m, 5m, 15m"))
        if spec.threshold is None:
            errors.append(_err("threshold", "required"))
        else:
            t = spec.threshold
            if spec.metric == "error_ratio" and not 0 <= t <= 1:
                errors.append(_err("threshold", "must be between 0 and 1"))
            elif spec.metric == "latency_p95" and not 0 < t <= 600:
                errors.append(_err("threshold", "must be > 0 and <= 600 seconds"))
            elif spec.metric == "request_rate" and t < 0:
                errors.append(_err("threshold", "must be >= 0"))
        spec.params = {}
    elif spec.type == "absence":
        if spec.metric != "data_absent":
            errors.append(_err("metric", "absence rules use data_absent"))
        spec.comparator = None
        spec.threshold = None
        spec.window = None
        spec.params = {}
        if spec.duration_seconds is None:
            spec.duration_seconds = s.target_stale_after_seconds
    elif spec.type == "anomaly":
        if spec.metric not in ANOMALY_METRICS:
            errors.append(_err("metric", f"anomaly rules support {sorted(ANOMALY_METRICS)}"))
        params = {**DEFAULT_ANOMALY_PARAMS, **(spec.params or {})}
        unknown = set(params) - set(DEFAULT_ANOMALY_PARAMS)
        if unknown:
            errors.append(_err("params", f"unknown keys {sorted(unknown)}"))
        try:
            bp, zt, cons = int(params["baseline_points"]), float(params["z_threshold"]), int(params["consecutive"])
        except (TypeError, ValueError):
            errors.append(_err("params", "must be numbers"))
            bp, zt, cons = 0, 0.0, 0
        if not 10 <= bp <= 1440:
            errors.append(_err("params.baseline_points", "must be between 10 and 1440"))
        if not 1 <= zt <= 10:
            errors.append(_err("params.z_threshold", "must be between 1 and 10"))
        if not 1 <= cons <= 20:
            errors.append(_err("params.consecutive", "must be between 1 and 20"))
        spec.params = {"baseline_points": bp, "z_threshold": zt, "consecutive": cons}
        spec.comparator = None
        spec.threshold = None
        spec.window = spec.window or "5m"
        if spec.window not in WINDOWS:
            errors.append(_err("window", "must be one of 1m, 5m, 15m"))
        if spec.duration_seconds is None:
            spec.duration_seconds = cons * eval_s
    else:
        errors.append(_err("type", "must be threshold, absence or anomaly"))

    if spec.duration_seconds is None:
        errors.append(_err("duration_seconds", "required"))
    elif not eval_s <= spec.duration_seconds <= 86400:
        errors.append(_err("duration_seconds", f"must be between {eval_s} and 86400"))
    if errors:
        raise ApiError(ErrorCode.VALIDATION_ERROR, details=errors)
    return spec


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "firing": {"acknowledged", "resolved"},
    "acknowledged": {"resolved", "firing"},  # acknowledged → firing only as a compensating undo
    "resolved": set(),
}


def check_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ApiError(ErrorCode.INVALID_TRANSITION, f"Cannot move an alert from {current} to {target}.")
