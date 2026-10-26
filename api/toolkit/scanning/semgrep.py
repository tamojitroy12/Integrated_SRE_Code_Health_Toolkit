"""Semgrep static analysis (IF-08, FR-SAST-01/03).

Fixed argument vector, metrics off, version check off, per-file timeout, file-size cap and
default exclusions. Snippets are read from the clone (not from Semgrep output) and bounded.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from toolkit.core.config import get_settings
from toolkit.core.process import run

BUNDLED_RULES = Path(__file__).parent / "rules" / "toolkit-rules.yml"
DEFAULT_EXCLUDES = [
    ".git",
    "node_modules",
    "dist",
    "build",
    "venv",
    ".venv",
    "env",
    ".tox",
    "vendor",
    "__pycache__",
    "site-packages",
    ".next",
    "coverage",
    "*.min.js",
]
SEVERITY_MAP = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}


class SemgrepError(Exception):
    pass


@dataclass
class CodeMatch:
    rule_id: str
    path: str
    line_start: int
    line_end: int
    message: str
    severity: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SemgrepResult:
    matches: list[CodeMatch] = field(default_factory=list)
    errors: int = 0
    version: str | None = None


def rules_config(repo_rules_dir: Path | None = None) -> list[str]:
    s = get_settings()
    configs = [str(BUNDLED_RULES)] if s.semgrep_rules == "bundled" else [s.semgrep_rules]
    if repo_rules_dir is not None and repo_rules_dir.is_dir():
        configs.append(str(repo_rules_dir))  # FR-SAST-02 explicit opt-in only
    return configs


def build_argv(configs: list[str]) -> list[str]:
    s = get_settings()
    argv = [
        "semgrep",
        "scan",
        "--json",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        "--timeout",
        "10",
        "--max-target-bytes",
        str(s.semgrep_max_file_bytes),
        "--max-memory",
        "1500",
        "--jobs",
        "2",
    ]
    for c in configs:
        argv += ["--config", c]
    for ex in DEFAULT_EXCLUDES:
        argv += ["--exclude", ex]
    argv.append(".")
    return argv


def normalize_rule_id(check_id: str) -> str:
    """Local rule IDs are prefixed with the config file's dotted path; keep our namespace."""
    idx = check_id.find("toolkit.")
    return check_id[idx:] if idx >= 0 else check_id


def safe_relpath(path: str) -> str | None:
    """Repository-relative POSIX path, or None if it points outside the workspace."""
    p = posixpath.normpath(path.replace("\\", "/"))
    if p.startswith(("../", "/")) or p in ("..", ".") or ":" in p.split("/")[0]:
        return None
    return p


def parse(report: dict[str, Any]) -> SemgrepResult:
    out = SemgrepResult(errors=len(report.get("errors") or []), version=report.get("version"))
    for r in report.get("results") or []:
        rel = safe_relpath(str(r.get("path", "")))
        if rel is None:
            continue
        extra = r.get("extra") or {}
        start = int((r.get("start") or {}).get("line", 1))
        end = int((r.get("end") or {}).get("line", start))
        out.matches.append(
            CodeMatch(
                rule_id=normalize_rule_id(str(r.get("check_id"))),
                path=rel,
                line_start=start,
                line_end=max(start, end),
                message=str(extra.get("message", ""))[:1000],
                severity=SEVERITY_MAP.get(str(extra.get("severity", "")).upper(), "low"),
                metadata={k: v for k, v in (extra.get("metadata") or {}).items() if k in ("cwe", "category", "owasp")},
            )
        )
    return out


def _failure_reason(stdout: str, stderr: str) -> str:
    """With --json --quiet, fatal errors (e.g. rule parse errors) are in the JSON, not on stderr."""
    try:
        errors = json.loads(stdout or "{}").get("errors") or []
    except (json.JSONDecodeError, AttributeError):
        errors = []
    for err in errors:
        if isinstance(err, dict) and err.get("level") == "error":
            first_line = str(err.get("message") or "").strip().splitlines()[:1]
            return f"{err.get('type', 'error')}: {first_line[0] if first_line else ''}".strip()
    tail = stderr.strip().splitlines()[-1:]
    return tail[0] if tail else "semgrep failed"


def scan(repo: Path, timeout: int, repo_rules_dir: Path | None = None) -> SemgrepResult:
    result = run(
        build_argv(rules_config(repo_rules_dir)),
        timeout=timeout,
        cwd=str(repo),
        env={"SEMGREP_SEND_METRICS": "off", "SEMGREP_ENABLE_VERSION_CHECK": "0"},
    )
    if result.timed_out:
        raise SemgrepError(f"timeout after {timeout}s")
    # Exit code 1 means "findings present" only with --error; other non-zero codes are failures.
    if result.exit_code not in (0, 1):
        raise SemgrepError(f"exit {result.exit_code}: {_failure_reason(result.stdout, result.stderr)[:250]}")
    try:
        return parse(json.loads(result.stdout or "{}"))
    except json.JSONDecodeError as exc:
        raise SemgrepError("semgrep produced invalid JSON") from exc
