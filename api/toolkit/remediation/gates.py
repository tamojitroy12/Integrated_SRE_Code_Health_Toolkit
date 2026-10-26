"""Approval gates (WF-06 table; FR-REM-06, FR-REM-09, FR-REM-12; SM-07)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from toolkit.core.errors import ApiError, ErrorCode
from toolkit.db.enums import UserRole
from toolkit.db.models import FixProposal


@dataclass(frozen=True)
class ApprovalRequest:
    acknowledge_unverified: bool
    acknowledge_breaking_change: bool
    comment: str | None


def check_approval(p: FixProposal, role: UserRole, req: ApprovalRequest) -> bool:
    """Raise if approval is not allowed; return True when this is an admin override."""
    if p.status != "ready":
        raise ApiError(ErrorCode.INVALID_TRANSITION, f"Only proposals in ready state can be approved (is {p.status}).")
    override = False
    if p.validation_result == "failed":
        if role != UserRole.ADMIN:
            raise ApiError(ErrorCode.FORBIDDEN, "Tests failed after the change; only an admin can override.")
        if not req.comment or len(req.comment.strip()) < 10:
            raise ApiError(
                ErrorCode.ACK_REQUIRED,
                "An admin override requires a justification comment.",
                details=[{"field": "comment", "issue": "justification of at least 10 characters"}],
            )
        override = True
    if p.validation_result in ("unverified", "not_run") and not req.acknowledge_unverified:
        raise ApiError(
            ErrorCode.ACK_REQUIRED,
            "Acknowledge that tests were missing or failing before the change.",
            details=[{"field": "acknowledge_unverified", "issue": "must be true"}],
        )
    if p.has_major_bump and not req.acknowledge_breaking_change:
        raise ApiError(
            ErrorCode.ACK_REQUIRED,
            "Acknowledge that a major version change may break compatibility.",
            details=[{"field": "acknowledge_breaking_change", "issue": "must be true"}],
        )
    return override


def record_approval(p: FixProposal, user_id: object, now: datetime, req: ApprovalRequest, override: bool) -> None:
    # approved_by / approved_at and the status change land in one transaction (CHECK constraint).
    p.approved_by = user_id  # type: ignore[assignment]
    p.approved_at = now
    p.approval_ack = {
        "acknowledge_unverified": req.acknowledge_unverified,
        "acknowledge_breaking_change": req.acknowledge_breaking_change,
        "comment": req.comment,
        "admin_override": override,
    }
    p.status = "approved"
    p.pr_error = None
