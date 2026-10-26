#!/usr/bin/env python3
"""Live end-to-end smoke test against a running stack (docker compose --profile demo up).

Exercises: login → project → monitoring target (demo-app) → live metrics → fault injection →
alert fires (detection time measured against T_ingest + N·Δ_eval) → auto-resolve → repository
connect → real scan (Trivy, OSV, registries, Semgrep) → findings explorer → overview.

    python scripts/smoke_e2e.py --email admin@example.com --password ... --demo-token ...
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from typing import Any

API = "http://localhost:8000/api/v1"
TOKEN = ""


def call(method: str, path: str, body: Any = None, base: str = API, token: str | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    tok = TOKEN if token is None else token
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - local stack
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:400]}") from e


def wait(what: str, fn: Any, timeout: float, every: float = 5) -> Any:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        out = fn()
        if out:
            return out
        time.sleep(every)
    raise SystemExit(f"timed out waiting for {what}")


def step(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    global TOKEN  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--demo-url", default="http://localhost:8080")
    ap.add_argument("--demo-token", required=True)
    ap.add_argument("--repo", default="https://github.com/snyk-labs/nodejs-goof")
    ap.add_argument("--eval-interval", type=int, default=15)
    ap.add_argument("--skip-scan", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the smoke project instead of archiving it")
    args = ap.parse_args()
    results: dict[str, Any] = {}

    TOKEN = call("POST", "/auth/login", {"email": args.email, "password": args.password}, token="")["access_token"]
    step("logged in")
    project = call("POST", "/projects", {"name": f"smoke-{int(time.time())}", "description": "Live smoke test"})
    pid = project["id"]
    target = call("POST", f"/projects/{pid}/monitoring-targets",
                  {"name": "Demo app", "service_name": "demo-app", "environment": "dev", "create_default_rules": True})
    step(f"project {pid} with target {target['id']}")
    t0 = time.monotonic()
    wait("target receiving", lambda: call("GET", f"/monitoring-targets/{target['id']}")["status"] == "receiving", 180)
    results["time_to_receiving_s"] = round(time.monotonic() - t0, 1)
    step(f"target receiving after {results['time_to_receiving_s']} s")

    series = call("GET", f"/monitoring-targets/{target['id']}/metrics?metric=request_rate&range=15m")
    assert series["status"] == "ok" and any(p["v"] for p in series["series"]), series
    results["request_rate_points"] = sum(1 for p in series["series"] if p["v"] is not None)
    step(f"request_rate chart ok ({results['request_rate_points']} points)")

    duration = args.eval_interval * 2
    rule = call("POST", f"/projects/{pid}/alert-rules", {
        "target_id": target["id"], "name": "Smoke: 5xx ratio", "type": "threshold", "metric": "error_ratio",
        "comparator": "gt", "threshold": 0.2, "window": "1m", "duration_seconds": duration, "resolve_after": 2,
        "severity": "high", "guidance": "Smoke test fault injection."})
    call("POST", "/admin/fault", {"error_rate": 0.9, "latency_seconds": 0, "ttl_seconds": 600},
         base=args.demo_url, token=args.demo_token)
    injected = time.monotonic()
    step("fault injected (90 % 5xx)")

    def firing() -> Any:
        items = call("GET", f"/alerts?project_id={pid}&status=firing")["items"]
        return next((a for a in items if a["rule_id"] == rule["id"]), None)

    alert = wait("alert firing", firing, 300, every=2)
    detect = time.monotonic() - injected
    n = math.ceil(duration / args.eval_interval)
    # T_ingest ≈ export interval (5 s) + collector batch (2 s) + rate window lag to cross 20 % of a 1m window (~15 s).
    bound = 5 + 2 + 15 + n * args.eval_interval + args.eval_interval  # + one tick of phase alignment
    results.update({"detection_time_s": round(detect, 1), "detection_bound_s": bound,
                    "observed_value": alert["evidence"]["observed_value"]})
    step(f"alert fired after {detect:.1f} s (bound {bound} s), observed {alert['evidence']['observed_value']}")
    for key in ("query", "observed_value", "threshold", "window", "guidance"):
        assert alert["evidence"].get(key) not in (None, ""), key
    call("POST", "/admin/clear", {}, base=args.demo_url, token=args.demo_token)
    step("fault cleared")
    wait("alert auto-resolved", lambda: call("GET", f"/alerts/{alert['id']}")["status"] == "resolved", 300, every=3)
    step("alert auto-resolved")
    results["alert_lifecycle"] = "fired+auto-resolved"

    if not args.skip_scan:
        repo = call("PUT", f"/projects/{pid}/repository", {"url": args.repo})
        step(f"repository verified: {repo['owner']}/{repo['name']} ecosystems={repo['ecosystems']}")
        started = call("POST", f"/projects/{pid}/scans", {})
        job_id = started["job"]["id"]

        def done() -> Any:
            job = call("GET", f"/jobs/{job_id}")
            return job if job["status"] in ("succeeded", "partial", "failed", "cancelled") else None

        job = wait("scan finished", done, 1500, every=10)
        scan = call("GET", f"/scans/{started['scan']['id']}")
        results["scan"] = {"status": scan["status"], "commit": scan["commit_sha"], "summary": scan["summary"],
                           "providers": {p["name"]: [p["status"], p["duration_ms"], p["error"]] for p in scan["providers"]},
                           "job_error": job.get("error")}
        step(f"scan {scan['status']}: {json.dumps(results['scan']['providers'])}")
        findings = call("GET", f"/projects/{pid}/findings?limit=5&sort=-severity")
        results["findings_total"] = findings["total"]
        results["top_findings"] = [f["title"][:100] for f in findings["items"]]
        step(f"{findings['total']} open findings")

    overview = call("GET", f"/projects/{pid}/overview")
    results["overview_sections"] = {k: overview[k]["status"] for k in ("monitoring", "alerts", "latest_scan", "top_findings")}
    if not args.keep:
        call("DELETE", f"/projects/{pid}")
        step("smoke project archived (pass --keep to leave it active)")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
