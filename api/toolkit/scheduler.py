"""Scheduled rescans (FR-DEP-08). Uses the same code path as manual scans."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError
from toolkit.db.models import Project, Repository, Scan

log = logging.getLogger(__name__)


def enqueue_scheduled_scans(db: Session, now: datetime) -> int:
    hours = get_settings().scheduled_scan_interval_hours
    if hours <= 0:
        return 0
    from toolkit.api.routes.scans import create_scan

    due_before = now - timedelta(hours=hours)
    latest = select(Scan.project_id, func.max(Scan.created_at).label("last")).group_by(Scan.project_id).subquery()
    rows = db.execute(
        select(Project.id)
        .join(Repository, Repository.project_id == Project.id)
        .outerjoin(latest, latest.c.project_id == Project.id)
        .where(Project.archived_at.is_(None), (latest.c.last.is_(None)) | (latest.c.last < due_before))
    ).all()
    created = 0
    for (pid,) in rows:
        try:
            with db.begin_nested():
                create_scan(db, pid, None, None, None, trigger="scheduled")
            created += 1
        except ApiError:
            continue  # a scan is already active for this project
    if created:
        log.info("scheduled scans enqueued", extra={"count": created})
    return created
