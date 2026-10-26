"""Alert rules, evaluation engine, lifecycle and notifications (FR-ALR-01..08, FR-MON-04, NFR-REL-05)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.conftest import Users, set_env
from tests.fakes import FakePrometheus, WebhookReceiver
from toolkit.alerting.engine import evaluate_once
from toolkit.alerting.notify import deliver_pending
from toolkit.core.clock import FakeClock
from toolkit.db.models import Alert, AlertRuleState, MonitoringTarget, NotificationDelivery
from toolkit.monitoring import prometheus
from toolkit.monitoring.prometheus import PrometheusClient

API = "/api/v1"


@pytest.fixture
def fake_prom(monkeypatch: pytest.MonkeyPatch) -> FakePrometheus:
    fp = FakePrometheus()
    monkeypatch.setattr(prometheus, "DEFAULT_TRANSPORT", fp.transport)
    return fp


def make_rule(
    client: TestClient, users: Users, project: dict[str, Any], target: dict[str, Any], **over: Any
) -> dict[str, Any]:
    body = {
        "target_id": target["id"],
        "name": "High 5xx ratio",
        "type": "threshold",
        "metric": "error_ratio",
        "comparator": "gt",
        "threshold": 0.05,
        "window": "5m",
        "duration_seconds": 90,
        "resolve_after": 2,
        "severity": "high",
        "guidance": "Check recent deployments.",
    }
    body.update(over)
    r = client.post(f"{API}/projects/{project['id']}/alert-rules", json=body, headers=users.headers("maintainer"))
    assert r.status_code == 201, r.text
    return dict(r.json())


def seen_now(fake: FakePrometheus, clock: FakeClock, service: str = "demo-api") -> None:
    fake.on(
        "max by (service_name",
        lambda q: [
            {"metric": {"service_name": service}, "value": [clock.now().timestamp(), str(clock.now().timestamp())]}
        ],
    )


@pytest.mark.at("FR-ALR-01")
@pytest.mark.parametrize(
    "over,field",
    [
        ({"metric": "nonsense"}, "metric"),
        ({"duration_seconds": 0}, "duration_seconds"),
        ({"duration_seconds": 10}, "duration_seconds"),
        ({"threshold": 1.5}, "threshold"),
        ({"metric": "latency_p95", "threshold": 0}, "threshold"),
        ({"window": "7m"}, "window"),
        ({"type": "absence", "metric": "error_ratio"}, "metric"),
        ({"type": "anomaly", "metric": "request_rate", "params": {"z_threshold": 50}}, "params.z_threshold"),
    ],
)
def test_rule_validation(
    client: TestClient, users: Users, project: dict[str, Any], target: dict[str, Any], over: dict[str, Any], field: str
) -> None:
    body = {
        "target_id": target["id"],
        "name": "r",
        "type": "threshold",
        "metric": "error_ratio",
        "comparator": "gt",
        "threshold": 0.05,
        "window": "5m",
        "duration_seconds": 120,
        "severity": "high",
        **over,
    }
    r = client.post(f"{API}/projects/{project['id']}/alert-rules", json=body, headers=users.headers("maintainer"))
    assert r.status_code == 422
    fields = [d["field"] for d in r.json()["error"]["details"]]
    assert any(f.startswith(field) for f in fields), fields


@pytest.mark.at("FR-ALR-01")
def test_rule_crud(client: TestClient, users: Users, project: dict[str, Any], target: dict[str, Any]) -> None:
    rule = make_rule(client, users, project, target)
    h = users.headers("maintainer")
    r = client.patch(f"{API}/alert-rules/{rule['id']}", json={"threshold": 0.1, "enabled": False}, headers=h)
    assert r.status_code == 200 and r.json()["threshold"] == 0.1 and r.json()["enabled"] is False
    r = client.patch(f"{API}/alert-rules/{rule['id']}", json={"type": "absence"}, headers=h)
    assert r.status_code == 422  # type is immutable (unknown field)
    assert client.delete(f"{API}/alert-rules/{rule['id']}", headers=h).status_code == 204
    other = client.post(f"{API}/projects", json={"name": "other"}, headers=h).json()
    r = client.post(
        f"{API}/projects/{other['id']}/alert-rules",
        json={"target_id": target["id"], "name": "x", "type": "absence", "metric": "data_absent", "severity": "low"},
        headers=h,
    )
    assert r.status_code == 422  # target from another project


@pytest.mark.at("FR-ALR-02")
@pytest.mark.at("FR-ALR-03")
@pytest.mark.at("FR-ALR-04")
@pytest.mark.at("FR-MON-04")
def test_threshold_fires_after_n_dedupes_and_auto_resolves(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
) -> None:
    rule = make_rule(client, users, project, target)  # 90 s / 30 s → N = 3
    prom = PrometheusClient()
    seen_now(fake_prom, clock)
    fake_prom.on("http_response_status_code", 0.12)
    for i in range(2):
        assert evaluate_once(db, prom, clock.now()).get("pending") == 1, i
        clock.advance(30)
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
    assert evaluate_once(db, prom, clock.now()).get("fired") == 1
    alert = db.scalar(select(Alert))
    assert alert is not None and alert.status == "firing"
    for key in ("query", "observed_value", "threshold", "window", "guidance"):
        assert alert.evidence[key] not in (None, ""), key
    assert alert.evidence["observed_value"] == 0.12 and alert.evidence["threshold"] == 0.05
    # Repeated breaches update the open alert, never create a second one (FR-ALR-03).
    clock.advance(30)
    assert evaluate_once(db, prom, clock.now()).get("updated") == 1
    db.refresh(alert)
    assert alert.occurrence_count == 2 and db.scalar(select(func.count()).select_from(Alert)) == 1
    # Condition clears for resolve_after (=2) evaluations → auto-resolve.
    fake_prom.on("http_response_status_code", 0.0)
    clock.advance(30)
    evaluate_once(db, prom, clock.now())
    db.refresh(alert)
    assert alert.status == "firing"
    clock.advance(30)
    assert evaluate_once(db, prom, clock.now()).get("resolved") == 1
    db.refresh(alert)
    assert alert.status == "resolved" and alert.resolved_by is None
    # A new breach after resolution creates a new alert.
    fake_prom.on("http_response_status_code", 0.2)
    for _ in range(3):
        clock.advance(30)
        evaluate_once(db, prom, clock.now())
    assert db.scalar(select(func.count()).select_from(Alert)) == 2
    assert rule["id"]


@pytest.mark.at("FR-ALR-02")
def test_no_traffic_is_not_a_breach_and_state_is_durable(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
) -> None:
    rule = make_rule(client, users, project, target)
    prom = PrometheusClient()
    seen_now(fake_prom, clock)
    fake_prom.on("http_response_status_code", 0.12)
    evaluate_once(db, prom, clock.now())
    state = db.get(AlertRuleState, rule["id"])
    assert state is not None and state.consecutive_breaches == 1 and state.breach_since is not None
    fake_prom.on("http_response_status_code", float("nan"))
    clock.advance(30)
    evaluate_once(db, prom, clock.now())
    db.refresh(state)
    assert state.consecutive_breaches == 0 and state.last_outcome == "no traffic"


@pytest.mark.nt("REL-05")
def test_prometheus_down_changes_nothing(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
) -> None:
    make_rule(client, users, project, target, duration_seconds=30)
    prom = PrometheusClient()
    seen_now(fake_prom, clock)
    fake_prom.on("http_response_status_code", 0.5)
    evaluate_once(db, prom, clock.now())
    alert = db.scalar(select(Alert))
    assert alert is not None and alert.status == "firing"
    fake_prom.down = True
    for _ in range(5):
        clock.advance(30)
        assert evaluate_once(db, prom, clock.now()) == {"evaluation_error": 1}
    db.refresh(alert)
    assert alert.status == "firing"
    assert db.get(MonitoringTarget, target["id"]).status == "receiving"  # type: ignore[union-attr]


@pytest.mark.at("FR-ALR-08")
def test_absence_rule_fires_when_data_stops_and_resolves_on_restart(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
) -> None:
    make_rule(
        client,
        users,
        project,
        target,
        name="No data",
        type="absence",
        metric="data_absent",
        duration_seconds=300,
        resolve_after=1,
    )
    prom = PrometheusClient()
    # Never-seen target: absence is not evaluated (no noise for "waiting" targets).
    fake_prom.on("absent_over_time", 1)
    evaluate_once(db, prom, clock.now())
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
    seen_now(fake_prom, clock)
    fake_prom.on("absent_over_time", [])
    evaluate_once(db, prom, clock.now())
    fake_prom.rules = [r for r in fake_prom.rules if r[0]("max by (service_name") is False]
    fake_prom.on("absent_over_time", 1)
    clock.advance(330)
    evaluate_once(db, prom, clock.now())
    alert = db.scalar(select(Alert))
    assert alert is not None and alert.status == "firing" and alert.evidence["query_name"] == "data_absent"
    assert db.get(MonitoringTarget, target["id"]).status == "stale"  # type: ignore[union-attr]
    seen_now(fake_prom, clock)
    fake_prom.on("absent_over_time", [])
    clock.advance(30)
    evaluate_once(db, prom, clock.now())
    db.refresh(alert)
    assert alert.status == "resolved"


@pytest.mark.at("FR-MON-05")
def test_anomaly_rule(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
) -> None:
    make_rule(
        client,
        users,
        project,
        target,
        name="Rate anomaly",
        type="anomaly",
        metric="request_rate",
        params={"baseline_points": 20, "z_threshold": 3, "consecutive": 2},
    )
    prom = PrometheusClient()
    seen_now(fake_prom, clock)
    baseline = [10.0, 10.2, 9.8, 10.1, 9.9] * 4
    fake_prom.on("sum(rate(", [*baseline, 10.0])
    evaluate_once(db, prom, clock.now())
    assert db.scalar(select(func.count()).select_from(Alert)) == 0
    fake_prom.on("sum(rate(", [*baseline, 30.0])
    evaluate_once(db, prom, clock.now())
    clock.advance(30)
    evaluate_once(db, prom, clock.now())
    alert = db.scalar(select(Alert))
    assert alert is not None and alert.evidence["z_score"] > 3


def _fire(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
) -> Alert:
    make_rule(client, users, project, target, duration_seconds=30)
    seen_now(fake_prom, clock)
    fake_prom.on("http_response_status_code", 0.5)
    evaluate_once(db, PrometheusClient(), clock.now())
    db.commit()
    alert = db.scalar(select(Alert))
    assert alert is not None
    return alert


@pytest.mark.at("FR-ALR-02")
@pytest.mark.at("FR-DSH-04")
def test_alert_lifecycle_api(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
) -> None:
    alert = _fire(db, client, users, project, target, fake_prom, clock)
    h = users.headers("maintainer")
    lst = client.get(
        f"{API}/alerts?project_id={project['id']}&status=firing&status=acknowledged", headers=users.headers("viewer")
    )
    assert lst.status_code == 200 and lst.json()["items"][0]["target"]["service_name"] == "demo-api"
    assert client.get(f"{API}/alerts?project_id={uuid_str()}", headers=h).json()["items"] == []
    assert client.get(f"{API}/alerts?status=bogus", headers=h).status_code == 422
    r = client.post(f"{API}/alerts/{alert.id}/acknowledge", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "acknowledged"
    assert r.json()["acknowledged_by"]["display_name"] == "Maintainer"
    assert client.post(f"{API}/alerts/{alert.id}/acknowledge", headers=h).status_code == 409
    assert client.post(f"{API}/alerts/{alert.id}/unacknowledge", headers=h).json()["status"] == "firing"
    r = client.post(f"{API}/alerts/{alert.id}/resolve", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    r = client.post(f"{API}/alerts/{alert.id}/acknowledge", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    detail = client.get(f"{API}/alerts/{alert.id}", headers=users.headers("viewer")).json()
    assert detail["evidence"]["guidance"] == "Check recent deployments."


def uuid_str() -> str:
    import uuid

    return str(uuid.uuid4())


@pytest.mark.at("FR-ALR-05")
@pytest.mark.at("FR-ALR-06")
def test_webhook_delivery_and_cooldown(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_env(monkeypatch, allow_private_webhooks="true")
    with WebhookReceiver() as hook:
        r = client.post(
            f"{API}/notification-channels",
            json={"type": "webhook", "name": "ops", "config": {"url": hook.url}},
            headers=users.headers("admin"),
        )
        assert r.status_code == 201 and r.json()["config"] == {
            "host": "127.0.0.1",
            "port": hook.server.server_address[1],
        }
        assert "/hook" not in r.text
        alert = _fire(db, client, users, project, target, fake_prom, clock)
        assert deliver_pending(db, clock.now()) == 1
        assert hook.received[0]["json"]["event"] == "firing"
        assert hook.received[0]["json"]["alert_id"] == str(alert.id)
        # Resolve and re-fire within the cooldown: the second firing is suppressed and logged.
        client.post(f"{API}/alerts/{alert.id}/resolve", headers=users.headers("maintainer"))
        deliver_pending(db, clock.now())
        assert hook.received[1]["json"]["event"] == "resolved"
        clock.advance(30)
        evaluate_once(db, PrometheusClient(), clock.now())
        statuses = [
            d.status for d in db.scalars(select(NotificationDelivery).order_by(NotificationDelivery.created_at))
        ]
        assert statuses[-1] == "suppressed"
        dr = client.get(f"{API}/alerts/{alert.id}/deliveries", headers=users.headers("viewer"))
        assert dr.status_code == 200, dr.text
        deliveries = dr.json()
        assert deliveries[0]["status"] == "delivered" and deliveries[0]["channel_name"] is None


@pytest.mark.at("FR-ALR-05")
def test_failed_delivery_retries_then_fails(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    target: dict[str, Any],
    fake_prom: FakePrometheus,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_env(monkeypatch, allow_private_webhooks="true")
    with WebhookReceiver(status=500) as hook:
        client.post(
            f"{API}/notification-channels",
            json={"type": "webhook", "name": "down", "config": {"url": hook.url}},
            headers=users.headers("admin"),
        )
        alert = _fire(db, client, users, project, target, fake_prom, clock)
        for _ in range(3):
            deliver_pending(db, clock.now())
            clock.advance(600)
        d = db.scalar(select(NotificationDelivery))
        assert d is not None and d.status == "failed" and d.attempts == 3 and d.error == "HTTP 500"
        assert db.get(Alert, alert.id).status == "firing"  # type: ignore[union-attr]


@pytest.mark.nt("SEC-09")
def test_channel_validation_and_test_endpoint(
    client: TestClient, users: Users, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = users.headers("admin")
    for url in ("http://hooks.example.com/x", "https://127.0.0.1/x", "https://u:p@hooks.example.com/x"):
        r = client.post(
            f"{API}/notification-channels", json={"type": "webhook", "name": "x", "config": {"url": url}}, headers=h
        )
        assert r.status_code == 422, url
    r = client.post(
        f"{API}/notification-channels",
        json={"type": "email", "name": "x", "config": {"url": "https://a.example.com"}},
        headers=h,
    )
    assert r.status_code == 422
    set_env(monkeypatch, allow_private_webhooks="true")
    with WebhookReceiver() as hook:
        ch = client.post(
            f"{API}/notification-channels",
            json={"type": "webhook", "name": "t", "config": {"url": hook.url}},
            headers=h,
        ).json()
        r = client.post(f"{API}/notification-channels/{ch['id']}/test", headers=h)
        assert r.status_code == 200 and r.json()["status"] == "delivered"
        assert hook.received[0]["json"]["event"] == "test"
        assert client.post(f"{API}/notification-channels/{ch['id']}/test", headers=h).status_code == 429
        assert client.get(f"{API}/notification-channels", headers=users.headers("maintainer")).status_code == 200
        assert client.delete(f"{API}/notification-channels/{ch['id']}", headers=h).status_code == 204
