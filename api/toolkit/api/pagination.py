"""Opaque keyset cursors (API_SPEC §1): ``?limit=1..100&cursor=<opaque>``."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from toolkit.core.errors import validation_error


def encode_cursor(values: list[Any]) -> str:
    def enc(v: Any) -> Any:
        if isinstance(v, datetime):
            return {"t": v.isoformat()}
        if isinstance(v, uuid.UUID):
            return {"u": str(v)}
        return v

    raw = json.dumps([enc(v) for v in values], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, arity: int) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(data, list) or len(data) != arity:
            raise ValueError
        out: list[Any] = []
        for v in data:
            if isinstance(v, dict) and "t" in v:
                out.append(datetime.fromisoformat(v["t"]))
            elif isinstance(v, dict) and "u" in v:
                out.append(uuid.UUID(v["u"]))
            else:
                out.append(v)
        return out
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise validation_error("cursor", "invalid cursor") from exc
