"""OSV.dev adapter (IF-03, TRD §5.1 step 3).

Batch query (≤ 1,000 queries per request, with ``next_page_token`` pagination) returns
vulnerability IDs; full records are fetched by ID with bounded parallelism and cached by
``(id, modified)``.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from toolkit.core.config import get_settings
from toolkit.core.http import HttpClient, host_of
from toolkit.core.validators import normalize_pypi_name
from toolkit.scanning.cvss import severity_from_vector

OSV_ECOSYSTEM = {"npm": "npm", "pypi": "PyPI"}
BATCH_LIMIT = 1000
MAX_DETAILS = 8 * 1024
_GHSA_SEVERITY = {"LOW": "low", "MODERATE": "medium", "MEDIUM": "medium", "HIGH": "high", "CRITICAL": "critical"}


@dataclass
class Advisory:
    id: str
    aliases: list[str]
    summary: str | None
    details: str | None
    severity: str | None
    cvss_vector: str | None
    fixed_versions: list[str]
    references: list[str]
    modified: str | None
    published: str | None
    withdrawn: str | None
    raw_size: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"https://osv.dev/vulnerability/{quote(self.id)}"

    def record(self) -> dict[str, Any]:
        """Bounded representation stored as evidence (≤ 64 KB, DATA_MODEL §2.5)."""
        return {
            "id": self.id,
            "aliases": self.aliases,
            "summary": self.summary,
            "details": self.details,
            "severity": self.severity,
            "cvss_vector": self.cvss_vector,
            "fixed_versions": self.fixed_versions,
            "references": self.references[:20],
            "modified": self.modified,
            "published": self.published,
        }


class _LruCache:
    def __init__(self, size: int = 5000) -> None:
        self._data: OrderedDict[tuple[str, str], Advisory | dict[str, Any]] = OrderedDict()
        self._size = size
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> Any:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            return None

    def put(self, key: tuple[str, str], value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._size:
                self._data.popitem(last=False)


_record_cache = _LruCache()


def parse_record(raw: dict[str, Any], ecosystem: str, package: str) -> Advisory:
    eco = OSV_ECOSYSTEM[ecosystem]
    pkg_norm = normalize_pypi_name(package) if ecosystem == "pypi" else package
    fixed: list[str] = []
    for affected in raw.get("affected") or []:
        p = affected.get("package") or {}
        name = str(p.get("name", ""))
        name = normalize_pypi_name(name) if ecosystem == "pypi" else name
        if p.get("ecosystem") != eco or name != pkg_norm:
            continue
        for rng in affected.get("ranges") or []:
            if rng.get("type") not in ("ECOSYSTEM", "SEMVER"):
                continue
            for event in rng.get("events") or []:
                if "fixed" in event and event["fixed"] not in fixed:
                    fixed.append(str(event["fixed"]))
    vector = None
    for sev in raw.get("severity") or []:
        if str(sev.get("type", "")).startswith("CVSS_V3"):
            vector = str(sev.get("score"))
            break
    db_sev = str((raw.get("database_specific") or {}).get("severity", "")).upper()
    severity = _GHSA_SEVERITY.get(db_sev) or (severity_from_vector(vector) if vector else None)
    details = raw.get("details")
    if isinstance(details, str) and len(details) > MAX_DETAILS:
        details = details[:MAX_DETAILS] + "…"
    return Advisory(
        id=str(raw["id"]),
        aliases=sorted({str(a) for a in raw.get("aliases") or []}),
        summary=raw.get("summary"),
        details=details,
        severity=severity,
        cvss_vector=vector,
        fixed_versions=fixed,
        references=[str(r.get("url")) for r in raw.get("references") or [] if r.get("url")][:30],
        modified=raw.get("modified"),
        published=raw.get("published"),
        withdrawn=raw.get("withdrawn"),
    )


class OsvClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.base = s.osv_api_url.rstrip("/")
        self.parallelism = s.provider_parallelism
        self._http = HttpClient(
            allowed_hosts={host_of(self.base)},
            timeout=s.provider_http_timeout_seconds,
            max_retries=3,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def query_batch(self, queries: list[tuple[str, str, str]]) -> list[list[tuple[str, str]]]:
        """For each (ecosystem, name, version) return [(vuln_id, modified)], preserving order."""
        results: list[list[tuple[str, str]]] = [[] for _ in queries]
        for offset in range(0, len(queries), BATCH_LIMIT):
            chunk = list(range(offset, min(offset + BATCH_LIMIT, len(queries))))
            tokens: dict[int, str | None] = dict.fromkeys(chunk)
            while tokens:
                body = {
                    "queries": [
                        {
                            "package": {"ecosystem": OSV_ECOSYSTEM[queries[i][0]], "name": queries[i][1]},
                            "version": queries[i][2],
                            **({"page_token": tok} if tok else {}),
                        }
                        for i, tok in tokens.items()
                    ]
                }
                data = self._http.post_json(f"{self.base}/v1/querybatch", body)
                next_tokens: dict[int, str | None] = {}
                for idx, item in zip(list(tokens), data.get("results", []), strict=False):
                    for v in item.get("vulns") or []:
                        results[idx].append((str(v["id"]), str(v.get("modified", ""))))
                    if item.get("next_page_token"):
                        next_tokens[idx] = item["next_page_token"]
                tokens = next_tokens
        return results

    def get_vuln(self, vuln_id: str, modified: str) -> dict[str, Any]:
        cached = _record_cache.get((vuln_id, modified))
        if cached is not None:
            return dict(cached)
        data: dict[str, Any] = self._http.get_json(f"{self.base}/v1/vulns/{quote(vuln_id, safe='')}")
        _record_cache.put((vuln_id, modified), data)
        return data

    def get_vulns(self, ids: list[tuple[str, str]]) -> dict[str, dict[str, Any]]:
        unique = sorted(set(ids))
        with ThreadPoolExecutor(max_workers=self.parallelism, thread_name_prefix="osv") as pool:
            records = list(pool.map(lambda pair: self.get_vuln(*pair), unique))
        return {pair[0]: rec for pair, rec in zip(unique, records, strict=True)}
