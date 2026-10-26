"""Bounded, redacted code snippets for code-issue evidence (FR-SAST-01, DATA_MODEL §2.5)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from toolkit.ai.redact import redact_text

MAX_LINES = 31
MAX_BYTES = 4096
CONTEXT = 5


def _read_lines(repo: Path, rel: str) -> list[str] | None:
    path = (repo / rel).resolve()
    try:
        path.relative_to(repo.resolve())
    except ValueError:
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def normalized_match_hash(repo: Path, rel: str, line_start: int, line_end: int) -> str:
    """Hash of the matched lines with whitespace collapsed (fingerprint subject_key, TRD §5.2)."""
    lines = _read_lines(repo, rel) or []
    matched = "\n".join(lines[max(0, line_start - 1) : line_end])
    normalized = re.sub(r"\s+", " ", matched).strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def extract(repo: Path, rel: str, line_start: int, line_end: int) -> dict[str, Any] | None:
    lines = _read_lines(repo, rel)
    if lines is None:
        return None
    if line_end - line_start + 1 >= MAX_LINES:
        first, last = line_start, line_start + MAX_LINES - 1
    else:
        spare = MAX_LINES - (line_end - line_start + 1)
        before = min(CONTEXT, spare // 2, line_start - 1)
        first = line_start - before
        last = min(len(lines), line_end + min(CONTEXT, spare - before))
    chunk = lines[first - 1 : last]
    text = "\n".join(chunk)
    while len(text.encode()) > MAX_BYTES and len(chunk) > 1:
        chunk = chunk[:-1]
        last -= 1
        text = "\n".join(chunk)
    if len(text.encode()) > MAX_BYTES:
        text = text.encode()[:MAX_BYTES].decode("utf-8", errors="ignore")
    red = redact_text(text)
    return {
        "path": rel,
        "line_start": first,
        "line_end": last,
        "match_start": line_start,
        "match_end": line_end,
        "snippet": red.text,
        "redactions": red.redactions,
        "omitted": red.omitted,
        "omitted_reason": red.reason,
    }
