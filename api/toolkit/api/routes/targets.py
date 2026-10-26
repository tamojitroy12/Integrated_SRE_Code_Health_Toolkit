"""Monitoring targets, onboarding instructions and chart data (API_SPEC §5.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from toolkit import audit
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.schemas.common import Out, StrictModel, UtcDatetime
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode, not_found
from toolkit.core.netguard import UnsafeUrlError, validate_outbound_url
from toolkit.core.validators import ENVIRONMENT_RE, SERVICE_NAME_RE
from toolkit.db.enums import UserRole
from toolkit.db.models import Alert, AlertRule, MonitoringTarget
from toolkit.monitoring.prometheus import PrometheusClient, PrometheusUnavailable
from toolkit.monitoring.service import chart
from toolkit.services.projects import get_project

router = APIRouter(tags=["monitoring"])

ChartMetricLit = Literal["request_rate", "error_ratio", "latency_p50", "latency_p95", "latency_p99"]
RangeLit = Literal["15m", "1h", "6h", "24h"]


class TargetCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    service_name: str
    environment: str
    ingestion_mode: Literal["otlp_push", "prometheus_scrape"] = "otlp_push"
    scrape_url: str | None = Field(default=None, max_length=500)
    create_default_rules: bool = False

    @field_validator("service_name")
    @classmethod
    def _svc(cls, v: str) -> str:
        if not SERVICE_NAME_RE.match(v):
            raise ValueError("must match ^[A-Za-z0-9_.:-]{1,100}$")
        return v

    @field_validator("environment")
    @classmethod
    def _env(cls, v: str) -> str:
        if not ENVIRONMENT_RE.match(v):
            raise ValueError("must match ^[a-z0-9-]{1,50}$")
        return v


class TargetPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    environment: str | None = None

    @field_validator("environment")
    @classmethod
    def _env(cls, v: str | None) -> str | None:
        if v is not None and not ENVIRONMENT_RE.match(v):
            raise ValueError("must match ^[a-z0-9-]{1,50}$")
        return v


class TargetOut(Out):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    service_name: str
    environment: str
    ingestion_mode: str
    status: str
    last_seen_at: UtcDatetime | None
    created_at: UtcDatetime


DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "High error ratio",
        "type": "threshold",
        "metric": "error_ratio",
        "comparator": "gt",
        "threshold": 0.05,
        "window": "5m",
        "duration_seconds": 120,
        "severity": "high",
        "guidance": "Check recent deployments, upstream dependencies and error logs for the service.",
    },
    {
        "name": "High p95 latency",
        "type": "threshold",
        "metric": "latency_p95",
        "comparator": "gt",
        "threshold": 2.0,
        "window": "5m",
        "duration_seconds": 300,
        "severity": "medium",
        "guidance": "Look for saturation (CPU, connection pools) and slow downstream calls.",
    },
    {
        "name": "Telemetry stale",
        "type": "absence",
        "metric": "data_absent",
        "duration_seconds": 300,
        "severity": "high",
        "guidance": "The service stopped sending metrics. Check that it is running and can reach the collector.",
    },
]


def get_target(db: DB, target_id: uuid.UUID) -> MonitoringTarget:
    target = db.get(MonitoringTarget, target_id)
    if target is None:
        raise not_found("Monitoring target")
    return target


@router.post("/projects/{project_id}/monitoring-targets", response_model=TargetOut, status_code=201)
def create_target(
    project_id: uuid.UUID, body: TargetCreate, principal: Maintainer, db: DB, request: Request
) -> TargetOut:
    project = get_project(db, project_id, writable=True)
    if body.ingestion_mode == "prometheus_scrape":
        if not body.scrape_url:
            raise ApiError(ErrorCode.VALIDATION_ERROR, details=[{"field": "scrape_url", "issue": "required"}])
        try:
            validate_outbound_url(body.scrape_url, allow_private=get_settings().allow_private_webhooks)
        except UnsafeUrlError as exc:
            raise ApiError(ErrorCode.VALIDATION_ERROR, details=[{"field": "scrape_url", "issue": str(exc)}]) from exc
    target = MonitoringTarget(
        project_id=project.id,
        name=body.name,
        service_name=body.service_name,
        environment=body.environment,
        ingestion_mode=body.ingestion_mode,
        scrape_url=body.scrape_url,
        status="waiting",
    )
    db.add(target)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(ErrorCode.CONFLICT, "This service and environment are already registered.") from exc
    if body.create_default_rules:
        for spec in DEFAULT_RULES:
            db.add(
                AlertRule(
                    project_id=project.id,
                    target_id=target.id,
                    created_by=principal.id,
                    resolve_after=3,
                    params={},
                    enabled=True,
                    **spec,
                )
            )
    audit.record(
        db,
        "target.created",
        actor_id=principal.id,
        resource_type="monitoring_target",
        resource_id=target.id,
        ip=client_ip(request),
    )
    db.refresh(target)
    return TargetOut.model_validate(target)


@router.get("/projects/{project_id}/monitoring-targets", response_model=list[TargetOut])
def list_targets(project_id: uuid.UUID, principal: Viewer, db: DB) -> list[TargetOut]:
    get_project(db, project_id)
    rows = db.scalars(
        select(MonitoringTarget)
        .where(MonitoringTarget.project_id == project_id)
        .order_by(MonitoringTarget.name, MonitoringTarget.id)
    )
    return [TargetOut.model_validate(t) for t in rows]


@router.get("/monitoring-targets/{target_id}", response_model=TargetOut)
def target_detail(target_id: uuid.UUID, principal: Viewer, db: DB) -> TargetOut:
    return TargetOut.model_validate(get_target(db, target_id))


@router.patch("/monitoring-targets/{target_id}", response_model=TargetOut)
def update_target(target_id: uuid.UUID, body: TargetPatch, principal: Maintainer, db: DB) -> TargetOut:
    target = get_target(db, target_id)
    get_project(db, target.project_id, writable=True)
    if body.name is not None:
        target.name = body.name
    if body.environment is not None:
        target.environment = body.environment
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(ErrorCode.CONFLICT, "This service and environment are already registered.") from exc
    db.refresh(target)
    return TargetOut.model_validate(target)


@router.delete("/monitoring-targets/{target_id}", status_code=204)
def delete_target(target_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep, request: Request) -> Response:
    target = get_target(db, target_id)
    get_project(db, target.project_id, writable=True)
    now: datetime = clock.now()
    # Open alerts are resolved by the system; history is kept with target_id = NULL.
    db.execute(
        update(Alert)
        .where(Alert.target_id == target.id, Alert.status != "resolved")
        .values(status="resolved", resolved_at=now, resolved_by=None)
    )
    db.delete(target)  # cascades to its rules and rule states
    audit.record(
        db,
        "target.deleted",
        actor_id=principal.id,
        resource_type="monitoring_target",
        resource_id=target_id,
        ip=client_ip(request),
    )
    return Response(status_code=204)


@router.get("/monitoring-targets/{target_id}/onboarding")
def onboarding(target_id: uuid.UUID, principal: Maintainer, db: DB) -> dict[str, Any]:
    target = get_target(db, target_id)
    s = get_settings()
    endpoint = s.otlp_public_endpoint.rstrip("/")
    is_admin = principal.at_least(UserRole.ADMIN)
    token_value = s.otlp_ingest_token.get_secret_value() if is_admin else "<OTLP_INGEST_TOKEN>"
    env = {
        "OTEL_SERVICE_NAME": target.service_name,
        "OTEL_RESOURCE_ATTRIBUTES": f"deployment.environment.name={target.environment}",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_ENDPOINT": endpoint,
        "OTEL_EXPORTER_OTLP_HEADERS": f"Authorization=Bearer%20{token_value}",
        "OTEL_METRIC_EXPORT_INTERVAL": "15000",
    }
    return {
        "otlp_http_endpoint": endpoint,
        "env": env,
        "token_included": is_admin,
        "token_note": (
            "The ingest token value is included because you are an admin. Treat it as a secret."
            if is_admin
            else "Ask an admin for the ingest token."
        ),
        "required_metric": "http.server.request.duration (histogram, seconds, with http.response.status_code)",
        "notes": [
            "Do not put personal data in service.name or resource attributes.",
            "Status changes from waiting to receiving after the first sample arrives.",
        ],
    }


@router.get("/monitoring-targets/{target_id}/metrics")
def target_metrics(
    target_id: uuid.UUID,
    principal: Viewer,
    db: DB,
    clock: ClockDep,
    metric: ChartMetricLit,
    range: Annotated[RangeLit, Query()] = "1h",
    step: Annotated[int | None, Query(ge=15, le=3600)] = None,
) -> dict[str, Any]:
    target = get_target(db, target_id)
    client = PrometheusClient()
    try:
        result = chart(client, target, metric, range, step, clock.now())
    except PrometheusUnavailable as exc:
        raise ApiError(ErrorCode.PROMETHEUS_UNAVAILABLE) from exc
    finally:
        client.close()
    return {
        "metric": result.metric,
        "unit": result.unit,
        "range": result.range,
        "step_seconds": result.step_seconds,
        "status": result.status,
        "target_status": target.status,
        "series": result.series,
    }
