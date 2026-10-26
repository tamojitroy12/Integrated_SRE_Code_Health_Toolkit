"""SQLAlchemy models for every relational entity in DATA_MODEL §2."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from toolkit.db import enums as E
from toolkit.db.base import Base, created_at, one_of, updated_at, uuid_pk

TZ = DateTime(timezone=True)


# --------------------------------------------------------------------------- identity
class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        one_of("role", E.values(E.UserRole)),
        Index("uq_user_email_lower", func.lower(text("email")), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    last_login_at: Mapped[datetime | None] = mapped_column(TZ)


class RefreshSession(Base):
    __tablename__ = "refresh_session"
    __table_args__ = (Index("ix_refresh_session_user", "user_id", "revoked_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TZ)
    rotated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))


class LoginAttempt(Base):
    __tablename__ = "login_attempt"
    __table_args__ = (
        Index("ix_login_attempt_email_ip", "email", "ip", "created_at"),
        Index("ix_login_attempt_ip", "ip", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_created", "created_at"),
        Index("ix_audit_log_actor", "actor_id", "created_at"),
        Index("ix_audit_log_action", "action", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())


# --------------------------------------------------------------------------- projects
class Project(Base):
    __tablename__ = "project"
    __table_args__ = (
        Index(
            "uq_project_name_active",
            func.lower(text("name")),
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    archived_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    repository: Mapped[Repository | None] = relationship(back_populates="project", uselist=False)


class Credential(Base):
    __tablename__ = "credential"
    __table_args__ = (one_of("kind", ["github_pat"]),)

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()


class Repository(Base):
    __tablename__ = "repository"
    __table_args__ = (one_of("provider", ["github"]),)

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="github")
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    url: Mapped[str] = mapped_column(String(300), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    ecosystems: Mapped[list[str]] = mapped_column(ARRAY(String(10)), nullable=False, default=list)
    manifests: Mapped[list[str]] = mapped_column(ARRAY(String(300)), nullable=False, default=list)
    test_command: Mapped[str | None] = mapped_column(String(50))
    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credential.id", ondelete="SET NULL"))
    can_open_prs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()

    project: Mapped[Project] = relationship(back_populates="repository")


class MonitoringTarget(Base):
    __tablename__ = "monitoring_target"
    __table_args__ = (
        UniqueConstraint("project_id", "service_name", "environment", name="uq_target_identity"),
        one_of("ingestion_mode", ["otlp_push", "prometheus_scrape"]),
        one_of("status", E.values(E.TargetStatus)),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(50), nullable=False)
    ingestion_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="otlp_push")
    scrape_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="waiting")
    last_seen_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


# --------------------------------------------------------------------------- alerting
class AlertRule(Base):
    __tablename__ = "alert_rule"
    __table_args__ = (
        one_of("type", E.values(E.RuleType)),
        one_of("metric", E.values(E.RuleMetric)),
        one_of("comparator", E.values(E.Comparator), nullable=True),
        one_of("window", ["1m", "5m", "15m"], nullable=True),
        one_of("severity", E.values(E.Severity)),
        CheckConstraint("duration_seconds > 0", name="duration_positive"),
        CheckConstraint("resolve_after >= 1", name="resolve_after_positive"),
        Index("ix_alert_rule_project", "project_id"),
        Index("ix_alert_rule_enabled", "enabled"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("monitoring_target.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    metric: Mapped[str] = mapped_column(String(30), nullable=False)
    comparator: Mapped[str | None] = mapped_column(String(5))
    threshold: Mapped[float | None] = mapped_column(Float)
    window: Mapped[str | None] = mapped_column("window", String(5))
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    resolve_after: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    guidance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class AlertRuleState(Base):
    __tablename__ = "alert_rule_state"

    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alert_rule.id", ondelete="CASCADE"), primary_key=True)
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("monitoring_target.id", ondelete="CASCADE"), nullable=False)
    breach_since: Mapped[datetime | None] = mapped_column(TZ)
    consecutive_breaches: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_clears: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(TZ)
    last_value: Mapped[float | None] = mapped_column(Float)
    last_outcome: Mapped[str | None] = mapped_column(String(30))


class Alert(Base):
    __tablename__ = "alert"
    __table_args__ = (
        one_of("status", E.values(E.AlertStatus)),
        one_of("severity", E.values(E.Severity)),
        Index(
            "uq_alert_open_per_rule_target",
            "rule_id",
            "target_id",
            unique=True,
            postgresql_where=text("status <> 'resolved'"),
        ),
        Index("ix_alert_project_status", "project_id", "status"),
        Index("ix_alert_last_seen", "last_seen_at", "id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alert_rule.id", ondelete="SET NULL"))
    target_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("monitoring_target.id", ondelete="SET NULL"))
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(TZ)
    resolved_at: Mapped[datetime | None] = mapped_column(TZ)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()


class NotificationChannel(Base):
    __tablename__ = "notification_channel"
    __table_args__ = (one_of("type", ["webhook", "email"]),)

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    config_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(String(40), nullable=False)
    config_public: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_at: Mapped[datetime | None] = mapped_column(TZ)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class NotificationDelivery(Base):
    __tablename__ = "notification_delivery"
    __table_args__ = (
        one_of("event", ["firing", "resolved", "test"]),
        one_of("status", E.values(E.DeliveryStatus)),
        Index("ix_delivery_alert", "alert_id"),
        Index("ix_delivery_pending", "next_attempt_at", postgresql_where=text("status = 'pending'")),
        Index("ix_delivery_cooldown", "channel_id", "rule_id", "event", "attempted_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    alert_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alert.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alert_rule.id", ondelete="SET NULL"))
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_channel.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(TZ)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(200))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempted_at: Mapped[datetime | None] = mapped_column(TZ)
    created_at: Mapped[datetime] = created_at()


# --------------------------------------------------------------------------- jobs
class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        one_of("type", E.values(E.JobType)),
        one_of("status", E.values(E.JobStatus)),
        Index("ix_job_claim", "status", "created_at"),
        Index("ix_job_lease", "lease_expires_at", postgresql_where=text("status = 'running'")),
        Index("ix_job_resource", "resource_type", "resource_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    stage: Mapped[str | None] = mapped_column(String(60))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(TZ)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resource_type: Mapped[str | None] = mapped_column(String(30))
    resource_id: Mapped[uuid.UUID | None] = mapped_column()
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
    available_at: Mapped[datetime | None] = mapped_column(TZ)


# --------------------------------------------------------------------------- scanning
class Scan(Base):
    __tablename__ = "scan"
    __table_args__ = (
        one_of("status", E.values(E.JobStatus)),
        one_of("trigger", ["manual", "scheduled"]),
        Index("ix_scan_project_created", "project_id", text("created_at DESC")),
        Index(
            "uq_scan_active_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("repository.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"))
    ref: Mapped[str] = mapped_column(String(200), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    providers: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    started_at: Mapped[datetime | None] = mapped_column(TZ)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)


class ScanProviderRun(Base):
    __tablename__ = "scan_provider_run"
    __table_args__ = (
        one_of("provider", E.values(E.Provider)),
        one_of("status", E.values(E.ProviderStatus)),
        UniqueConstraint("scan_id", "provider", name="uq_provider_run"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    tool_version: Mapped[str | None] = mapped_column(String(100))
    db_info: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Dependency(Base):
    __tablename__ = "dependency"
    __table_args__ = (
        UniqueConstraint("scan_id", "ecosystem", "name", "version", "manifest_path", name="uq_dependency"),
        one_of("ecosystem", ["npm", "pypi"]),
        one_of("scope", ["direct", "transitive"]),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan.id", ondelete="CASCADE"), nullable=False)
    ecosystem: Mapped[str] = mapped_column(String(10), nullable=False)
    name: Mapped[str] = mapped_column(String(214), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(12), nullable=False)
    manifest_path: Mapped[str] = mapped_column(String(300), nullable=False)
    purl: Mapped[str | None] = mapped_column(String(400))


class Finding(Base):
    __tablename__ = "finding"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_finding_fingerprint"),
        one_of("type", E.values(E.FindingType)),
        one_of("severity", E.values(E.Severity), nullable=True),
        one_of("status", E.values(E.FindingStatus)),
        one_of("dismissal_reason", E.values(E.DismissalReason), nullable=True),
        one_of("last_change", E.values(E.FindingChange)),
        Index("ix_finding_explorer", "project_id", "status", "severity_rank"),
        Index("ix_finding_type", "project_id", "type"),
        Index("ix_finding_last_seen", "project_id", "last_seen_at", "id"),
        Index("ix_finding_advisory", "advisory", postgresql_using="gin"),
        Index(
            "ix_finding_search",
            "search_text",
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(10))
    severity_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    severity_source: Mapped[str | None] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    last_change: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    ecosystem: Mapped[str | None] = mapped_column(String(10))
    package_name: Mapped[str | None] = mapped_column(String(214))
    package_version: Mapped[str | None] = mapped_column(String(100))
    scope: Mapped[str | None] = mapped_column(String(12))
    manifest_path: Mapped[str | None] = mapped_column(String(300))
    file_path: Mapped[str | None] = mapped_column(String(500))
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    rule_id: Mapped[str | None] = mapped_column(String(300))
    message: Mapped[str | None] = mapped_column(Text)
    advisory: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sources: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dismissal_reason: Mapped[str | None] = mapped_column(String(20))
    dismissal_note: Mapped[str | None] = mapped_column(String(1000))
    dismissed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    dismissed_at: Mapped[datetime | None] = mapped_column(TZ)
    first_seen_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scan.id", ondelete="SET NULL"))
    last_seen_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scan.id", ondelete="SET NULL"))
    resolved_scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scan.id", ondelete="SET NULL"))
    first_seen_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(TZ)


class FindingOccurrence(Base):
    __tablename__ = "finding_occurrence"
    __table_args__ = (
        UniqueConstraint("scan_id", "fingerprint", name="uq_occurrence_scan_fingerprint"),
        one_of("change", ["new", "unchanged"]),
        Index("ix_occurrence_finding", "finding_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scan.id", ondelete="CASCADE"), nullable=False)
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding.id", ondelete="CASCADE"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    change: Mapped[str] = mapped_column(String(20), nullable=False)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("finding_id", "evidence_key", name="uq_evidence_key"),
        UniqueConstraint("finding_id", "content_sha256", name="uq_evidence_content"),
        one_of("kind", ["advisory_record", "registry_metadata", "code_snippet", "scanner_output"]),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding.id", ondelete="CASCADE"), nullable=False)
    scan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("scan.id", ondelete="SET NULL"))
    evidence_key: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(TZ, nullable=False)


# --------------------------------------------------------------------------- AI
class Recommendation(Base):
    __tablename__ = "recommendation"
    __table_args__ = (
        one_of("kind", E.values(E.RecommendationKind)),
        one_of("status", E.values(E.RecommendationStatus)),
        one_of("validation_status", E.values(E.ValidationStatus), nullable=True),
        Index("ix_recommendation_finding", "finding_id", "created_at"),
        Index("ix_recommendation_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    validation_status: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence_pack_sha256: Mapped[str | None] = mapped_column(String(64))
    evidence_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    content: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    raw_output: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    feedback_rating: Mapped[str | None] = mapped_column(String(20))
    feedback_comment: Mapped[str | None] = mapped_column(String(1000))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TZ, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(TZ)


# --------------------------------------------------------------------------- remediation
class FixProposal(Base):
    __tablename__ = "fix_proposal"
    __table_args__ = (
        one_of("status", E.values(E.ProposalStatus)),
        one_of("validation_result", E.values(E.ValidationResult)),
        CheckConstraint(
            "pr_branch IS NULL OR pr_branch ~ "
            "'^toolkit/fix/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
            name="pr_branch_pattern",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'pr_opened') OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="approval_recorded",
        ),
        Index("ix_fix_proposal_project", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    stage: Mapped[str | None] = mapped_column(String(40))
    base_commit_sha: Mapped[str | None] = mapped_column(String(40))
    base_ref: Mapped[str | None] = mapped_column(String(200))
    changes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    has_major_bump: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    diff: Mapped[str | None] = mapped_column(Text)
    changed_files: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_result: Mapped[str] = mapped_column(String(20), nullable=False, default="not_run")
    delta_scan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    risk_notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(String(500))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(TZ)
    approval_ack: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    rejection_reason: Mapped[str | None] = mapped_column(String(1000))
    pr_number: Mapped[int | None] = mapped_column(Integer)
    pr_url: Mapped[str | None] = mapped_column(String(500))
    pr_branch: Mapped[str | None] = mapped_column(String(100))
    pr_error: Mapped[str | None] = mapped_column(String(500))
    pr_closed_at: Mapped[datetime | None] = mapped_column(TZ)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class FixProposalFinding(Base):
    __tablename__ = "fix_proposal_finding"

    fix_proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fix_proposal.id", ondelete="CASCADE"), primary_key=True
    )
    finding_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("finding.id", ondelete="CASCADE"), primary_key=True)


class ValidationRun(Base):
    __tablename__ = "validation_run"
    __table_args__ = (
        one_of("stage", ["baseline", "apply", "post_change", "rescan"]),
        one_of("status", ["passed", "failed", "skipped", "error"]),
        Index("ix_validation_run_proposal", "fix_proposal_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    fix_proposal_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fix_proposal.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    output_tail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(TZ, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(TZ)
