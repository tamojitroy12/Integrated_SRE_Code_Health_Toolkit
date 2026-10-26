"""OTLP ingestion authentication (FR-MON-01, IF-01, T-03.03).

The Collector is third-party; the static test pins the configuration that enforces bearer auth on
both protocols, and the live test (``--run-live``, stack running) proves that requests without the
right token are rejected and write nothing.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

import httpx
import pytest
import yaml

COLLECTOR_CONFIG = Path(__file__).resolve().parents[2] / "deploy" / "otel-collector.yaml"


@pytest.mark.at("FR-MON-01")
def test_collector_requires_bearer_token_on_every_receiver() -> None:
    cfg = yaml.safe_load(COLLECTOR_CONFIG.read_text(encoding="utf-8"))
    auth = cfg["extensions"]["bearertokenauth"]
    assert auth["token"] == "${env:OTLP_INGEST_TOKEN}" and auth["scheme"] == "Bearer"
    assert "bearertokenauth" in cfg["service"]["extensions"]
    protocols = cfg["receivers"]["otlp"]["protocols"]
    assert set(protocols) == {"grpc", "http"}
    for proto in protocols.values():
        assert proto["auth"]["authenticator"] == "bearertokenauth"
    # Metrics only (CON-03): no traces or logs pipelines.
    assert set(cfg["service"]["pipelines"]) == {"metrics"}


def _otlp_payload(service: str) -> dict[str, object]:
    now = time.time_ns()
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": service}}]},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "toolkit_ingest_probe",
                                "gauge": {"dataPoints": [{"timeUnixNano": str(now), "asDouble": 1.0}]},
                            }
                        ]
                    }
                ],
            }
        ]
    }


@pytest.mark.live
@pytest.mark.at("FR-MON-01")
def test_collector_rejects_missing_or_wrong_token_live() -> None:
    url = os.environ.get("TEST_OTLP_URL", "http://127.0.0.1:4318") + "/v1/metrics"
    token = os.environ.get("TEST_OTLP_TOKEN") or pytest.skip("set TEST_OTLP_TOKEN to the stack's OTLP_INGEST_TOKEN")
    rejected = f"probe-rejected-{uuid.uuid4().hex[:8]}"
    accepted = f"probe-accepted-{uuid.uuid4().hex[:8]}"
    with httpx.Client(timeout=10) as client:
        for headers in ({}, {"Authorization": "Bearer wrong-token"}, {"Authorization": token}):
            r = client.post(url, json=_otlp_payload(rejected), headers=headers)
            assert r.status_code == 401, (headers, r.status_code)
        r = client.post(url, json=_otlp_payload(accepted), headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        prom = os.environ.get("TEST_PROMETHEUS_URL")
        if prom:

            def count(service: str) -> int:
                q = f'count({{service_name="{service}"}})'
                return len(client.get(f"{prom}/api/v1/query", params={"query": q}).json()["data"]["result"])

            deadline = time.monotonic() + 30
            while count(accepted) == 0 and time.monotonic() < deadline:
                time.sleep(2)
            assert count(accepted) == 1, "authorized write never arrived"
            assert count(rejected) == 0, "unauthenticated write reached Prometheus"
