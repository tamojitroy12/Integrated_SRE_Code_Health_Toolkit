"""Evidence pack construction (FR-AI-02, AI_DESIGN §4).

The pack is built only from stored findings/evidence plus registry metadata fetched by the
Toolkit. Every item gets an ID (``ev-n``) and a SHA-256; the pack hash is stored with the
recommendation. Snippets are re-redacted here and omitted when redaction is uncertain.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from toolkit.ai.redact import redact_text
from toolkit.db.models import Evidence, Finding
from toolkit.integrations.registry import PackageMeta

CHARS_PER_TOKEN = 3.5  # conservative estimate used for the input budget


@dataclass
class PackItem:
    id: str
    kind: str
    source: str
    url: str | None
    retrieved_at: datetime | None
    content: dict[str, Any]
    stored_key: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.content, sort_keys=True, default=str).encode()).hexdigest()

    def ref(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "url": self.url,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "stored_evidence_id": self.stored_key,
            "sha256": self.sha256,
        }


@dataclass
class EvidencePack:
    items: list[PackItem] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    registry: dict[str, PackageMeta] = field(default_factory=dict)

    @property
    def ids(self) -> set[str]:
        return {i.id for i in self.items}

    def get(self, item_id: str) -> PackItem | None:
        return next((i for i in self.items if i.id == item_id), None)

    @property
    def sha256(self) -> str:
        joined = "\n".join(f"{i.id}:{i.sha256}" for i in self.items)
        return hashlib.sha256(joined.encode()).hexdigest()

    def estimated_tokens(self) -> int:
        size = sum(len(json.dumps(i.content, default=str)) + 80 for i in self.items)
        return int(size / CHARS_PER_TOKEN)

    def advisories(self) -> list[dict[str, Any]]:
        return [i.content for i in self.items if i.kind == "advisory_record"]

    def snippet(self) -> dict[str, Any] | None:
        return next((i.content for i in self.items if i.kind == "code_snippet"), None)


def _scanner_item(f: Finding) -> dict[str, Any]:
    content: dict[str, Any] = {
        "finding_type": f.type,
        "title": f.title,
        "severity": f.severity or "unrated",
        "severity_source": f.severity_source,
        "sources": f.sources,
    }
    if f.type == "code_issue":
        content.update(
            {
                "rule_id": f.rule_id,
                "message": f.message,
                "file": f.file_path,
                "line_start": f.line_start,
                "line_end": f.line_end,
            }
        )
    else:
        adv = f.advisory or {}
        content.update(
            {
                "package": f.package_name,
                "ecosystem": f.ecosystem,
                "installed_version": f.package_version,
                "scope": f.scope,
                "manifest_path": f.manifest_path,
                "advisory_ids": adv.get("ids", []),
                "fixed_versions": adv.get("fixed_versions", []),
                "heuristic": (f.detail or {}).get("heuristic"),
                "detail": f.detail,
            }
        )
    return content


def build_pack(
    finding: Finding,
    evidence: list[Evidence],
    registry_meta: PackageMeta | None,
    max_input_tokens: int,
    instructions_tokens: int,
) -> EvidencePack:
    pack = EvidencePack()
    n = 0

    def add(
        kind: str,
        source: str,
        url: str | None,
        retrieved: datetime | None,
        content: dict[str, Any],
        stored: str | None = None,
    ) -> None:
        nonlocal n
        n += 1
        pack.items.append(PackItem(f"ev-{n}", kind, source, url, retrieved, content, stored))

    add("scanner_output", "toolkit", None, finding.last_seen_at, _scanner_item(finding))
    # Latest version of each stored evidence item, newest first per kind.
    for ev in sorted(evidence, key=lambda e: e.retrieved_at, reverse=True):
        if ev.kind == "advisory_record":
            if any(i.kind == "advisory_record" and i.content.get("id") == ev.content.get("id") for i in pack.items):
                continue
            add(ev.kind, ev.source, ev.url, ev.retrieved_at, copy.deepcopy(ev.content), ev.evidence_key)
        elif ev.kind == "code_snippet":
            if pack.snippet() is not None:
                continue
            snippet = ev.content.get("snippet")
            red = redact_text(snippet) if isinstance(snippet, str) else None
            if red is None or red.omitted or red.text is None:
                pack.limitations.append("The code snippet was omitted because secret redaction was uncertain.")
                continue
            add(ev.kind, ev.source, ev.url, ev.retrieved_at, {**ev.content, "snippet": red.text}, ev.evidence_key)
    if registry_meta is not None:
        add("registry_metadata", registry_meta.ecosystem, registry_meta.source_url, None, registry_meta.evidence())
        pack.registry[registry_meta.name.lower()] = registry_meta

    _trim(pack, max_input_tokens - instructions_tokens)
    return pack


def _trim(pack: EvidencePack, budget: int) -> None:
    """Fixed trimming order (AI_DESIGN §4): long advisory text first, then snippet context."""
    if pack.estimated_tokens() <= budget:
        return
    for limit in (2000, 500, 0):
        for item in pack.items:
            if item.kind == "advisory_record" and isinstance(item.content.get("details"), str):
                d = item.content["details"]
                item.content["details"] = (d[:limit] + "…") if limit and len(d) > limit else (d if limit else None)
            if item.kind == "advisory_record" and limit == 0:
                item.content["references"] = item.content.get("references", [])[:5]
        if pack.estimated_tokens() <= budget:
            pack.limitations.append("Long advisory text was shortened to fit the input limit.")
            return
    snip = next((i for i in pack.items if i.kind == "code_snippet"), None)
    if snip is not None:
        lines = str(snip.content.get("snippet", "")).splitlines()
        s, e = snip.content.get("match_start", 1), snip.content.get("match_end", 1)
        first = snip.content.get("line_start", 1)
        core = lines[max(0, s - first) : max(0, e - first) + 1]
        snip.content["snippet"] = "\n".join(core)
        snip.content["line_start"], snip.content["line_end"] = s, e
        pack.limitations.append("Code snippet context was reduced to the matched lines to fit the input limit.")
    if pack.estimated_tokens() > budget:
        raise ValueError("evidence pack exceeds AI_MAX_INPUT_TOKENS even after trimming")
