"""Provider output → normalized findings (TRD §5.1 step 6, §5.2, §5.3; FR-DEP-03..06, FR-SAST-01)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from toolkit.core.validators import normalize_pypi_name
from toolkit.integrations.osv import Advisory
from toolkit.scanning.inventory import Dep
from toolkit.scanning.semgrep import CodeMatch
from toolkit.scanning.trivy import TrivyVuln
from toolkit.scanning.versions import bump, compare, parse, pick_fix_version


@dataclass
class EvidenceDraft:
    kind: str
    source: str
    url: str | None
    content: dict[str, Any]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.content, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class FindingDraft:
    type: str
    fingerprint: str
    title: str
    severity: str | None
    severity_source: str | None
    sources: list[str]
    ecosystem: str | None = None
    package_name: str | None = None
    package_version: str | None = None
    scope: str | None = None
    manifest_path: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    rule_id: str | None = None
    message: str | None = None
    advisory: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    evidence: list[EvidenceDraft] = field(default_factory=list)

    @property
    def search_text(self) -> str:
        parts = [self.title, self.package_name or "", self.file_path or "", self.rule_id or ""]
        if self.advisory:
            parts += self.advisory.get("ids", [])
        return " ".join(parts).lower()[:4000]


def fingerprint(ftype: str, rule_or_advisory_key: str, subject_key: str) -> str:
    """SHA256(type ‖ key ‖ subject). Line numbers are excluded on purpose (TRD §5.2)."""
    return hashlib.sha256("\x1f".join((ftype, rule_or_advisory_key, subject_key)).encode()).hexdigest()


def dep_subject(ecosystem: str, name: str, version: str) -> str:
    n = normalize_pypi_name(name) if ecosystem == "pypi" else name
    return f"{ecosystem}:{n}:{version}"


# --------------------------------------------------------------------------- vulnerabilities
@dataclass
class _Record:
    ids: set[str]
    provider: str
    trivy: TrivyVuln | None = None
    osv: Advisory | None = None


def _merge_alias_sets(records: list[_Record]) -> list[list[_Record]]:
    """Union records whose identifier sets intersect (FR-DEP-04)."""
    groups: list[tuple[set[str], list[_Record]]] = []
    for rec in records:
        hits = [g for g in groups if g[0] & rec.ids]
        merged_ids = set(rec.ids)
        merged_recs = [rec]
        for g in hits:
            merged_ids |= g[0]
            merged_recs += g[1]
            groups.remove(g)
        groups.append((merged_ids, merged_recs))
    return [recs for _ids, recs in groups]


_SEV_ORDER = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


def vulnerability_findings(
    deps: list[Dep],
    trivy_vulns: list[TrivyVuln],
    osv_by_dep: dict[tuple[str, str, str], list[Advisory]],
) -> list[FindingDraft]:
    by_key: dict[tuple[str, str, str], list[_Record]] = {}
    for tv in trivy_vulns:
        by_key.setdefault(_key(tv.ecosystem, tv.name, tv.version), []).append(_Record({tv.vuln_id}, "trivy", trivy=tv))
    for key, advisories in osv_by_dep.items():
        for adv in advisories:
            if adv.withdrawn:
                continue
            by_key.setdefault(key, []).append(_Record({adv.id, *adv.aliases}, "osv", osv=adv))
    dep_index: dict[tuple[str, str, str], Dep] = {}
    for d in sorted(deps, key=lambda d: d.scope != "direct"):  # direct occurrences win
        dep_index.setdefault(d.key, d)

    drafts: list[FindingDraft] = []
    for key, records in by_key.items():
        eco, name_n, version = key
        dep = dep_index.get(key)
        tv0 = next((r.trivy for r in records if r.trivy), None)
        name = dep.name if dep else (tv0.name if tv0 else name_n)
        for group in _merge_alias_sets(records):
            ids = sorted(set().union(*(r.ids for r in group)))
            primary = ids[0]
            osv_recs = [r.osv for r in group if r.osv]
            trivy_recs = [r.trivy for r in group if r.trivy]
            severity, sev_source = None, None
            for adv in osv_recs:
                if adv.severity and (severity is None or _SEV_ORDER[adv.severity] > _SEV_ORDER[severity]):
                    severity, sev_source = adv.severity, "osv"
            if severity is None:
                for tv in trivy_recs:
                    if tv.severity and (severity is None or _SEV_ORDER[tv.severity] > _SEV_ORDER[severity]):
                        severity, sev_source = tv.severity, "trivy"
            fixed: list[str] = []
            for adv in osv_recs:
                fixed += [f for f in adv.fixed_versions if f not in fixed]
            for tv in trivy_recs:
                fixed += [f for f in tv.fixed_versions if f not in fixed]
            fixed = [f for f in fixed if parse(eco, f) is not None]
            references: list[str] = []
            for adv in osv_recs:
                references += [u for u in adv.references if u not in references]
            for tv in trivy_recs:
                references += [
                    u for u in ([tv.primary_url] if tv.primary_url else []) + tv.references if u and u not in references
                ]
            summary = next((a.summary for a in osv_recs if a.summary), None) or next(
                (t.title for t in trivy_recs if t.title), None
            )
            recommended = pick_fix_version(eco, version, fixed)
            evidence: list[EvidenceDraft] = []
            for adv in osv_recs:
                evidence.append(EvidenceDraft("advisory_record", "osv", adv.url, adv.record()))
            for tv in trivy_recs:
                evidence.append(
                    EvidenceDraft(
                        "scanner_output",
                        "trivy",
                        tv.primary_url,
                        {
                            "vulnerability_id": tv.vuln_id,
                            "package": tv.name,
                            "installed_version": tv.version,
                            "severity": tv.severity,
                            "fixed_versions": tv.fixed_versions,
                            "title": tv.title,
                            "target": tv.manifest_path,
                        },
                    )
                )
            drafts.append(
                FindingDraft(
                    type="dependency_vulnerability",
                    fingerprint=fingerprint("dependency_vulnerability", primary, dep_subject(eco, name, version)),
                    title=f"{name}@{version} is affected by {primary}" + (f": {summary}" if summary else ""),
                    severity=severity,
                    severity_source=sev_source,
                    sources=sorted({r.provider for r in group}),
                    ecosystem=eco,
                    package_name=name,
                    package_version=version,
                    scope=dep.scope if dep else None,
                    manifest_path=dep.manifest_path if dep else (tv0.manifest_path if tv0 else None),
                    advisory={
                        "ids": ids,
                        "primary_id": primary,
                        "aliases": [i for i in ids if i != primary],
                        "fixed_versions": fixed,
                        "recommended_fix": recommended,
                        "summary": summary,
                        "references": references[:20],
                    },
                    evidence=evidence,
                )
            )
    return drafts


def _key(ecosystem: str, name: str, version: str) -> tuple[str, str, str]:
    return (ecosystem, normalize_pypi_name(name) if ecosystem == "pypi" else name, version)


# --------------------------------------------------------------------------- outdated / incompatibility
@dataclass
class RegistryFacts:
    latest: str | None
    latest_deprecated: str | None
    installed_deprecated: str | None
    latest_runtime: str | None
    source_url: str


_MIN_VERSION = re.compile(r"(?:>=|\^|~|>|==|=)?\s*v?(\d+)(?:\.(\d+))?")


def min_runtime_major_minor(constraint: str | None) -> tuple[int, int] | None:
    """Lower bound of a simple runtime constraint (">=18", "^16.14", ">=3.9,<4"). Heuristic."""
    if not constraint:
        return None
    lows = []
    for part in re.split(r"\s*(?:\|\||,|\s)\s*", constraint.strip()):
        if part.startswith(("<", "!")) or not part:
            continue
        m = _MIN_VERSION.match(part)
        if m:
            lows.append((int(m.group(1)), int(m.group(2) or 0)))
    return min(lows) if lows else None


def outdated_and_incompat_findings(
    deps: list[Dep],
    facts: dict[tuple[str, str, str], RegistryFacts],
    project_runtime: dict[str, str | None],
    vuln_drafts: list[FindingDraft],
) -> list[FindingDraft]:
    drafts: list[FindingDraft] = []
    seen: set[str] = set()
    for dep in deps:
        f = facts.get(dep.key)
        if f is None:
            continue
        subject = dep_subject(dep.ecosystem, dep.name, dep.version)
        reg_ev = EvidenceDraft(
            "registry_metadata",
            dep.ecosystem,
            f.source_url,
            {
                "name": dep.name,
                "installed_version": dep.version,
                "latest_version": f.latest,
                "installed_deprecated": f.installed_deprecated,
                "latest_runtime_constraint": f.latest_runtime,
            },
        )
        if f.latest and compare(dep.ecosystem, dep.version, f.latest) == -1:
            lag = bump(dep.ecosystem, dep.version, f.latest)
            fp = fingerprint("dependency_outdated", "outdated", subject)
            if fp not in seen:
                seen.add(fp)
                drafts.append(
                    FindingDraft(
                        type="dependency_outdated",
                        fingerprint=fp,
                        title=f"{dep.name} {dep.version} is behind the latest release {f.latest} ({lag})",
                        severity="low" if lag == "major" else "info",
                        severity_source="heuristic",
                        sources=["registry"],
                        ecosystem=dep.ecosystem,
                        package_name=dep.name,
                        package_version=dep.version,
                        scope=dep.scope,
                        manifest_path=dep.manifest_path,
                        detail={"heuristic": "outdated", "installed": dep.version, "latest": f.latest, "lag": lag},
                        evidence=[reg_ev],
                    )
                )
        if f.installed_deprecated:
            fp = fingerprint("dependency_incompatibility", "registry_deprecation", subject)
            if fp not in seen:
                seen.add(fp)
                drafts.append(
                    FindingDraft(
                        type="dependency_incompatibility",
                        fingerprint=fp,
                        title=f"{dep.name}@{dep.version} is deprecated by its registry",
                        severity="low",
                        severity_source="heuristic",
                        sources=["registry"],
                        ecosystem=dep.ecosystem,
                        package_name=dep.name,
                        package_version=dep.version,
                        scope=dep.scope,
                        manifest_path=dep.manifest_path,
                        detail={
                            "heuristic": "registry_deprecation",
                            "message": f.installed_deprecated[:500],
                            "label": "heuristic",
                        },
                        evidence=[reg_ev],
                    )
                )
        project_rt = project_runtime.get(dep.manifest_path)
        need, have = min_runtime_major_minor(f.latest_runtime), min_runtime_major_minor(project_rt)
        if f.latest and need and have and need > have:
            fp = fingerprint("dependency_incompatibility", "runtime_constraint_mismatch", subject)
            if fp not in seen:
                seen.add(fp)
                drafts.append(
                    FindingDraft(
                        type="dependency_incompatibility",
                        fingerprint=fp,
                        title=f"Latest {dep.name} {f.latest} requires runtime {f.latest_runtime}; project declares "
                        f"{project_rt}",
                        severity="low",
                        severity_source="heuristic",
                        sources=["registry"],
                        ecosystem=dep.ecosystem,
                        package_name=dep.name,
                        package_version=dep.version,
                        scope=dep.scope,
                        manifest_path=dep.manifest_path,
                        detail={
                            "heuristic": "runtime_constraint_mismatch",
                            "latest": f.latest,
                            "latest_requires": f.latest_runtime,
                            "project_declares": project_rt,
                            "label": "heuristic",
                        },
                        evidence=[reg_ev],
                    )
                )
    for v in vuln_drafts:
        adv = v.advisory or {}
        fix = adv.get("recommended_fix")
        eco, version = v.ecosystem, v.package_version
        if not fix or not eco or not version or bump(eco, version, fix) != "major":
            continue
        subject = dep_subject(eco, v.package_name or "", version)
        fp = fingerprint("dependency_incompatibility", "fix_requires_major_upgrade", subject)
        if fp in seen:
            continue
        seen.add(fp)
        drafts.append(
            FindingDraft(
                type="dependency_incompatibility",
                fingerprint=fp,
                title=f"Fixing {v.package_name}@{version} requires a major upgrade to {fix}",
                severity="low",
                severity_source="heuristic",
                sources=sorted(set(v.sources)),
                ecosystem=eco,
                package_name=v.package_name,
                package_version=version,
                scope=v.scope,
                manifest_path=v.manifest_path,
                detail={
                    "heuristic": "fix_requires_major_upgrade",
                    "fix_version": fix,
                    "advisory": adv.get("primary_id"),
                    "label": "heuristic",
                },
                evidence=[
                    EvidenceDraft(
                        "scanner_output",
                        v.sources[0],
                        None,
                        {
                            "advisory": adv.get("primary_id"),
                            "installed_version": version,
                            "fix_version": fix,
                            "bump": "major",
                        },
                    )
                ],
            )
        )
    return drafts


# --------------------------------------------------------------------------- code issues
def code_findings(
    matches: list[CodeMatch], snippets: dict[int, dict[str, Any] | None], match_hashes: dict[int, str]
) -> list[FindingDraft]:
    drafts: list[FindingDraft] = []
    seen: set[str] = set()
    for idx, m in enumerate(matches):
        fp = fingerprint("code_issue", m.rule_id, f"{m.path}:{match_hashes[idx]}")
        if fp in seen:
            continue
        seen.add(fp)
        first_sentence = m.message.split(". ")[0].rstrip(".")
        evidence = [
            EvidenceDraft(
                "scanner_output",
                "semgrep",
                None,
                {
                    "rule_id": m.rule_id,
                    "message": m.message,
                    "path": m.path,
                    "line_start": m.line_start,
                    "line_end": m.line_end,
                    "severity": m.severity,
                    "metadata": m.metadata,
                },
            )
        ]
        snip = snippets.get(idx)
        if snip is not None and not snip.get("omitted"):
            evidence.append(EvidenceDraft("code_snippet", "semgrep", None, snip))
        drafts.append(
            FindingDraft(
                type="code_issue",
                fingerprint=fp,
                title=f"{first_sentence} ({m.path}:{m.line_start})"[:500],
                severity=m.severity,
                severity_source="semgrep",
                sources=["semgrep"],
                file_path=m.path,
                line_start=m.line_start,
                line_end=m.line_end,
                rule_id=m.rule_id,
                message=m.message,
                detail={
                    "metadata": m.metadata,
                    **({"snippet_omitted": snip.get("omitted_reason")} if snip and snip.get("omitted") else {}),
                },
                evidence=evidence,
            )
        )
    return drafts
