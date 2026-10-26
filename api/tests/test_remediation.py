"""Remediation: plans, sandbox pipeline, approval gates, draft PRs, safety invariants (FR-REM-01..12, SM-07)."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.conftest import Users, set_env
from tests.fakes import json_transport
from tests.scanning_fakes import VULN_REPO, osv_factory
from toolkit.core.clock import FakeClock
from toolkit.core.errors import JobError
from toolkit.db.models import AuditLog, Finding, FixProposal, Repository, Scan
from toolkit.integrations import github
from toolkit.integrations.github import BranchNotAllowedError, GitHubClient
from toolkit.jobs import queue
from toolkit.jobs.runner import execute
from toolkit.remediation import pipeline, pr
from toolkit.remediation.plan import PlanError, apply_requirements_change, build_plan
from toolkit.remediation.sandbox import StageResult

API = "/api/v1"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)


def finding(project_id: uuid.UUID, **over: Any) -> Finding:
    base: dict[str, Any] = {
        "project_id": project_id,
        "type": "dependency_vulnerability",
        "fingerprint": uuid.uuid4().hex * 2,
        "title": "lodash vuln",
        "severity": "high",
        "severity_rank": 4,
        "status": "open",
        "last_change": "new",
        "ecosystem": "npm",
        "package_name": "lodash",
        "package_version": "4.17.15",
        "scope": "direct",
        "manifest_path": "npm-app/package-lock.json",
        "advisory": {"ids": ["CVE-2020-8203"], "fixed_versions": ["4.17.19"], "recommended_fix": "4.17.19"},
        "sources": ["osv"],
        "search_text": "lodash",
        "first_seen_at": NOW,
        "last_seen_at": NOW,
    }
    base.update(over)
    return Finding(**base)


# ----------------------------------------------------------------------------- plans
@pytest.mark.at("FR-REM-01")
def test_plan_is_deterministic_and_validated() -> None:
    pid = uuid.uuid4()
    plan = build_plan(
        [finding(pid), finding(pid, advisory={"fixed_versions": ["4.17.21"], "recommended_fix": "4.17.21"})]
    )
    assert len(plan) == 1
    c = plan[0]
    assert (c.package, c.from_version, c.to_version, c.bump) == ("lodash", "4.17.15", "4.17.21", "patch")
    assert (c.manifest_path, c.lockfile_path) == ("npm-app/package.json", "npm-app/package-lock.json")
    py = build_plan(
        [
            finding(
                pid,
                ecosystem="pypi",
                package_name="PyYAML",
                package_version="5.3.1",
                manifest_path="python-app/requirements.txt",
                advisory={"fixed_versions": ["5.4"], "recommended_fix": "5.4"},
            )
        ]
    )
    assert py[0].manifest_path == py[0].lockfile_path == "python-app/requirements.txt"
    outdated_major = finding(pid, type="dependency_outdated", detail={"latest": "9.0.0", "lag": "major"}, advisory=None)
    with pytest.raises(PlanError):
        build_plan([outdated_major])
    for bad in (
        finding(pid, package_name="lodash;rm"),
        finding(pid, manifest_path="../../etc/package-lock.json"),
        finding(pid, manifest_path="npm-app/package.json"),
        finding(pid, ecosystem="pypi", manifest_path="poetry.lock", package_name="x"),
    ):
        with pytest.raises(PlanError):
            build_plan([bad])
    with pytest.raises(PlanError):
        build_plan([finding(pid), finding(uuid.uuid4())])


@pytest.mark.at("FR-REM-03")
def test_requirements_rewrite_preserves_format() -> None:
    src = "# deps\nFlask[async]==1.1.2 ; python_version > '3.8'  # web\nrequests==2.25.0\n"
    out = apply_requirements_change(src, "flask", "1.1.2", "2.3.3")
    assert out == "# deps\nFlask[async]==2.3.3 ; python_version > '3.8'  # web\nrequests==2.25.0\n"
    with pytest.raises(PlanError):
        apply_requirements_change(src, "django", "1.0", "2.0")
    with pytest.raises(PlanError):
        apply_requirements_change("pyyaml==5.3.1 --hash=sha256:abc\n", "pyyaml", "5.3.1", "5.4")


# ----------------------------------------------------------------------------- fake sandbox
class FakeSandbox:
    """In-memory sandbox that interprets the allowlisted commands the pipeline issues."""

    def __init__(
        self, *, baseline_exit: int = 0, post_exit: int = 0, touch_extra: str | None = None, install_fails: bool = False
    ) -> None:
        self.files: dict[str, str] = {}
        self.applied = False
        self.baseline_exit, self.post_exit = baseline_exit, post_exit
        self.touch_extra = touch_extra
        self.install_fails = install_fails
        self.commands: list[tuple[list[str], bool]] = []
        self.destroyed = False

    def create_workspace(self) -> str:
        return "ws-1"

    def upload(self, workspace: str, root: Path) -> None:
        for p in root.rglob("*"):
            if p.is_file():
                self.files[p.relative_to(root).as_posix()] = p.read_text(encoding="utf-8", errors="replace")

    def write_files(self, workspace: str, files: dict[str, str]) -> None:
        self.files.update(files)
        self.applied = True

    def read_files(self, workspace: str, paths: Sequence[str]) -> dict[str, str | None]:
        return {p: self.files.get(p) for p in paths}

    def destroy(self, workspace: str) -> None:
        self.destroyed = True

    def run(self, workspace: str, image: str, argv: Sequence[str], *, network: bool, timeout: int) -> StageResult:
        argv = list(argv)
        self.commands.append((argv, network))
        ok = StageResult(0, "ok", 0.1, False)
        if argv[:2] == ["sh", "-c"]:
            target = argv[2].rsplit("> ", 1)[1]
            lines = [
                f"{hashlib.sha256(c.encode()).hexdigest()}  ./{p}"
                for p, c in sorted(self.files.items())
                if not p.startswith(".toolkit-hashes")
            ]
            self.files[target] = "\n".join(lines)
            return ok
        if argv[:2] == ["npm", "ci"] or "pip" in argv[0] or argv[1:3] == ["-m", "venv"]:
            if self.install_fails and self.applied:
                return StageResult(1, "ERROR: Could not find a version that satisfies the requirement", 1.0, False)
            return ok
        if argv[:2] == ["npm", "install"]:
            assert network and "--ignore-scripts" in argv and "--package-lock-only" in argv
            prefix = argv[argv.index("--prefix") + 1]
            lock_path = f"{prefix}/package-lock.json"
            lock = json.loads(self.files[lock_path])
            specs = argv[argv.index("--") + 1 :] if "--" in argv else []
            overrides = json.loads(self.files[f"{prefix}/package.json"]).get("overrides", {})
            for spec in specs:
                name, ver = spec.rsplit("@", 1)
                lock["packages"][f"node_modules/{name}"]["version"] = ver
            for name, ver in overrides.items():
                lock["packages"][f"node_modules/{name}"]["version"] = ver
            self.files[lock_path] = json.dumps(lock, indent=2)
            if self.touch_extra:
                self.files[self.touch_extra] = "tampered"
            self.applied = True
            return ok
        if argv in (["npm", "test"], ["/work/.venv/bin/python", "-m", "pytest", "-q"]):
            assert not network, "tests must run with networking disabled"
            code = self.post_exit if self.applied else self.baseline_exit
            return StageResult(code, f"tests exit {code}", 2.0, False)
        raise AssertionError(f"unexpected command {argv}")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    shutil.copytree(VULN_REPO, root)
    return root


def _now() -> datetime:
    return NOW


@pytest.mark.at("FR-REM-02")
@pytest.mark.at("FR-REM-04")
@pytest.mark.at("FR-REM-05")
def test_pipeline_passed(workspace: Path) -> None:
    sb = FakeSandbox()
    changes = build_plan(
        [
            finding(
                uuid.uuid4(),
                package_name="minimist",
                package_version="1.2.5",
                advisory={"fixed_versions": ["1.2.6"], "recommended_fix": "1.2.6"},
            )
        ]
    )
    report = pipeline.run_pipeline(sb, workspace, changes, "npm test", _now, osv_factory(), lambda s: None)
    assert report.validation_result == "passed", report.delta_scan
    assert set(report.changed_files) == {"npm-app/package-lock.json"}
    assert '-      "version": "1.2.5"' in report.diff.replace("'", '"') or "1.2.6" in report.diff
    stages = {r["stage"]: r["status"] for r in report.runs}
    assert stages == {"baseline": "passed", "apply": "passed", "post_change": "passed", "rescan": "passed"}
    assert report.delta_scan["resolved_finding_ids"] and sb.destroyed
    # Every test run had networking disabled; installs had it enabled with scripts disabled.
    assert all(not net for argv, net in sb.commands if argv == ["npm", "test"])


@pytest.mark.at("FR-REM-12")
def test_pipeline_unverified_and_failed(workspace: Path) -> None:
    changes = build_plan([finding(uuid.uuid4())])
    no_tests = pipeline.run_pipeline(FakeSandbox(), workspace, changes, None, _now, osv_factory(), lambda s: None)
    assert no_tests.validation_result == "unverified"
    failing_base = pipeline.run_pipeline(
        FakeSandbox(baseline_exit=1), workspace, changes, "npm test", _now, osv_factory(), lambda s: None
    )
    assert failing_base.validation_result == "unverified"
    broken = pipeline.run_pipeline(
        FakeSandbox(post_exit=1), workspace, changes, "npm test", _now, osv_factory(), lambda s: None
    )
    assert broken.validation_result == "failed" and any("failed after" in n for n in broken.risk_notes)


@pytest.mark.at("FR-REM-03")
def test_pipeline_scope_violation_aborts(workspace: Path) -> None:
    sb = FakeSandbox(touch_extra=".github/workflows/ci.yml")
    with pytest.raises(JobError) as exc:
        pipeline.run_pipeline(
            sb, workspace, build_plan([finding(uuid.uuid4())]), "npm test", _now, osv_factory(), lambda s: None
        )
    assert exc.value.code.value == "DIFF_SCOPE_VIOLATION" and sb.destroyed


def test_pipeline_transitive_uses_overrides_and_pypi_edit(workspace: Path) -> None:
    sb = FakeSandbox()
    pid = uuid.uuid4()
    changes = build_plan(
        [
            finding(
                pid,
                package_name="qs",
                package_version="6.7.0",
                scope="transitive",
                advisory={"fixed_versions": ["6.7.3"], "recommended_fix": "6.7.3"},
            ),
            finding(
                pid,
                ecosystem="pypi",
                package_name="pyyaml",
                package_version="5.3.1",
                manifest_path="python-app/requirements.txt",
                advisory={"fixed_versions": ["5.4"], "recommended_fix": "5.4"},
            ),
        ]
    )
    report = pipeline.run_pipeline(sb, workspace, changes, "pytest", _now, osv_factory(), lambda s: None)
    assert json.loads(report.changed_files["npm-app/package.json"])["overrides"] == {"qs": "6.7.3"}
    assert "pyyaml==5.4" in report.changed_files["python-app/requirements.txt"]
    assert any("overrides" in n for n in report.risk_notes)


def test_pipeline_sdist_required(workspace: Path) -> None:
    changes = build_plan(
        [
            finding(
                uuid.uuid4(),
                ecosystem="pypi",
                package_name="pyyaml",
                package_version="5.3.1",
                manifest_path="python-app/requirements.txt",
                advisory={"fixed_versions": ["5.4"], "recommended_fix": "5.4"},
            )
        ]
    )
    with pytest.raises(JobError) as exc:
        pipeline.run_pipeline(
            FakeSandbox(install_fails=True), workspace, changes, "pytest", _now, osv_factory(), lambda s: None
        )
    assert exc.value.code.value == "SDIST_BUILD_REQUIRED"


# ----------------------------------------------------------------------------- API + jobs
@pytest.fixture
def remediation_project(
    db: Session,
    client: TestClient,
    users: Users,
    project: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,
) -> dict[str, Any]:
    set_env(monkeypatch, remediation_enabled="true")
    pid = uuid.UUID(project["id"])
    from toolkit.services.credentials import store_token

    cred = store_token(db, "ghp_writetoken000000000000000000000", None)
    db.flush()
    repo = Repository(
        project_id=pid,
        owner="example-org",
        name="vulnerable-repo",
        url="https://github.com/example-org/vulnerable-repo",
        default_branch="main",
        ecosystems=["npm"],
        manifests=[],
        can_open_prs=True,
        credential_id=cred.id,
        test_command="npm test",
    )
    db.add(repo)
    db.flush()
    scan = Scan(
        project_id=pid,
        repository_id=repo.id,
        ref="main",
        commit_sha="a" * 40,
        status="succeeded",
        providers=["trivy"],
        summary={},
    )
    db.add(scan)
    db.flush()
    f = finding(pid, last_seen_scan_id=scan.id)
    db.add(f)
    db.commit()
    project["finding_id"] = str(f.id)

    def fake_clone(url: str, ref: str, dest: Path, **_: Any) -> str:
        assert ref == "a" * 40 and url == "https://github.com/example-org/vulnerable-repo.git"
        shutil.copytree(workspace, dest)
        return ref

    monkeypatch.setattr(
        pipeline,
        "TOOLBOX",
        pipeline.RemediationToolbox(sandbox_factory=FakeSandbox, clone=fake_clone, osv_factory=osv_factory()),
    )
    return project


def _run(db: Session, clock: FakeClock, session_factory: Any, job_type: str) -> str:
    job = queue.claim(db, "w", clock.now(), 60, types=[job_type])
    assert job is not None
    db.commit()  # like a real worker: the claim is committed before the handler runs
    return execute(job, "w", clock=clock, session_factory=session_factory, heartbeat=False)


def github_routes(calls: list[Any]) -> dict[tuple[str, str], Any]:
    repo = "/repos/example-org/vulnerable-repo"
    return {
        ("GET", f"{repo}/git/commits/{'a' * 40}"): (200, {"sha": "a" * 40, "tree": {"sha": "t" * 40}}),
        ("POST", f"{repo}/git/blobs"): (201, {"sha": "b" * 40}),
        ("POST", f"{repo}/git/trees"): (201, {"sha": "c" * 40}),
        ("POST", f"{repo}/git/commits"): (201, {"sha": "d" * 40}),
        ("POST", f"{repo}/git/refs"): (201, {"ref": "x"}),
        ("POST", f"{repo}/pulls"): lambda req: _pr(req, calls),
        ("PATCH", f"{repo}/pulls/12"): (200, {"state": "closed"}),
        ("DELETE", f"{repo}/git/refs/heads/*"): lambda req: __import__("httpx").Response(204),
    }


def _pr(req: Any, calls: list[Any]) -> Any:
    import httpx

    calls.append(json.loads(req.content))
    return httpx.Response(
        201, json={"number": 12, "html_url": "https://github.com/example-org/vulnerable-repo/pull/12", "draft": True}
    )


@pytest.mark.at("FR-REM-06")
@pytest.mark.at("FR-REM-07")
@pytest.mark.at("FR-REM-10")
@pytest.mark.nt("SM-07")
def test_proposal_to_draft_pr(
    db: Session,
    client: TestClient,
    users: Users,
    remediation_project: dict[str, Any],
    clock: FakeClock,
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = users.headers("maintainer")
    pid = remediation_project["id"]
    r = client.post(
        f"{API}/projects/{pid}/fix-proposals", json={"finding_ids": [remediation_project["finding_id"]]}, headers=h
    )
    assert r.status_code == 202, r.text
    prop_id = r.json()["proposal"]["id"]
    # Approval before validation is impossible.
    assert client.post(f"{API}/fix-proposals/{prop_id}/approve", json={}, headers=h).status_code == 409
    assert _run(db, clock, session_factory, "fix_proposal") == "succeeded"
    detail = client.get(f"{API}/fix-proposals/{prop_id}", headers=users.headers("viewer")).json()
    assert detail["status"] == "ready" and detail["validation"]["result"] == "passed"
    assert detail["diff"].startswith("diff --git a/npm-app/package-lock.json")
    assert detail["validation"]["baseline"]["status"] == "passed"
    assert (
        client.post(f"{API}/fix-proposals/{prop_id}/approve", json={}, headers=users.headers("viewer")).status_code
        == 403
    )
    calls: list[Any] = []
    monkeypatch.setattr(github, "DEFAULT_TRANSPORT", json_transport(github_routes(calls)))
    r = client.post(f"{API}/fix-proposals/{prop_id}/approve", json={"comment": "Reviewed diff."}, headers=h)
    assert r.status_code == 202 and r.json()["job"]["type"] == "pr_creation"
    assert _run(db, clock, session_factory, "pr_creation") == "succeeded"
    detail = client.get(f"{API}/fix-proposals/{prop_id}", headers=h).json()
    assert detail["status"] == "pr_opened"
    assert detail["pull_request"]["url"].endswith("/pull/12") and detail["pull_request"]["draft"] is True
    assert detail["pull_request"]["branch"] == f"toolkit/fix/{prop_id}"
    assert calls[0]["draft"] is True and calls[0]["head"] == f"toolkit/fix/{prop_id}" and calls[0]["base"] == "main"
    assert "the Toolkit never merges" in calls[0]["body"]
    actions = {a.action for a in db.scalars(select(AuditLog))}
    assert {"fix.proposal_created", "fix.approved", "fix.pr_opened"} <= actions
    # Cleanup closes the PR and deletes only the Toolkit branch.
    assert client.post(f"{API}/fix-proposals/{prop_id}/cleanup", headers=h).status_code == 202
    assert _run(db, clock, session_factory, "pr_cleanup") == "succeeded"


@pytest.mark.at("FR-REM-09")
@pytest.mark.at("FR-REM-12")
def test_approval_matrix(db: Session, client: TestClient, users: Users, remediation_project: dict[str, Any]) -> None:
    pid = uuid.UUID(remediation_project["id"])
    h_m, h_a = users.headers("maintainer"), users.headers("admin")

    def proposal(result: str, major: bool = False) -> str:
        p = FixProposal(
            project_id=pid,
            status="ready",
            base_commit_sha="a" * 40,
            validation_result=result,
            has_major_bump=major,
            changes=[],
            risk_notes=[],
            changed_files={"x": "y"},
        )
        db.add(p)
        db.commit()
        return str(p.id)

    def approve(pid_: str, h: dict[str, str], **body: Any) -> Any:
        return client.post(f"{API}/fix-proposals/{pid_}/approve", json=body, headers=h)

    p = proposal("unverified")
    r = approve(p, h_m)
    assert r.status_code == 409 and r.json()["error"]["code"] == "ACK_REQUIRED"
    assert approve(p, h_m, acknowledge_unverified=True).status_code == 202
    p = proposal("passed", major=True)
    assert approve(p, h_m).json()["error"]["code"] == "ACK_REQUIRED"
    assert approve(p, h_m, acknowledge_breaking_change=True).status_code == 202
    p = proposal("failed")
    assert approve(p, h_m, comment="please").status_code == 403
    assert approve(p, h_a).json()["error"]["code"] == "ACK_REQUIRED"  # justification required
    assert approve(p, h_a, comment="Known flaky test, verified manually.").status_code == 202
    assert any(a.action == "fix.admin_override" for a in db.scalars(select(AuditLog)))
    p = proposal("passed")
    assert approve(p, h_m, acknowledge_reviewed=False).json()["error"]["code"] == "ACK_REQUIRED"
    r = client.post(f"{API}/fix-proposals/{p}/reject", json={"reason": "not now"}, headers=h_m)
    assert r.json()["status"] == "rejected"
    assert approve(p, h_m).json()["error"]["code"] == "INVALID_TRANSITION"


def test_remediation_disabled(client: TestClient, users: Users, project: dict[str, Any]) -> None:
    r = client.post(
        f"{API}/projects/{project['id']}/fix-proposals",
        json={"finding_ids": [str(uuid.uuid4())]},
        headers=users.headers("maintainer"),
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "REMEDIATION_DISABLED"


@pytest.mark.nt("SM-07")
def test_pr_job_refuses_unapproved_and_db_enforces_invariants(
    db: Session,
    remediation_project: dict[str, Any],
    clock: FakeClock,
    session_factory: Any,
) -> None:
    pid = uuid.UUID(remediation_project["id"])
    p = FixProposal(
        project_id=pid,
        status="ready",
        validation_result="passed",
        changes=[],
        risk_notes=[],
        changed_files={"a": "b"},
        base_commit_sha="a" * 40,
    )
    db.add(p)
    db.commit()
    queue.enqueue(
        db,
        "pr_creation",
        payload={"proposal_id": str(p.id)},
        resource_type="fix_proposal",
        resource_id=p.id,
        max_attempts=1,
    )
    db.commit()
    assert _run(db, clock, session_factory, "pr_creation") == "failed"
    # Status 'approved' without an approver violates the CHECK constraint.
    p.status = "approved"
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    bad = FixProposal(
        project_id=pid, status="ready", validation_result="passed", changes=[], risk_notes=[], pr_branch="main"
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


@pytest.mark.at("FR-REM-07")
def test_git_adapter_has_no_merge_and_rejects_foreign_branches() -> None:
    assert not [m for m in dir(GitHubClient) if "merge" in m.lower()]
    gh = GitHubClient("t", transport=json_transport({}))
    for branch in ("main", "toolkit/fix/not-a-uuid", "feature/x"):
        with pytest.raises(BranchNotAllowedError):
            gh.create_fix_branch_with_files("o", "r", branch=branch, base_sha="a" * 40, files={}, message="m")
        with pytest.raises(BranchNotAllowedError):
            gh.delete_fix_branch("o", "r", branch)
    assert pr.branch_for(uuid.UUID(int=1)).startswith("toolkit/fix/")
