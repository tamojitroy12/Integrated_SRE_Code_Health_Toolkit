#!/usr/bin/env python3
"""Wait until the stack is healthy (API /ready, web /login) with bounded backoff.

    python scripts/wait_for_health.py [--api http://localhost:8000] [--web http://localhost:3000] [--timeout 300]
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request


def ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - local health URLs
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError):
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--web", default="http://localhost:3000")
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()
    checks = {"api /ready": f"{args.api}/ready", "web /login": f"{args.web}/login"}
    deadline = time.monotonic() + args.timeout
    delay = 1.0
    pending = dict(checks)
    while pending and time.monotonic() < deadline:
        for name, url in list(pending.items()):
            if ok(url):
                print(f"ready: {name}")
                del pending[name]
        if pending:
            time.sleep(delay)
            delay = min(10.0, delay * 1.5)
    if pending:
        print(f"not ready after {args.timeout:.0f}s: {', '.join(pending)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
