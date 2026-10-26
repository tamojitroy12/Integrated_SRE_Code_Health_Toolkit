"""Error model shared by the API (API_SPEC §3) and job failures."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105 - error code
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    ACK_REQUIRED = "ACK_REQUIRED"
    AI_DISABLED = "AI_DISABLED"
    REMEDIATION_DISABLED = "REMEDIATION_DISABLED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    REPO_ACCESS_DENIED = "REPO_ACCESS_DENIED"
    REPO_NOT_FOUND = "REPO_NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    AI_BUDGET_EXCEEDED = "AI_BUDGET_EXCEEDED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    PROMETHEUS_UNAVAILABLE = "PROMETHEUS_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_STATUS: dict[ErrorCode, int] = {
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INVALID_TRANSITION: 409,
    ErrorCode.APPROVAL_REQUIRED: 409,
    ErrorCode.ACK_REQUIRED: 409,
    ErrorCode.AI_DISABLED: 409,
    ErrorCode.REMEDIATION_DISABLED: 409,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.REPO_ACCESS_DENIED: 422,
    ErrorCode.REPO_NOT_FOUND: 422,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.AI_BUDGET_EXCEEDED: 429,
    ErrorCode.UPSTREAM_ERROR: 502,
    ErrorCode.SANDBOX_UNAVAILABLE: 503,
    ErrorCode.PROMETHEUS_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}

_DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.UNAUTHENTICATED: "Authentication required.",
    ErrorCode.TOKEN_EXPIRED: "Access token expired.",
    ErrorCode.INVALID_CREDENTIALS: "Invalid email or password.",
    ErrorCode.FORBIDDEN: "Your role does not permit this action.",
    ErrorCode.NOT_FOUND: "Resource not found.",
    ErrorCode.VALIDATION_ERROR: "Request validation failed.",
    ErrorCode.AI_DISABLED: "AI recommendations are disabled in this deployment.",
    ErrorCode.REMEDIATION_DISABLED: "Remediation is disabled in this deployment.",
    ErrorCode.PROMETHEUS_UNAVAILABLE: "Metrics store unreachable.",
    ErrorCode.INTERNAL_ERROR: "An unexpected error occurred.",
}


class ApiError(Exception):
    """An error that maps onto the documented JSON error envelope."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        details: list[dict[str, Any]] | None = None,
        status: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message or _DEFAULT_MESSAGES.get(code, code.value.replace("_", " ").capitalize())
        self.details = details or []
        self.status = status or _STATUS[code]
        self.headers = headers
        super().__init__(self.message)


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(ErrorCode.NOT_FOUND, f"{what} not found.")


def validation_error(field: str, issue: str) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, details=[{"field": field, "issue": issue}])


class JobErrorCode(StrEnum):
    CLONE_FAILED = "CLONE_FAILED"
    SCAN_TIMEOUT = "SCAN_TIMEOUT"
    PROVIDER_FAILED = "PROVIDER_FAILED"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    DIFF_SCOPE_VIOLATION = "DIFF_SCOPE_VIOLATION"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    TESTS_FAILED = "TESTS_FAILED"
    SDIST_BUILD_REQUIRED = "SDIST_BUILD_REQUIRED"
    PR_PUSH_FAILED = "PR_PUSH_FAILED"
    PLAN_INVALID = "PLAN_INVALID"
    AI_UNAVAILABLE = "AI_UNAVAILABLE"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class JobError(Exception):
    """Raised inside job handlers to fail a job with a documented code."""

    def __init__(self, code: JobErrorCode, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message[:500]
        self.retryable = retryable
        super().__init__(self.message)


class JobCancelled(Exception):  # noqa: N818 - control-flow signal, not an error
    """Raised when a job observes its cancel flag."""
