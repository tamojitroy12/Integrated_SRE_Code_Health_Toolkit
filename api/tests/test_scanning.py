"""Dependency scanning and static analysis (FR-DEP-01..09, FR-SAST-01..04, NFR-REL-02/04)."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.conftest import Users
from tests.scanning_fakes import (
    FIXTURES,
    VULN_REPO,
    failing_trivy,
    fake_semgrep,
    fake_trivy,
    osv_factory,
    registry_factory,
)
from toolkit.core.clock import FakeClock
from toolkit.db.models import Dependency, Evidence, Finding, FindingOccurrence, Job, Repository, Scan, ScanProviderRun
from toolkit.integrations.osv import parse_record
from toolkit.jobs import queue
from toolkit.scanning import orchestrator
from toolkit.scanning.cvss import base_score, severity_from_vector
from toolkit.scanning.inventory import Dep, Inventory, build_inventory, parse_requirements
from toolkit.scanning.normalize import fingerprint, vulnerability_findings
from toolkit.scanning.semgrep import parse as parse_semgrep
from toolkit.scanning.trivy import build_argv
from toolkit.scanning.trivy import parse as parse_trivy
from toolkit.scanning.versions import bump, compare, pick_fix_version

API = "/api/v1"


# ----------------------------------------------------------------------------- units
def test_versions() -> None:
    assert compare("npm", "1.2.3", "1.10.0") == -1 and compare("npm", "1.0.0-beta", "1.0.0") == -1
    assert compare("pypi", "2.25.0", "2.25") == 0
    assert bump("npm", "4.17.15", "4.17.21") == "patch" and bump("npm", "4.1.0", "4.17.0") == "minor"
    assert bump("npm", "0.21.0", "0.27.2") == "major"  # 0.x minor is breaking
    assert bump("pypi", "1.1.2", "3.1.0") == "major" and bump("npm", "2.0.0", "1.0.0") == "none"
    assert pick_fix_version("npm", "4.17.15", ["4.17.19", "4.17.21", "3.0.0"]) == "4.17.19"
    assert pick_fix_version("npm", "1.2.5", ["2.0.0"]) == "2.0.0"


def test_cvss_calculator() -> None:
    assert base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H") == 9.8
    assert base_score("CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:H/A:H") == 7.4
    assert base_score("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N") == 6.1
    assert severity_from_vector("CVSS:4.0/AV:N/AC:L") is None


@pytest.mark.at("FR-DEP-02")
def test_inventory_of_fixture_repo() -> None:
    inv = build_inventory(VULN_REPO)
    deps = {(d.ecosystem, d.name, d.version): d for d in inv.unique()}
    assert deps[("npm", "lodash", "4.17.15")].scope == "direct"
    assert deps[("npm", "lodash", "4.17.15")].manifest_path == "npm-app/package-lock.json"
    assert any(d.scope == "transitive" for d in inv.unique() if d.ecosystem == "npm")
    assert deps[("pypi", "pyyaml", "5.3.1")].scope == "direct"
    manifest = json.loads((VULN_REPO / "fixture-manifest.json").read_text())
    for s in manifest["seeded"]:
        assert (s["ecosystem"], s["name"], s["version"]) in deps, s
    assert set(inv.manifests) == {"npm-app/package-lock.json", "python-app/requirements.txt"}


def test_requirements_parser_edge_cases() -> None:
    inv = Inventory()
    parse_requirements(
        "# c\nFlask[async]==1.1.2 ; python_version>'3'\n-r other.txt\nrequests>=2\n"
        "git+https://x/y.git\nurllib3==1.26.4 \\\n  --hash=sha256:abc\n",
        "r.txt",
        inv,
    )
    assert [(d.name, d.version) for d in inv.deps] == [("Flask", "1.1.2"), ("urllib3", "1.26.4")]


@pytest.mark.at("FR-DEP-03")
def test_trivy_parse_and_argv() -> None:
    res = parse_trivy(json.loads((FIXTURES / "trivy.json").read_text()))
    assert {(v.name, v.vuln_id) for v in res.vulns} >= {("lodash", "CVE-2020-8203"), ("pyyaml", "CVE-2020-14343")}
    qs = next(v for v in res.vulns if v.name == "qs")
    assert qs.fixed_versions == ["6.7.3", "6.10.3"]
    argv = build_argv("/work/x")
    assert argv[argv.index("--scanners") + 1] == "vuln"  # secret scanning explicitly not enabled


@pytest.mark.at("FR-SAST-01")
@pytest.mark.at("FR-SAST-03")
def test_semgrep_parse() -> None:
    res = parse_semgrep(json.loads((FIXTURES / "semgrep.json").read_text()))
    assert [m.rule_id for m in res.matches] == ["toolkit.python.weak-hash", "toolkit.python.subprocess-shell-true"]
    assert res.matches[0].severity == "medium" and res.matches[1].severity == "high"
    assert res.matches[1].path == "python-app/app.py"  # normalized; path-escape result dropped
    assert "other" not in res.matches[0].metadata


def test_semgrep_failure_reason_comes_from_json_errors() -> None:
    from toolkit.scanning.semgrep import _failure_reason

    stdout = json.dumps(
        {
            "errors": [
                {"level": "warn", "type": "Timeout", "message": "slow file"},
                {
                    "level": "error",
                    "type": "Rule parse error",
                    "message": "Rule parse error in rule x:\n Invalid pattern",
                },
            ]
        }
    )
    assert _failure_reason(stdout, "") == "Rule parse error: Rule parse error in rule x:"
    assert _failure_reason("not json", "boom\nfatal: out of memory") == "fatal: out of memory"
    assert _failure_reason("", "") == "semgrep failed"


@pytest.mark.at("FR-SAST-01")
@pytest.mark.skipif(shutil.which("semgrep") is None, reason="semgrep binary not installed (runs in the toolkit image)")
def test_bundled_rules_parse_and_find_seeded_code_issues() -> None:
    # Recorded fixtures cannot catch an unparsable bundled rule; run the real binary when available.
    from toolkit.scanning.semgrep import scan as semgrep_scan

    res = semgrep_scan(VULN_REPO, timeout=300)
    assert res.errors == 0
    found = {(m.rule_id, m.path) for m in res.matches}
    manifest = json.loads((VULN_REPO / "fixture-manifest.json").read_text(encoding="utf-8"))
    for issue in manifest["code_issues"]:
        assert (issue["rule_id"], issue["path"]) in found, issue


@pytest.mark.at("FR-DEP-04")
def test_alias_merge_trivy_and_osv() -> None:
    rec = json.loads((FIXTURES / "osv" / "GHSA-p6mc-m468-83gw.json").read_text())
    adv = parse_record(rec, "npm", "lodash")
    assert "4.17.19" in adv.fixed_versions and adv.severity == "high" and "CVE-2020-8203" in adv.aliases
    trivy = parse_trivy(json.loads((FIXTURES / "trivy.json").read_text()))
    deps = [Dep("npm", "lodash", "4.17.15", "direct", "npm-app/package-lock.json")]
    drafts = vulnerability_findings(
        deps, [v for v in trivy.vulns if v.name == "lodash"], {("npm", "lodash", "4.17.15"): [adv]}
    )
    assert len(drafts) == 1
    d = drafts[0]
    assert d.sources == ["osv", "trivy"] and d.advisory is not None
    assert d.advisory["primary_id"] == "CVE-2020-8203" and d.advisory["recommended_fix"] == "4.17.19"
    assert {e.source for e in d.evidence} == {"osv", "trivy"}


def test_fingerprint_excludes_lines_and_is_stable() -> None:
    a = fingerprint("code_issue", "rule", "a.py:hash1")
    assert a == fingerprint("code_issue", "rule", "a.py:hash1") and a != fingerprint("code_issue", "rule", "b.py:hash1")


# ----------------------------------------------------------------------------- end to end
def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    shutil.copytree(VULN_REPO, repo)
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "fixture", cwd=repo)
    return repo


@pytest.fixture
def scan_project(
    db: Session, client: TestClient, users: Users, project: dict[str, Any], local_repo: Path
) -> dict[str, Any]:
    db.add(
        Repository(
            project_id=uuid.UUID(project["id"]),
            owner="example-org",
            name="vulnerable-repo",
            url=local_repo.as_uri(),
            default_branch="main",
            ecosystems=["npm", "pypi"],
            manifests=[],
        )
    )
    db.commit()
    return project


def _toolbox(**over: Any) -> orchestrator.Toolbox:
    tb = orchestrator.Toolbox(
        trivy=fake_trivy,
        semgrep=fake_semgrep,
        osv_factory=osv_factory(),
        registry_factory=registry_factory(),
        allow_file_clone=True,
    )
    for k, v in over.items():
        setattr(tb, k, v)
    return tb


def run_scan(
    db: Session,
    session_factory: Any,
    clock: FakeClock,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    toolbox: orchestrator.Toolbox,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    r = client.post(f"{API}/projects/{project['id']}/scans", json=body or {}, headers=users.headers("maintainer"))
    assert r.status_code == 202, r.text
    job = queue.claim(db, "test-worker", clock.now(), 600)
    assert job is not None and job.type == "scan"
    db.commit()
    monkeypatch.setattr(orchestrator, "TOOLBOX", toolbox)
    from toolkit.jobs.runner import execute

    status = execute(job, "test-worker", clock=clock, session_factory=session_factory, heartbeat=False)
    db.commit()
    out = client.get(f"{API}/scans/{r.json()['scan']['id']}", headers=users.headers("viewer")).json()
    out["_job_status"] = status
    return dict(out)


@pytest.mark.at("FR-DEP-01")
@pytest.mark.at("FR-DEP-03")
@pytest.mark.at("FR-DEP-05")
@pytest.mark.at("FR-DEP-06")
@pytest.mark.at("FR-SAST-01")
def test_full_scan_job(
    db: Session,
    session_factory: Any,
    clock: FakeClock,
    client: TestClient,
    users: Users,
    scan_project: dict[str, Any],
    local_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = run_scan(db, session_factory, clock, client, users, scan_project, _toolbox(), monkeypatch)
    assert scan["_job_status"] == "succeeded" and scan["status"] == "succeeded"
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=local_repo, capture_output=True, text=True).stdout.strip()
    assert scan["commit_sha"] == sha
    assert {p["name"]: p["status"] for p in scan["providers"]} == {
        "osv": "ok",
        "registry": "ok",
        "semgrep": "ok",
        "trivy": "ok",
    }
    assert scan["summary"]["dependencies"] > 100 and scan["summary"]["new"] > 0
    findings = list(db.scalars(select(Finding).where(Finding.project_id == uuid.UUID(scan_project["id"]))))
    by_type: dict[str, list[Finding]] = {}
    for f in findings:
        by_type.setdefault(f.type, []).append(f)
    lodash = [f for f in by_type["dependency_vulnerability"] if f.package_name == "lodash"]
    assert any(set(f.sources) == {"osv", "trivy"} for f in lodash)  # merged across providers
    assert all(f.advisory and f.advisory["ids"] for f in by_type["dependency_vulnerability"])
    outdated = {f.package_name: f.detail for f in by_type["dependency_outdated"]}
    assert outdated["lodash"]["lag"] == "patch" and outdated["flask"]["lag"] == "major"
    heuristics = {(f.package_name, f.detail["heuristic"]) for f in by_type["dependency_incompatibility"]}  # type: ignore[index]
    assert ("request", "registry_deprecation") in heuristics
    assert ("node-fetch", "runtime_constraint_mismatch") in heuristics
    code = by_type["code_issue"]
    assert {f.rule_id for f in code} == {"toolkit.python.weak-hash", "toolkit.python.subprocess-shell-true"}
    weak = next(f for f in code if f.rule_id == "toolkit.python.weak-hash")
    snippet = db.scalar(select(Evidence).where(Evidence.finding_id == weak.id, Evidence.kind == "code_snippet"))
    assert snippet is not None and snippet.content["line_start"] <= 23 <= snippet.content["line_end"]
    stored = json.dumps([e.content for e in db.scalars(select(Evidence))])
    assert "FAKE_KEY_DO_NOT_USE_0000" not in stored  # redacted before storage (FR-AI-06)
    # The workspace was deleted.
    from toolkit.core.config import get_settings

    assert not any(Path(get_settings().work_dir).glob("scan-*"))


@pytest.mark.at("FR-DEP-09")
@pytest.mark.nt("REL-04")
@pytest.mark.at("FR-SAST-04")
def test_rescan_change_labels_resolution_and_dismissal(
    db: Session,
    session_factory: Any,
    clock: FakeClock,
    client: TestClient,
    users: Users,
    scan_project: dict[str, Any],
    local_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = run_scan(db, session_factory, clock, client, users, scan_project, _toolbox(), monkeypatch)
    pid = uuid.UUID(scan_project["id"])
    weak = db.scalar(select(Finding).where(Finding.project_id == pid, Finding.rule_id == "toolkit.python.weak-hash"))
    assert weak is not None
    h = users.headers("maintainer")
    assert client.patch(f"{API}/findings/{weak.id}", json={"status": "dismissed"}, headers=h).status_code == 422
    r = client.patch(
        f"{API}/findings/{weak.id}",
        json={"status": "dismissed", "dismissal_reason": "false_positive", "note": "Covered by WAF"},
        headers=h,
    )
    assert r.status_code == 200 and r.json()["dismissal"]["by"]["display_name"] == "Maintainer"
    # Bump minimist in the repository: its findings must resolve, everything else unchanged.
    lock = local_repo / "npm-app" / "package-lock.json"
    data = json.loads(lock.read_text())
    data["packages"]["node_modules/minimist"]["version"] = "1.2.8"
    lock.write_text(json.dumps(data, indent=2))
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "bump", cwd=local_repo)
    clock.advance(3600)
    second = run_scan(db, session_factory, clock, client, users, scan_project, _toolbox(), monkeypatch)
    assert second["summary"]["resolved"] >= 1
    minimist = db.scalar(
        select(Finding).where(
            Finding.project_id == pid,
            Finding.package_name == "minimist",
            Finding.package_version == "1.2.5",
            Finding.type == "dependency_vulnerability",
        )
    )
    assert minimist is not None and minimist.status == "resolved" and minimist.last_change == "resolved"
    db.refresh(weak)
    assert weak.status == "dismissed" and weak.last_change == "unchanged"
    # Re-processing the same scan creates no duplicates (unique (scan_id, fingerprint)).
    count = db.scalar(
        select(func.count()).select_from(FindingOccurrence).where(FindingOccurrence.scan_id == uuid.UUID(second["id"]))
    )
    from toolkit.scanning.persist import persist_findings

    scan = db.get(Scan, uuid.UUID(second["id"]))
    assert scan is not None
    persist_findings(db, scan, [], ok_providers=set(), partial=True, now=clock.now())
    assert (
        db.scalar(select(func.count()).select_from(FindingOccurrence).where(FindingOccurrence.scan_id == scan.id))
        == count
    )
    er = client.get(f"{API}/projects/{pid}/findings?change=resolved", headers=users.headers("maintainer"))
    assert er.status_code == 200, er.text
    explorer = er.json()
    assert explorer["items"] and all(i["change"] == "resolved" for i in explorer["items"])
    assert first["id"] != second["id"]


@pytest.mark.at("FR-DEP-07")
@pytest.mark.nt("REL-02")
def test_provider_failure_gives_partial_and_never_resolves(
    db: Session,
    session_factory: Any,
    clock: FakeClock,
    client: TestClient,
    users: Users,
    scan_project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_scan(db, session_factory, clock, client, users, scan_project, _toolbox(), monkeypatch)
    open_before = db.scalar(select(func.count()).select_from(Finding).where(Finding.status == "open"))
    clock.advance(60)
    scan = run_scan(
        db,
        session_factory,
        clock,
        client,
        users,
        scan_project,
        _toolbox(trivy=failing_trivy, osv_factory=osv_factory(fail=True)),
        monkeypatch,
    )
    assert scan["status"] == "partial" and scan["_job_status"] == "partial"
    statuses = {p["name"]: p for p in scan["providers"]}
    assert statuses["trivy"]["status"] == "failed" and "unavailable" in statuses["trivy"]["error"]
    assert statuses["osv"]["status"] == "failed" and statuses["semgrep"]["status"] == "ok"
    assert scan["summary"]["resolved"] == 0 and set(scan["summary"]["failed_providers"]) == {"trivy", "osv"}
    assert db.scalar(select(func.count()).select_from(Finding).where(Finding.status == "open")) == open_before
    overview = client.get(f"{API}/projects/{scan_project['id']}/overview", headers=users.headers("viewer")).json()
    assert overview["latest_scan"]["scan_status"] == "partial"


@pytest.mark.at("FR-DEP-05")
def test_registry_outage_is_failure_not_up_to_date(
    db: Session,
    session_factory: Any,
    clock: FakeClock,
    client: TestClient,
    users: Users,
    scan_project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = run_scan(
        db,
        session_factory,
        clock,
        client,
        users,
        scan_project,
        _toolbox(registry_factory=registry_factory(fail=True)),
        monkeypatch,
    )
    assert {p["name"]: p["status"] for p in scan["providers"]}["registry"] == "failed"
    assert scan["status"] == "partial"
    assert db.scalar(select(func.count()).select_from(Finding).where(Finding.type == "dependency_outdated")) == 0


@pytest.mark.at("FR-DEP-01")
def test_scan_api_validation_conflict_and_cancel(
    db: Session, client: TestClient, users: Users, scan_project: dict[str, Any], clock: FakeClock
) -> None:
    h = users.headers("maintainer")
    url = f"{API}/projects/{scan_project['id']}/scans"
    for ref in ("-rf", "a..b", "a b"):
        assert client.post(url, json={"ref": ref}, headers=h).status_code == 422
    r = client.post(url, json={"providers": ["semgrep"]}, headers=h)
    assert r.status_code == 202
    second = client.post(url, json={}, headers=h)
    assert second.status_code == 409
    job_id = r.json()["job"]["id"]
    assert client.get(f"{API}/jobs/{job_id}", headers=users.headers("viewer")).json()["status"] == "queued"
    c = client.post(f"{API}/jobs/{job_id}/cancel", headers=h)
    assert c.status_code == 202 and c.json()["status"] == "cancelled"
    scan = client.get(f"{API}/scans/{r.json()['scan']['id']}", headers=h).json()
    assert scan["status"] == "cancelled"
    assert client.post(f"{API}/jobs/{job_id}/cancel", headers=h).status_code == 409
    no_repo = client.post(f"{API}/projects", json={"name": "norepo"}, headers=h).json()
    assert client.post(f"{API}/projects/{no_repo['id']}/scans", json={}, headers=h).status_code == 409


@pytest.mark.at("FR-DSH-02")
@pytest.mark.at("FR-DSH-03")
def test_findings_explorer_filters_sort_pagination(
    db: Session,
    session_factory: Any,
    clock: FakeClock,
    client: TestClient,
    users: Users,
    scan_project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_scan(db, session_factory, clock, client, users, scan_project, _toolbox(), monkeypatch)
    h = users.headers("viewer")
    base = f"{API}/projects/{scan_project['id']}/findings"
    page = client.get(f"{base}?limit=5&sort=-severity", headers=h).json()
    assert len(page["items"]) == 5 and page["next_cursor"] and page["total"] > 5
    seen = [i["id"] for i in page["items"]]
    nxt = client.get(f"{base}?limit=5&sort=-severity&cursor={page['next_cursor']}", headers=h).json()
    assert not set(seen) & {i["id"] for i in nxt["items"]}
    ranks = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1, None: 0}
    sev = [ranks[i["severity"]] for i in page["items"] + nxt["items"]]
    assert sev == sorted(sev, reverse=True)
    combo = client.get(f"{base}?type=dependency_vulnerability&severity=high&package=lodash", headers=h).json()
    assert combo["items"] and all(i["subject"]["name"] == "lodash" and i["severity"] == "high" for i in combo["items"])
    code = client.get(f"{base}?type=code_issue&path=python-app/", headers=h).json()
    assert len(code["items"]) == 2
    assert client.get(f"{base}?q=cve-2020-8203", headers=h).json()["items"]
    assert client.get(f"{base}?severity=bogus", headers=h).status_code == 422
    assert client.get(f"{base}?limit=500", headers=h).status_code == 422
    sugg = client.get(f"{base}/suggestions?q=lod", headers=h).json()
    assert "lodash" in sugg["packages"]
    fid = combo["items"][0]["id"]
    detail = client.get(f"{API}/findings/{fid}", headers=h).json()
    assert detail["evidence"] and detail["history"] and detail["recommendations"] == []
    assert detail["fix_proposals"] == [] and detail["fixable"] is True
    deps = client.get(f"{API}/scans/{detail['last_seen_scan_id']}/dependencies?ecosystem=npm&q=lod", headers=h).json()
    assert deps["items"][0]["name"] == "lodash"
    assert db.scalar(select(func.count()).select_from(Dependency)) > 100
    assert db.scalar(select(func.count()).select_from(ScanProviderRun)) == 4
    assert db.scalar(select(func.count()).select_from(Job)) == 1


def test_clone_rejects_bad_refs_and_non_https(tmp_path: Path) -> None:
    from toolkit.core.errors import JobError
    from toolkit.scanning.clone import clone_ref

    for url, ref in (("file:///etc", "main"), ("https://github.com/a/b.git", "--upload-pack=x")):
        with pytest.raises(JobError):
            clone_ref(url, ref, tmp_path / uuid.uuid4().hex, token=None, timeout=10, max_mb=10)


def test_clone_disables_symlinks(tmp_path: Path, local_repo: Path) -> None:
    from toolkit.scanning.clone import clone_ref

    (local_repo / "link").symlink_to("/etc/passwd") if hasattr(Path, "symlink_to") else None
    try:
        _git("-c", "user.email=t@t", "-c", "user.name=t", "add", "-A", cwd=local_repo)
        _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "link", cwd=local_repo)
    except (subprocess.CalledProcessError, OSError):
        pytest.skip("symlinks not supported on this platform")
    dest = tmp_path / "clone"
    sha = clone_ref(local_repo.as_uri(), "main", dest, token="t0ken", timeout=60, max_mb=50, allow_file_protocol=True)
    assert len(sha) == 40 and not (dest / ".git").exists()
    link = dest / "link"
    assert not link.is_symlink()
