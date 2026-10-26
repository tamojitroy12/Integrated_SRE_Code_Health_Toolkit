"""Monitoring: query templates, SLI math, z-score, charts, target status (FR-MON-02..05, FR-PRJ-04)."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import Users
from tests.fakes import FakePrometheus
from toolkit.alerting.engine import update_target_statuses
from toolkit.core.clock import FakeClock
from toolkit.db.models import MonitoringTarget
from toolkit.monitoring import prometheus
from toolkit.monitoring import queries as Q
from toolkit.monitoring.prometheus import PrometheusClient
from toolkit.monitoring.sli import counter_increase, detection_bound, required_consecutive, window_sli, zscore

API = "/api/v1"


@pytest.fixture
def fake_prom(monkeypatch: pytest.MonkeyPatch) -> FakePrometheus:
    fp = FakePrometheus()
    monkeypatch.setattr(prometheus, "DEFAULT_TRANSPORT", fp.transport)
    return fp


def test_query_templates_are_parameter_safe() -> None:
    sel = Q.Selector("demo-api", "dev")
    q = Q.error_ratio(sel, "5m")
    assert 'service_name="demo-api"' in q and 'http_response_status_code=~"5.."' in q
    assert 'deployment_environment_name=~"dev|"' in q
    for bad in ('x"}) or vector(1', "a b", "", "x" * 101):
        with pytest.raises(Q.InvalidQueryParamError):
            Q.Selector(bad)
    with pytest.raises(Q.InvalidQueryParamError):
        Q.request_rate(sel, "5m])or(vector(1)")
    with pytest.raises(Q.InvalidQueryParamError):
        Q.metric_query("drop_table", sel, "5m")
    assert Q.seconds_to_promql(300) == "5m" and Q.seconds_to_promql(7200) == "2h" and Q.seconds_to_promql(45) == "45s"


@pytest.mark.parametrize(("service", "env"), [("demo-app", "dev-eu-1"), ("svc.v2:api_x", "prod")])
def test_regex_matchers_use_only_valid_promql_escapes(service: str, env: str) -> None:
    # PromQL string literals accept Go escapes only: "\-" (Python re.escape) is a parse error.
    queries = [Q.error_ratio(Q.Selector(service, env), "5m"), Q.last_sample_batch([service, "other"])]
    for q in queries:
        assert "\\" not in q.replace("\\\\", ""), q
    assert Q.regex_literal("svc.v2") == "svc\\\\.v2"
    assert Q.regex_literal("demo-app") == "demo-app"
    sel = Q.Selector(service, env)
    assert f'=~"{Q.regex_literal(env)}|"' in Q.request_rate(sel, "1m")
    assert '"demo\\\\.api"' in Q.last_sample_batch(["demo.api"])


@pytest.mark.at("FR-MON-03")
def test_sli_from_fixed_counter_series() -> None:
    total = [100, 150, 220, 300]  # 200 requests
    errors = [5, 5, 15, 25]  # 20 errors
    sli = window_sli(total, errors)
    assert sli.total == 200 and sli.errors == 20
    assert sli.error_ratio == pytest.approx(0.1) and sli.availability == pytest.approx(0.9)
    assert counter_increase([10, 20, 5, 15]) == 25  # counter reset handled like PromQL
    idle = window_sli([50, 50], [1, 1])
    assert idle.no_traffic and idle.availability is None  # never "100 % available" without traffic


@pytest.mark.at("FR-MON-05")
def test_zscore_step_change_and_noise() -> None:
    import random

    rnd = random.Random(7)
    noise = [100 + rnd.gauss(0, 2) for _ in range(60)]
    stationary = zscore(noise[:-1], noise[-1])
    assert stationary is not None and abs(stationary.z) < 3
    step = zscore(noise, 140.0)
    assert step is not None and step.z > 3
    assert zscore([1.0], 2.0) is None and zscore([1.0, math.nan, 1.0], math.nan) is None
    flat = zscore([10.0] * 30, 10.5)
    assert flat is not None and abs(flat.z) < 10  # relative epsilon floor


@pytest.mark.nt("PERF-04")
def test_detection_bound_formula() -> None:
    assert required_consecutive(120, 30) == 4 and required_consecutive(10, 30) == 1
    assert detection_bound(5.0, 120, 30) == 125.0


@pytest.mark.at("FR-MON-02")
def test_metrics_endpoint_series_and_states(
    client: TestClient, users: Users, target: dict[str, Any], fake_prom: FakePrometheus
) -> None:
    h = users.headers("viewer")
    fake_prom.on("increase(", 120.0)
    fake_prom.on("sum(rate(", [1.0, 2.0, "NaN", 4.0])
    r = client.get(f"{API}/monitoring-targets/{target['id']}/metrics?metric=request_rate&range=1h", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["unit"] == "requests_per_second" and body["step_seconds"] == 15
    assert [p["v"] for p in body["series"]] == [1.0, 2.0, None, 4.0]
    fake_prom.on("increase(", 0.0)
    r = client.get(f"{API}/monitoring-targets/{target['id']}/metrics?metric=error_ratio&range=15m", headers=h)
    assert r.json()["status"] == "no_traffic"
    fake_prom.rules.clear()
    r = client.get(f"{API}/monitoring-targets/{target['id']}/metrics?metric=latency_p99&range=24h", headers=h)
    assert r.json()["status"] == "no_data" and r.json()["step_seconds"] >= 285
    assert (
        client.get(f"{API}/monitoring-targets/{target['id']}/metrics?metric=x&range=1h", headers=h).status_code == 422
    )
    assert (
        client.get(
            f"{API}/monitoring-targets/{target['id']}/metrics?metric=error_ratio&range=2d", headers=h
        ).status_code
        == 422
    )
    fake_prom.down = True
    r = client.get(f"{API}/monitoring-targets/{target['id']}/metrics?metric=error_ratio&range=1h", headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "PROMETHEUS_UNAVAILABLE"


@pytest.mark.at("FR-PRJ-04")
def test_target_status_transitions(
    db: Session, target: dict[str, Any], fake_prom: FakePrometheus, clock: FakeClock
) -> None:
    client = PrometheusClient()
    t = db.get(MonitoringTarget, target["id"])
    assert t is not None
    update_target_statuses(db, client, clock.now())
    assert t.status == "waiting"
    seen = clock.now().timestamp() - 10
    fake_prom.on(
        "max by (service_name",
        [
            {
                "metric": {"service_name": "demo-api", "deployment_environment_name": "dev"},
                "value": [clock.now().timestamp(), str(seen)],
            }
        ],
    )
    update_target_statuses(db, client, clock.now())
    assert t.status == "receiving" and t.last_seen_at is not None
    fake_prom.rules.clear()
    clock.advance(301)
    update_target_statuses(db, client, clock.now())
    assert t.status == "stale"
    # A sample for another environment does not count for this target.
    fake_prom.on(
        "max by (service_name",
        [
            {
                "metric": {"service_name": "demo-api", "deployment_environment_name": "prod"},
                "value": [clock.now().timestamp(), str(clock.now().timestamp())],
            }
        ],
    )
    update_target_statuses(db, client, clock.now() + timedelta(seconds=1))
    assert t.status == "stale"
