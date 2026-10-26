"""Scan job (WF-04): clone → inventory → providers → normalize → persist.

Provider failures are isolated: each provider's outcome is recorded and any failure makes
the scan ``partial`` instead of aborting the others (FR-DEP-07, NFR-REL-02). Repository
content is data only; nothing from the repository is executed here (CON-06).
"""

from __future__ import annotations

import json
import logging
import socket
import time
import tomllib
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from toolkit.core.config import get_settings
from toolkit.core.errors import JobError, JobErrorCode
from toolkit.core.http import UpstreamError
from toolkit.core.metrics import PROVIDER_RUNS
from toolkit.db.models import Job, Repository, Scan, ScanProviderRun
from toolkit.integrations.github import clone_url
from toolkit.integrations.osv import Advisory, OsvClient, parse_record
from toolkit.integrations.registry import PackageNotFound, RegistryClient
from toolkit.jobs.queue import register_terminal_hook
from toolkit.jobs.runner import JobContext, register
from toolkit.scanning import clone as clone_mod
from toolkit.scanning import semgrep as semgrep_mod
from toolkit.scanning import snippet as snippet_mod
from toolkit.scanning import trivy as trivy_mod
from toolkit.scanning.inventory import Dep, Inventory, build_inventory
from toolkit.scanning.normalize import (
    FindingDraft,
    RegistryFacts,
    code_findings,
    outdated_and_incompat_findings,
    vulnerability_findings,
)
from toolkit.scanning.persist import persist_findings, store_dependencies
from toolkit.services.credentials import load_token

log = logging.getLogger(__name__)


@dataclass
class ProviderOutcome:
    name: str
    status: str = "ok"  # ok | failed | skipped
    duration_ms: int = 0
    error: str | None = None
    tool_version: str | None = None
    db_info: dict[str, Any] | None = None
    data: Any = None


@dataclass
class Toolbox:
    """Injectable provider implementations (real ones by default; fakes in tests)."""

    clone: Callable[..., str] = clone_mod.clone_ref
    trivy: Callable[[str, int], trivy_mod.TrivyResult] = trivy_mod.scan
    semgrep: Callable[[Path, int], semgrep_mod.SemgrepResult] = semgrep_mod.scan
    osv_factory: Callable[[], OsvClient] = OsvClient
    registry_factory: Callable[[], RegistryClient] = RegistryClient
    allow_file_clone: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


TOOLBOX = Toolbox()


def _timed(name: str, fn: Callable[[], ProviderOutcome]) -> ProviderOutcome:
    started = time.monotonic()
    try:
        outcome = fn()
    except (trivy_mod.TrivyError, semgrep_mod.SemgrepError, UpstreamError) as exc:
        outcome = ProviderOutcome(name, "failed", error=str(exc)[:500])
    except Exception as exc:
        log.exception("provider crashed", extra={"provider": name})
        outcome = ProviderOutcome(name, "failed", error=f"{type(exc).__name__}: provider error")
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    PROVIDER_RUNS.labels(name, outcome.status).inc()
    return outcome


def _merge_inventories(native: Inventory, trivy_deps: list[Dep]) -> list[Dep]:
    inv = Inventory(deps=list(native.deps))
    known = {d.key for d in native.deps}
    for d in trivy_deps:
        if d.key not in known:
            inv.add(d)
    return inv.unique()


def run_osv(deps: list[Dep], factory: Callable[[], OsvClient]) -> ProviderOutcome:
    if not deps:
        return ProviderOutcome("osv", "skipped", error="no dependencies to query")
    unique = sorted({d.key for d in deps})
    client = factory()
    try:
        ids_per_query = client.query_batch([(e, n, v) for e, n, v in unique])
        records = client.get_vulns([pair for ids in ids_per_query for pair in ids])
    finally:
        client.close()
    by_dep: dict[tuple[str, str, str], list[Advisory]] = {}
    for key, ids in zip(unique, ids_per_query, strict=True):
        advisories = [parse_record(records[i], key[0], key[1]) for i, _mod in ids if i in records]
        if advisories:
            by_dep[key] = advisories
    return ProviderOutcome("osv", "ok", data=by_dep)


def run_registry(deps: list[Dep], factory: Callable[[], RegistryClient], parallelism: int) -> ProviderOutcome:
    direct = sorted({d.key: d for d in deps if d.scope == "direct"}.values(), key=lambda d: d.key)
    if not direct:
        return ProviderOutcome("registry", "skipped", error="no direct dependencies")
    client = factory()
    failures: list[str] = []

    def facts(dep: Dep) -> tuple[tuple[str, str, str], RegistryFacts | None]:
        try:
            latest = client.latest_info(dep.ecosystem, dep.name)
            installed = client.version(dep.ecosystem, dep.name, dep.version)
        except PackageNotFound:
            return dep.key, None
        except UpstreamError as exc:
            failures.append(f"{dep.name}: {exc}")
            return dep.key, None
        source = (
            f"https://www.npmjs.com/package/{dep.name}"
            if dep.ecosystem == "npm"
            else f"https://pypi.org/project/{dep.name}/"
        )
        return dep.key, RegistryFacts(
            latest=latest.version,
            latest_deprecated=latest.deprecated,
            installed_deprecated=installed.deprecated if installed.exists else None,
            latest_runtime=latest.runtime_constraint,
            source_url=source,
        )

    try:
        with ThreadPoolExecutor(max_workers=parallelism, thread_name_prefix="registry") as pool:
            results = dict(pool.map(facts, direct))
    finally:
        client.close()
    if failures and len(failures) >= max(1, len(direct) // 2):
        # Too many lookups failed: never report "up to date" from missing data (FR-DEP-05).
        return ProviderOutcome(
            "registry", "failed", error=f"{len(failures)} registry lookups failed; first: {failures[0][:200]}"
        )
    data = {k: v for k, v in results.items() if v is not None}
    outcome = ProviderOutcome("registry", "ok", data=data)
    if failures:
        outcome.status = "failed"
        outcome.error = f"{len(failures)} of {len(direct)} lookups failed; results incomplete"
    return outcome


def project_runtimes(repo: Path, manifests: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for rel in manifests:
        folder = (repo / rel).parent
        constraint = None
        pj = folder / "package.json"
        pp = folder / "pyproject.toml"
        try:
            if pj.is_file() and not pj.is_symlink():
                engines = json.loads(pj.read_text(encoding="utf-8")).get("engines") or {}
                constraint = engines.get("node") if isinstance(engines, dict) else None
            elif pp.is_file() and not pp.is_symlink():
                constraint = tomllib.loads(pp.read_text(encoding="utf-8")).get("project", {}).get("requires-python")
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            constraint = None
        out[rel] = constraint if isinstance(constraint, str) else None
    return out


def analyze(
    repo: Path, providers: list[str], ctx: JobContext | None, toolbox: Toolbox, timeout: int
) -> tuple[list[Dep], list[FindingDraft], list[ProviderOutcome], list[str]]:
    """Run the providers against a checked-out workspace. Pure with respect to the database."""
    s = get_settings()
    native = build_inventory(repo)
    if ctx:
        ctx.stage("providers")
    outcomes: dict[str, ProviderOutcome] = {}
    deadline = time.monotonic() + timeout
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="provider") as pool:
        futures: dict[str, Future[ProviderOutcome]] = {}
        if "semgrep" in providers:
            futures["semgrep"] = pool.submit(
                _timed,
                "semgrep",
                lambda: ProviderOutcome(
                    "semgrep", "ok", data=toolbox.semgrep(repo, min(s.semgrep_timeout_seconds, timeout))
                ),
            )
        if "trivy" in providers:

            def trivy_run() -> ProviderOutcome:
                result = toolbox.trivy(str(repo), timeout)
                return ProviderOutcome("trivy", "ok", tool_version=result.version, db_info=result.db_info, data=result)

            futures["trivy"] = pool.submit(_timed, "trivy", trivy_run)
        trivy_out = None
        if "trivy" in futures:
            try:
                trivy_out = futures["trivy"].result(timeout=max(1, deadline - time.monotonic()))
            except TimeoutError as exc:
                raise JobError(JobErrorCode.SCAN_TIMEOUT, f"scan exceeded {timeout}s") from exc
        if trivy_out:
            outcomes["trivy"] = trivy_out
        trivy_result: trivy_mod.TrivyResult | None = trivy_out.data if trivy_out and trivy_out.status == "ok" else None
        deps = _merge_inventories(native, trivy_result.deps if trivy_result else [])
        if ctx:
            ctx.check_cancelled()
        if "osv" in providers:
            futures["osv"] = pool.submit(_timed, "osv", lambda: run_osv(deps, toolbox.osv_factory))
        if "registry" in providers:
            futures["registry"] = pool.submit(
                _timed, "registry", lambda: run_registry(deps, toolbox.registry_factory, s.provider_parallelism)
            )
        for name, fut in futures.items():
            if name in outcomes:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise JobError(JobErrorCode.SCAN_TIMEOUT, f"scan exceeded {timeout}s")
            try:
                outcomes[name] = fut.result(timeout=remaining)
            except TimeoutError as exc:
                raise JobError(JobErrorCode.SCAN_TIMEOUT, f"scan exceeded {timeout}s") from exc

    if ctx:
        ctx.stage("normalize")
    osv_data = outcomes["osv"].data if "osv" in outcomes and outcomes["osv"].status == "ok" else {}
    drafts = vulnerability_findings(deps, trivy_result.vulns if trivy_result else [], osv_data or {})
    reg = outcomes.get("registry")
    reg_data = reg.data if reg and reg.data else {}
    drafts += outdated_and_incompat_findings(deps, reg_data, project_runtimes(repo, native.manifests), drafts)
    sem = outcomes.get("semgrep")
    if sem and sem.status == "ok":
        matches = sem.data.matches
        snippets = {i: snippet_mod.extract(repo, m.path, m.line_start, m.line_end) for i, m in enumerate(matches)}
        hashes = {
            i: snippet_mod.normalized_match_hash(repo, m.path, m.line_start, m.line_end) for i, m in enumerate(matches)
        }
        drafts += code_findings(matches, snippets, hashes)
        sem.tool_version = sem.data.version
    for name in providers:
        outcomes.setdefault(name, ProviderOutcome(name, "skipped", error="not run"))
    return deps, drafts, [outcomes[p] for p in sorted(outcomes)], native.warnings


def _worker_prefix() -> str:
    return f"scan-{socket.gethostname()[:30]}-"


@register("scan")
def handle_scan(ctx: JobContext, toolbox: Toolbox | None = None) -> str:
    toolbox = toolbox or TOOLBOX
    s = get_settings()
    scan_id = uuid.UUID(ctx.payload["scan_id"])
    with ctx.session() as db:
        scan = db.get(Scan, scan_id, with_for_update=True)
        if scan is None:
            raise JobError(JobErrorCode.INTERNAL_ERROR, "scan row missing")
        repo = db.get(Repository, scan.repository_id) if scan.repository_id else None
        if repo is None:
            raise JobError(JobErrorCode.CLONE_FAILED, "repository is no longer connected")
        token = load_token(db, repo.credential_id)
        scan.status = "running"
        scan.started_at = scan.started_at or ctx.clock.now()
        url = clone_url(repo.owner, repo.name) if not toolbox.allow_file_clone else repo.url
        ref, providers = scan.ref, list(scan.providers)

    workspace = Path(s.work_dir) / f"{_worker_prefix()}{scan_id}-{ctx.attempt}"
    started = time.monotonic()
    try:
        ctx.stage("clone")
        commit = toolbox.clone(
            url,
            ref,
            workspace,
            token=token,
            timeout=s.clone_timeout_seconds,
            max_mb=s.clone_max_mb,
            allow_file_protocol=toolbox.allow_file_clone,
        )
        token = None  # drop the plaintext token as soon as it is no longer needed
        with ctx.session() as db:
            db.get(Scan, scan_id).commit_sha = commit  # type: ignore[union-attr]
        ctx.stage("dependency_inventory")
        remaining = max(30, s.scan_timeout_seconds - int(time.monotonic() - started))
        deps, drafts, outcomes, warnings = analyze(workspace, providers, ctx, toolbox, remaining)
        ctx.stage("persist")
        partial = any(o.status == "failed" for o in outcomes)
        with ctx.session() as db:
            scan = db.get(Scan, scan_id, with_for_update=True)
            assert scan is not None
            _store_provider_runs(db, scan_id, outcomes)
            dep_count = store_dependencies(db, scan_id, deps)
            ok = {o.name for o in outcomes if o.status in ("ok", "skipped")}
            summary = persist_findings(db, scan, drafts, ok_providers=ok, partial=partial, now=ctx.clock.now())
            summary["dependencies"] = dep_count
            summary["warnings"] = warnings[:20]
            summary["failed_providers"] = [o.name for o in outcomes if o.status == "failed"]
            scan.summary = summary
            scan.status = "partial" if partial else "succeeded"
            scan.finished_at = ctx.clock.now()
        return "partial" if partial else "succeeded"
    except JobError as exc:
        if exc.code == JobErrorCode.CLONE_FAILED and not exc.retryable:
            _mark_scan(ctx, scan_id, "failed", exc.code.value, exc.message)
        raise
    finally:
        clone_mod.cleanup(workspace)


def _store_provider_runs(db: Session, scan_id: uuid.UUID, outcomes: list[ProviderOutcome]) -> None:
    existing = {r.provider: r for r in db.scalars(select(ScanProviderRun).where(ScanProviderRun.scan_id == scan_id))}
    for o in outcomes:
        row = existing.get(o.name) or ScanProviderRun(scan_id=scan_id, provider=o.name)
        row.status, row.duration_ms, row.error = o.status, o.duration_ms, o.error
        row.tool_version, row.db_info = o.tool_version, o.db_info
        db.add(row)


def _mark_scan(ctx: JobContext, scan_id: uuid.UUID, status: str, code: str, message: str) -> None:
    with ctx.session() as db:
        scan = db.get(Scan, scan_id, with_for_update=True)
        if scan and scan.status in ("queued", "running"):
            scan.status, scan.error_code, scan.error_message = status, code, message[:500]
            scan.finished_at = ctx.clock.now()


def _scan_terminal(db: Session, job: Job, status: str) -> None:
    scan = db.get(Scan, job.resource_id) if job.resource_id else None
    if scan and scan.status in ("queued", "running"):
        scan.status = status
        scan.error_code = job.error_code
        scan.error_message = job.error_message
        scan.finished_at = job.finished_at


register_terminal_hook("scan", _scan_terminal)
