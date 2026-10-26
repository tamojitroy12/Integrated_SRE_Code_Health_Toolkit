"""Durable job queue on PostgreSQL (DEC-003, NFR-REL-01, DATA_MODEL §2.4).

* enqueue happens in the same transaction as the business row it belongs to;
* workers claim with ``FOR UPDATE SKIP LOCKED`` so any number of workers can run;
* a claimed job holds a lease that the worker extends with heartbeats;
* a reaper requeues jobs whose lease expired (worker crash) until ``max_attempts``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from toolkit.core.config import get_settings
from toolkit.db.enums import TERMINAL_JOB_STATUSES
from toolkit.db.models import Job

# Called with (session, job, terminal_status) whenever a job reaches a terminal state
# outside its handler (reaper, cancel-before-start), so resource rows stay consistent.
TerminalHook = Callable[[Session, Job, str], None]
_terminal_hooks: dict[str, TerminalHook] = {}


def register_terminal_hook(job_type: str, hook: TerminalHook) -> None:
    _terminal_hooks[job_type] = hook


def run_terminal_hook(db: Session, job: Job, status: str) -> None:
    hook = _terminal_hooks.get(job.type)
    if hook is not None:
        hook(db, job, status)


def enqueue(
    db: Session,
    job_type: str,
    *,
    payload: dict[str, Any] | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    max_attempts: int | None = None,
) -> Job:
    job = Job(
        id=uuid.uuid4(),
        type=job_type,
        status="queued",
        payload=payload or {},
        resource_type=resource_type,
        resource_id=resource_id,
        created_by=created_by,
        attempts=0,
        max_attempts=max_attempts or get_settings().job_max_attempts,
    )
    db.add(job)
    db.flush()
    return job


def claim(db: Session, worker_id: str, now: datetime, lease_seconds: int, types: list[str] | None = None) -> Job | None:
    q = (
        select(Job)
        .where(Job.status == "queued", or_(Job.available_at.is_(None), Job.available_at <= now))
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if types:
        q = q.where(Job.type.in_(types))
    job = db.scalar(q)
    if job is None:
        return None
    job.status = "running"
    job.attempts += 1
    job.locked_by = worker_id
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.started_at = job.started_at or now
    job.error_code = None
    job.error_message = None
    db.flush()
    return job


def heartbeat(db: Session, job_id: uuid.UUID, worker_id: str, now: datetime, lease_seconds: int) -> bool:
    """Extend the lease. Returns False if the worker no longer owns the job."""
    result = db.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == "running", Job.locked_by == worker_id)
        .values(lease_expires_at=now + timedelta(seconds=lease_seconds))
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def set_stage(db: Session, job_id: uuid.UUID, stage: str) -> None:
    db.execute(update(Job).where(Job.id == job_id).values(stage=stage[:60]))


def is_cancel_requested(db: Session, job_id: uuid.UUID) -> bool:
    return bool(db.scalar(select(Job.cancel_requested).where(Job.id == job_id)))


def finish(
    db: Session,
    job: Job,
    status: str,
    now: datetime,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.finished_at = now
    job.locked_by = None
    job.lease_expires_at = None
    job.error_code = error_code
    job.error_message = error_message[:500] if error_message else None
    db.flush()


def retry_later(db: Session, job: Job, now: datetime, error_code: str, error_message: str) -> None:
    job.status = "queued"
    job.locked_by = None
    job.lease_expires_at = None
    job.available_at = now + timedelta(seconds=min(300, 15 * (2 ** max(0, job.attempts - 1))))
    job.error_code = error_code
    job.error_message = error_message[:500]
    db.flush()


def reap_expired(db: Session, now: datetime) -> int:
    """Requeue (or fail) running jobs whose lease expired. Returns the number reaped."""
    expired = db.scalars(
        select(Job).where(Job.status == "running", Job.lease_expires_at < now).with_for_update(skip_locked=True)
    ).all()
    for job in expired:
        if job.cancel_requested:
            finish(db, job, "cancelled", now, error_code="CANCELLED", error_message="Cancelled while worker was lost")
            run_terminal_hook(db, job, "cancelled")
        elif job.attempts < job.max_attempts:
            job.status = "queued"
            job.locked_by = None
            job.lease_expires_at = None
            job.available_at = now
            job.error_code = "INTERNAL_ERROR"
            job.error_message = "Worker lease expired; job requeued"
        else:
            finish(
                db,
                job,
                "failed",
                now,
                error_code="INTERNAL_ERROR",
                error_message=f"Worker lease expired after {job.attempts} attempts",
            )
            run_terminal_hook(db, job, "failed")
    db.flush()
    return len(expired)


def request_cancel(db: Session, job: Job, now: datetime) -> None:
    if job.status in TERMINAL_JOB_STATUSES:
        return
    if job.status == "queued":
        finish(db, job, "cancelled", now, error_code="CANCELLED", error_message="Cancelled before start")
        run_terminal_hook(db, job, "cancelled")
    else:
        job.cancel_requested = True
    db.flush()


def queue_depth(db: Session) -> dict[str, int]:
    rows = db.execute(select(Job.type, func.count()).where(Job.status == "queued").group_by(Job.type)).all()
    return {str(t): int(c) for t, c in rows}


def active_job_for(db: Session, resource_type: str, resource_id: uuid.UUID) -> Job | None:
    return db.scalar(
        select(Job)
        .where(
            and_(
                Job.resource_type == resource_type,
                Job.resource_id == resource_id,
                Job.status.in_(["queued", "running"]),
            )
        )
        .limit(1)
    )


def job_out(job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "type": job.type,
        "status": job.status,
        "stage": job.stage,
        "attempts": job.attempts,
        "error": {"code": job.error_code, "message": job.error_message}
        if job.error_code and job.status in ("failed", "partial", "cancelled")
        else None,
        "resource": {"type": job.resource_type, "id": str(job.resource_id)} if job.resource_id else None,
        "cancel_requested": job.cancel_requested,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
