"""Shared schema primitives."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, PlainSerializer


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, PlainSerializer(_iso, return_type=str, when_used="json")]


class StrictModel(BaseModel):
    """Request bodies: unknown fields are rejected with 422 (API_SPEC §1)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class JobRef(Out):
    id: Any
    type: str
    status: str
