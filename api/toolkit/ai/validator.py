"""Mechanical validation of model output (FR-AI-04, AI_DESIGN §6, NFR-AI-01).

A recommendation is ``validated`` only if every automated check passes. Checks never trust
model-provided facts: package/version existence comes from the registry, fixed versions from
stored advisory data, code locations from the stored snippet.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from toolkit.ai.evidence import EvidencePack
from toolkit.ai.schema import CHECKABLE_CLAIMS, JUDGMENT_CLAIMS, Claim, ModelOutput
from toolkit.core.http import UpstreamError
from toolkit.core.validators import is_valid_package_name, is_valid_version, normalize_pypi_name
from toolkit.db.models import Finding
from toolkit.integrations.registry import PackageMeta, PackageNotFound, RegistryClient
from toolkit.scanning.versions import compare, parse

# A patch checker returns True (applies), False (does not apply) or None (could not check).
PatchChecker = Callable[[str, str], bool | None]

_COMMAND_RE = re.compile(
    r"(`|\$\(|&&|\|\||;\s*\w|\brm\s+-|\bsudo\b|\bcurl\b|\bwget\b|\bchmod\b|\bnpm\s+(i|install|run|exec)\b"
    r"|\bnpx\b|\bpip3?\s+install\b|\bpython\s+-m\b|\bgit\s+\w+|https?://|^\s*\$\s|>\s*/|\beval\b|\bbash\b)",
    re.I,
)


@dataclass
class ValidatedOutput:
    status: str
    content: dict[str, Any]
    checks: list[dict[str, Any]] = field(default_factory=list)


def _registry_safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except (PackageNotFound, UpstreamError):
        return None


def _norm(eco: str, name: str) -> str:
    return normalize_pypi_name(name) if eco == "pypi" else name


class Validator:
    def __init__(
        self, finding: Finding, pack: EvidencePack, registry: RegistryClient, patch_checker: PatchChecker | None = None
    ) -> None:
        self.finding = finding
        self.pack = pack
        self.registry = registry
        self.patch_checker = patch_checker
        self.eco = finding.ecosystem

    # ---------------------------------------------------------------- per-claim checks
    def _refs_ok(self, refs: list[str]) -> tuple[bool, str]:
        if not refs:
            return False, "No evidence reference provided."
        unknown = [r for r in refs if r not in self.pack.ids]
        if unknown:
            return False, f"Unknown evidence IDs: {', '.join(unknown[:5])}."
        return True, ""

    def _fixed_versions(self) -> list[str]:
        out = list((self.finding.advisory or {}).get("fixed_versions") or [])
        for adv in self.pack.advisories():
            out += [v for v in adv.get("fixed_versions") or [] if v not in out]
        return out

    def _pkg(self, claim: Claim) -> tuple[str | None, str | None]:
        sub = claim.subject
        eco = (sub.ecosystem if sub and sub.ecosystem else None) or self.eco
        pkg = (sub.package if sub and sub.package else None) or self.finding.package_name
        return eco, pkg

    def _meta(self, eco: str, pkg: str) -> PackageMeta | None:
        cached = self.pack.registry.get(pkg.lower())
        if cached is not None and cached.ecosystem == eco:
            return cached
        meta = _registry_safe(lambda: self.registry.package(eco, pkg))
        if meta is not None:
            self.pack.registry[pkg.lower()] = meta
        return meta  # type: ignore[no-any-return]

    def check_claim(self, claim: Claim, patch_ok: bool | None) -> tuple[str, str]:
        ok, note = self._refs_ok(claim.evidence_refs)
        if not ok:
            return "unsupported", note
        if claim.type in JUDGMENT_CLAIMS:
            return "unverifiable", "Judgment; cannot be checked mechanically."
        sub = claim.subject
        eco, pkg = self._pkg(claim)
        if claim.type in ("fixed_version", "version_exists"):
            version = sub.version if sub else None
            if (
                not (eco and pkg and version)
                or not is_valid_package_name(eco, pkg)
                or not is_valid_version(eco, version)
            ):
                return "unsupported", "Claim does not name a valid package and version."
            v: str = version
            ver = _registry_safe(lambda: self.registry.version(eco, pkg, v))
            if ver is None:
                return "unsupported", "Registry could not confirm the version."
            if not ver.exists:
                return "unsupported", f"{pkg}@{version} does not exist in the registry."
            if claim.type == "version_exists":
                return "supported", "Version exists in the registry."
            if _norm(eco, pkg) != _norm(eco, self.finding.package_name or ""):
                return "unsupported", "Fixed-version claim refers to a different package."
            fixed = self._fixed_versions()
            if not fixed:
                return "unsupported", "Stored advisory data lists no fixed version."
            if version in fixed:
                return "supported", "Matches a fixed version in the stored advisory data."
            installed = self.finding.package_version or "0"
            applicable = [f for f in fixed if compare(eco, installed, f) == -1]
            parsed = parse(eco, version)
            if applicable and parsed is not None:
                smallest = min(applicable, key=lambda f: parse(eco, f))  # type: ignore[arg-type,return-value]
                if compare(eco, smallest, version) == -1 and _same_major(eco, smallest, version):
                    return "supported", f"Later than the fixed version {smallest} on the same major line."
            return "unsupported", "Version is not within the advisory's fixed versions."
        if claim.type == "deprecation":
            if not (eco and pkg):
                return "unsupported", "Claim does not name a package."
            meta = self._meta(eco, pkg)
            if meta is None:
                return "unsupported", "Package not found in the registry."
            version = sub.version if sub else None
            deprecated: bool
            if version:
                ver = _registry_safe(lambda: self.registry.version(eco, pkg, version))
                if ver is None or not ver.exists:
                    return "unsupported", "Version not found in the registry."
                deprecated = bool(ver.deprecated)
            else:
                deprecated = bool(meta.deprecated)
            claimed = _truthy(sub.value if sub else None, default=True)
            if claimed == deprecated:
                return "supported", "Deprecation status matches registry metadata."
            return "unsupported", "Deprecation status contradicts registry metadata."
        if claim.type in ("alternative_exists", "alternative_property"):
            if not (eco and pkg) or not is_valid_package_name(eco, pkg):
                return "unsupported", "Claim does not name a valid package."
            meta = self._meta(eco, pkg)
            if meta is None:
                return "unsupported", f"{pkg} was not found in the {eco} registry."
            if claim.type == "alternative_exists":
                return "supported", "Package exists in the registry (existence is not trust)."
            prop = sub.property if sub else None
            value = (sub.value or "").strip() if sub else ""
            actual = {
                "license": meta.license,
                "latest_version": meta.latest,
                "deprecated": "true" if meta.deprecated else "false",
                "repository_url": meta.repository_url,
            }.get(prop or "")
            if prop is None or actual is None:
                return "unsupported", "Property not available in registry metadata."
            if _same_value(prop, value, actual):
                return "supported", "Matches registry metadata."
            return "unsupported", f"Registry metadata says {prop} = {actual!r}."
        if claim.type == "code_location":
            snip = self.pack.snippet()
            if snip is None or sub is None or not sub.file:
                return "unsupported", "No code snippet evidence to check against."
            if sub.file != snip.get("path"):
                return "unsupported", "File does not match the evidence snippet."
            start, end = sub.line_start or 0, sub.line_end or sub.line_start or 0
            if not (snip.get("line_start", 0) <= start <= end <= snip.get("line_end", 0)):
                return "unsupported", "Lines are outside the evidence snippet."
            return "supported", "Location lies within the evidence snippet."
        if claim.type == "patch_applies":
            if patch_ok:
                return "supported", "git apply --check succeeded on the scanned commit."
            return "unsupported", "Patch was missing or did not apply."
        return "unsupported", "Unknown claim type."

    # ---------------------------------------------------------------- whole output
    def validate(self, out: ModelOutput, kind: str) -> ValidatedOutput:
        patch, patch_ok, patch_note = self._check_patch(out.proposed_patch, kind)
        claims: list[dict[str, Any]] = []
        failed_checkable, supported = 0, 0
        for c in out.claims:
            status, note = self.check_claim(c, patch_ok)
            claims.append(
                {
                    "claim_id": c.claim_id,
                    "type": c.type,
                    "kind": "judgment" if c.type in JUDGMENT_CLAIMS else "checkable",
                    "text": c.text,
                    "evidence_refs": c.evidence_refs,
                    "subject": c.subject.model_dump() if c.subject else None,
                    "validation": status,
                    "validation_note": note,
                }
            )
            if status == "supported":
                supported += 1
            elif status == "unsupported":
                failed_checkable += 1  # judgment claims without refs count here too (VC-09)

        alternatives, removed_alts = self._check_alternatives(out, kind)
        steps = [s for s in out.suggested_steps if not _COMMAND_RE.search(s)]
        removed_steps = len(out.suggested_steps) - len(steps)
        checkable = [c for c in claims if c["type"] in CHECKABLE_CLAIMS]

        problems = failed_checkable + removed_alts + (1 if out.proposed_patch and not patch_ok else 0)
        if checkable and supported == 0:
            status = "rejected"
        elif problems == 0 and checkable:
            status = "validated"
        else:
            status = "partially_validated"

        limitations = list(dict.fromkeys([*out.limitations, *self.pack.limitations, *self._toolkit_limitations(kind)]))
        if not checkable:
            limitations.append("No mechanically checkable claim was made; treat the advice as unverified.")
        if removed_steps:
            limitations.append(f"{removed_steps} suggested step(s) were removed because they contained commands.")
        if removed_alts:
            limitations.append(f"{removed_alts} alternative(s) were removed because they failed registry checks.")
        if patch_note:
            limitations.append(patch_note)
        confidence: str | None = out.confidence
        if status == "partially_validated" and confidence == "high":
            confidence = "medium"
        if status == "rejected":
            confidence = None
        content = {
            "summary": out.summary,
            "claims": claims,
            "alternatives": alternatives,
            "suggested_steps": steps,
            "proposed_patch": patch,
            "confidence": confidence,
            "model_confidence": out.confidence,
            "limitations": limitations,
        }
        return ValidatedOutput(status, content, claims)

    def _check_alternatives(self, out: ModelOutput, kind: str) -> tuple[list[dict[str, Any]], int]:
        result: list[dict[str, Any]] = []
        removed = 0
        for alt in out.alternatives:
            ok, _note = self._refs_ok(alt.evidence_refs)
            same = self.eco is None or alt.ecosystem == self.eco
            self_ref = _norm(alt.ecosystem, alt.name) == _norm(alt.ecosystem, self.finding.package_name or "")
            meta = (
                self._meta(alt.ecosystem, alt.name)
                if (
                    ok
                    and same
                    and not self_ref
                    and kind == "library_alternative"
                    and is_valid_package_name(alt.ecosystem, alt.name)
                )
                else None
            )
            if meta is None:
                removed += 1
                continue
            result.append(
                {
                    "name": meta.name,
                    "ecosystem": alt.ecosystem,
                    "rationale": alt.rationale,
                    "evidence_refs": alt.evidence_refs,
                    # FR-AI-07: verifiable criteria come from the registry, never from the model.
                    "criteria": {**meta.evidence(), "registry_url": meta.source_url},
                    "validation": "supported",
                }
            )
        return result, removed

    def _check_patch(self, patch: str | None, kind: str) -> tuple[str | None, bool | None, str | None]:
        if not patch:
            return None, None, None
        if kind != "code_improvement":
            return None, False, "A proposed patch was removed: patches are only allowed for code improvements."
        target = self.finding.file_path or ""
        touched = set(re.findall(r"^(?:\+\+\+|---) (?:[ab]/)?(\S+)", patch, re.M)) - {"/dev/null"}
        if not touched or touched != {target}:
            return None, False, "The proposed patch was removed because it touches files other than the finding's file."
        if self.patch_checker is None:
            return None, False, "The proposed patch could not be checked and was removed."
        ok = self.patch_checker(target, patch)
        if ok:
            return patch, True, None
        return None, False, "The proposed patch did not apply to the scanned commit and was removed."

    def _toolkit_limitations(self, kind: str) -> list[str]:
        out = ["AI-generated and advisory: review before acting."]
        if self.finding.type == "dependency_vulnerability":
            out.append("Reachability of the vulnerable code path was not analyzed.")
        if kind in ("upgrade_guidance", "library_alternative"):
            out.append("Compatibility of a change cannot be established from this evidence; rely on tests.")
        if kind == "library_alternative":
            out.append("Existence in a registry is not evidence that a package is trustworthy.")
        return out


def _same_major(eco: str, a: str, b: str) -> bool:
    pa, pb = parse(eco, a), parse(eco, b)
    if pa is None or pb is None:
        return False
    return bool(pa.major == pb.major)  # both SemVer and packaging.Version expose .major


def _truthy(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("true", "yes", "1", "deprecated")


def _same_value(prop: str, claimed: str, actual: str) -> bool:
    if prop == "repository_url":

        def norm(u: str) -> str:
            return u.lower().removesuffix("/").removesuffix(".git").replace("http://", "https://")

        return norm(claimed) == norm(actual)
    if prop == "deprecated":
        return _truthy(claimed, default=False) == (actual == "true")
    return claimed.strip().lower() == actual.strip().lower()
