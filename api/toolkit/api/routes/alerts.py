"""Alert rules and alerts (API_SPEC §5.5, FR-ALR-01..04, FR-DSH-04)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field
from sqlalchemy import and_, or_, select

from toolkit import audit
from toolkit.alerting.notify import enqueue_notifications
from toolkit.alerting.rules import RuleSpec, check_transition, validate_rule
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.pagination import decode_cursor, encode_cursor
from toolkit.api.schemas.common import Out, Page, StrictModel, UtcDatetime
from toolkit.core.errors import ApiError, ErrorCode, not_found, validation_error
from toolkit.db.enums import UserRole
from toolkit.db.models import (
    Alert,
    AlertRule,
    AlertRuleState,
    MonitoringTarget,
    NotificationChannel,
    NotificationDelivery,
    User,
)
from toolkit.services.projects import get_project

router = APIRouter(tags=["alerts"])

SeverityLit = Literal["critical", "high", "medium", "low", "info"]
StatusLit = Literal["firing", "acknowledged", "resolved"]


class RuleCreate(StrictModel):
    target_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    type: Literal["threshold", "absence", "anomaly"]
    metric: Literal["error_ratio", "latency_p95", "request_rate", "data_absent"]
    comparator: Literal["gt", "lt"] | None = None
    threshold: float | None = None
    window: Literal["1m", "5m", "15m"] | None = None
    duration_seconds: int | None = None
    resolve_after: int = 3
    params: dict[str, Any] | None = None
    severity: SeverityLit
    guidance: str = Field(default="", max_length=2000)
    enabled: bool = True


class RulePatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    comparator: Literal["gt", "lt"] | None = None
    threshold: float | None = None
    window: Literal["1m", "5m", "15m"] | None = None
    duration_seconds: int | None = None
    resolve_after: int | None = None
    params: dict[str, Any] | None = None
    severity: SeverityLit | None = None
    guidance: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None


class RuleOut(Out):
    id: uuid.UUID
    project_id: uuid.UUID
    target_id: uuid.UUID
    name: str
    type: str
    metric: str
    comparator: str | None
    threshold: float | None
    window: str | None
    duration_seconds: int
    resolve_after: int
    params: dict[str, Any]
    severity: str
    guidance: str
    enabled: bool
    created_at: UtcDatetime
    updated_at: UtcDatetime


class Attribution(Out):
    id: uuid.UUID
    display_name: str


class AlertOut(Out):
    id: uuid.UUID
    rule_id: uuid.UUID | None
    rule_name: str
    target_id: uuid.UUID | None
    project_id: uuid.UUID
    status: str
    severity: str
    first_seen_at: UtcDatetime
    last_seen_at: UtcDatetime
    occurrence_count: int
    evidence: dict[str, Any]
    acknowledged_by: Attribution | None = None
    acknowledged_at: UtcDatetime | None
    resolved_at: UtcDatetime | None
    resolved_by: Attribution | None = None
    target: dict[str, Any] | None = None


class DeliveryOut(Out):
    id: uuid.UUID
    channel_id: uuid.UUID
    channel_name: str | None
    event: str
    status: str
    http_status: int | None
    error: str | None
    attempts: int
    attempted_at: UtcDatetime | None


# ----------------------------------------------------------------------------- rules
def _target_in_project(db: DB, target_id: uuid.UUID, project_id: uuid.UUID) -> MonitoringTarget:
    target = db.get(MonitoringTarget, target_id)
    if target is None or target.project_id != project_id:
        raise validation_error("target_id", "target does not belong to this project")
    return target


@router.post("/projects/{project_id}/alert-rules", response_model=RuleOut, status_code=201)
def create_rule(project_id: uuid.UUID, body: RuleCreate, principal: Maintainer, db: DB, request: Request) -> RuleOut:
    project = get_project(db, project_id, writable=True)
    _target_in_project(db, body.target_id, project.id)
    spec = validate_rule(
        RuleSpec(
            body.type,
            body.metric,
            body.comparator,
            body.threshold,
            body.window,
            body.duration_seconds,
            body.resolve_after,
            body.params or {},
        )
    )
    rule = AlertRule(
        project_id=project.id,
        target_id=body.target_id,
        name=body.name,
        type=spec.type,
        metric=spec.metric,
        comparator=spec.comparator,
        threshold=spec.threshold,
        window=spec.window,
        duration_seconds=spec.duration_seconds,
        resolve_after=spec.resolve_after,
        params=spec.params,
        severity=body.severity,
        guidance=body.guidance,
        enabled=body.enabled,
        created_by=principal.id,
    )
    db.add(rule)
    db.flush()
    audit.record(
        db,
        "alert_rule.created",
        actor_id=principal.id,
        resource_type="alert_rule",
        resource_id=rule.id,
        ip=client_ip(request),
    )
    db.refresh(rule)
    return RuleOut.model_validate(rule)


@router.get("/projects/{project_id}/alert-rules", response_model=list[RuleOut])
def list_rules(project_id: uuid.UUID, principal: Viewer, db: DB, target_id: uuid.UUID | None = None) -> list[RuleOut]:
    get_project(db, project_id)
    q = select(AlertRule).where(AlertRule.project_id == project_id)
    if target_id:
        q = q.where(AlertRule.target_id == target_id)
    return [RuleOut.model_validate(r) for r in db.scalars(q.order_by(AlertRule.created_at, AlertRule.id))]


def _get_rule(db: DB, rule_id: uuid.UUID) -> AlertRule:
    rule = db.get(AlertRule, rule_id, with_for_update=True)
    if rule is None:
        raise not_found("Alert rule")
    return rule


@router.patch("/alert-rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: uuid.UUID, body: RulePatch, principal: Maintainer, db: DB, request: Request) -> RuleOut:
    rule = _get_rule(db, rule_id)
    get_project(db, rule.project_id, writable=True)
    fields = body.model_fields_set
    spec = RuleSpec(
        rule.type,
        rule.metric,
        body.comparator if "comparator" in fields else rule.comparator,
        body.threshold if "threshold" in fields else rule.threshold,
        body.window if "window" in fields else rule.window,
        body.duration_seconds if "duration_seconds" in fields else rule.duration_seconds,
        body.resolve_after if body.resolve_after is not None else rule.resolve_after,
        body.params if body.params is not None else dict(rule.params),
    )
    spec = validate_rule(spec)
    condition_changed = (spec.comparator, spec.threshold, spec.window, spec.duration_seconds, spec.params) != (
        rule.comparator,
        rule.threshold,
        rule.window,
        rule.duration_seconds,
        rule.params,
    )
    rule.comparator, rule.threshold, rule.window = spec.comparator, spec.threshold, spec.window
    rule.duration_seconds = spec.duration_seconds or rule.duration_seconds
    rule.resolve_after, rule.params = spec.resolve_after, spec.params
    for attr in ("name", "severity", "guidance", "enabled"):
        if attr in fields and getattr(body, attr) is not None:
            setattr(rule, attr, getattr(body, attr))
    if condition_changed or body.enabled is False:
        # The rule must re-confirm for the full duration before firing again.
        state = db.get(AlertRuleState, rule.id)
        if state is not None:
            state.consecutive_breaches = 0
            state.consecutive_clears = 0
            state.breach_since = None
    audit.record(
        db,
        "alert_rule.updated",
        actor_id=principal.id,
        resource_type="alert_rule",
        resource_id=rule.id,
        metadata={"fields": sorted(fields)},
        ip=client_ip(request),
    )
    db.flush()
    db.refresh(rule)
    return RuleOut.model_validate(rule)


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep, request: Request) -> Response:
    rule = _get_rule(db, rule_id)
    get_project(db, rule.project_id, writable=True)
    now = clock.now()
    for alert in db.scalars(select(Alert).where(Alert.rule_id == rule.id, Alert.status != "resolved")):
        alert.status, alert.resolved_at = "resolved", now
    db.delete(rule)
    audit.record(
        db,
        "alert_rule.deleted",
        actor_id=principal.id,
        resource_type="alert_rule",
        resource_id=rule_id,
        ip=client_ip(request),
    )
    return Response(status_code=204)


# ----------------------------------------------------------------------------- alerts
def _attribution(db: DB, user_id: uuid.UUID | None) -> Attribution | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return Attribution(id=user.id, display_name=user.display_name) if user else None


_ALERT_FIELDS = (
    "id",
    "rule_id",
    "rule_name",
    "target_id",
    "project_id",
    "status",
    "severity",
    "first_seen_at",
    "last_seen_at",
    "occurrence_count",
    "evidence",
    "acknowledged_at",
    "resolved_at",
)


def _alert_out(db: DB, alert: Alert, with_target: bool = True) -> AlertOut:
    out = AlertOut(
        **{f: getattr(alert, f) for f in _ALERT_FIELDS},
        acknowledged_by=_attribution(db, alert.acknowledged_by),
        resolved_by=_attribution(db, alert.resolved_by),
    )
    if with_target and alert.target_id:
        t = db.get(MonitoringTarget, alert.target_id)
        if t:
            out.target = {"id": str(t.id), "name": t.name, "service_name": t.service_name, "environment": t.environment}
    return out


@router.get("/alerts", response_model=Page[AlertOut])
def list_alerts(
    principal: Viewer,
    db: DB,
    project_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    status: Annotated[list[StatusLit] | None, Query()] = None,
    severity: Annotated[list[SeverityLit] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> Page[AlertOut]:
    q = select(Alert)
    if project_id:
        q = q.where(Alert.project_id == project_id)
    if target_id:
        q = q.where(Alert.target_id == target_id)
    if status:
        q = q.where(Alert.status.in_(status))
    if severity:
        q = q.where(Alert.severity.in_(severity))
    if cursor:
        seen, aid = decode_cursor(cursor, 2)
        q = q.where(or_(Alert.last_seen_at < seen, and_(Alert.last_seen_at == seen, Alert.id < aid)))
    rows = list(db.scalars(q.order_by(Alert.last_seen_at.desc(), Alert.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    targets = {
        t.id: t
        for t in db.scalars(
            select(MonitoringTarget).where(MonitoringTarget.id.in_({a.target_id for a in page if a.target_id}))
        )
    }
    items = []
    for a in page:
        out = _alert_out(db, a, with_target=False)
        t = targets.get(a.target_id) if a.target_id else None
        if t:
            out.target = {"id": str(t.id), "name": t.name, "service_name": t.service_name, "environment": t.environment}
        items.append(out)
    nxt = encode_cursor([page[-1].last_seen_at, page[-1].id]) if len(rows) > limit else None
    return Page(items=items, next_cursor=nxt)


def _get_alert(db: DB, alert_id: uuid.UUID, lock: bool = False) -> Alert:
    alert = db.get(Alert, alert_id, with_for_update=lock)
    if alert is None:
        raise not_found("Alert")
    return alert


@router.get("/alerts/{alert_id}", response_model=AlertOut)
def alert_detail(alert_id: uuid.UUID, principal: Viewer, db: DB) -> AlertOut:
    alert = _get_alert(db, alert_id)
    out = _alert_out(db, alert)
    if alert.rule_id:
        rule = db.get(AlertRule, alert.rule_id)
        if rule:
            out.evidence = {
                **alert.evidence,
                "rule_type": rule.type,
                "metric": rule.metric,
                "comparator": rule.comparator,
                "duration_seconds": rule.duration_seconds,
            }
    return out


@router.get("/alerts/{alert_id}/deliveries", response_model=list[DeliveryOut])
def alert_deliveries(alert_id: uuid.UUID, principal: Viewer, db: DB) -> list[DeliveryOut]:
    _get_alert(db, alert_id)
    rows = db.execute(
        select(NotificationDelivery, NotificationChannel.name)
        .join(NotificationChannel, NotificationChannel.id == NotificationDelivery.channel_id)
        .where(NotificationDelivery.alert_id == alert_id)
        .order_by(NotificationDelivery.created_at)
    ).all()
    show_names = principal.at_least(UserRole.MAINTAINER)
    return [
        DeliveryOut(
            id=d.id,
            channel_id=d.channel_id,
            channel_name=name if show_names else None,
            event=d.event,
            status=d.status,
            http_status=d.http_status,
            error=d.error,
            attempts=d.attempts,
            attempted_at=d.attempted_at,
        )
        for d, name in rows
    ]


def _transition(db: DB, alert: Alert, target: str, principal: Maintainer, now: datetime, request: Request) -> None:
    check_transition(alert.status, target)
    previous = alert.status
    if target == "acknowledged":
        alert.status, alert.acknowledged_by, alert.acknowledged_at = "acknowledged", principal.id, now
    elif target == "firing":
        alert.status, alert.acknowledged_by, alert.acknowledged_at = "firing", None, None
    else:
        alert.status, alert.resolved_at, alert.resolved_by = "resolved", now, principal.id
        enqueue_notifications(db, alert, "resolved", now)
        if alert.rule_id:
            state = db.get(AlertRuleState, alert.rule_id)
            if state is not None:
                state.consecutive_breaches = 0
                state.breach_since = None
    audit.record(
        db,
        f"alert.{target if target != 'firing' else 'unacknowledged'}",
        actor_id=principal.id,
        resource_type="alert",
        resource_id=alert.id,
        metadata={"from": previous},
        ip=client_ip(request),
    )


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(
    alert_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> AlertOut:
    alert = _get_alert(db, alert_id, lock=True)
    project = get_project(db, alert.project_id)
    if project.archived_at is not None:
        raise ApiError(ErrorCode.CONFLICT, "Cannot acknowledge alert in an archived project")
    _transition(db, alert, "acknowledged", principal, clock.now(), request)
    return _alert_out(db, alert)


@router.post("/alerts/{alert_id}/unacknowledge", response_model=AlertOut)
def unacknowledge_alert(
    alert_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> AlertOut:
    """Compensating undo for an acknowledgment (UI_UX_SPEC §9, 6 s undo toast)."""
    alert = _get_alert(db, alert_id, lock=True)
    _transition(db, alert, "firing", principal, clock.now(), request)
    return _alert_out(db, alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(alert_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep, request: Request) -> AlertOut:
    alert = _get_alert(db, alert_id, lock=True)
    _transition(db, alert, "resolved", principal, clock.now(), request)
    return _alert_out(db, alert)
