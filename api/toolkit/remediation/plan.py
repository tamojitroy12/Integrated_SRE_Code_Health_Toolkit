"""Deterministic change plans for dependency fixes (FR-REM-01, FR-REM-08, SECURITY §9.1).

Package names and versions come from stored findings and advisory/registry data — never
from model output — and are validated against ecosystem grammars before they can reach a
package-manager argument vector.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from toolkit.core.validators import is_valid_package_name, is_valid_version, normalize_pypi_name
from toolkit.db.models import Finding
from toolkit.scanning.versions import bump, compare, pick_fix_version

FIXABLE_TYPES = {"dependency_vulnerability", "dependency_outdated", "dependency_incompatibility"}
NPM_LOCKFILES = {"package-lock.json", "npm-shrinkwrap.json"}


class PlanError(ValueError):
    pass


@dataclass
class Change:
    ecosystem: str
    package: str
    from_version: str
    to_version: str
    bump: str
    manifest_path: str
    lockfile_path: str
    scope: str | None
    finding_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def target_version_for(f: Finding) -> str | None:
    """The version a fix for this finding would move to, or None if not fixable."""
    if f.type not in FIXABLE_TYPES or not f.ecosystem or not f.package_version:
        return None
    if f.type == "dependency_vulnerability":
        adv = f.advisory or {}
        fix = adv.get("recommended_fix") or pick_fix_version(
            f.ecosystem, f.package_version, adv.get("fixed_versions") or []
        )
        return fix if fix and compare(f.ecosystem, f.package_version, fix) == -1 else None
    detail = f.detail or {}
    if f.type == "dependency_outdated":
        latest = detail.get("latest")
        # Only patch/minor updates are proposed for plain staleness (FR-REM-01).
        if latest and detail.get("lag") in ("patch", "minor"):
            return str(latest)
        return None
    if detail.get("heuristic") == "fix_requires_major_upgrade":
        return str(detail.get("fix_version")) if detail.get("fix_version") else None
    return None


def _paths(ecosystem: str, recorded: str | None) -> tuple[str, str]:
    if not recorded:
        raise PlanError("finding has no manifest path")
    path = posixpath.normpath(recorded)
    if path.startswith(("../", "/")) or ".." in path.split("/"):
        raise PlanError("manifest path escapes the repository")
    folder, name = posixpath.split(path)
    if ecosystem == "npm":
        if name not in NPM_LOCKFILES:
            raise PlanError(f"npm fixes need a package-lock.json (found {name})")
        return posixpath.join(folder, "package.json") if folder else "package.json", path
    if re.fullmatch(r"requirements[\w.-]*\.txt", name):
        return path, path
    raise PlanError(f"PyPI fixes support pinned requirements*.txt only (found {name})")


def build_plan(findings: list[Finding]) -> list[Change]:
    if not findings:
        raise PlanError("no findings selected")
    if len({f.project_id for f in findings}) != 1:
        raise PlanError("findings belong to different projects")
    grouped: dict[tuple[str, str, str], Change] = {}
    for f in findings:
        target = target_version_for(f)
        if target is None:
            raise PlanError(f"finding {f.id} has no known fixed version or patch/minor update")
        eco, name, current = f.ecosystem or "", f.package_name or "", f.package_version or ""
        if not is_valid_package_name(eco, name):
            raise PlanError(f"invalid package name for {eco}")
        if not is_valid_version(eco, current) or not is_valid_version(eco, target):
            raise PlanError(f"invalid version for {name}")
        manifest, lockfile = _paths(eco, f.manifest_path)
        key = (eco, normalize_pypi_name(name) if eco == "pypi" else name, lockfile)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = Change(
                eco, name, current, target, bump(eco, current, target), manifest, lockfile, f.scope, [str(f.id)]
            )
            continue
        if existing.from_version != current:
            raise PlanError(f"{name} appears with different installed versions in {lockfile}")
        existing.finding_ids.append(str(f.id))
        if compare(eco, existing.to_version, target) == -1:
            existing.to_version = target
            existing.bump = bump(eco, current, target)
    return sorted(grouped.values(), key=lambda c: (c.ecosystem, c.lockfile_path, c.package))


def allowed_paths(changes: list[Change]) -> set[str]:
    return {c.manifest_path for c in changes} | {c.lockfile_path for c in changes}


_REQ_LINE = re.compile(
    r"^(?P<lead>\s*)(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\s*\[[^\]]*\])?\s*==\s*(?P<version>[^\s;#\\]+)"
    r"(?P<rest>.*)$"
)


def apply_requirements_change(text: str, package: str, from_version: str, to_version: str) -> str:
    """Rewrite ``package==from`` to ``package==to`` keeping extras, markers and comments."""
    out, hits = [], 0
    target = normalize_pypi_name(package)
    for line in text.splitlines(keepends=True):
        m = _REQ_LINE.match(line.rstrip("\r\n"))
        if m and normalize_pypi_name(m.group("name")) == target and m.group("version") == from_version:
            if "--hash" in m.group("rest") or line.rstrip().endswith("\\"):
                raise PlanError(f"{package} is hash-pinned; regenerate the requirements file instead")
            newline = line[len(line.rstrip("\r\n")) :]
            out.append(
                f"{m.group('lead')}{m.group('name')}{m.group('extras') or ''}=={to_version}{m.group('rest')}{newline}"
            )
            hits += 1
        else:
            out.append(line)
    if hits == 0:
        raise PlanError(f"{package}=={from_version} not found in the requirements file")
    return "".join(out)
