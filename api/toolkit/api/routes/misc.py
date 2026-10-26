"""Audit log, search, activity timeline (API_SPEC §5.10, UI_UX_SPEC Appendix B, FR-DSH-07)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from toolkit.api.deps import DB, Admin, Viewer
from toolkit.api.pagination import decode_cursor, encode_cursor
from toolkit.db.models import Alert, AuditLog, Finding, FixProposal, Project, Scan, User
from toolkit.services.projects import get_project

router = APIRouter(tags=["misc"])


@router.get("/audit-log")
def audit_log(
    principal: Admin,
    db: DB,
    actor_id: uuid.UUID | None = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    q = select(AuditLog, User.display_name).outerjoin(User, User.id == AuditLog.actor_id)
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if action:
        q = q.where(AuditLog.action.startswith(action, autoescape=True))
    if from_:
        q = q.where(AuditLog.created_at >= from_)
    if to:
        q = q.where(AuditLog.created_at <= to)
    if cursor:
        created, aid = decode_cursor(cursor, 2)
        q = q.where(or_(AuditLog.created_at < created, and_(AuditLog.created_at == created, AuditLog.id < aid)))
    rows = db.execute(q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)).all()
    page = rows[:limit]
    nxt = encode_cursor([page[-1][0].created_at, page[-1][0].id]) if len(rows) > limit else None
    return {
        "items": [
            {
                "id": str(a.id),
                "action": a.action,
                "actor": {"id": str(a.actor_id), "display_name": name} if a.actor_id else None,
                "resource_type": a.resource_type,
                "resource_id": a.resource_id,
                "metadata": a.meta,
                "ip": a.ip,
                "created_at": a.created_at,
            }
            for a, name in page
        ],
        "next_cursor": nxt,
    }


@router.get("/search")
def search(
    principal: Viewer,
    db: DB,
    q: Annotated[str, Query(min_length=1, max_length=100)],
    project_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=5)] = 5,
) -> dict[str, Any]:
    """Grouped matches for the ⌘K palette (UI_UX_SPEC Appendix B.2)."""
    term = q.strip().lower()
    projects = db.scalars(
        select(Project)
        .where(Project.archived_at.is_(None), func.lower(Project.name).contains(term, autoescape=True))
        .order_by(Project.name)
        .limit(limit)
    ).all()
    fq = select(Finding).where(Finding.search_text.contains(term, autoescape=True), Finding.status != "resolved")
    aq = select(Alert).where(func.lower(Alert.rule_name).contains(term, autoescape=True))
    if project_id:
        fq = fq.where(Finding.project_id == project_id)
        aq = aq.where(Alert.project_id == project_id)
    findings = db.scalars(fq.order_by(Finding.severity_rank.desc(), Finding.last_seen_at.desc()).limit(limit)).all()
    alerts = db.scalars(aq.order_by(Alert.last_seen_at.desc()).limit(limit)).all()
    return {
        "projects": [{"id": str(p.id), "name": p.name} for p in projects],
        "findings": [
            {"id": str(f.id), "project_id": str(f.project_id), "title": f.title, "severity": f.severity, "type": f.type}
            for f in findings
        ],
        "alerts": [
            {
                "id": str(a.id),
                "project_id": str(a.project_id),
                "rule_name": a.rule_name,
                "severity": a.severity,
                "status": a.status,
            }
            for a in alerts
        ],
    }


@router.get("/projects/{project_id}/timeline")
def timeline(
    project_id: uuid.UUID, principal: Viewer, db: DB, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> dict[str, Any]:
    """Time-ordered alerts, scans and PR events. Temporal order only, not causation (FR-DSH-07)."""
    get_project(db, project_id)
    events: list[dict[str, Any]] = []
    for a in db.scalars(
        select(Alert).where(Alert.project_id == project_id).order_by(Alert.first_seen_at.desc()).limit(limit)
    ):
        events.append(
            {
                "at": a.first_seen_at,
                "kind": "alert_fired",
                "id": str(a.id),
                "label": f"{a.rule_name} fired ({a.severity})",
            }
        )
        if a.resolved_at:
            events.append(
                {"at": a.resolved_at, "kind": "alert_resolved", "id": str(a.id), "label": f"{a.rule_name} resolved"}
            )
    for s in db.scalars(
        select(Scan).where(Scan.project_id == project_id).order_by(Scan.created_at.desc()).limit(limit)
    ):
        events.append(
            {
                "at": s.finished_at or s.created_at,
                "kind": "scan",
                "id": str(s.id),
                "label": f"Scan {s.status}" + (f" at {s.commit_sha[:7]}" if s.commit_sha else ""),
            }
        )
    for p in db.scalars(
        select(FixProposal)
        .where(FixProposal.project_id == project_id, FixProposal.pr_url.is_not(None))
        .order_by(FixProposal.updated_at.desc())
        .limit(limit)
    ):
        events.append(
            {"at": p.updated_at, "kind": "pr_opened", "id": str(p.id), "label": f"Draft PR #{p.pr_number} opened"}
        )
    events.sort(key=lambda e: e["at"], reverse=True)
    return {"items": events[:limit], "note": "Events are ordered by time only; no causation is implied."}
