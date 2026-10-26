"""Scans, dependency inventory and job status (API_SPEC §5.6)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from toolkit import audit
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.pagination import decode_cursor, encode_cursor
from toolkit.api.schemas.common import StrictModel
from toolkit.core.errors import ApiError, ErrorCode, not_found
from toolkit.core.validators import is_valid_git_ref
from toolkit.db.models import Dependency, Job, Repository, Scan, ScanProviderRun
from toolkit.jobs import queue
from toolkit.services.projects import get_project

router = APIRouter(tags=["scans"])

ProviderLit = Literal["trivy", "osv", "registry", "semgrep"]
ALL_PROVIDERS = ["trivy", "osv", "registry", "semgrep"]


class ScanCreate(StrictModel):
    ref: str | None = Field(default=None, max_length=200)
    providers: list[ProviderLit] | None = Field(default=None, min_length=1, max_length=4)

    @field_validator("ref")
    @classmethod
    def _ref(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_git_ref(v):
            raise ValueError("must match ^[A-Za-z0-9._/-]{1,200}$, not contain '..' and not start with '-'")
        return v


def scan_out(db: DB, scan: Scan, *, with_job: bool = True) -> dict[str, Any]:
    providers = db.scalars(
        select(ScanProviderRun).where(ScanProviderRun.scan_id == scan.id).order_by(ScanProviderRun.provider)
    ).all()
    job = db.get(Job, scan.job_id) if (with_job and scan.job_id) else None
    return {
        "id": str(scan.id),
        "project_id": str(scan.project_id),
        "status": scan.status,
        "ref": scan.ref,
        "commit_sha": scan.commit_sha,
        "trigger": scan.trigger,
        "requested_providers": scan.providers,
        "created_at": scan.created_at,
        "started_at": scan.started_at,
        "finished_at": scan.finished_at,
        "error": {"code": scan.error_code, "message": scan.error_message} if scan.error_code else None,
        "providers": [
            {
                "name": p.provider,
                "status": p.status,
                "duration_ms": p.duration_ms,
                "error": p.error,
                "tool_version": p.tool_version,
                "db_info": p.db_info,
            }
            for p in providers
        ],
        "summary": scan.summary,
        "job": queue.job_out(job) if job else None,
    }


def create_scan(
    db: DB,
    project_id: uuid.UUID,
    ref: str | None,
    providers: Sequence[str] | None,
    actor_id: uuid.UUID | None,
    trigger: str = "manual",
) -> tuple[Scan, Job]:
    """Shared by the manual endpoint and the scheduler (FR-DEP-08: identical code paths)."""
    repo = db.scalar(select(Repository).where(Repository.project_id == project_id))
    if repo is None:
        raise ApiError(ErrorCode.CONFLICT, "Connect a repository before scanning.")
    active = db.scalar(select(Scan.id).where(Scan.project_id == project_id, Scan.status.in_(["queued", "running"])))
    if active:
        raise ApiError(ErrorCode.CONFLICT, "A scan is already running for this project.")
    scan = Scan(
        id=uuid.uuid4(),
        project_id=project_id,
        repository_id=repo.id,
        ref=ref or repo.default_branch,
        status="queued",
        trigger=trigger,
        providers=sorted(set(providers or ALL_PROVIDERS)),
        created_by=actor_id,
        summary={},
    )
    db.add(scan)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(ErrorCode.CONFLICT, "A scan is already running for this project.") from exc
    job = queue.enqueue(
        db, "scan", payload={"scan_id": str(scan.id)}, resource_type="scan", resource_id=scan.id, created_by=actor_id
    )
    scan.job_id = job.id
    return scan, job


@router.post("/projects/{project_id}/scans", status_code=202)
def start_scan(
    project_id: uuid.UUID, principal: Maintainer, db: DB, request: Request, body: ScanCreate | None = None
) -> dict[str, Any]:
    get_project(db, project_id, writable=True, lock=True)
    body = body or ScanCreate()
    scan, job = create_scan(db, project_id, body.ref, body.providers, principal.id)
    audit.record(
        db,
        "scan.triggered",
        actor_id=principal.id,
        resource_type="scan",
        resource_id=scan.id,
        metadata={"ref": scan.ref, "providers": scan.providers},
        ip=client_ip(request),
    )
    return {
        "scan": {"id": str(scan.id), "status": scan.status, "ref": scan.ref},
        "job": {"id": str(job.id), "type": job.type, "status": job.status},
    }


@router.get("/projects/{project_id}/scans")
def list_scans(
    project_id: uuid.UUID,
    principal: Viewer,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: str | None = None,
) -> dict[str, Any]:
    get_project(db, project_id)
    q = select(Scan).where(Scan.project_id == project_id)
    if cursor:
        created, sid = decode_cursor(cursor, 2)
        q = q.where(or_(Scan.created_at < created, and_(Scan.created_at == created, Scan.id < sid)))
    rows = list(db.scalars(q.order_by(Scan.created_at.desc(), Scan.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    nxt = encode_cursor([page[-1].created_at, page[-1].id]) if len(rows) > limit else None
    return {"items": [scan_out(db, s) for s in page], "next_cursor": nxt}


def _get_scan(db: DB, scan_id: uuid.UUID) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None:
        raise not_found("Scan")
    return scan


@router.get("/scans/{scan_id}")
def scan_detail(scan_id: uuid.UUID, principal: Viewer, db: DB) -> dict[str, Any]:
    return scan_out(db, _get_scan(db, scan_id))


@router.get("/scans/{scan_id}/dependencies")
def scan_dependencies(
    scan_id: uuid.UUID,
    principal: Viewer,
    db: DB,
    ecosystem: Literal["npm", "pypi"] | None = None,
    scope: Literal["direct", "transitive"] | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    _get_scan(db, scan_id)
    stmt = select(Dependency).where(Dependency.scan_id == scan_id)
    if ecosystem:
        stmt = stmt.where(Dependency.ecosystem == ecosystem)
    if scope:
        stmt = stmt.where(Dependency.scope == scope)
    if q:
        stmt = stmt.where(Dependency.name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    if cursor:
        name, did = decode_cursor(cursor, 2)
        stmt = stmt.where(or_(Dependency.name > name, and_(Dependency.name == name, Dependency.id > did)))
    rows = list(db.scalars(stmt.order_by(Dependency.name, Dependency.id).limit(limit + 1)))
    page = rows[:limit]
    nxt = encode_cursor([page[-1].name, page[-1].id]) if len(rows) > limit else None
    return {
        "items": [
            {
                "id": str(d.id),
                "ecosystem": d.ecosystem,
                "name": d.name,
                "version": d.version,
                "scope": d.scope,
                "manifest_path": d.manifest_path,
                "purl": d.purl,
            }
            for d in page
        ],
        "next_cursor": nxt,
    }


@router.get("/jobs/{job_id}")
def job_status(job_id: uuid.UUID, principal: Viewer, db: DB) -> dict[str, Any]:
    job = db.get(Job, job_id)
    if job is None:
        raise not_found("Job")
    return queue.job_out(job)


@router.post("/jobs/{job_id}/cancel", status_code=202)
def cancel_job(job_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep, request: Request) -> JSONResponse:
    job = db.get(Job, job_id, with_for_update=True)
    if job is None:
        raise not_found("Job")
    if job.status in ("succeeded", "partial", "failed", "cancelled"):
        raise ApiError(ErrorCode.INVALID_TRANSITION, f"Job is already {job.status}.")
    queue.request_cancel(db, job, clock.now())
    audit.record(
        db,
        "job.cancel_requested",
        actor_id=principal.id,
        resource_type="job",
        resource_id=job.id,
        ip=client_ip(request),
    )
    db.flush()
    return JSONResponse(status_code=202, content=jsonable_encoder(queue.job_out(job)))
