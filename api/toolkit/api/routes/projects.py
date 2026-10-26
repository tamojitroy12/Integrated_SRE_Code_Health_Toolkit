"""/projects endpoints, overview read model and lightweight summary (API_SPEC §5.2, WF-07)."""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError

from toolkit import audit
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.pagination import decode_cursor, encode_cursor
from toolkit.api.schemas.common import Out, Page, StrictModel, UtcDatetime
from toolkit.core.errors import ApiError, ErrorCode
from toolkit.db.models import (
    Alert,
    Finding,
    FixProposal,
    MonitoringTarget,
    Project,
    Repository,
    Scan,
    ScanProviderRun,
)
from toolkit.monitoring.prometheus import PrometheusClient, PrometheusUnavailable
from toolkit.monitoring.service import current_values
from toolkit.services.projects import get_project

log = logging.getLogger(__name__)
router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class ProjectPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)


class ProjectHealth(Out):
    open_alerts: int = 0
    unacknowledged_alerts: int = 0
    last_scan_status: str | None = None
    last_scan_at: UtcDatetime | None = None
    has_repository: bool = False
    target_count: int = 0


class ProjectOut(Out):
    id: uuid.UUID
    name: str
    description: str | None
    archived_at: UtcDatetime | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    health: ProjectHealth | None = None


def _health(db: DB, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, ProjectHealth]:
    """Health columns for many projects in a constant number of queries."""
    out = {pid: ProjectHealth() for pid in project_ids}
    if not project_ids:
        return out
    for pid, total, unack in db.execute(
        select(
            Alert.project_id,
            func.count(),
            func.count().filter(Alert.status == "firing"),
        )
        .where(Alert.project_id.in_(project_ids), Alert.status != "resolved")
        .group_by(Alert.project_id)
    ):
        out[pid].open_alerts = total
        out[pid].unacknowledged_alerts = unack
    latest = (
        select(Scan.project_id, Scan.status, Scan.created_at)
        .ext(distinct_on(Scan.project_id))
        .where(Scan.project_id.in_(project_ids))
        .order_by(Scan.project_id, Scan.created_at.desc())
    )
    for pid, status, created in db.execute(latest):
        out[pid].last_scan_status = status
        out[pid].last_scan_at = created
    for (pid,) in db.execute(select(Repository.project_id).where(Repository.project_id.in_(project_ids))):
        out[pid].has_repository = True
    for pid, count in db.execute(
        select(MonitoringTarget.project_id, func.count())
        .where(MonitoringTarget.project_id.in_(project_ids))
        .group_by(MonitoringTarget.project_id)
    ):
        out[pid].target_count = count
    return out


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, principal: Maintainer, db: DB, request: Request) -> ProjectOut:
    project = Project(name=body.name, description=body.description, created_by=principal.id)
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(ErrorCode.CONFLICT, "A project with this name already exists.") from exc
    audit.record(
        db,
        "project.created",
        actor_id=principal.id,
        resource_type="project",
        resource_id=project.id,
        ip=client_ip(request),
    )
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("", response_model=Page[ProjectOut])
def list_projects(
    principal: Viewer,
    db: DB,
    include_archived: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> Page[ProjectOut]:
    stmt = select(Project)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    if q:
        stmt = stmt.where(Project.name.ilike(f"%{_escape_like(q)}%", escape="\\"))
    if cursor:
        name, pid = decode_cursor(cursor, 2)
        stmt = stmt.where(
            or_(func.lower(Project.name) > name, and_(func.lower(Project.name) == name, Project.id > pid))
        )
    rows = list(db.scalars(stmt.order_by(func.lower(Project.name), Project.id).limit(limit + 1)))
    page = rows[:limit]
    health = _health(db, [p.id for p in page])
    items = [ProjectOut.model_validate(p).model_copy(update={"health": health[p.id]}) for p in page]
    nxt = encode_cursor([page[-1].name.lower(), page[-1].id]) if len(rows) > limit else None
    return Page(items=items, next_cursor=nxt)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/{project_id}", response_model=ProjectOut)
def get_project_detail(project_id: uuid.UUID, principal: Viewer, db: DB) -> ProjectOut:
    project = get_project(db, project_id)
    return ProjectOut.model_validate(project).model_copy(update={"health": _health(db, [project.id])[project.id]})


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, body: ProjectPatch, principal: Maintainer, db: DB, request: Request
) -> ProjectOut:
    project = get_project(db, project_id, writable=True, lock=True)
    if body.name is not None:
        project.name = body.name
    if "description" in body.model_fields_set:
        project.description = body.description
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(ErrorCode.CONFLICT, "A project with this name already exists.") from exc
    audit.record(
        db,
        "project.updated",
        actor_id=principal.id,
        resource_type="project",
        resource_id=project.id,
        ip=client_ip(request),
    )
    db.refresh(project)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=204)
def archive_project(
    project_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> Response:
    project = get_project(db, project_id, lock=True)
    if project.archived_at is None:
        project.archived_at = clock.now()
        # Archived projects are read-only: disable their rules so no new alerts fire.
        from toolkit.db.models import AlertRule

        for rule in db.scalars(select(AlertRule).where(AlertRule.project_id == project.id)):
            rule.enabled = False
        audit.record(
            db,
            "project.archived",
            actor_id=principal.id,
            resource_type="project",
            resource_id=project.id,
            ip=client_ip(request),
        )
    return Response(status_code=204)


# ----------------------------------------------------------------------------- overview
def _monitoring_section(db: DB, project: Project) -> dict[str, Any]:
    targets = list(
        db.scalars(
            select(MonitoringTarget).where(MonitoringTarget.project_id == project.id).order_by(MonitoringTarget.name)
        )
    )
    base: list[dict[str, Any]] = [
        {
            "id": str(t.id),
            "name": t.name,
            "service_name": t.service_name,
            "environment": t.environment,
            "status": t.status,
            "last_seen_at": t.last_seen_at,
            "current": None,
        }
        for t in targets
    ]
    if not targets:
        return {"status": "empty", "targets": []}
    client = PrometheusClient()
    try:
        values = current_values(client, targets)
    except PrometheusUnavailable:
        return {
            "status": "error",
            "error": {"code": "PROMETHEUS_UNAVAILABLE", "message": "Metrics store unreachable."},
            "targets": base,
        }
    finally:
        client.close()
    for item in base:
        item["current"] = values.get(str(item["id"]))
    return {"status": "ok", "targets": base}


def _alerts_section(db: DB, project: Project) -> dict[str, Any]:
    rows = db.execute(
        select(Alert.severity, Alert.status, func.count())
        .where(Alert.project_id == project.id, Alert.status != "resolved")
        .group_by(Alert.severity, Alert.status)
    ).all()
    by_sev: dict[str, int] = {}
    unack = 0
    for sev, status, count in rows:
        by_sev[sev] = by_sev.get(sev, 0) + count
        if status == "firing":
            unack += count
    recent = db.scalars(
        select(Alert)
        .where(Alert.project_id == project.id, Alert.status != "resolved")
        .order_by(Alert.last_seen_at.desc())
        .limit(5)
    ).all()
    total = sum(by_sev.values())
    return {
        "status": "ok" if total else "empty",
        "open_count": total,
        "unacknowledged_count": unack,
        "by_severity": by_sev,
        "recent": [
            {
                "id": str(a.id),
                "rule_name": a.rule_name,
                "severity": a.severity,
                "status": a.status,
                "last_seen_at": a.last_seen_at,
                "observed_value": a.evidence.get("observed_value"),
                "threshold": a.evidence.get("threshold"),
            }
            for a in recent
        ],
    }


def _scan_section(db: DB, project: Project) -> dict[str, Any]:
    has_repo = db.scalar(select(Repository.id).where(Repository.project_id == project.id)) is not None
    scan = db.scalar(select(Scan).where(Scan.project_id == project.id).order_by(Scan.created_at.desc()).limit(1))
    if scan is None:
        return {"status": "empty", "has_repository": has_repo}
    providers = db.scalars(
        select(ScanProviderRun).where(ScanProviderRun.scan_id == scan.id).order_by(ScanProviderRun.provider)
    ).all()
    return {
        "status": "ok",
        "has_repository": has_repo,
        "scan_id": str(scan.id),
        "scan_status": scan.status,
        "ref": scan.ref,
        "commit_sha": scan.commit_sha,
        "created_at": scan.created_at,
        "finished_at": scan.finished_at,
        "counts": scan.summary.get("by_type_severity", {}),
        "summary": scan.summary,
        "providers": [{"name": p.provider, "status": p.status, "error": p.error} for p in providers],
    }


def _top_findings(db: DB, project: Project) -> dict[str, Any]:
    rows = db.scalars(
        select(Finding)
        .where(Finding.project_id == project.id, Finding.status == "open")
        .order_by(Finding.severity_rank.desc(), Finding.last_seen_at.desc(), Finding.id)
        .limit(5)
    ).all()
    counts = dict(
        db.execute(
            select(Finding.severity, func.count())
            .where(Finding.project_id == project.id, Finding.status == "open")
            .group_by(Finding.severity)
        ).all()
    )
    return {
        "status": "ok" if rows else "empty",
        "open_by_severity": {(k or "unrated"): v for k, v in counts.items()},
        "items": [
            {
                "id": str(f.id),
                "type": f.type,
                "title": f.title,
                "severity": f.severity,
                "change": f.last_change,
                "package_name": f.package_name,
                "file_path": f.file_path,
            }
            for f in rows
        ],
    }


def _section(name: str, fn: Any, db: DB, project: Project) -> dict[str, Any]:
    try:
        result: dict[str, Any] = fn(db, project)
        return result
    except Exception:
        log.exception("overview section failed", extra={"section": name})
        return {"status": "error", "error": {"code": "INTERNAL_ERROR", "message": f"{name} unavailable"}}


@router.get("/{project_id}/overview")
def project_overview(project_id: uuid.UUID, principal: Viewer, db: DB, clock: ClockDep) -> dict[str, Any]:
    project = get_project(db, project_id)
    open_proposals = db.scalar(
        select(func.count())
        .select_from(FixProposal)
        .where(
            FixProposal.project_id == project.id,
            FixProposal.status.in_(["pending", "validating", "ready", "approved"]),
        )
    )
    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "description": project.description,
            "archived_at": project.archived_at,
        },
        "monitoring": _section("monitoring", _monitoring_section, db, project),
        "alerts": _section("alerts", _alerts_section, db, project),
        "latest_scan": _section("latest_scan", _scan_section, db, project),
        "top_findings": _section("top_findings", _top_findings, db, project),
        "open_fix_proposals": open_proposals or 0,
        "server_timestamp": clock.now(),
    }


@router.get("/{project_id}/summary")
def project_summary(project_id: uuid.UUID, principal: Viewer, db: DB, clock: ClockDep) -> dict[str, Any]:
    """Lightweight payload for the 15 s TopBar / overview poll (UI_UX_SPEC Appendix B.3)."""
    project = get_project(db, project_id)
    health = _health(db, [project.id])[project.id]
    counts = dict(
        db.execute(
            select(Finding.severity, func.count())
            .where(Finding.project_id == project.id, Finding.status == "open")
            .group_by(Finding.severity)
        ).all()
    )
    return {
        "project_id": str(project.id),
        "unacknowledged_alerts_count": health.unacknowledged_alerts,
        "open_alerts_count": health.open_alerts,
        "last_scan_status": health.last_scan_status,
        "open_findings_counts": {(k or "unrated"): v for k, v in counts.items()},
        "server_timestamp": clock.now(),
    }
