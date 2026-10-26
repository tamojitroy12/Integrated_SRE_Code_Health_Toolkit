"""Daily retention job (DATA_MODEL §7, NFR-DATA-01). Every period is configurable."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.orm import Session

from toolkit.core.config import get_settings
from toolkit.db.models import (
    Alert,
    AuditLog,
    Evidence,
    Finding,
    FixProposal,
    Job,
    LoginAttempt,
    NotificationDelivery,
    Recommendation,
    RefreshSession,
    Scan,
    ValidationRun,
)

log = logging.getLogger(__name__)
_last_run: datetime | None = None


def run_retention_if_due(db: Session, now: datetime) -> dict[str, int] | None:
    global _last_run  # noqa: PLW0603 - per-process throttle; the job itself is idempotent
    if _last_run is not None and now - _last_run < timedelta(hours=24):
        return None
    _last_run = now
    return run_retention(db, now)


def _count(result: object) -> int:
    return int(getattr(result, "rowcount", 0) or 0)


def run_retention(db: Session, now: datetime) -> dict[str, int]:
    s = get_settings()

    def days(n: int) -> datetime:
        return now - timedelta(days=n)

    out: dict[str, int] = {}

    ranked = (
        select(
            Scan.id, func.row_number().over(partition_by=Scan.project_id, order_by=Scan.created_at.desc()).label("rn")
        )
        .where(Scan.status.in_(["succeeded", "partial", "failed", "cancelled"]))
        .subquery()
    )
    old_scans = select(ranked.c.id).where(ranked.c.rn > s.retention_scans_per_project)
    out["scans"] = _count(db.execute(delete(Scan).where(Scan.id.in_(old_scans))))

    out["findings"] = _count(
        db.execute(
            delete(Finding).where(
                Finding.status == "resolved", Finding.resolved_at < days(s.retention_resolved_findings_days)
            )
        )
    )
    resolved_long_ago = select(Finding.id).where(
        Finding.status == "resolved", Finding.resolved_at < days(s.retention_snippet_days)
    )
    out["snippets"] = _count(
        db.execute(delete(Evidence).where(Evidence.kind == "code_snippet", Evidence.finding_id.in_(resolved_long_ago)))
    )
    out["raw_output"] = _count(
        db.execute(
            update(Recommendation)
            .where(
                Recommendation.raw_output.is_not(None), Recommendation.created_at < days(s.retention_raw_output_days)
            )
            .values(raw_output=None)
        )
    )
    terminal = ["pr_opened", "rejected", "failed", "superseded"]
    out["output_tail"] = _count(
        db.execute(
            update(ValidationRun)
            .where(
                ValidationRun.output_tail.is_not(None), ValidationRun.started_at < days(s.retention_output_tail_days)
            )
            .values(output_tail=None)
        )
    )
    out["fix_proposals"] = _count(
        db.execute(
            delete(FixProposal).where(
                FixProposal.status.in_(terminal), FixProposal.updated_at < days(s.retention_fix_proposals_days)
            )
        )
    )
    out["alerts"] = _count(
        db.execute(delete(Alert).where(Alert.status == "resolved", Alert.resolved_at < days(s.retention_alerts_days)))
    )
    out["deliveries"] = _count(
        db.execute(
            delete(NotificationDelivery).where(NotificationDelivery.created_at < days(s.retention_deliveries_days))
        )
    )
    out["jobs"] = _count(
        db.execute(
            delete(Job).where(
                Job.status.in_(["succeeded", "partial", "failed", "cancelled"]),
                Job.finished_at < days(s.retention_jobs_days),
            )
        )
    )
    out["sessions"] = _count(
        db.execute(delete(RefreshSession).where(and_(RefreshSession.expires_at < days(s.retention_sessions_days))))
    )
    out["login_attempts"] = _count(db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < days(1))))
    out["audit_log"] = _count(db.execute(delete(AuditLog).where(AuditLog.created_at < days(s.retention_audit_days))))
    log.info("retention applied", extra={"deleted": out})
    return out
