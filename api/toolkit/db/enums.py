"""Enumerations: the single source of truth from DATA_MODEL §3."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    VIEWER = "viewer"
    MAINTAINER = "maintainer"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return {"viewer": 0, "maintainer": 1, "admin": 2}[self.value]


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


SEVERITY_RANK: dict[str | None, int] = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1, None: 0}


class FindingType(StrEnum):
    DEPENDENCY_VULNERABILITY = "dependency_vulnerability"
    DEPENDENCY_OUTDATED = "dependency_outdated"
    DEPENDENCY_INCOMPATIBILITY = "dependency_incompatibility"
    CODE_ISSUE = "code_issue"


class FindingStatus(StrEnum):
    OPEN = "open"
    DISMISSED = "dismissed"
    RESOLVED = "resolved"


class FindingChange(StrEnum):
    NEW = "new"
    UNCHANGED = "unchanged"
    RESOLVED = "resolved"


class DismissalReason(StrEnum):
    FALSE_POSITIVE = "false_positive"
    ACCEPTED_RISK = "accepted_risk"
    WONT_FIX = "wont_fix"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.PARTIAL, JobStatus.FAILED, JobStatus.CANCELLED)


TERMINAL_JOB_STATUSES = ("succeeded", "partial", "failed", "cancelled")


class JobType(StrEnum):
    SCAN = "scan"
    RECOMMENDATION = "recommendation"
    FIX_PROPOSAL = "fix_proposal"
    PR_CREATION = "pr_creation"
    PR_CLEANUP = "pr_cleanup"


class Provider(StrEnum):
    TRIVY = "trivy"
    OSV = "osv"
    REGISTRY = "registry"
    SEMGREP = "semgrep"


class ProviderStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


class AlertStatus(StrEnum):
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class TargetStatus(StrEnum):
    WAITING = "waiting"
    RECEIVING = "receiving"
    STALE = "stale"


class RuleType(StrEnum):
    THRESHOLD = "threshold"
    ANOMALY = "anomaly"
    ABSENCE = "absence"


class RuleMetric(StrEnum):
    ERROR_RATIO = "error_ratio"
    LATENCY_P95 = "latency_p95"
    REQUEST_RATE = "request_rate"
    DATA_ABSENT = "data_absent"


class Comparator(StrEnum):
    GT = "gt"
    LT = "lt"


class RecommendationKind(StrEnum):
    LIBRARY_ALTERNATIVE = "library_alternative"
    UPGRADE_GUIDANCE = "upgrade_guidance"
    CODE_IMPROVEMENT = "code_improvement"


class RecommendationStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class ValidationStatus(StrEnum):
    VALIDATED = "validated"
    PARTIALLY_VALIDATED = "partially_validated"
    REJECTED = "rejected"


class ProposalStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    READY = "ready"
    APPROVED = "approved"
    PR_OPENED = "pr_opened"
    REJECTED = "rejected"
    FAILED = "failed"
    SUPERSEDED = "superseded"


class ValidationResult(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    UNVERIFIED = "unverified"
    NOT_RUN = "not_run"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


def values(enum: type[StrEnum]) -> list[str]:
    return [e.value for e in enum]
