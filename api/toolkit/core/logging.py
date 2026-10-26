"""Structured JSON logging with request/job correlation and secret redaction.

NFR-OBS-01 (JSON with request_id / job_id) and NFR-SEC-08 (redact tokens, passwords,
Authorization headers).
"""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

_REDACTED = "[REDACTED]"

# Ordered from most to least specific. Each pattern either matches the full secret or
# uses a group 'secret' marking the part that must be hidden.
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(?P<prefix>authorization[\"']?\s*[:=]\s*[\"']?)(?P<secret>(?:bearer|basic|token)\s+[^\s\"',;]+)"),
    re.compile(r"(?i)(?P<prefix>bearer\s+)(?P<secret>[A-Za-z0-9\-._~+/]{8,}=*)"),
    re.compile(r"(?P<secret>github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"(?P<secret>gh[pousr]_[A-Za-z0-9]{20,})"),
    re.compile(r"(?P<secret>sk-ant-[A-Za-z0-9\-_]{10,})"),
    re.compile(r"(?P<secret>xox[abposr]-[A-Za-z0-9-]{10,})"),
    re.compile(r"(?P<secret>AKIA[0-9A-Z]{16})"),
    re.compile(r"(?P<secret>eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"),
    re.compile(
        r"(?i)(?P<prefix>[\"']?(?:password|passwd|secret|token|api[_-]?key|access[_-]?token|refresh[_-]?token"
        r"|initial_password|private[_-]?key)[\"']?\s*[:=]\s*[\"']?)(?P<secret>[^\s\"',;&]{3,})"
    ),
    re.compile(r"(?P<prefix>https?://[^\s:/@]+:)(?P<secret>[^\s@/]+)(?=@)"),
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(_replace, text)
    return text


def _replace(m: re.Match[str]) -> str:
    prefix = m.groupdict().get("prefix") or ""
    return f"{prefix}{_REDACTED}"


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: (_REDACTED if _sensitive_key(str(k)) else redact_value(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


_SENSITIVE_KEYS = re.compile(r"(?i)(password|secret|token|authorization|api[_-]?key|cookie|credential)")


def _sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEYS.search(key))


_RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        rid = request_id_var.get()
        jid = job_id_var.get()
        if rid:
            entry["request_id"] = rid
        if jid:
            entry["job_id"] = jid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                entry[key] = _REDACTED if _sensitive_key(key) else redact_value(value)
        if record.exc_info:
            entry["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Uvicorn's access log duplicates our request log and would print raw query strings.
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    for noisy in ("httpx", "httpcore", "docker", "urllib3"):
        logging.getLogger(noisy).setLevel("WARNING")
