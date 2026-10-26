"""Append-only audit log writer (FR-AUTH-04, SECURITY §11)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from toolkit.core.logging import redact_value
from toolkit.db.models import AuditLog


def record(
    db: Session,
    action: str,
    *,
    actor_id: uuid.UUID | None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            meta=redact_value(metadata or {}),
            ip=ip,
        )
    )
