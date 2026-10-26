"""Persist a scan's normalized output (FR-DEP-09, NFR-REL-04, DATA_MODEL §6).

* findings are upserted by ``(project_id, fingerprint)``; occurrences are unique per
  ``(scan_id, fingerprint)``, so re-processing a scan never duplicates anything;
* dismissals persist across scans because they live on the fingerprint-identified row;
* findings are resolved only by a **non-partial** scan whose providers covered that
  finding type, so a failed provider can never produce a false "fixed" state.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from toolkit.db.enums import SEVERITY_RANK
from toolkit.db.models import Dependency, Evidence, Finding, FindingOccurrence, Scan
from toolkit.scanning.inventory import Dep
from toolkit.scanning.normalize import FindingDraft

# Which providers must have run successfully for a finding type to be considered "absent".
COVERAGE: dict[str, set[str]] = {
    "dependency_vulnerability": {"trivy", "osv"},
    "dependency_outdated": {"registry"},
    "dependency_incompatibility": {"registry", "trivy", "osv"},
    "code_issue": {"semgrep"},
}
_CHUNK = 1000


def _chunks(items: list[Any], size: int = _CHUNK) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def store_dependencies(db: Session, scan_id: uuid.UUID, deps: list[Dep]) -> int:
    rows = [
        {
            "id": uuid.uuid4(),
            "scan_id": scan_id,
            "ecosystem": d.ecosystem,
            "name": d.name,
            "version": d.version,
            "scope": d.scope,
            "manifest_path": d.manifest_path[:300],
            "purl": d.purl[:400],
        }
        for d in deps
    ]
    for chunk in _chunks(rows):
        db.execute(insert(Dependency).values(chunk).on_conflict_do_nothing(constraint="uq_dependency"))
    return len(rows)


def persist_findings(
    db: Session,
    scan: Scan,
    drafts: list[FindingDraft],
    *,
    ok_providers: set[str],
    partial: bool,
    now: datetime,
) -> dict[str, Any]:
    project_id = scan.project_id
    by_fp: dict[str, FindingDraft] = {}
    for d in drafts:
        by_fp.setdefault(d.fingerprint, d)
    fps = list(by_fp)

    existing: dict[str, Finding] = {}
    for chunk in _chunks(fps):
        for row in db.scalars(
            select(Finding).where(Finding.project_id == project_id, Finding.fingerprint.in_(chunk)).with_for_update()
        ):
            existing[row.fingerprint] = row

    changes: Counter[str] = Counter()
    for fp, d in by_fp.items():
        found: Finding | None = existing.get(fp)
        if found is None:
            f = Finding(
                id=uuid.uuid4(),
                project_id=project_id,
                fingerprint=fp,
                status="open",
                first_seen_at=now,
                first_seen_scan_id=scan.id,
            )
            db.add(f)
            existing[fp] = f
            change = "new"
        else:
            f = found
            if f.last_seen_scan_id == scan.id:
                change = "unchanged" if f.last_change != "new" else "new"  # re-processing the same scan
            elif f.status == "resolved":
                change = "new"
                f.status = "open"
                f.resolved_at = None
                f.resolved_scan_id = None
            else:
                change = "unchanged"
        f.type = d.type
        f.title = d.title[:500]
        f.severity = d.severity
        f.severity_rank = SEVERITY_RANK[d.severity]
        f.severity_source = d.severity_source
        f.ecosystem, f.package_name, f.package_version = d.ecosystem, d.package_name, d.package_version
        f.scope, f.manifest_path = d.scope, d.manifest_path
        f.file_path, f.line_start, f.line_end, f.rule_id = d.file_path, d.line_start, d.line_end, d.rule_id
        f.message = d.message
        f.advisory, f.detail = d.advisory, d.detail
        f.sources = d.sources
        f.search_text = d.search_text
        f.last_seen_at = now
        f.last_seen_scan_id = scan.id
        f.last_change = change
        changes[change] += 1
    db.flush()

    for chunk in _chunks(
        [
            {
                "id": uuid.uuid4(),
                "scan_id": scan.id,
                "finding_id": existing[fp].id,
                "fingerprint": fp,
                "change": existing[fp].last_change,
            }
            for fp in fps
        ]
    ):
        db.execute(
            insert(FindingOccurrence).values(chunk).on_conflict_do_nothing(constraint="uq_occurrence_scan_fingerprint")
        )

    _store_evidence(db, scan, by_fp, existing, now)

    resolved = 0
    if not partial:
        resolved = _resolve_absent(db, scan, set(fps), ok_providers, now)
    changes["resolved"] = resolved

    by_type_severity: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for d in by_fp.values():
        by_type_severity[d.type][d.severity or "unrated"] += 1
    return {
        "new": changes["new"],
        "unchanged": changes["unchanged"],
        "resolved": resolved,
        "findings": len(by_fp),
        "by_type_severity": {t: dict(v) for t, v in by_type_severity.items()},
    }


def _store_evidence(
    db: Session, scan: Scan, by_fp: dict[str, FindingDraft], findings: dict[str, Finding], now: datetime
) -> None:
    ids = [findings[fp].id for fp in by_fp]
    known: dict[uuid.UUID, set[str]] = defaultdict(set)
    counts: Counter[uuid.UUID] = Counter()
    for chunk in _chunks(ids):
        for fid, sha, key in db.execute(
            select(Evidence.finding_id, Evidence.content_sha256, Evidence.evidence_key).where(
                Evidence.finding_id.in_(chunk)
            )
        ):
            known[fid].add(sha)
            counts[fid] = max(counts[fid], int(key.split("-")[1]) if key.startswith("ev-") else 0)
    rows = []
    for fp, d in by_fp.items():
        fid = findings[fp].id
        for ev in d.evidence:
            sha = ev.sha256
            if sha in known[fid]:
                continue
            known[fid].add(sha)
            counts[fid] += 1
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "finding_id": fid,
                    "scan_id": scan.id,
                    "evidence_key": f"ev-{counts[fid]}",
                    "kind": ev.kind,
                    "source": ev.source,
                    "url": ev.url[:1000] if ev.url else None,
                    "content": ev.content,
                    "content_sha256": sha,
                    "retrieved_at": now,
                }
            )
    for chunk in _chunks(rows, 500):
        db.execute(insert(Evidence).values(chunk).on_conflict_do_nothing())


def _resolve_absent(db: Session, scan: Scan, seen: set[str], ok_providers: set[str], now: datetime) -> int:
    # ``ok_providers`` contains providers that finished ``ok`` or were ``skipped`` as not applicable.
    usable = set(scan.providers) & ok_providers
    covered = [t for t, needs in COVERAGE.items() if needs <= usable]
    if not covered:
        return 0
    count = 0
    candidates = db.scalars(
        select(Finding)
        .where(
            Finding.project_id == scan.project_id, Finding.status.in_(["open", "dismissed"]), Finding.type.in_(covered)
        )
        .with_for_update()
    )
    for f in candidates:
        if f.fingerprint in seen:
            continue
        f.status = "resolved"
        f.resolved_scan_id = scan.id
        f.resolved_at = now
        f.last_change = "resolved"
        count += 1
    return count
