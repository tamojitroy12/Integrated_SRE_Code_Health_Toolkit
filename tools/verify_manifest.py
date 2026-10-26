#!/usr/bin/env python3
"""Offline check that a fixture manifest matches the lockfiles it describes (SM-02 fixture hygiene).

Every seeded (ecosystem, name, version) must be present in the referenced manifest/lockfile, and
every entry must carry at least one advisory ID recorded at creation time. No network access.

    python tools/verify_manifest.py examples/vulnerable-repo/fixture-manifest.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _npm_versions(lock: Path) -> dict[str, set[str]]:
    data = json.loads(lock.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for key, meta in (data.get("packages") or {}).items():
        if "node_modules/" in key and isinstance(meta.get("version"), str):
            out.setdefault(key.rsplit("node_modules/", 1)[1], set()).add(meta["version"])
    return out


def _pypi_versions(req: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for line in req.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Za-z0-9._-]+)\s*==\s*([^\s;#]+)", line)
        if m:
            out.setdefault(re.sub(r"[-_.]+", "-", m.group(1)).lower(), set()).add(m.group(2))
    return out


def verify(manifest_path: Path) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent
    errors: list[str] = []
    cache: dict[str, dict[str, set[str]]] = {}
    seeded = manifest.get("seeded", [])
    if len(seeded) < 10:
        errors.append(f"only {len(seeded)} seeded versions; SM-02 requires at least 10")
    for entry in seeded:
        rel = entry["manifest_path"]
        path = root / rel
        if not path.is_file():
            errors.append(f"{rel}: file not found")
            continue
        if rel not in cache:
            cache[rel] = _npm_versions(path) if entry["ecosystem"] == "npm" else _pypi_versions(path)
        name = entry["name"] if entry["ecosystem"] == "npm" else re.sub(r"[-_.]+", "-", entry["name"]).lower()
        if entry["version"] not in cache[rel].get(name, set()):
            errors.append(f"{entry['ecosystem']}:{entry['name']}@{entry['version']} not found in {rel}")
        if not entry.get("advisory_ids"):
            errors.append(f"{entry['ecosystem']}:{entry['name']}@{entry['version']} has no recorded advisory IDs")
    for issue in manifest.get("code_issues", []):
        if not (root / issue["path"]).is_file():
            errors.append(f"code issue file missing: {issue['path']}")
    return errors


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "examples/vulnerable-repo/fixture-manifest.json")
    errors = verify(path)
    if errors:
        for e in errors:
            print(f"FAIL {e}")
        return 1
    print(f"OK {path}: all seeded versions present with recorded advisories")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
