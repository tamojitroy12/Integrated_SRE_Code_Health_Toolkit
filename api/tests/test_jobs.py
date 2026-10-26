"""Durable job queue (NFR-REL-01, DEC-003): claim, lease, reaper, retries, cancel, concurrency."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from toolkit.core.clock import FakeClock
from toolkit.core.errors import JobError, JobErrorCode
from toolkit.db.models import Job
from toolkit.jobs import queue, runner


@pytest.mark.nt("REL-01")
def test_lease_expiry_requeues_then_fails(db: Session, clock: FakeClock) -> None:
    job = queue.enqueue(db, "scan", payload={"x": 1}, max_attempts=3)
    for attempt in range(1, 4):
        claimed = queue.claim(db, "w1", clock.now(), lease_seconds=60)
        assert claimed is not None and claimed.id == job.id and claimed.attempts == attempt
        assert queue.claim(db, "w2", clock.now(), lease_seconds=60) is None  # leased
        clock.advance(61)  # worker "crashed": no heartbeat
        assert queue.reap_expired(db, clock.now()) == 1
    db.refresh(job)
    assert job.status == "failed" and "lease expired" in (job.error_message or "")


def test_heartbeat_extends_lease_and_ownership(db: Session, clock: FakeClock) -> None:
    queue.enqueue(db, "scan")
    job = queue.claim(db, "w1", clock.now(), 60)
    assert job is not None
    clock.advance(50)
    assert queue.heartbeat(db, job.id, "w1", clock.now(), 60)
    assert not queue.heartbeat(db, job.id, "intruder", clock.now(), 60)
    clock.advance(50)
    assert queue.reap_expired(db, clock.now()) == 0


def test_cancel_queued_and_running(db: Session, clock: FakeClock) -> None:
    q = queue.enqueue(db, "recommendation")
    queue.request_cancel(db, q, clock.now())
    assert q.status == "cancelled"
    r = queue.enqueue(db, "recommendation")
    claimed = queue.claim(db, "w", clock.now(), 60)
    assert claimed is not None and claimed.id == r.id
    queue.request_cancel(db, claimed, clock.now())
    assert claimed.status == "running" and claimed.cancel_requested
    assert queue.is_cancel_requested(db, r.id)


def _ctx_factory(db: Session) -> Any:
    from contextlib import contextmanager

    @contextmanager
    def factory():  # type: ignore[no-untyped-def]
        yield db
        db.flush()

    return factory


def test_runner_outcomes(db: Session, clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def ok(ctx: runner.JobContext) -> str:
        ctx.stage("working")
        calls.append("ok")
        return "succeeded"

    def boom(ctx: runner.JobContext) -> str:
        raise RuntimeError("unexpected")

    def bad(ctx: runner.JobContext) -> str:
        raise JobError(JobErrorCode.PLAN_INVALID, "nope")

    monkeypatch.setitem(runner.HANDLERS, "scan", ok)
    monkeypatch.setitem(runner.HANDLERS, "recommendation", boom)
    monkeypatch.setitem(runner.HANDLERS, "fix_proposal", bad)
    sf = _ctx_factory(db)
    for jt in ("scan", "recommendation", "fix_proposal"):
        queue.enqueue(db, jt, max_attempts=2)
    statuses = {}
    for _ in range(3):
        job = queue.claim(db, "w", clock.now(), 60)
        assert job is not None
        statuses[job.type] = runner.execute(job, "w", clock=clock, session_factory=sf, heartbeat=False)
    assert statuses == {"scan": "succeeded", "recommendation": "retrying", "fix_proposal": "failed"}
    failed = db.query(Job).filter(Job.type == "fix_proposal").one()
    assert failed.error_code == "PLAN_INVALID" and failed.status == "failed"
    retry = db.query(Job).filter(Job.type == "recommendation").one()
    assert retry.status == "queued" and retry.available_at is not None
    assert queue.claim(db, "w", clock.now(), 60) is None  # backoff not yet elapsed
    clock.advance(400)
    again = queue.claim(db, "w", clock.now(), 60)
    assert again is not None and again.attempts == 2
    assert runner.execute(again, "w", clock=clock, session_factory=sf, heartbeat=False) == "failed"
    assert calls == ["ok"]


@pytest.mark.nt("REL-01")
@pytest.mark.nt("CAP-01")
def test_skip_locked_two_workers_never_claim_the_same_job(engine: Any, clock: FakeClock) -> None:
    """Uses real committed rows and two connections (outside the per-test rollback)."""
    marker = f"concurrency-{uuid.uuid4()}"
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        for _ in range(4):
            queue.enqueue(s, "scan", payload={"marker": marker})
        s.commit()
    a, b = factory(), factory()
    try:
        ja = queue.claim(a, "A", clock.now(), 60)
        jb = queue.claim(b, "B", clock.now(), 60)  # first row is locked by A → B skips it
        assert ja is not None and jb is not None and ja.id != jb.id
        a.commit()
        b.commit()
    finally:
        a.close()
        b.close()
        with factory() as s:
            s.execute(delete(Job).where(Job.payload["marker"].astext == marker))
            s.commit()
