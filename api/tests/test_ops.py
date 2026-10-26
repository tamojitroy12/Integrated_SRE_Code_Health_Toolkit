"""Operational endpoints, headers, retention, scheduler, CLI and worker loops (NFR-REL-03, NFR-DATA-01, FR-DEP-08)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.conftest import Users, set_env
from tests.fakes import FakePrometheus
from toolkit.core.clock import FakeClock
from toolkit.db.models import Alert, AuditLog, Job, LoginAttempt, Project, Repository, Scan
from toolkit.monitoring import prometheus


@pytest.mark.nt("REL-03")
def test_health_ready_and_headers(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = client.get("/health")
    assert r.json() == {"status": "ok"}
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Request-ID"]
    assert client.get("/health", headers={"X-Request-ID": "abcdef12-3456"}).headers["X-Request-ID"] == "abcdef12-3456"
    fp = FakePrometheus()
    monkeypatch.setattr(prometheus, "DEFAULT_TRANSPORT", fp.transport)
    ready = client.get("/ready").json()
    assert ready["status"] == "ok" and ready["checks"]["database"] == "ok" and ready["checks"]["prometheus"] == "ok"
    fp.down = True
    assert client.get("/ready").json()["checks"]["prometheus"] == "degraded"


@pytest.mark.nt("OBS-02")
def test_metrics_endpoint_is_internal(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = client.get("/metrics")  # TestClient host counts as internal
    assert r.status_code == 200 and "toolkit_http_requests_total" in r.text and "toolkit_queue_depth" in r.text
    set_env(monkeypatch, metrics_scrape_token="scrape-secret")
    assert client.get("/metrics").status_code == 403
    assert client.get("/metrics", headers={"Authorization": "Bearer scrape-secret"}).status_code == 200


@pytest.mark.nt("MNT-02")
def test_openapi_generated_and_contains_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for p in (
        "/api/v1/auth/login",
        "/api/v1/projects/{project_id}/overview",
        "/api/v1/projects/{project_id}/scans",
        "/api/v1/fix-proposals/{proposal_id}/approve",
        "/api/v1/alerts/{alert_id}/acknowledge",
        "/api/v1/findings/{finding_id}/recommendations",
        "/api/v1/notification-channels/{channel_id}/test",
    ):
        assert p in paths, p
    assert "/metrics" not in paths


def test_unknown_route_and_method(client: TestClient, users: Users) -> None:
    r = client.get("/api/v1/nope", headers=users.headers("viewer"))
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.nt("DATA-01")
def test_retention_deletes_old_rows(db: Session, clock: FakeClock, users: Users) -> None:
    from toolkit.retention import run_retention

    p = Project(name=f"ret-{uuid.uuid4().hex[:6]}")
    db.add(p)
    db.flush()
    old = clock.now() - timedelta(days=400)
    db.add(
        Alert(
            project_id=p.id,
            rule_name="r",
            status="resolved",
            severity="low",
            first_seen_at=old,
            last_seen_at=old,
            resolved_at=old,
            evidence={},
        )
    )
    db.add(
        Alert(
            project_id=p.id,
            rule_name="r",
            status="firing",
            severity="low",
            first_seen_at=old,
            last_seen_at=old,
            evidence={},
        )
    )
    db.add(LoginAttempt(email="x", ip="1", success=False, created_at=old))
    db.add(AuditLog(action="old", created_at=old))
    db.add(Job(type="scan", status="succeeded", finished_at=old))
    db.flush()
    out = run_retention(db, clock.now())
    assert out["alerts"] == 1 and out["login_attempts"] >= 1 and out["audit_log"] >= 1 and out["jobs"] >= 1
    assert db.scalar(select(func.count()).select_from(Alert).where(Alert.project_id == p.id)) == 1


def test_audit_log_rows_are_immutable(db: Session) -> None:
    from sqlalchemy.exc import DBAPIError

    row = AuditLog(action="x")
    db.add(row)
    db.flush()
    row.action = "tampered"
    with pytest.raises(DBAPIError):
        db.flush()
    db.rollback()


@pytest.mark.at("FR-DEP-08")
def test_scheduled_scans_use_the_manual_path(db: Session, clock: FakeClock, monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.scheduler import enqueue_scheduled_scans

    p = Project(name=f"sched-{uuid.uuid4().hex[:6]}")
    db.add(p)
    db.flush()
    db.add(
        Repository(
            project_id=p.id,
            owner="o",
            name="r",
            url="https://github.com/o/r",
            default_branch="main",
            ecosystems=[],
            manifests=[],
        )
    )
    db.flush()
    assert enqueue_scheduled_scans(db, clock.now()) == 0  # disabled by default
    set_env(monkeypatch, scheduled_scan_interval_hours="24")
    assert enqueue_scheduled_scans(db, clock.now()) >= 1
    scan = db.scalar(select(Scan).where(Scan.project_id == p.id))
    assert scan is not None and scan.trigger == "scheduled" and scan.job_id is not None
    assert enqueue_scheduled_scans(db, clock.now()) == 0  # one active scan per project


@pytest.mark.at("FR-PRJ-06")
def test_cli_seed_demo_and_create_user(engine: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    from toolkit import cli
    from toolkit.db.session import get_engine, get_session_factory

    get_engine.cache_clear()
    get_session_factory.cache_clear()
    name = f"demo-{uuid.uuid4().hex[:6]}"
    try:
        assert cli.main(["seed-demo", "--name", name]) == 0
        assert cli.main(["seed-demo", "--name", name]) == 0  # idempotent
        email = f"cli-{uuid.uuid4().hex[:6]}@example.edu"
        assert cli.main(["create-user", email, "--role", "maintainer", "--password", "long-enough-pw"]) == 0
        assert cli.main(["create-user", email, "--password", "long-enough-pw"]) == 1
        assert cli.main(["create-user", "x@example.edu", "--password", "short"]) == 2
    finally:
        from sqlalchemy import delete

        from toolkit.db.models import User
        from toolkit.db.session import session_scope

        with session_scope() as s:
            pid = s.scalar(select(Project.id).where(Project.name == name))
            if pid:
                s.execute(delete(Project).where(Project.id == pid))
            s.execute(delete(User).where(User.email.like("cli-%@example.edu")))


def test_worker_loops_run_once(engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from toolkit.db.session import get_engine, get_session_factory
    from toolkit.worker.main import MONITOR_LOCK, Worker, advisory_lock

    get_engine.cache_clear()
    get_session_factory.cache_clear()
    w = Worker()
    w.reap()
    w.deliver()
    w.scheduler_tick()
    with advisory_lock(MONITOR_LOCK) as first, advisory_lock(MONITOR_LOCK) as second:
        assert first is True and second is False  # only one leader at a time
