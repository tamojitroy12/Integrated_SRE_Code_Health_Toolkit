#!/usr/bin/env python3
"""Requirement-to-test traceability report (TEST_STRATEGY §2.1 item 2, §4).

Parses docs/FRD.md for every functional requirement and scans the test suites for
``@pytest.mark.at("FR-…")`` markers (backend) and ``FR-…`` references in web tests.

    python tools/at_coverage.py [--min-priority M|S|C|W] [--format table|markdown|json]
                                [--uncovered-only] [--fail-uncovered]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIORITY_ORDER = {"M": 0, "S": 1, "C": 2, "W": 3}
FR_ROW = re.compile(r"^\|\s*(FR-[A-Z]+-\d{2})\s*\|.*\|\s*([MSCW])\s*\|", re.M)


def requirements() -> dict[str, str]:
    text = (ROOT / "docs" / "FRD.md").read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in FR_ROW.finditer(text)}


def covered() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    patterns = [(ROOT / "api" / "tests", "*.py", re.compile(r'mark\.at\("(FR-[A-Z]+-\d{2})"\)')),
                (ROOT / "web" / "tests", "*.ts*", re.compile(r"(FR-[A-Z]+-\d{2})")),
                (ROOT / "web" / "e2e", "*.ts", re.compile(r"(FR-[A-Z]+-\d{2})"))]
    for folder, glob, pattern in patterns:
        if not folder.is_dir():
            continue
        for path in folder.rglob(glob):
            for fr in pattern.findall(path.read_text(encoding="utf-8")):
                hits.setdefault(fr, []).append(path.relative_to(ROOT).as_posix())
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-priority", choices=list(PRIORITY_ORDER), default="M")
    ap.add_argument("--format", choices=["table", "markdown", "json"], default="table")
    ap.add_argument("--uncovered-only", action="store_true")
    ap.add_argument("--fail-uncovered", action="store_true")
    args = ap.parse_args()
    reqs = requirements()
    if len(reqs) != 70:
        print(f"expected 70 functional requirements in docs/FRD.md, found {len(reqs)}", file=sys.stderr)
        return 2
    hits = covered()
    limit = PRIORITY_ORDER[args.min_priority]
    rows = [(fr, pri, sorted(set(hits.get(fr, [])))) for fr, pri in reqs.items()
            if PRIORITY_ORDER[pri] <= limit and pri != "W"]
    if args.uncovered_only:
        rows = [r for r in rows if not r[2]]
    total = [r for r in reqs.items() if PRIORITY_ORDER[r[1]] <= limit and r[1] != "W"]
    done = sum(1 for fr, _ in total if hits.get(fr))
    if args.format == "json":
        print(json.dumps({"covered": done, "total": len(total),
                          "rows": [{"fr": f, "priority": p, "tests": t} for f, p, t in rows]}, indent=2))
    else:
        sep = "|" if args.format == "markdown" else " "
        if args.format == "markdown":
            print("| FR | Pri | Tests |\n|---|---|---|")
        for fr, pri, tests in rows:
            mark = ", ".join(tests) if tests else "UNCOVERED"
            print(f"{sep} {fr} {sep} {pri} {sep} {mark} {sep}" if args.format == "markdown" else f"{fr:<12} {pri}  {mark}")
        print(f"\nCoverage: {done}/{len(total)} ({100 * done / max(1, len(total)):.1f}%) at priority <= {args.min_priority}")
    return 1 if args.fail_uncovered and done < len(total) else 0


if __name__ == "__main__":
    sys.exit(main())
