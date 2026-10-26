"""Job execution: handler registry, heartbeats, cooperative cancel and finalization."""

from __future__ import annotations

import logging
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from toolkit.core.clock import Clock, system_clock
from toolkit.core.config import get_settings
from toolkit.core.errors import JobCancelled, JobError, JobErrorCode
from toolkit.core.logging import job_id_var
from toolkit.core.metrics import JOB_DURATION, JOBS
from toolkit.db.models import Job
from toolkit.db.session import session_scope
from toolkit.jobs import queue

log = logging.getLogger(__name__)


class LeaseLost(Exception):  # noqa: N818
    """Another worker took over this job after our lease expired."""


@dataclass
class JobContext:
    job_id: uuid.UUID
    job_type: str
    attempt: int
    payload: dict[str, Any]
    worker_id: str
    clock: Clock = field(default=system_clock)
    session_factory: Callable[[], Any] = session_scope
    lease_lost: threading.Event = field(default_factory=threading.Event)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.session_factory() as db:
            yield db

    def check_cancelled(self) -> None:
        if self.lease_lost.is_set():
            raise LeaseLost()
        with self.session() as db:
            if queue.is_cancel_requested(db, self.job_id):
                raise JobCancelled()

    def stage(self, name: str) -> None:
        """Record the current stage (shown in the UI) after checking for cancellation."""
        self.check_cancelled()
        with self.session() as db:
            queue.set_stage(db, self.job_id, name)
        log.info("job stage", extra={"stage": name, "job_type": self.job_type})


Handler = Callable[[JobContext], str]
HANDLERS: dict[str, Handler] = {}


def register(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return deco


class _Heartbeat(threading.Thread):
    def __init__(self, ctx: JobContext, lease_seconds: int) -> None:
        super().__init__(daemon=True, name=f"heartbeat-{ctx.job_id}")
        self.ctx = ctx
        self.lease = lease_seconds
        self.stop_event = threading.Event()

    def run(self) -> None:
        interval = max(5.0, self.lease / 3)
        while not self.stop_event.wait(interval):
            try:
                with self.ctx.session() as db:
                    owned = queue.heartbeat(db, self.ctx.job_id, self.ctx.worker_id, self.ctx.clock.now(), self.lease)
                if not owned:
                    self.ctx.lease_lost.set()
                    return
            except Exception:
                log.warning("heartbeat failed", exc_info=True)


def execute(
    job: Job,
    worker_id: str,
    *,
    clock: Clock = system_clock,
    session_factory: Callable[[], Any] = session_scope,
    heartbeat: bool = True,
) -> str:
    """Run the handler for a claimed job and record the terminal state. Returns the job status."""
    settings = get_settings()
    ctx = JobContext(job.id, job.type, job.attempts, dict(job.payload), worker_id, clock, session_factory)
    token = job_id_var.set(str(job.id))
    hb = _Heartbeat(ctx, settings.job_lease_seconds) if heartbeat else None
    if hb:
        hb.start()
    started = time.monotonic()
    status = "failed"
    try:
        try:
            handler = HANDLERS.get(job.type)
            if handler is None:
                raise JobError(JobErrorCode.INTERNAL_ERROR, f"no handler for job type {job.type}")
            status = handler(ctx)
            _finish(ctx, status)
        except LeaseLost:
            log.warning("lease lost; abandoning job")
            status = "abandoned"
        except JobCancelled:
            status = "cancelled"
            _finish(ctx, "cancelled", "CANCELLED", "Cancelled by user")
        except JobError as exc:
            status = _fail_or_retry(ctx, exc.code.value, exc.message, retryable=exc.retryable)
        except Exception as exc:
            log.error("job crashed", extra={"error": type(exc).__name__, "trace": traceback.format_exc()[-2000:]})
            status = _fail_or_retry(ctx, "INTERNAL_ERROR", f"{type(exc).__name__}: unexpected error", retryable=True)
    finally:
        if hb:
            hb.stop_event.set()
        JOB_DURATION.labels(job.type).observe(time.monotonic() - started)
        JOBS.labels(job.type, status).inc()
        job_id_var.reset(token)
    return status


def _finish(ctx: JobContext, status: str, code: str | None = None, message: str | None = None) -> None:
    with ctx.session() as db:
        job = db.get(Job, ctx.job_id, with_for_update=True)
        if job is None or job.locked_by != ctx.worker_id:
            return
        queue.finish(db, job, status, ctx.clock.now(), error_code=code, error_message=message)
        if status in ("failed", "cancelled"):
            queue.run_terminal_hook(db, job, status)


def _fail_or_retry(ctx: JobContext, code: str, message: str, *, retryable: bool) -> str:
    with ctx.session() as db:
        job = db.get(Job, ctx.job_id, with_for_update=True)
        if job is None or job.locked_by != ctx.worker_id:
            return "abandoned"
        if retryable and job.attempts < job.max_attempts:
            queue.retry_later(db, job, ctx.clock.now(), code, message)
            return "retrying"
        queue.finish(db, job, "failed", ctx.clock.now(), error_code=code, error_message=message)
        queue.run_terminal_hook(db, job, "failed")
        return "failed"
