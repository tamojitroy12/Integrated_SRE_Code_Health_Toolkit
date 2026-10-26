"""AI recommendation workflow (WF-05): API-side gating and the worker job."""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from toolkit import audit
from toolkit.ai import prompt
from toolkit.ai.client import AiUnavailable, ClaudeClient, LlmClient
from toolkit.ai.evidence import CHARS_PER_TOKEN, build_pack
from toolkit.ai.patchcheck import make_checker
from toolkit.ai.schema import OUTPUT_JSON_SCHEMA, ModelOutput
from toolkit.ai.validator import PatchChecker, Validator
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode, JobError, JobErrorCode
from toolkit.core.http import UpstreamError
from toolkit.core.metrics import AI_REQUESTS, AI_VALIDATION
from toolkit.db.models import Evidence, Finding, Job, Recommendation, Repository, Scan
from toolkit.integrations.github import clone_url
from toolkit.integrations.registry import PackageNotFound, RegistryClient
from toolkit.jobs import queue
from toolkit.jobs.runner import JobContext, register
from toolkit.services.credentials import load_token

log = logging.getLogger(__name__)

ALLOWED_KINDS = {
    "dependency_vulnerability": {"library_alternative", "upgrade_guidance"},
    "dependency_outdated": {"library_alternative", "upgrade_guidance"},
    "dependency_incompatibility": {"library_alternative", "upgrade_guidance"},
    "code_issue": {"code_improvement"},
}

LLM_FACTORY: Callable[[], LlmClient] = ClaudeClient
REGISTRY_FACTORY: Callable[[], RegistryClient] = RegistryClient
PATCH_CHECKER_FACTORY: Callable[[Session, Finding], PatchChecker | None] | None = None


def requests_today(db: Session, now: datetime) -> int:
    start = datetime.combine(now.astimezone(UTC).date(), time.min, tzinfo=UTC)
    return db.scalar(select(func.count()).select_from(Recommendation).where(Recommendation.created_at >= start)) or 0


def request_recommendation(
    db: Session, finding: Finding, kind: str, actor_id: uuid.UUID, now: datetime, ip: str | None
) -> tuple[Recommendation, Job]:
    s = get_settings()
    if not s.ai_available:
        raise ApiError(ErrorCode.AI_DISABLED)
    if kind not in ALLOWED_KINDS.get(finding.type, set()):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            details=[{"field": "kind", "issue": f"{kind} is not available for {finding.type} findings"}],
        )
    # Serialize the cap check so concurrent requests cannot both pass it (FR-AI-10).
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('toolkit.ai_daily_cap'))"))
    if requests_today(db, now) >= s.ai_daily_request_cap:
        raise ApiError(ErrorCode.AI_BUDGET_EXCEEDED, "The daily AI request cap has been reached.")
    rec = Recommendation(
        id=uuid.uuid4(),
        finding_id=finding.id,
        kind=kind,
        status="pending",
        model=s.claude_model,
        prompt_version=prompt.PROMPT_VERSION,
        requested_by=actor_id,
        created_at=now,
    )
    db.add(rec)
    db.flush()
    job = queue.enqueue(
        db,
        "recommendation",
        payload={"recommendation_id": str(rec.id)},
        resource_type="recommendation",
        resource_id=rec.id,
        created_by=actor_id,
    )
    rec.job_id = job.id
    audit.record(
        db,
        "recommendation.requested",
        actor_id=actor_id,
        resource_type="recommendation",
        resource_id=rec.id,
        metadata={"kind": kind, "finding_id": str(finding.id)},
        ip=ip,
    )
    return rec, job


def _default_patch_checker(db: Session, finding: Finding) -> PatchChecker | None:
    scan = db.get(Scan, finding.last_seen_scan_id) if finding.last_seen_scan_id else None
    repo = db.get(Repository, scan.repository_id) if scan and scan.repository_id else None
    if scan is None or repo is None or not scan.commit_sha:
        return None
    return make_checker(clone_url(repo.owner, repo.name), scan.commit_sha, load_token(db, repo.credential_id))  # type: ignore[no-any-return]


def _parse(text_out: str) -> ModelOutput:
    return ModelOutput.model_validate(json.loads(text_out))


@register("recommendation")
def handle_recommendation(ctx: JobContext) -> str:
    s = get_settings()
    rec_id = uuid.UUID(ctx.payload["recommendation_id"])
    if not s.ai_available:
        raise JobError(JobErrorCode.AI_UNAVAILABLE, "AI is disabled in this deployment")
    with ctx.session() as db:
        rec = db.get(Recommendation, rec_id)
        if rec is None:
            raise JobError(JobErrorCode.INTERNAL_ERROR, "recommendation row missing")
        finding = db.get(Finding, rec.finding_id)
        assert finding is not None
        evidence = list(db.scalars(select(Evidence).where(Evidence.finding_id == finding.id)))
        kind = rec.kind
        db.expunge_all()
    ctx.stage("evidence_pack")
    registry = REGISTRY_FACTORY()
    meta = None
    limitations: list[str] = []
    if finding.ecosystem and finding.package_name:
        try:
            meta = registry.package(finding.ecosystem, finding.package_name)
        except (PackageNotFound, UpstreamError):
            limitations.append("Registry metadata for the package was unavailable.")
    instructions_tokens = int((len(prompt.SYSTEM_PROMPT) + len(prompt.KIND_CHECKLIST[kind]) + 600) / CHARS_PER_TOKEN)
    try:
        pack = build_pack(finding, evidence, meta, s.ai_max_input_tokens, instructions_tokens)
    except ValueError as exc:
        raise JobError(JobErrorCode.AI_UNAVAILABLE, str(exc)) from exc
    pack.limitations += limitations

    ctx.stage("model")
    try:
        llm = LLM_FACTORY()
    except AiUnavailable as exc:
        raise JobError(JobErrorCode.AI_UNAVAILABLE, exc.reason) from exc
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt.user_message(kind, pack)}]
    usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
    output: ModelOutput | None = None
    raw = ""
    model_name = s.claude_model
    error = ""
    for attempt in range(2):  # at most one repair attempt (FR-AI-03)
        try:
            completion = llm.complete(prompt.SYSTEM_PROMPT, messages, OUTPUT_JSON_SCHEMA)
        except AiUnavailable as exc:
            raise JobError(JobErrorCode.AI_UNAVAILABLE, exc.reason, retryable=exc.retryable) from exc
        AI_REQUESTS.labels(kind).inc()
        usage["input_tokens"] += completion.input_tokens
        usage["output_tokens"] += completion.output_tokens
        usage["calls"] += 1
        model_name = completion.model or model_name
        raw = completion.text
        try:
            output = _parse(raw)
            break
        except (json.JSONDecodeError, ValidationError) as exc:
            error = str(exc)
            if attempt == 0:
                messages += [
                    {"role": "assistant", "content": raw or "{}"},
                    {"role": "user", "content": prompt.repair_message(error)},
                ]

    ctx.stage("validate")
    now = ctx.clock.now()
    with ctx.session() as db:
        rec = db.get(Recommendation, rec_id, with_for_update=True)
        assert rec is not None
        rec.model = model_name
        rec.evidence_pack_sha256 = pack.sha256
        rec.evidence_refs = [i.ref() for i in pack.items]
        rec.usage = usage
        rec.raw_output = raw[:50_000]
        rec.completed_at = now
        rec.status = "completed"
        if output is None:
            rec.validation_status = "rejected"
            rec.error_code = "SCHEMA_INVALID"
            rec.error_message = "AI output could not be validated against the schema."
            rec.content = {
                "summary": None,
                "claims": [],
                "alternatives": [],
                "suggested_steps": [],
                "proposed_patch": None,
                "confidence": None,
                "limitations": ["The model output did not match the required schema twice."],
            }
        else:
            checker_factory = PATCH_CHECKER_FACTORY or _default_patch_checker
            checker = checker_factory(db, finding) if output.proposed_patch else None
            result = Validator(finding, pack, registry, checker).validate(output, kind)
            rec.validation_status = result.status
            rec.content = result.content
        AI_VALIDATION.labels(kind, rec.validation_status).inc()
        log.info(
            "recommendation stored",
            extra={
                "validation_status": rec.validation_status,
                "pack_sha256": pack.sha256,
                "prompt_version": prompt.PROMPT_VERSION,
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
            },
        )
    registry.close()
    return "succeeded"


def _rec_terminal(db: Session, job: Job, status: str) -> None:
    rec = db.get(Recommendation, job.resource_id) if job.resource_id else None
    if rec and rec.status == "pending":
        rec.status = "failed"
        rec.error_code = job.error_code or "INTERNAL_ERROR"
        rec.error_message = job.error_message
        rec.completed_at = job.finished_at


queue.register_terminal_hook("recommendation", _rec_terminal)


def recommendation_out(db: Session, rec: Recommendation, *, include_raw: bool = False) -> dict[str, Any]:
    content = rec.content or {}
    job = db.get(Job, rec.job_id) if rec.job_id else None
    out = {
        "id": str(rec.id),
        "finding_id": str(rec.finding_id),
        "kind": rec.kind,
        "status": rec.status,
        "validation_status": rec.validation_status,
        "model": rec.model,
        "prompt_version": rec.prompt_version,
        "summary": content.get("summary"),
        "claims": content.get("claims", []),
        "alternatives": content.get("alternatives", []),
        "suggested_steps": content.get("suggested_steps", []),
        "proposed_patch": content.get("proposed_patch"),
        "confidence": content.get("confidence"),
        "limitations": content.get("limitations", []),
        "evidence": rec.evidence_refs,
        "evidence_pack_sha256": rec.evidence_pack_sha256,
        "usage": rec.usage,
        "error": {"code": rec.error_code, "message": rec.error_message} if rec.error_code else None,
        "feedback": {"rating": rec.feedback_rating, "comment": rec.feedback_comment} if rec.feedback_rating else None,
        "label": "AI-generated, advisory",
        "job": queue.job_out(job) if job else None,
        "created_at": rec.created_at,
        "completed_at": rec.completed_at,
    }
    if include_raw and rec.validation_status == "rejected":
        out["raw_output"] = rec.raw_output
    return out
