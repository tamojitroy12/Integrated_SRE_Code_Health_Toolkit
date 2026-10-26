"""Fix proposals (API_SPEC §5.9, FR-REM-01, FR-REM-06..12). There is no merge endpoint."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import and_, or_, select

from toolkit import audit
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.pagination import decode_cursor, encode_cursor
from toolkit.api.schemas.common import StrictModel
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode, not_found, validation_error
from toolkit.db.models import Finding, FixProposal, FixProposalFinding, Job, Repository, User, ValidationRun
from toolkit.jobs import queue
from toolkit.remediation.gates import ApprovalRequest, check_approval, record_approval
from toolkit.remediation.plan import PlanError, build_plan
from toolkit.services.projects import get_project

router = APIRouter(tags=["fix-proposals"])


class ProposalCreate(StrictModel):
    finding_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class ApproveIn(StrictModel):
    acknowledge_unverified: bool = False
    acknowledge_breaking_change: bool = False
    acknowledge_reviewed: bool = True
    comment: str | None = Field(default=None, max_length=2000)


class RejectIn(StrictModel):
    reason: str | None = Field(default=None, max_length=1000)


def _run_out(r: ValidationRun) -> dict[str, Any]:
    return {
        "stage": r.stage,
        "status": r.status,
        "exit_code": r.exit_code,
        "duration_s": r.duration_s,
        "output_tail": r.output_tail,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
    }


def proposal_out(db: DB, p: FixProposal, *, detail: bool = True) -> dict[str, Any]:
    finding_ids = [
        str(f)
        for f in db.scalars(select(FixProposalFinding.finding_id).where(FixProposalFinding.fix_proposal_id == p.id))
    ]
    out: dict[str, Any] = {
        "id": str(p.id),
        "project_id": str(p.project_id),
        "status": p.status,
        "finding_ids": finding_ids,
        "base_commit_sha": p.base_commit_sha,
        "changes": p.changes,
        "has_major_bump": p.has_major_bump,
        "validation": {"result": p.validation_result},
        "pull_request": {
            "number": p.pr_number,
            "url": p.pr_url,
            "draft": True,
            "branch": p.pr_branch,
            "closed_at": p.pr_closed_at,
        }
        if p.pr_number
        else None,
        "pr_error": p.pr_error,
        "error": {"code": p.error_code, "message": p.error_message} if p.error_code else None,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }
    job = db.get(Job, p.job_id) if p.job_id else None
    out["job"] = queue.job_out(job) if job else None
    if not detail:
        return out
    runs = list(
        db.scalars(
            select(ValidationRun).where(ValidationRun.fix_proposal_id == p.id).order_by(ValidationRun.started_at)
        )
    )
    by_stage = {r.stage: r for r in runs}
    out["validation"] = {
        "result": p.validation_result,
        "baseline": _run_out(by_stage["baseline"]) if "baseline" in by_stage else None,
        "apply": _run_out(by_stage["apply"]) if "apply" in by_stage else None,
        "post_change": _run_out(by_stage["post_change"]) if "post_change" in by_stage else None,
        "delta_scan": p.delta_scan,
        "runs": [_run_out(r) for r in runs],
    }
    out["diff"] = p.diff
    out["risk_notes"] = p.risk_notes
    approver = db.get(User, p.approved_by) if p.approved_by else None
    out["approval"] = (
        {
            "by": {"id": str(approver.id), "display_name": approver.display_name} if approver else None,
            "at": p.approved_at,
            **(p.approval_ack or {}),
        }
        if p.approved_at
        else None
    )
    out["rejection"] = {"reason": p.rejection_reason} if p.status == "rejected" else None
    repo = db.scalar(select(Repository).where(Repository.project_id == p.project_id))
    out["repository"] = {"can_open_prs": repo.can_open_prs, "url": repo.url} if repo else None
    return out


@router.post("/projects/{project_id}/fix-proposals", status_code=202)
def create_proposal(
    project_id: uuid.UUID, body: ProposalCreate, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> dict[str, Any]:
    if not get_settings().remediation_enabled:
        raise ApiError(ErrorCode.REMEDIATION_DISABLED)
    project = get_project(db, project_id, writable=True)
    ids = list(dict.fromkeys(body.finding_ids))
    findings = list(db.scalars(select(Finding).where(Finding.id.in_(ids))))
    if len(findings) != len(ids) or any(f.project_id != project.id for f in findings):
        raise validation_error("finding_ids", "all findings must exist and belong to this project")
    if any(f.status != "open" for f in findings):
        raise validation_error("finding_ids", "only open findings can be fixed")
    try:
        changes = build_plan(findings)  # validated up front so the user gets a precise 422
    except PlanError as exc:
        raise validation_error("finding_ids", str(exc)) from exc
    repo = db.scalar(select(Repository).where(Repository.project_id == project.id))
    if repo is None:
        raise ApiError(ErrorCode.CONFLICT, "Connect a repository first.")
    from toolkit.db.models import Scan

    scan = db.get(Scan, findings[0].last_seen_scan_id) if findings[0].last_seen_scan_id else None
    p = FixProposal(
        id=uuid.uuid4(),
        project_id=project.id,
        status="pending",
        base_commit_sha=scan.commit_sha if scan else None,
        base_ref=scan.ref if scan else None,
        changes=[c.as_dict() for c in changes],
        has_major_bump=any(c.bump == "major" for c in changes),
        validation_result="not_run",
        risk_notes=[],
        requested_by=principal.id,
    )
    db.add(p)
    db.flush()
    for f in findings:
        db.add(FixProposalFinding(fix_proposal_id=p.id, finding_id=f.id))
    # Older ready proposals for the same findings are superseded (WF-06 state machine).
    older = (
        db.scalars(
            select(FixProposal)
            .join(FixProposalFinding, FixProposalFinding.fix_proposal_id == FixProposal.id)
            .where(FixProposalFinding.finding_id.in_(ids), FixProposal.id != p.id, FixProposal.status == "ready")
        )
        .unique()
        .all()
    )
    for o in older:
        o.status = "superseded"
    job = queue.enqueue(
        db,
        "fix_proposal",
        payload={"proposal_id": str(p.id)},
        resource_type="fix_proposal",
        resource_id=p.id,
        created_by=principal.id,
    )
    p.job_id = job.id
    audit.record(
        db,
        "fix.proposal_created",
        actor_id=principal.id,
        resource_type="fix_proposal",
        resource_id=p.id,
        metadata={"findings": [str(i) for i in ids]},
        ip=client_ip(request),
    )
    return {
        "proposal": {"id": str(p.id), "status": p.status, "changes": p.changes},
        "job": {"id": str(job.id), "type": job.type, "status": job.status},
    }


@router.get("/projects/{project_id}/fix-proposals")
def list_proposals(
    project_id: uuid.UUID,
    principal: Viewer,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    get_project(db, project_id)
    q = select(FixProposal).where(FixProposal.project_id == project_id)
    if cursor:
        created, pid = decode_cursor(cursor, 2)
        q = q.where(
            or_(FixProposal.created_at < created, and_(FixProposal.created_at == created, FixProposal.id < pid))
        )
    rows = list(db.scalars(q.order_by(FixProposal.created_at.desc(), FixProposal.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    nxt = encode_cursor([page[-1].created_at, page[-1].id]) if len(rows) > limit else None
    return {
        "items": [proposal_out(db, p, detail=False) for p in page],
        "next_cursor": nxt,
        "remediation_enabled": get_settings().remediation_enabled,
    }


def _get(db: DB, proposal_id: uuid.UUID, lock: bool = False) -> FixProposal:
    p = db.get(FixProposal, proposal_id, with_for_update=lock)
    if p is None:
        raise not_found("Fix proposal")
    return p


@router.get("/fix-proposals/{proposal_id}")
def proposal_detail(proposal_id: uuid.UUID, principal: Viewer, db: DB) -> dict[str, Any]:
    return proposal_out(db, _get(db, proposal_id))


@router.post("/fix-proposals/{proposal_id}/approve", status_code=202)
def approve_proposal(
    proposal_id: uuid.UUID, body: ApproveIn, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> JSONResponse:
    if not get_settings().remediation_enabled:
        raise ApiError(ErrorCode.REMEDIATION_DISABLED)
    p = _get(db, proposal_id, lock=True)
    get_project(db, p.project_id, writable=True)
    if not body.acknowledge_reviewed:
        raise ApiError(ErrorCode.ACK_REQUIRED, "Confirm that you reviewed the diff and test report.")
    req = ApprovalRequest(body.acknowledge_unverified, body.acknowledge_breaking_change, body.comment)
    override = check_approval(p, principal.role, req)
    repo = db.scalar(select(Repository).where(Repository.project_id == p.project_id))
    if repo is None or repo.credential_id is None:
        raise ApiError(ErrorCode.CONFLICT, "A repository token with write access is required to open a PR.")
    record_approval(p, principal.id, clock.now(), req, override)
    db.flush()
    job = queue.enqueue(
        db,
        "pr_creation",
        payload={"proposal_id": str(p.id)},
        resource_type="fix_proposal",
        resource_id=p.id,
        created_by=principal.id,
        max_attempts=1,
    )
    audit.record(
        db,
        "fix.approved",
        actor_id=principal.id,
        resource_type="fix_proposal",
        resource_id=p.id,
        metadata={"acknowledgments": p.approval_ack},
        ip=client_ip(request),
    )
    if override:
        audit.record(
            db,
            "fix.admin_override",
            actor_id=principal.id,
            resource_type="fix_proposal",
            resource_id=p.id,
            metadata={"comment": body.comment},
            ip=client_ip(request),
        )
    return JSONResponse(
        status_code=202,
        content=jsonable_encoder(
            {
                "proposal": {"id": str(p.id), "status": p.status},
                "job": {"id": str(job.id), "type": job.type, "status": job.status},
            }
        ),
    )


@router.post("/fix-proposals/{proposal_id}/retry-pr", status_code=202)
def retry_pr(proposal_id: uuid.UUID, principal: Maintainer, db: DB, request: Request) -> dict[str, Any]:
    """User-initiated retry after a PR error (WORKFLOW error paths: no automatic retry loop)."""
    p = _get(db, proposal_id, lock=True)
    if p.status != "approved" or not p.pr_error:
        raise ApiError(ErrorCode.INVALID_TRANSITION, "Only approved proposals with a PR error can be retried.")
    if queue.active_job_for(db, "fix_proposal", p.id):
        raise ApiError(ErrorCode.CONFLICT, "A job for this proposal is already running.")
    job = queue.enqueue(
        db,
        "pr_creation",
        payload={"proposal_id": str(p.id)},
        resource_type="fix_proposal",
        resource_id=p.id,
        created_by=principal.id,
        max_attempts=1,
    )
    audit.record(
        db, "fix.pr_retry", actor_id=principal.id, resource_type="fix_proposal", resource_id=p.id, ip=client_ip(request)
    )
    return {
        "proposal": {"id": str(p.id), "status": p.status},
        "job": {"id": str(job.id), "type": job.type, "status": job.status},
    }


@router.post("/fix-proposals/{proposal_id}/reject")
def reject_proposal(
    proposal_id: uuid.UUID, principal: Maintainer, db: DB, request: Request, body: RejectIn | None = None
) -> dict[str, Any]:
    p = _get(db, proposal_id, lock=True)
    if p.status != "ready":
        raise ApiError(ErrorCode.INVALID_TRANSITION, f"Only ready proposals can be rejected (is {p.status}).")
    p.status = "rejected"
    p.rejected_by = principal.id
    p.rejection_reason = body.reason if body else None
    audit.record(
        db, "fix.rejected", actor_id=principal.id, resource_type="fix_proposal", resource_id=p.id, ip=client_ip(request)
    )
    db.flush()
    return proposal_out(db, p)


@router.post("/fix-proposals/{proposal_id}/cleanup", status_code=202)
def cleanup_proposal(proposal_id: uuid.UUID, principal: Maintainer, db: DB, request: Request) -> dict[str, Any]:
    p = _get(db, proposal_id, lock=True)
    if p.status != "pr_opened" or not p.pr_branch:
        raise ApiError(ErrorCode.INVALID_TRANSITION, "Only proposals with an open Toolkit PR can be cleaned up.")
    if p.pr_closed_at is not None:
        raise ApiError(ErrorCode.CONFLICT, "The PR was already closed.")
    job = queue.enqueue(
        db,
        "pr_cleanup",
        payload={"proposal_id": str(p.id)},
        resource_type="fix_proposal",
        resource_id=p.id,
        created_by=principal.id,
        max_attempts=1,
    )
    audit.record(
        db,
        "fix.cleanup_requested",
        actor_id=principal.id,
        resource_type="fix_proposal",
        resource_id=p.id,
        ip=client_ip(request),
    )
    return {
        "proposal": {"id": str(p.id), "status": p.status},
        "job": {"id": str(job.id), "type": job.type, "status": job.status},
    }
