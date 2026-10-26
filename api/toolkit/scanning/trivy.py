"""Trivy filesystem scan (IF-07, TRD §5.1 step 2).

Fixed argument vector with ``--scanners vuln`` explicitly: Trivy's default also enables
secret scanning, which the Toolkit deliberately avoids (SECURITY §11).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from toolkit.core.config import get_settings
from toolkit.core.process import run
from toolkit.scanning.inventory import Dep
from toolkit.scanning.versions import split_fixed_versions

ECOSYSTEM_BY_TYPE = {
    "npm": "npm",
    "yarn": "npm",
    "pnpm": "npm",
    "node-pkg": "npm",
    "bun": "npm",
    "pip": "pypi",
    "pipenv": "pypi",
    "poetry": "pypi",
    "uv": "pypi",
    "python-pkg": "pypi",
}
_SEVERITY = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


class TrivyError(Exception):
    pass


@dataclass
class TrivyVuln:
    ecosystem: str
    name: str
    version: str
    manifest_path: str
    vuln_id: str
    severity: str | None
    title: str | None
    fixed_versions: list[str]
    primary_url: str | None
    references: list[str]
    cvss_vector: str | None


@dataclass
class TrivyResult:
    deps: list[Dep] = field(default_factory=list)
    vulns: list[TrivyVuln] = field(default_factory=list)
    version: str | None = None
    db_info: dict[str, Any] | None = None


def build_argv(target: str, output_file: str | None = None) -> list[str]:
    s = get_settings()
    argv = [
        "trivy",
        "fs",
        "--quiet",
        "--format",
        "json",
        "--scanners",
        "vuln",
        "--list-all-pkgs",
        "--pkg-types",
        "library",
        "--cache-dir",
        s.trivy_cache_dir,
        "--timeout",
        f"{max(60, s.scan_timeout_seconds // 2)}s",
        "--skip-dirs",
        "**/node_modules",
        "--skip-dirs",
        "**/.venv",
    ]
    if s.trivy_skip_db_update:
        argv += ["--skip-db-update", "--skip-java-db-update"]
    if output_file:
        argv += ["--output", output_file]
    argv.append(target)
    return argv


def parse(report: dict[str, Any]) -> TrivyResult:
    out = TrivyResult()
    for res in report.get("Results") or []:
        eco = ECOSYSTEM_BY_TYPE.get(str(res.get("Type", "")).lower())
        if eco is None:
            continue
        target = str(res.get("Target", ""))
        for pkg in res.get("Packages") or []:
            name, version = pkg.get("Name"), pkg.get("Version")
            if not name or not version:
                continue
            rel = str(pkg.get("Relationship", "")).lower()
            scope = "direct" if rel in ("direct", "root") else "transitive"
            out.deps.append(Dep(eco, name, version, scope, target))
        for v in res.get("Vulnerabilities") or []:
            cvss = None
            for src in (v.get("CVSS") or {}).values():
                if isinstance(src, dict) and src.get("V3Vector"):
                    cvss = str(src["V3Vector"])
                    break
            out.vulns.append(
                TrivyVuln(
                    ecosystem=eco,
                    name=str(v.get("PkgName")),
                    version=str(v.get("InstalledVersion")),
                    manifest_path=target,
                    vuln_id=str(v.get("VulnerabilityID")),
                    severity=_SEVERITY.get(str(v.get("Severity", "")).upper()),
                    title=v.get("Title"),
                    fixed_versions=split_fixed_versions(v.get("FixedVersion")),
                    primary_url=v.get("PrimaryURL"),
                    references=list(v.get("References") or [])[:20],
                    cvss_vector=cvss,
                )
            )
    return out


def scan(path: str, timeout: int) -> TrivyResult:
    result = run(build_argv(path), timeout=timeout, cwd=path)
    if result.timed_out:
        raise TrivyError(f"timeout after {timeout}s")
    if result.exit_code != 0:
        tail = result.stderr.strip().splitlines()[-1:] or ["trivy failed"]
        raise TrivyError(tail[0][:300])
    try:
        report = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise TrivyError("trivy produced invalid JSON") from exc
    parsed = parse(report)
    parsed.version, parsed.db_info = tool_info()
    return parsed


def tool_info() -> tuple[str | None, dict[str, Any] | None]:
    """Trivy version and vulnerability DB freshness, shown to users as data age."""
    s = get_settings()
    res = run(["trivy", "version", "--format", "json", "--cache-dir", s.trivy_cache_dir], timeout=30)
    if not res.ok:
        return None, None
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return None, None
    db = data.get("VulnerabilityDB") or {}
    return data.get("Version"), {
        "updated_at": db.get("UpdatedAt"),
        "next_update": db.get("NextUpdate"),
        "downloaded_at": db.get("DownloadedAt"),
    } if db else None
