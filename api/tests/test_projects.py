"""Projects, repository connection and onboarding (FR-PRJ-01..05, FR-DSH-01, NFR-REL-05)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.conftest import Users
from tests.fakes import FakePrometheus, json_transport
from toolkit.db.models import Credential, Repository
from toolkit.integrations import github
from toolkit.monitoring import prometheus

API = "/api/v1"


@pytest.fixture
def fake_prom(monkeypatch: pytest.MonkeyPatch) -> FakePrometheus:
    fp = FakePrometheus()
    monkeypatch.setattr(prometheus, "DEFAULT_TRANSPORT", fp.transport)
    return fp


def github_ok(private: bool = False, push: bool = True) -> dict[tuple[str, str], Any]:
    return {
        ("GET", "/repos/example-org/example-repo"): (
            200,
            {
                "owner": {"login": "example-org"},
                "name": "example-repo",
                "default_branch": "main",
                "private": private,
                "archived": False,
                "permissions": {"push": push, "pull": True},
            },
        ),
        ("GET", "/repos/example-org/example-repo/git/trees/main"): (
            200,
            {
                "tree": [
                    {"path": "package.json", "type": "blob"},
                    {"path": "package-lock.json", "type": "blob"},
                    {"path": "api/requirements.txt", "type": "blob"},
                    {"path": "node_modules/x/package.json", "type": "blob"},
                    {"path": "README.md", "type": "blob"},
                ]
            },
        ),
        ("GET", "/repos/example-org/example-repo/branches/main"): (200, {"name": "main"}),
    }


@pytest.mark.at("FR-PRJ-01")
def test_project_crud_archive_and_readonly(client: TestClient, users: Users) -> None:
    h = users.headers("maintainer")
    r = client.post(f"{API}/projects", json={"name": "Shop", "description": "d"}, headers=h)
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.post(f"{API}/projects", json={"name": "shop"}, headers=h).status_code == 409
    r = client.patch(f"{API}/projects/{pid}", json={"description": None}, headers=h)
    assert r.status_code == 200 and r.json()["description"] is None
    assert client.delete(f"{API}/projects/{pid}", headers=h).status_code == 204
    resp = client.get(f"{API}/projects", headers=users.headers("viewer"))
    assert resp.status_code == 200, resp.text
    listed = resp.json()["items"]
    assert pid not in [p["id"] for p in listed]
    ar = client.get(f"{API}/projects?include_archived=true", headers=h)
    assert ar.status_code == 200, ar.text
    archived = ar.json()["items"]
    assert pid in [p["id"] for p in archived]
    r = client.patch(f"{API}/projects/{pid}", json={"name": "x"}, headers=h)
    assert r.status_code == 409 and "archived" in r.json()["error"]["message"]
    # Name is reusable once the old project is archived.
    assert client.post(f"{API}/projects", json={"name": "Shop"}, headers=h).status_code == 201


def test_validation_and_unknown_params(client: TestClient, users: Users) -> None:
    h = users.headers("maintainer")
    r = client.post(f"{API}/projects", json={"name": "a", "bogus": 1}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["issue"] == "unknown field"
    assert r.json()["error"]["request_id"]
    r = client.get(f"{API}/projects?nope=1", headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_REQUEST"
    assert client.get(f"{API}/projects?limit=101", headers=h).status_code == 422
    r = client.post(f"{API}/projects", content=b"{not json", headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 400


@pytest.mark.at("FR-PRJ-02")
@pytest.mark.nt("SEC-02")
def test_connect_repository_token_never_returned(
    client: TestClient, users: Users, project: dict[str, Any], db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(github, "DEFAULT_TRANSPORT", json_transport(github_ok(private=True), calls))
    h = users.headers("maintainer")
    body = {
        "url": "https://github.com/example-org/example-repo",
        "token": " ghp_supersecrettoken1234567890 ",
        "test_command": "npm test",
    }
    r = client.put(f"{API}/projects/{project['id']}/repository", json=body, headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ecosystems"] == ["npm", "pypi"]
    assert data["has_token"] is True and data["can_open_prs"] is True and data["verified_at"]
    assert "node_modules/x/package.json" not in data["manifests"]
    assert "ghp_" not in r.text
    assert calls[0].headers["authorization"] == "Bearer ghp_supersecrettoken1234567890"  # trimmed (Postel)
    cred = db.scalar(select(Credential))
    assert cred is not None and b"ghp_supersecret" not in cred.ciphertext
    got = client.get(f"{API}/projects/{project['id']}/repository", headers=users.headers("viewer"))
    assert got.status_code == 200 and "token" not in got.json() and "ghp_" not in got.text
    # Disconnect deletes the stored credential.
    assert client.delete(f"{API}/projects/{project['id']}/repository", headers=h).status_code == 204
    assert db.scalar(select(Credential)) is None


@pytest.mark.at("FR-PRJ-02")
@pytest.mark.parametrize(
    "status,code", [(401, "REPO_ACCESS_DENIED"), (403, "REPO_ACCESS_DENIED"), (404, "REPO_NOT_FOUND")]
)
def test_repository_errors_store_nothing(
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str,
) -> None:
    monkeypatch.setattr(
        github,
        "DEFAULT_TRANSPORT",
        json_transport({("GET", "/repos/example-org/example-repo"): (status, {"message": "x"})}),
    )
    r = client.put(
        f"{API}/projects/{project['id']}/repository",
        json={"url": "https://github.com/example-org/example-repo", "token": "bad"},
        headers=users.headers("maintainer"),
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert db.scalar(select(Repository)) is None and db.scalar(select(Credential)) is None


@pytest.mark.at("FR-PRJ-02")
def test_invalid_repo_url_and_test_command(client: TestClient, users: Users, project: dict[str, Any]) -> None:
    h = users.headers("maintainer")
    for body in ({"url": "https://gitlab.com/a/b"}, {"url": "https://github.com/a/b", "test_command": "rm -rf /"}):
        r = client.put(f"{API}/projects/{project['id']}/repository", json=body, headers=h)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.at("FR-PRJ-03")
def test_target_onboarding_token_reference(client: TestClient, users: Users, target: dict[str, Any]) -> None:
    r = client.get(f"{API}/monitoring-targets/{target['id']}/onboarding", headers=users.headers("maintainer"))
    assert r.status_code == 200
    env = r.json()["env"]
    assert env["OTEL_SERVICE_NAME"] == "demo-api"
    assert "<OTLP_INGEST_TOKEN>" in env["OTEL_EXPORTER_OTLP_HEADERS"] and "test-ingest-token" not in r.text
    admin = client.get(f"{API}/monitoring-targets/{target['id']}/onboarding", headers=users.headers("admin"))
    assert "test-ingest-token" in admin.json()["env"]["OTEL_EXPORTER_OTLP_HEADERS"]


def test_target_validation_and_uniqueness(
    client: TestClient, users: Users, project: dict[str, Any], target: dict[str, Any]
) -> None:
    h = users.headers("maintainer")
    url = f"{API}/projects/{project['id']}/monitoring-targets"
    dup = {"name": "dup", "service_name": "demo-api", "environment": "dev"}
    assert client.post(url, json=dup, headers=h).status_code == 409
    for bad in (
        {"name": "x", "service_name": 'a"}', "environment": "dev"},
        {"name": "x", "service_name": "ok", "environment": "Prod!"},
    ):
        assert client.post(url, json=bad, headers=h).status_code == 422
    r = client.post(
        url, json={"name": "w", "service_name": "web", "environment": "prod", "create_default_rules": True}, headers=h
    )
    rules = client.get(f"{API}/projects/{project['id']}/alert-rules?target_id={r.json()['id']}", headers=h).json()
    assert {x["metric"] for x in rules} == {"error_ratio", "latency_p95", "data_absent"}


@pytest.mark.at("FR-PRJ-05")
@pytest.mark.at("FR-DSH-01")
def test_overview_with_nothing_connected(client: TestClient, users: Users, project: dict[str, Any]) -> None:
    r = client.get(f"{API}/projects/{project['id']}/overview", headers=users.headers("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert body["monitoring"]["status"] == "empty"
    assert body["latest_scan"]["status"] == "empty" and body["latest_scan"]["has_repository"] is False
    assert body["alerts"]["status"] == "empty" and body["top_findings"]["status"] == "empty"


@pytest.mark.nt("REL-05")
@pytest.mark.at("FR-DSH-01")
def test_overview_prometheus_down_keeps_other_sections(
    client: TestClient, users: Users, project: dict[str, Any], target: dict[str, Any], fake_prom: FakePrometheus
) -> None:
    fake_prom.down = True
    body = client.get(f"{API}/projects/{project['id']}/overview", headers=users.headers("viewer")).json()
    assert body["monitoring"]["status"] == "error"
    assert body["monitoring"]["targets"][0]["service_name"] == "demo-api"
    assert body["alerts"]["status"] == "empty" and body["latest_scan"]["status"] == "empty"


@pytest.mark.at("FR-DSH-01")
def test_overview_current_values(
    client: TestClient, users: Users, project: dict[str, Any], target: dict[str, Any], fake_prom: FakePrometheus
) -> None:
    fake_prom.on("histogram_quantile(0.95", 0.12)
    fake_prom.on(lambda q: q.startswith("(sum(rate("), 0.02)
    fake_prom.on(lambda q: q.startswith("sum(rate("), 4.2)
    body = client.get(f"{API}/projects/{project['id']}/overview", headers=users.headers("viewer")).json()
    cur = body["monitoring"]["targets"][0]["current"]
    assert cur == {"request_rate": 4.2, "error_ratio": 0.02, "latency_p95_seconds": 0.12}


def test_summary_and_search(client: TestClient, users: Users, project: dict[str, Any]) -> None:
    h = users.headers("viewer")
    s = client.get(f"{API}/projects/{project['id']}/summary", headers=h).json()
    assert s["unacknowledged_alerts_count"] == 0 and "server_timestamp" in s
    found = client.get(f"{API}/search?q={project['name'][:6]}", headers=h).json()
    assert found["projects"][0]["id"] == project["id"]
    assert client.get(f"{API}/projects/{project['id']}/timeline", headers=h).status_code == 200
