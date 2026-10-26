"""Fix-proposal validation pipeline (WF-06, FR-REM-01..05, FR-REM-12, TRD §8).

Stages (each a separate sandbox container sharing one ephemeral workspace volume):

1. baseline install  — network on, lifecycle scripts disabled
2. baseline tests    — network **off**
3. apply change      — npm: lockfile-only resolution with scripts disabled; PyPI: deterministic
                       text edit of the pinned requirement (done in the worker, no execution)
4. scope check       — every changed path must be a planned manifest/lockfile, else abort
5. post-change install + tests (tests with network **off**)
6. delta re-scan     — inventory of the resulting lockfile + OSV, compared with the targets
"""

from __future__ import annotations

import difflib
import json
import logging
import posixpath
import socket
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from toolkit.core.config import get_settings
from toolkit.core.errors import JobError, JobErrorCode
from toolkit.core.http import UpstreamError
from toolkit.core.metrics import SANDBOX_STAGES
from toolkit.core.validators import allowed_test_argv
from toolkit.db.models import Finding, FixProposal, FixProposalFinding, Job, Repository, ValidationRun
from toolkit.integrations.github import clone_url
from toolkit.integrations.osv import OsvClient, parse_record
from toolkit.jobs.queue import register_terminal_hook
from toolkit.jobs.runner import JobContext, register
from toolkit.remediation.plan import Change, PlanError, allowed_paths, apply_requirements_change, build_plan
from toolkit.remediation.sandbox import DockerSandbox, SandboxRuntime, SandboxUnavailable, StageResult
from toolkit.scanning import clone as clone_mod
from toolkit.scanning.inventory import build_inventory
from toolkit.scanning.versions import compare

log = logging.getLogger(__name__)

HASH_FILE = ".toolkit-hashes"
HASH_CMD = (
    "find . -type f -not -path './node_modules/*' -not -path './.venv/*' -not -path './.git/*' "
    f"-not -name '*.pyc' -not -name '{HASH_FILE}*' -exec sha256sum {{}} + > "
)
_SDIST_MARKERS = ("Could not find a version that satisfies", "No matching distribution found")


@dataclass
class RemediationToolbox:
    sandbox_factory: Callable[[], SandboxRuntime] = DockerSandbox
    clone: Callable[..., str] = clone_mod.clone_ref
    osv_factory: Callable[[], OsvClient] = OsvClient
    allow_file_clone: bool = False


TOOLBOX = RemediationToolbox()


@dataclass
class PipelineReport:
    runs: list[dict[str, Any]] = field(default_factory=list)
    changed_files: dict[str, str] = field(default_factory=dict)
    diff: str = ""
    validation_result: str = "not_run"
    delta_scan: dict[str, Any] = field(default_factory=dict)
    risk_notes: list[str] = field(default_factory=list)


def _record(
    report: PipelineReport,
    stage: str,
    status: str,
    result: StageResult | None,
    started: datetime,
    finished: datetime,
    note: str | None = None,
) -> None:
    SANDBOX_STAGES.labels(stage, status).inc()
    report.runs.append(
        {
            "stage": stage,
            "status": status,
            "exit_code": result.exit_code if result else None,
            "duration_s": result.duration_s if result else 0.0,
            "output_tail": (note + "\n" if note else "") + (result.output_tail if result else ""),
            "started_at": started,
            "finished_at": finished,
        }
    )


def _parse_hashes(output: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and len(parts[0]) == 64:
            out[posixpath.normpath(parts[1].strip())] = parts[0]
    return out


def _workspace_hashes(sandbox: SandboxRuntime, ws: str, label: str) -> dict[str, str]:
    """SHA-256 of every workspace file (excluding installed dependencies), written to a file in
    the workspace so large repositories are not truncated by the log tail."""
    name = f"{HASH_FILE}-{label}"
    res = sandbox.run(ws, "busybox:1.37.0", ["sh", "-c", HASH_CMD + name], network=False, timeout=300)
    content = sandbox.read_files(ws, [name]).get(name)
    if not res.ok or content is None:
        raise JobError(JobErrorCode.SANDBOX_UNAVAILABLE, "could not inventory the sandbox workspace")
    return _parse_hashes(content)


def _install_cmds(changes: list[Change], images: dict[str, str]) -> list[tuple[str, list[str]]]:
    cmds: list[tuple[str, list[str]]] = []
    npm_dirs = sorted({posixpath.dirname(c.lockfile_path) or "." for c in changes if c.ecosystem == "npm"})
    for d in npm_dirs:
        cmds.append((images["npm"], ["npm", "ci", "--prefix", d, "--ignore-scripts", "--no-audit", "--no-fund"]))
    req_files = sorted({c.lockfile_path for c in changes if c.ecosystem == "pypi"})
    if req_files:
        cmds.append((images["pypi"], ["python", "-m", "venv", "/work/.venv"]))
        argv = ["/work/.venv/bin/pip", "install", "--no-input", "--disable-pip-version-check"]
        if not get_settings().sandbox_allow_sdist:
            argv += ["--only-binary", ":all:"]
        for r in req_files:
            argv += ["-r", r]
        cmds.append((images["pypi"], argv))
    return cmds


def _test_cmd(test_command: str | None, changes: list[Change], images: dict[str, str]) -> tuple[str, list[str]] | None:
    if not test_command:
        return None
    argv = allowed_test_argv(test_command)
    if argv is None:
        return None
    if argv[0] == "python":
        has_venv = any(c.ecosystem == "pypi" for c in changes)
        return images["pypi"], (["/work/.venv/bin/python", "-m", "pytest", "-q"] if has_venv else list(argv))
    return images["npm"], list(argv)


def run_pipeline(
    sandbox: SandboxRuntime,
    workspace_root: Path,
    changes: list[Change],
    test_command: str | None,
    now: Callable[[], datetime],
    osv_factory: Callable[[], OsvClient],
    check: Callable[[str], None],
) -> PipelineReport:
    s = get_settings()
    timeout = s.sandbox_stage_timeout_seconds
    images = {"npm": s.sandbox_node_image, "pypi": s.sandbox_python_image}
    report = PipelineReport()
    allowed = allowed_paths(changes)
    ws = sandbox.create_workspace()
    try:
        sandbox.upload(ws, workspace_root)
        installs = _install_cmds(changes, images)
        test = _test_cmd(test_command, changes, images)

        # 1-2. Baseline.
        check("baseline")
        baseline_status = "skipped"
        t0 = now()
        install_ok = True
        for image, argv in installs:
            res = sandbox.run(ws, image, argv, network=True, timeout=timeout)
            if not res.ok:
                install_ok = False
                _record(report, "baseline", "error", res, t0, now(), "Baseline dependency install failed.")
                break
        if install_ok:
            if test is None:
                _record(
                    report,
                    "baseline",
                    "skipped",
                    None,
                    t0,
                    now(),
                    "No allowlisted test command is configured for this repository.",
                )
            else:
                res = sandbox.run(ws, test[0], test[1], network=False, timeout=timeout)
                baseline_status = "passed" if res.ok else "failed"
                _record(report, "baseline", baseline_status, res, t0, now())
        else:
            baseline_status = "error"

        # 3-4. Apply with scope check.
        check("apply")
        t0 = now()
        hashes_before = _workspace_hashes(sandbox, ws, "before")
        originals = {
            p: (workspace_root / p).read_text(encoding="utf-8") if (workspace_root / p).is_file() else ""
            for p in sorted(allowed)
        }
        apply_res = _apply(sandbox, ws, changes, originals, images, timeout)
        if apply_res is not None and not apply_res.ok:
            out = apply_res.output_tail
            _record(report, "apply", "failed", apply_res, t0, now())
            if any(m in out for m in _SDIST_MARKERS):
                raise JobError(JobErrorCode.SDIST_BUILD_REQUIRED, "a package needs a source build")
            raise JobError(JobErrorCode.TESTS_FAILED, "dependency resolution failed in the sandbox")
        hashes_after = _workspace_hashes(sandbox, ws, "after")
        changed = {p for p in set(hashes_before) | set(hashes_after) if hashes_before.get(p) != hashes_after.get(p)}
        violations = sorted(changed - allowed)
        if violations:
            _record(report, "apply", "failed", apply_res, t0, now(), f"Changed paths outside scope: {violations[:10]}")
            raise JobError(
                JobErrorCode.DIFF_SCOPE_VIOLATION,
                f"the change touched {len(violations)} path(s) outside manifests/lockfiles",
            )
        new_contents = sandbox.read_files(ws, sorted(changed))
        report.changed_files = {p: c for p, c in new_contents.items() if c is not None}
        report.diff = unified_diff(originals, report.changed_files)
        _record(
            report,
            "apply",
            "passed",
            apply_res,
            t0,
            now(),
            f"Changed files: {', '.join(sorted(report.changed_files)) or 'none'}",
        )
        if not report.changed_files:
            raise JobError(JobErrorCode.PLAN_INVALID, "the change produced no file modifications")

        # 5. Post-change install + tests.
        check("post_change")
        t0 = now()
        post_status = "skipped"
        for image, argv in installs:
            res = sandbox.run(ws, image, argv, network=True, timeout=timeout)
            if not res.ok:
                _record(report, "post_change", "failed", res, t0, now(), "Post-change dependency install failed.")
                if any(m in res.output_tail for m in _SDIST_MARKERS):
                    raise JobError(JobErrorCode.SDIST_BUILD_REQUIRED, "a package needs a source build")
                post_status = "failed"
                break
        if post_status != "failed":
            if test is None:
                _record(report, "post_change", "skipped", None, t0, now(), "No test command configured.")
            else:
                res = sandbox.run(ws, test[0], test[1], network=False, timeout=timeout)
                post_status = "passed" if res.ok else "failed"
                _record(report, "post_change", post_status, res, t0, now())
    finally:
        sandbox.destroy(ws)

    # 6. Delta re-scan of the resulting lockfiles (read-only, in the worker).
    check("rescan")
    t0 = now()
    report.delta_scan = delta_scan(workspace_root, report.changed_files, changes, osv_factory)
    delta_ok = (
        report.delta_scan.get("status") == "ok"
        and not report.delta_scan.get("unresolved")
        and not report.delta_scan.get("new_findings")
    )
    report.runs.append(
        {
            "stage": "rescan",
            "status": "passed" if delta_ok else ("error" if report.delta_scan.get("status") != "ok" else "failed"),
            "exit_code": None,
            "duration_s": 0.0,
            "output_tail": json.dumps({k: v for k, v in report.delta_scan.items() if k != "status"})[:8000],
            "started_at": t0,
            "finished_at": now(),
        }
    )

    if post_status == "failed" and baseline_status == "passed":
        report.validation_result = "failed"
    elif baseline_status != "passed" or report.delta_scan.get("status") != "ok":
        report.validation_result = "unverified"
    elif not delta_ok:
        report.validation_result = "failed"
    else:
        report.validation_result = "passed"
    report.risk_notes = risk_notes(changes, report, baseline_status, post_status)
    return report


def _apply(
    sandbox: SandboxRuntime,
    ws: str,
    changes: list[Change],
    originals: dict[str, str],
    images: dict[str, str],
    timeout: int,
) -> StageResult | None:
    last: StageResult | None = None
    edits: dict[str, str] = {}
    for c in changes:
        if c.ecosystem == "pypi":
            current = edits.get(c.lockfile_path, originals.get(c.lockfile_path, ""))
            try:
                edits[c.lockfile_path] = apply_requirements_change(current, c.package, c.from_version, c.to_version)
            except PlanError as exc:
                raise JobError(JobErrorCode.PLAN_INVALID, str(exc)) from exc
    npm_direct = [c for c in changes if c.ecosystem == "npm" and c.scope == "direct"]
    npm_transitive = [c for c in changes if c.ecosystem == "npm" and c.scope != "direct"]
    for c in npm_transitive:
        # Transitive packages are pinned through package.json "overrides" (manifest change only).
        manifest = edits.get(c.manifest_path, originals.get(c.manifest_path, ""))
        try:
            data = json.loads(manifest or "{}")
        except json.JSONDecodeError as exc:
            raise JobError(JobErrorCode.PLAN_INVALID, f"{c.manifest_path} is not valid JSON") from exc
        overrides = data.setdefault("overrides", {})
        if not isinstance(overrides, dict):
            raise JobError(JobErrorCode.PLAN_INVALID, "package.json overrides has an unexpected shape")
        overrides[c.package] = c.to_version
        indent = 2 if '\n  "' in manifest else 4 if '\n    "' in manifest else 2
        edits[c.manifest_path] = json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
    if edits:
        sandbox.write_files(ws, edits)
    for d in sorted({posixpath.dirname(c.lockfile_path) or "." for c in npm_direct}):
        specs = [f"{c.package}@{c.to_version}" for c in npm_direct if (posixpath.dirname(c.lockfile_path) or ".") == d]
        last = sandbox.run(
            ws,
            images["npm"],
            [
                "npm",
                "install",
                "--prefix",
                d,
                "--package-lock-only",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                "--",
                *specs,
            ],
            network=True,
            timeout=timeout,
        )
        if not last.ok:
            return last
    for d in sorted({posixpath.dirname(c.lockfile_path) or "." for c in npm_transitive}):
        last = sandbox.run(
            ws,
            images["npm"],
            ["npm", "install", "--prefix", d, "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"],
            network=True,
            timeout=timeout,
        )
        if not last.ok:
            return last
    return last


def unified_diff(originals: dict[str, str], changed: dict[str, str]) -> str:
    chunks = []
    for path in sorted(changed):
        old, new = originals.get(path, ""), changed[path]
        if old == new:
            continue
        lines = difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}", n=3
        )
        body = "".join(lines)
        chunks.append(f"diff --git a/{path} b/{path}\n{body}" + ("" if body.endswith("\n") else "\n"))
    return "".join(chunks)


def delta_scan(
    root: Path, changed_files: dict[str, str], changes: list[Change], osv_factory: Callable[[], OsvClient]
) -> dict[str, Any]:
    """Compare the inventory before/after and query OSV for every package version that changed."""
    before = {(d.key, d.manifest_path) for d in build_inventory(root).unique()}
    with tempfile.TemporaryDirectory(prefix="delta-") as tmp:
        tmp_root = Path(tmp)
        for path in {d[1] for d in before} | set(changed_files):
            src = root / path
            dest = tmp_root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            if path in changed_files:
                dest.write_text(changed_files[path], encoding="utf-8")
            elif src.is_file():
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        for c in changes:  # sibling manifests are needed for direct/transitive detection
            src = root / c.manifest_path
            if src.is_file() and c.manifest_path not in changed_files:
                (tmp_root / c.manifest_path).parent.mkdir(parents=True, exist_ok=True)
                (tmp_root / c.manifest_path).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        after_deps = build_inventory(tmp_root).unique()
    after = {(d.key, d.manifest_path) for d in after_deps}
    added = sorted({k for k, _ in after - before})
    resolved_ids: list[str] = []
    unresolved: list[dict[str, Any]] = []
    after_keys = {k for k, _ in after}
    for c in changes:
        name = c.package.lower().replace("_", "-") if c.ecosystem == "pypi" else c.package
        still_old = any(k[0] == c.ecosystem and k[1] == name and k[2] == c.from_version for k in after_keys)
        has_new = any(
            k[0] == c.ecosystem and k[1] == name and compare(c.ecosystem, c.to_version, k[2]) in (0, -1)
            for k in after_keys
        )
        if still_old or not has_new:
            unresolved.append({"package": c.package, "expected": c.to_version, "still_present": c.from_version})
        else:
            resolved_ids += c.finding_ids
    new_findings: list[dict[str, Any]] = []
    if added:
        client = osv_factory()
        try:
            ids = client.query_batch(added)
            records = client.get_vulns([p for row in ids for p in row])
        except UpstreamError as exc:
            return {
                "status": "failed",
                "error": str(exc)[:300],
                "resolved_finding_ids": [],
                "new_findings": [],
                "unresolved": unresolved,
            }
        finally:
            client.close()
        targeted = {(c.ecosystem, c.package) for c in changes}
        for key, row in zip(added, ids, strict=True):
            for vid, _m in row:
                adv = parse_record(records[vid], key[0], key[1])
                if adv.withdrawn:
                    continue
                if adv.severity in ("critical", "high") or (key[0], key[1]) in targeted:
                    new_findings.append(
                        {
                            "ecosystem": key[0],
                            "package": key[1],
                            "version": key[2],
                            "advisory": adv.id,
                            "severity": adv.severity,
                        }
                    )
    return {
        "status": "ok",
        "resolved_finding_ids": resolved_ids,
        "unresolved": unresolved,
        "new_findings": new_findings,
        "changed_packages": [{"ecosystem": e, "package": n, "version": v} for e, n, v in added][:200],
    }


def risk_notes(changes: list[Change], report: PipelineReport, baseline: str, post: str) -> list[str]:
    notes: list[str] = []
    for c in changes:
        if c.bump == "major":
            notes.append(
                f"{c.package} {c.from_version} → {c.to_version} is a major version change and may break compatibility."
            )
        if c.scope != "direct" and c.ecosystem == "npm":
            notes.append(f"{c.package} is transitive; it is pinned through package.json overrides.")
    if all(c.scope != "direct" for c in changes if c.ecosystem == "npm") and any(c.ecosystem == "npm" for c in changes):
        notes.append("Transitive dependency updated; lockfile-only change apart from overrides.")
    if baseline == "skipped":
        notes.append("No test command is configured, so the change was not exercised by tests.")
    elif baseline in ("failed", "error"):
        notes.append("Baseline tests were missing or failing before the change; passing results prove little.")
    if post == "failed":
        notes.append("Tests failed after the change.")
    notes.append(
        "Install scripts were disabled in the sandbox; packages that need install-time builds may behave differently."
    )
    changed = report.delta_scan.get("changed_packages") or []
    if len(changed) > len(changes):
        notes.append(f"{len(changed)} package versions changed in total (including transitive updates).")
    if report.delta_scan.get("new_findings"):
        notes.append(
            f"Delta scan reports {len(report.delta_scan['new_findings'])} advisory match(es) on changed packages."
        )
    if report.delta_scan.get("unresolved"):
        notes.append("Some targeted versions are still present after the change.")
    return notes


def _worker_prefix() -> str:
    return f"scan-{socket.gethostname()[:30]}-fix-"


@register("fix_proposal")
def handle_fix_proposal(ctx: JobContext) -> str:
    s = get_settings()
    toolbox = TOOLBOX
    proposal_id = uuid.UUID(ctx.payload["proposal_id"])
    with ctx.session() as db:
        p = db.get(FixProposal, proposal_id, with_for_update=True)
        if p is None:
            raise JobError(JobErrorCode.INTERNAL_ERROR, "proposal missing")
        finding_ids = list(
            db.scalars(select(FixProposalFinding.finding_id).where(FixProposalFinding.fix_proposal_id == p.id))
        )
        findings = list(db.scalars(select(Finding).where(Finding.id.in_(finding_ids))))
        repo = db.scalar(select(Repository).where(Repository.project_id == p.project_id))
        if repo is None:
            raise JobError(JobErrorCode.PLAN_INVALID, "repository is no longer connected")
        try:
            changes = build_plan(findings)
        except PlanError as exc:
            raise JobError(JobErrorCode.PLAN_INVALID, str(exc)) from exc
        p.changes = [c.as_dict() for c in changes]
        p.has_major_bump = any(c.bump == "major" for c in changes)
        p.status = "validating"
        base_sha = p.base_commit_sha
        if not base_sha:
            raise JobError(JobErrorCode.PLAN_INVALID, "no scanned commit is recorded for these findings")
        from toolkit.services.credentials import load_token

        token = load_token(db, repo.credential_id)
        url = repo.url if toolbox.allow_file_clone else clone_url(repo.owner, repo.name)
        test_command = repo.test_command

    ctx.stage("sandbox")
    try:
        sandbox = toolbox.sandbox_factory()
    except SandboxUnavailable as exc:
        raise JobError(JobErrorCode.SANDBOX_UNAVAILABLE, str(exc)) from exc
    workspace = Path(s.work_dir) / f"{_worker_prefix()}{proposal_id}-{ctx.attempt}"
    try:
        toolbox.clone(
            url,
            base_sha,
            workspace,
            token=token,
            timeout=s.clone_timeout_seconds,
            max_mb=s.clone_max_mb,
            allow_file_protocol=toolbox.allow_file_clone,
        )
        token = None  # never passed to the sandbox
        report = run_pipeline(sandbox, workspace, changes, test_command, ctx.clock.now, toolbox.osv_factory, ctx.stage)
    finally:
        clone_mod.cleanup(workspace)

    with ctx.session() as db:
        p = db.get(FixProposal, proposal_id, with_for_update=True)
        assert p is not None
        _store_runs(db, proposal_id, report.runs)
        p.diff = report.diff
        p.changed_files = report.changed_files
        p.validation_result = report.validation_result
        p.delta_scan = report.delta_scan
        p.risk_notes = report.risk_notes
        p.status = "ready"
        p.stage = None
    return "succeeded"


def _store_runs(db: Session, proposal_id: uuid.UUID, runs: list[dict[str, Any]]) -> None:
    for r in runs:
        db.add(ValidationRun(fix_proposal_id=proposal_id, **r))


def _proposal_terminal(db: Session, job: Job, status: str) -> None:
    p = db.get(FixProposal, job.resource_id) if job.resource_id else None
    if p and p.status in ("pending", "validating"):
        p.status = "failed"
        p.error_code = job.error_code
        p.error_message = job.error_message


register_terminal_hook("fix_proposal", _proposal_terminal)
