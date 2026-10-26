"""AI recommendations (API_SPEC §5.8, FR-AI-01/05/08/10)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import Field
from sqlalchemy import select

from toolkit.ai.service import recommendation_out, request_recommendation
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.schemas.common import StrictModel
from toolkit.core.config import get_settings
from toolkit.core.errors import not_found
from toolkit.db.enums import UserRole
from toolkit.db.models import Finding, Recommendation
from toolkit.services.projects import get_project

router = APIRouter(tags=["recommendations"])


class RecommendationIn(StrictModel):
    kind: Literal["library_alternative", "upgrade_guidance", "code_improvement"]


class FeedbackIn(StrictModel):
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = Field(default=None, max_length=1000)


@router.get("/ai/status")
def ai_status(principal: Viewer) -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": s.ai_available,
        "model": s.claude_model if s.ai_available else None,
        "daily_cap": s.ai_daily_request_cap,
        "notice": "The finding's evidence, including a short code snippet where relevant, is sent to Anthropic's API.",
    }


@router.post("/findings/{finding_id}/recommendations", status_code=202)
def create_recommendation(
    finding_id: uuid.UUID, body: RecommendationIn, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> dict[str, Any]:
    finding = db.get(Finding, finding_id)
    if finding is None:
        raise not_found("Finding")
    get_project(db, finding.project_id, writable=True)
    rec, job = request_recommendation(db, finding, body.kind, principal.id, clock.now(), client_ip(request))
    return {
        "recommendation": {"id": str(rec.id), "status": rec.status, "kind": rec.kind},
        "job": {"id": str(job.id), "type": job.type, "status": job.status},
    }


@router.get("/findings/{finding_id}/recommendations")
def list_recommendations(finding_id: uuid.UUID, principal: Viewer, db: DB) -> dict[str, Any]:
    if db.get(Finding, finding_id) is None:
        raise not_found("Finding")
    rows = db.scalars(
        select(Recommendation)
        .where(Recommendation.finding_id == finding_id)
        .order_by(Recommendation.created_at.desc())
        .limit(50)
    )
    include_raw = principal.at_least(UserRole.MAINTAINER)
    return {"items": [recommendation_out(db, r, include_raw=include_raw) for r in rows]}


@router.get("/recommendations/{recommendation_id}")
def recommendation_detail(recommendation_id: uuid.UUID, principal: Viewer, db: DB) -> dict[str, Any]:
    rec = db.get(Recommendation, recommendation_id)
    if rec is None:
        raise not_found("Recommendation")
    # Rejected raw output is available to maintainers for debugging only (AI_DESIGN §7).
    return recommendation_out(db, rec, include_raw=principal.at_least(UserRole.MAINTAINER))


@router.post("/recommendations/{recommendation_id}/feedback", status_code=204)
def recommendation_feedback(recommendation_id: uuid.UUID, body: FeedbackIn, principal: Maintainer, db: DB) -> Response:
    rec = db.get(Recommendation, recommendation_id, with_for_update=True)
    if rec is None:
        raise not_found("Recommendation")
    rec.feedback_rating = body.rating
    rec.feedback_comment = body.comment
    return Response(status_code=204)
