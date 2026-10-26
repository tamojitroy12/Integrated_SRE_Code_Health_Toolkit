"""Reliability metrics (TRD §6.1, FR-MON-03) and anomaly statistics (TRD §6.2, FR-MON-05)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class WindowSli:
    total: float
    errors: float
    error_ratio: float | None
    availability: float | None

    @property
    def no_traffic(self) -> bool:
        return self.error_ratio is None


def counter_increase(samples: Sequence[float]) -> float:
    """Increase of a monotonic counter over a window, handling counter resets like PromQL."""
    if len(samples) < 2:
        return 0.0
    total = 0.0
    prev = samples[0]
    for cur in samples[1:]:
        total += cur if cur < prev else cur - prev
        prev = cur
    return total


def window_sli(total_counter: Sequence[float], error_counter: Sequence[float]) -> WindowSli:
    """ErrorRatio_W = R_5xx / R_total, SLI = 1 - ErrorRatio. R_total = 0 ⇒ undefined."""
    total = counter_increase(total_counter)
    errors = counter_increase(error_counter)
    if total <= 0:
        return WindowSli(total, errors, None, None)
    ratio = min(1.0, errors / total)
    return WindowSli(total, errors, ratio, 1.0 - ratio)


@dataclass(frozen=True)
class ZScore:
    z: float
    mean: float
    stddev: float


def zscore(history: Sequence[float], current: float, epsilon: float = 1e-9) -> ZScore | None:
    """z_t = (x_t - mean_t) / max(stddev_t, eps) over the B samples before t (sample stddev, B-1)."""
    clean = [x for x in history if not math.isnan(x)]
    if len(clean) < 2 or math.isnan(current):
        return None
    mean = sum(clean) / len(clean)
    var = sum((x - mean) ** 2 for x in clean) / (len(clean) - 1)
    sd = math.sqrt(var)
    # Relative floor so near-constant rates do not produce absurd z-scores (TRD §6.2 note).
    floor = max(epsilon, abs(mean) * 0.01)
    return ZScore((current - mean) / max(sd, floor), mean, sd)


def required_consecutive(duration_seconds: int, eval_interval_seconds: int) -> int:
    """N = ceil(duration / Δ_eval), at least 1."""
    return max(1, math.ceil(duration_seconds / eval_interval_seconds))


def detection_bound(t_ingest: float, duration_seconds: int, eval_interval_seconds: int) -> float:
    """T_detect ≤ T_ingest + N · Δ_eval (SM-03, NFR-PERF-04)."""
    return t_ingest + required_consecutive(duration_seconds, eval_interval_seconds) * eval_interval_seconds
