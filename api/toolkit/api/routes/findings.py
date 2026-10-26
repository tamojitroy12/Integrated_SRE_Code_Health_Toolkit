"""Findings explorer, detail and triage (API_SPEC §5.7, FR-DSH-02/03, FR-SAST-04)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import Select, and_, func, or_, select

from toolkit import audit
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.pagination import decode_cursor, encode_cursor
from toolkit.api.schemas.common import StrictModel
from toolkit.core.errors import ApiError, ErrorCode, not_found
from toolkit.db.models import (
    Evidence,
    Finding,
    FindingOccurrence,
    FixProposal,
    FixProposalFinding,
    Recommendation,
    Scan,
    User,
)
from toolkit.services.projects import get_project

router = APIRouter(tags=["findings"])

TypeLit = Literal["dependency_vulnerability", "dependency_outdated", "dependency_incompatibility", "code_issue"]
SeverityLit = Literal["critical", "high", "medium", "low", "info", "unrated"]
StatusLit = Literal["open", "dismissed", "resolved"]
ChangeLit = Literal["new", "unchanged", "resolved"]
SortLit = Literal["severity", "-severity", "first_seen_at", "-first_seen_at", "last_seen_at", "-last_seen_at"]

_SORT_COLUMNS = {
    "severity": Finding.severity_rank,
    "first_seen_at": Finding.first_seen_at,
    "last_seen_at": Finding.last_seen_at,
}


def evidence_out(e: Evidence) -> dict[str, Any]:
    return {
        "id": e.evidence_key,
        "kind": e.kind,
        "source": e.source,
        "url": e.url,
        "retrieved_at": e.retrieved_at,
        "content": e.content,
    }


def finding_summary(f: Finding) -> dict[str, Any]:
    return {
        "id": str(f.id),
        "project_id": str(f.project_id),
        "type": f.type,
        "title": f.title,
        "severity": f.severity,
        "severity_source": f.severity_source,
        "status": f.status,
        "change": f.last_change,
        "fingerprint": f.fingerprint,
        "subject": _subject(f),
        "advisory_ids": (f.advisory or {}).get("ids", []),
        "sources": f.sources,
        "dismissal_reason": f.dismissal_reason,
        "first_seen_at": f.first_seen_at,
        "last_seen_at": f.last_seen_at,
    }


def _subject(f: Finding) -> dict[str, Any]:
    if f.type == "code_issue":
        return {"file_path": f.file_path, "line_start": f.line_start, "line_end": f.line_end, "rule_id": f.rule_id}
    return {
        "ecosystem": f.ecosystem,
        "name": f.package_name,
        "version": f.package_version,
        "scope": f.scope,
        "manifest_path": f.manifest_path,
    }


def _apply_filters(
    stmt: Select[Any],
    *,
    type_: Sequence[str] | None,
    severity: Sequence[str] | None,
    status: Sequence[str] | None,
    scan_id: uuid.UUID | None,
    package: str | None,
    path: str | None,
    change: Sequence[str] | None,
    q: str | None,
) -> Select[Any]:
    if type_:
        stmt = stmt.where(Finding.type.in_(type_))
    if severity:
        sev = [s for s in severity if s != "unrated"]
        conds = [Finding.severity.in_(sev)] if sev else []
        if "unrated" in severity:
            conds.append(Finding.severity.is_(None))
        stmt = stmt.where(or_(*conds))
    if status:
        stmt = stmt.where(Finding.status.in_(status))
    if scan_id:
        stmt = stmt.where(
            Finding.id.in_(select(FindingOccurrence.finding_id).where(FindingOccurrence.scan_id == scan_id))
        )
    if package:
        stmt = stmt.where(Finding.package_name == package)
    if path:
        stmt = stmt.where(Finding.file_path.startswith(path, autoescape=True))
    if change:
        stmt = stmt.where(Finding.last_change.in_(change))
    if q:
        stmt = stmt.where(Finding.search_text.contains(q.lower(), autoescape=True))
    return stmt


@router.get("/projects/{project_id}/findings")
def list_findings(
    project_id: uuid.UUID,
    principal: Viewer,
    db: DB,
    type: Annotated[list[TypeLit] | None, Query()] = None,
    severity: Annotated[list[SeverityLit] | None, Query()] = None,
    status: Annotated[list[StatusLit] | None, Query()] = None,
    scan_id: uuid.UUID | None = None,
    package: Annotated[str | None, Query(max_length=214)] = None,
    path: Annotated[str | None, Query(max_length=500)] = None,
    change: Annotated[list[ChangeLit] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: SortLit = "-severity",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    get_project(db, project_id)
    base = _apply_filters(
        select(Finding).where(Finding.project_id == project_id),
        type_=type,
        severity=severity,
        status=status,
        scan_id=scan_id,
        package=package,
        path=path,
        change=change,
        q=q,
    )
    desc = sort.startswith("-")
    col = _SORT_COLUMNS[sort.lstrip("-")]
    stmt = base
    if cursor:
        value, fid = decode_cursor(cursor, 2)
        if desc:
            stmt = stmt.where(or_(col < value, and_(col == value, Finding.id > fid)))
        else:
            stmt = stmt.where(or_(col > value, and_(col == value, Finding.id > fid)))
    order: list[Any] = [col.desc() if desc else col.asc(), Finding.id.asc()]
    rows: list[Finding] = list(db.scalars(stmt.order_by(*order).limit(limit + 1)))
    page = rows[:limit]
    nxt = None
    if len(rows) > limit:
        last = page[-1]
        key = {"severity": last.severity_rank, "first_seen_at": last.first_seen_at, "last_seen_at": last.last_seen_at}[
            sort.lstrip("-")
        ]
        nxt = encode_cursor([key, last.id])
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    return {"items": [finding_summary(f) for f in page], "next_cursor": nxt, "total": total}


@router.get("/projects/{project_id}/findings/suggestions")
def finding_suggestions(
    project_id: uuid.UUID, principal: Viewer, db: DB, q: Annotated[str, Query(min_length=1, max_length=100)]
) -> dict[str, Any]:
    """Autocomplete for the explorer search (UI_UX_SPEC §9): packages, files, advisory IDs."""
    get_project(db, project_id)
    like = q.lower()
    packages = db.scalars(
        select(Finding.package_name)
        .where(
            Finding.project_id == project_id,
            Finding.package_name.is_not(None),
            func.lower(Finding.package_name).contains(like, autoescape=True),
        )
        .distinct()
        .limit(5)
    ).all()
    files = db.scalars(
        select(Finding.file_path)
        .where(
            Finding.project_id == project_id,
            Finding.file_path.is_not(None),
            func.lower(Finding.file_path).contains(like, autoescape=True),
        )
        .distinct()
        .limit(5)
    ).all()
    advisories = db.scalars(
        select(func.jsonb_array_elements_text(Finding.advisory["ids"]))
        .where(
            Finding.project_id == project_id,
            Finding.advisory.is_not(None),
            Finding.search_text.contains(like, autoescape=True),
        )
        .distinct()
        .limit(20)
    ).all()
    return {
        "packages": list(packages),
        "files": list(files),
        "advisories": [a for a in advisories if like in a.lower()][:5],
    }


def _get_finding(db: DB, finding_id: uuid.UUID, lock: bool = False) -> Finding:
    f = db.get(Finding, finding_id, with_for_update=lock)
    if f is None:
        raise not_found("Finding")
    return f


@router.get("/findings/{finding_id}")
def finding_detail(finding_id: uuid.UUID, principal: Viewer, db: DB) -> dict[str, Any]:
    f = _get_finding(db, finding_id)
    evidence = db.scalars(select(Evidence).where(Evidence.finding_id == f.id).order_by(Evidence.retrieved_at)).all()
    history = db.execute(
        select(FindingOccurrence.change, Scan.id, Scan.created_at, Scan.commit_sha, Scan.status)
        .join(Scan, Scan.id == FindingOccurrence.scan_id)
        .where(FindingOccurrence.finding_id == f.id)
        .order_by(Scan.created_at.desc())
        .limit(20)
    ).all()
    recs = db.scalars(
        select(Recommendation)
        .where(Recommendation.finding_id == f.id)
        .order_by(Recommendation.created_at.desc())
        .limit(10)
    ).all()
    proposals = db.scalars(
        select(FixProposal)
        .join(FixProposalFinding, FixProposalFinding.fix_proposal_id == FixProposal.id)
        .where(FixProposalFinding.finding_id == f.id)
        .order_by(FixProposal.created_at.desc())
        .limit(10)
    ).all()
    dismissed_by = db.get(User, f.dismissed_by) if f.dismissed_by else None
    out = finding_summary(f)
    out.update(
        {
            "message": f.message,
            "advisory": f.advisory,
            "detail": f.detail,
            "evidence": [evidence_out(e) for e in evidence],
            "first_seen_scan_id": str(f.first_seen_scan_id) if f.first_seen_scan_id else None,
            "last_seen_scan_id": str(f.last_seen_scan_id) if f.last_seen_scan_id else None,
            "resolved_scan_id": str(f.resolved_scan_id) if f.resolved_scan_id else None,
            "resolved_at": f.resolved_at,
            "dismissal": {
                "reason": f.dismissal_reason,
                "note": f.dismissal_note,
                "at": f.dismissed_at,
                "by": {"id": str(dismissed_by.id), "display_name": dismissed_by.display_name} if dismissed_by else None,
            }
            if f.status == "dismissed"
            else None,
            "history": [
                {"scan_id": str(sid), "created_at": created, "commit_sha": sha, "scan_status": sst, "change": change}
                for change, sid, created, sha, sst in history
            ],
            "recommendations": [
                {
                    "id": str(r.id),
                    "kind": r.kind,
                    "status": r.status,
                    "validation_status": r.validation_status,
                    "created_at": r.created_at,
                }
                for r in recs
            ],
            "fix_proposals": [
                {
                    "id": str(p.id),
                    "status": p.status,
                    "validation_result": p.validation_result,
                    "pr_url": p.pr_url,
                    "created_at": p.created_at,
                }
                for p in proposals
            ],
            "fixable": f.type in ("dependency_vulnerability", "dependency_outdated", "dependency_incompatibility")
            and f.status == "open"
            and bool(_fix_target(f)),
        }
    )
    return out


def _fix_target(f: Finding) -> str | None:
    from toolkit.remediation.plan import target_version_for

    return target_version_for(f)


class TriageIn(StrictModel):
    status: Literal["dismissed", "open"]
    dismissal_reason: Literal["false_positive", "accepted_risk", "wont_fix"] | None = None
    note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _reason(self) -> TriageIn:
        if self.status == "dismissed" and self.dismissal_reason is None:
            raise ValueError("dismissal_reason is required when dismissing")
        return self


@router.patch("/findings/{finding_id}")
def triage_finding(
    finding_id: uuid.UUID, body: TriageIn, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> dict[str, Any]:
    f = _get_finding(db, finding_id, lock=True)
    get_project(db, f.project_id, writable=True)
    if f.status == "resolved":
        raise ApiError(ErrorCode.INVALID_TRANSITION, "Resolved findings cannot be triaged.")
    if body.status == "dismissed":
        f.status = "dismissed"
        f.dismissal_reason = body.dismissal_reason
        f.dismissal_note = body.note
        f.dismissed_by = principal.id
        f.dismissed_at = clock.now()
    else:
        f.status = "open"
        f.dismissal_reason = f.dismissal_note = None
        f.dismissed_by = None
        f.dismissed_at = None
    audit.record(
        db,
        f"finding.{'dismissed' if body.status == 'dismissed' else 'reopened'}",
        actor_id=principal.id,
        resource_type="finding",
        resource_id=f.id,
        metadata={"reason": body.dismissal_reason},
        ip=client_ip(request),
    )
    db.flush()
    return finding_detail(f.id, principal, db)
