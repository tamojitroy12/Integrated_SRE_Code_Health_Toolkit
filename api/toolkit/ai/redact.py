"""Secret redaction for code snippets (FR-AI-06, T-06.02, T-08.02).

Runs before snippets are stored as evidence and again before anything is sent to the
model. If the redactor cannot be confident (for example a private-key block that is cut
off, or a credential-looking assignment it could not neutralize), the snippet is omitted.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

REDACTED = "[REDACTED]"

_TOKEN_PATTERNS = [
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{10,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{20,}"),
    re.compile(r"xox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)https?://[^\s:/@\"']+:[^\s@/\"']+@"),  # credentials in URLs
    re.compile(r"(?i)\bFAKE_[A-Z0-9_]*KEY[A-Z0-9_]*\b"),
]
_ASSIGNMENT = re.compile(
    r"(?P<key>(?i:[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|auth|credential"
    r"|private[_-]?key)[\w.-]*))(?P<sep>\s*[:=]\s*|\s*=>\s*)(?P<q>[\"'`])(?P<value>[^\"'`\n]{4,})(?P=q)"
)
_PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)
_QUOTED = re.compile(r"[\"'`]([A-Za-z0-9+/=_\-]{32,})[\"'`]")


@dataclass(frozen=True)
class Redaction:
    text: str | None
    redactions: int
    omitted: bool
    reason: str | None = None


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    counts = {c: s.count(c) for c in set(s)}
    return -sum((n / len(s)) * math.log2(n / len(s)) for n in counts.values())


def redact_text(text: str) -> Redaction:
    count = 0

    text, n = _PRIVATE_KEY_BLOCK.subn(REDACTED, text)
    count += n
    if _PRIVATE_KEY_BEGIN.search(text):
        return Redaction(None, count, True, "truncated private key block")

    def assign(m: re.Match[str]) -> str:
        nonlocal count
        value = m.group("value")
        if value == REDACTED or value.startswith(("${", "{{", "process.env", "os.environ")):
            return m.group(0)
        count += 1
        return f"{m.group('key')}{m.group('sep')}{m.group('q')}{REDACTED}{m.group('q')}"

    text = _ASSIGNMENT.sub(assign, text)
    for pattern in _TOKEN_PATTERNS:
        text, n = pattern.subn(REDACTED, text)
        count += n

    def high_entropy(m: re.Match[str]) -> str:
        nonlocal count
        value = m.group(1)
        if _entropy(value) >= 4.0 and not value.isdigit():
            count += 1
            return m.group(0).replace(value, REDACTED)
        return m.group(0)

    text = _QUOTED.sub(high_entropy, text)

    # Confidence check: a credential keyword followed by a long unquoted literal is ambiguous.
    for line in text.splitlines():
        if re.search(r"(?i)(password|secret|api[_-]?key|token)\s*[:=]\s*[A-Za-z0-9+/_\-]{16,}\s*$", line):
            return Redaction(None, count, True, "unquoted credential-like value")
    return Redaction(text, count, False)
