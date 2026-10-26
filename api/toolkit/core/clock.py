"""Injectable time source so time-dependent logic is testable (TEST_STRATEGY §2.1)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock:
    """Deterministic clock: ``sleep`` and ``advance`` move time without waiting."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
        self._mono = 1000.0

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._mono

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds


system_clock = SystemClock()


def utcnow() -> datetime:
    return datetime.now(UTC)
