# API Specification

> **Doc:** API_SPEC.md · **Version:** 0.1 · **Date:** 2026-10-13 · **Status:** Draft (proposed contract, **[P]**) · **Related:** [FRD](FRD.md), [DATA_MODEL](DATA_MODEL.md), [WORKFLOW](WORKFLOW.md)

The FastAPI application generates OpenAPI from code. This document is the **design contract**; a CI contract test (NFR-MNT-02) compares the generated schema with it. Values in examples are illustrative placeholders, not real packages, advisories, or results.

## 1. Conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1`. Operational endpoints (`/health`, `/ready`, `/metrics`) are unversioned. |
| Format | JSON (`application/json`), UTF-8. Timestamps ISO 8601 in UTC (`2026-10-13T09:30:00Z`). IDs are UUID strings. |
| Naming | `snake_case` fields; plural nouns for collections. |
| Pagination | `?limit=<1..100, default 50>&cursor=<opaque>`; response `{ "items": [...], "next_cursor": "..." \| null }`. |
| Sorting | `?sort=<field>` or `?sort=-<field>`; allowed fields are listed per endpoint. |
| Idempotency (Should) | `Idempotency-Key` header on job-creating `POST`s; same key within 24 h returns the original response. |
| Unknown fields | Rejected with `422 VALIDATION_ERROR`. |
| Secrets | Tokens/keys are write-only; no response ever contains them. |

## 2. Authentication and authorization

- `POST /auth/login` returns a short-lived **access token** (JWT, ≤ 15 min, **[P]**) in the body and sets a **refresh token** as an `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/v1/auth`.
- All other `/api/v1` calls require `Authorization: Bearer <access_token>`.
- Roles: `viewer` (V) < `maintainer` (M) < `admin` (A). The *Min role* column below is enforced server-side (FR-AUTH-03). Insufficient role → `403 FORBIDDEN`.
- Operational endpoints: `/health` and `/ready` are unauthenticated and reveal no data; `/metrics` is restricted to the internal network (or a static scrape token) **[P]**.

## 3. Error model

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [{ "field": "threshold", "issue": "must be between 0 and 1" }],
    "request_id": "7c1f1c1a-0f47-4a43-8a0a-3d5f2f5d6b11"
  }
}
```

| HTTP | `code` | When |
|---|---|---|
| 400 | `BAD_REQUEST` | Malformed JSON or unsupported query parameter |
| 401 | `UNAUTHENTICATED`, `TOKEN_EXPIRED`, `INVALID_CREDENTIALS` | Missing/expired token; wrong email or password (same message for both) |
| 403 | `FORBIDDEN` | Role insufficient |
| 404 | `NOT_FOUND` | Resource missing (also used when the caller may not know it exists) |
| 409 | `CONFLICT`, `INVALID_TRANSITION`, `APPROVAL_REQUIRED`, `ACK_REQUIRED`, `AI_DISABLED`, `REMEDIATION_DISABLED` | State or feature conflicts |
| 422 | `VALIDATION_ERROR`, `REPO_ACCESS_DENIED`, `REPO_NOT_FOUND` | Schema errors; GitHub reports 401/403/404 for the supplied repository/token |
| 429 | `RATE_LIMITED`, `AI_BUDGET_EXCEEDED` | Login throttling; AI daily cap or input-size limit |
| 502 | `UPSTREAM_ERROR` | A synchronous upstream call failed (e.g., repository verification) |
| 503 | `SANDBOX_UNAVAILABLE`, `PROMETHEUS_UNAVAILABLE` | Dependency down |

Job-level failures (not HTTP errors) appear in `job.error.code`: `CLONE_FAILED`, `SCAN_TIMEOUT`, `PROVIDER_FAILED`, `SCHEMA_INVALID`, `DIFF_SCOPE_VIOLATION`, `SANDBOX_UNAVAILABLE`, `TESTS_FAILED`, `SDIST_BUILD_REQUIRED`, `PR_PUSH_FAILED`, `INTERNAL_ERROR`.

## 4. Asynchronous jobs

Long-running operations return `202 Accepted` with the created resource and a `job`. Clients poll `GET /jobs/{job_id}` (suggested: every 2 s for 30 s, then every 5 s) until `status` is terminal.

```json
{
  "id": "0b8f…", "type": "scan",
  "status": "running",
  "stage": "dependency_inventory",
  "attempts": 1,
  "error": null,
  "resource": { "type": "scan", "id": "a1c2…" },
  "created_at": "2026-10-13T09:30:00Z",
  "started_at": "2026-10-13T09:30:02Z",
  "finished_at": null
}
```

`status` ∈ `queued, running, succeeded, partial, failed, cancelled` (state machine in [WORKFLOW](WORKFLOW.md#job-lifecycle-all-asynchronous-work)). `type` ∈ `scan, recommendation, fix_proposal, pr_creation`. Jobs are durable and leased; at most 3 attempts (NFR-REL-01).

## 5. Endpoints

### 5.1 Authentication and users

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| POST | `/auth/login` | public | Email + password | `200` |
| POST | `/auth/refresh` | cookie | New access token | `200` |
| POST | `/auth/logout` | V | Revoke refresh session | `204` |
| GET | `/auth/me` | V | Current user | `200` |
| GET | `/users` | A | List users | `200` |
| POST | `/users` | A | Create user `{email, display_name, role, initial_password}` | `201` |
| PATCH | `/users/{user_id}` | A | Change `role`, `display_name`, `is_active`, reset password | `200` |

```jsonc
// POST /auth/login
{ "email": "maintainer@example.edu", "password": "••••••••••••" }
// 200
{ "access_token": "<jwt>", "token_type": "bearer", "expires_in": 900,
  "user": { "id": "…", "email": "maintainer@example.edu", "display_name": "Maintainer", "role": "maintainer" } }
```

### 5.2 Projects and overview

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| POST | `/projects` | M | Create `{name, description?}` | `201` |
| GET | `/projects` | V | List; `?include_archived=false`, `?q=` | `200` |
| GET | `/projects/{project_id}` | V | Detail | `200` |
| PATCH | `/projects/{project_id}` | M | Update name/description | `200` |
| DELETE | `/projects/{project_id}` | M | Archive (soft delete) | `204` |
| GET | `/projects/{project_id}/overview` | V | Composite read model (FR-DSH-01) | `200` |

```jsonc
// GET /projects/{id}/overview — each section carries its own status (NFR-REL-05)
{
  "project": { "id": "…", "name": "demo" },
  "monitoring": { "status": "ok",
    "targets": [{ "id": "…", "service_name": "demo-api", "environment": "dev",
                  "status": "receiving", "last_seen_at": "2026-10-13T09:29:50Z",
                  "current": { "request_rate": 4.2, "error_ratio": 0.0, "latency_p95_seconds": 0.12 } }] },
  "alerts": { "status": "ok", "open_count": 1, "by_severity": { "high": 1 } },
  "latest_scan": { "status": "ok", "scan_id": "…", "scan_status": "partial",
    "commit_sha": "…", "counts": { "dependency_vulnerability": { "high": 2 }, "code_issue": { "medium": 3 } },
    "providers": [{ "name": "trivy", "status": "ok" }, { "name": "osv", "status": "failed" }] },
  "open_fix_proposals": 0
}
```

### 5.3 Repository

One repository per project (MVP).

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| PUT | `/projects/{project_id}/repository` | M | Connect or replace | `200` |
| GET | `/projects/{project_id}/repository` | V | Details (no token) | `200` |
| POST | `/projects/{project_id}/repository/verify` | M | Re-verify access and manifests | `200` |
| DELETE | `/projects/{project_id}/repository` | M | Disconnect and delete stored token | `204` |

```jsonc
// PUT body
{ "url": "https://github.com/example-org/example-repo",
  "token": "<fine-grained PAT, optional>",
  "default_branch": "main",
  "test_command": "npm test" }
// 200 (token never returned)
{ "id": "…", "provider": "github", "owner": "example-org", "name": "example-repo",
  "default_branch": "main", "ecosystems": ["npm"], "has_token": true,
  "can_open_prs": true, "test_command": "npm test", "verified_at": "2026-10-13T09:31:00Z" }
```

`can_open_prs` reflects whether the token appears to permit branch and PR creation, determined at verification **[A: GitHub permission introspection limits to be verified]**. `test_command`, if provided, is validated against an allowlist of patterns (`npm test`, `npm run test`, `pytest`, `python -m pytest`) **[P: UD-07]**.

### 5.4 Monitoring targets and metrics

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| POST | `/projects/{project_id}/monitoring-targets` | M | Create | `201` |
| GET | `/projects/{project_id}/monitoring-targets` | V | List | `200` |
| GET | `/monitoring-targets/{target_id}` | V | Detail with status | `200` |
| PATCH | `/monitoring-targets/{target_id}` | M | Update name/environment | `200` |
| DELETE | `/monitoring-targets/{target_id}` | M | Delete (disables its rules) | `204` |
| GET | `/monitoring-targets/{target_id}/onboarding` | M | Instrumentation instructions | `200` |
| GET | `/monitoring-targets/{target_id}/metrics` | V | Time series for charts | `200` |

```jsonc
// POST body
{ "name": "Demo API (dev)", "service_name": "demo-api", "environment": "dev", "ingestion_mode": "otlp_push" }
// GET onboarding (200)
{ "otlp_http_endpoint": "http://<toolkit-host>:4318",
  "env": { "OTEL_SERVICE_NAME": "demo-api", "OTEL_METRICS_EXPORTER": "otlp",
           "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
           "OTEL_EXPORTER_OTLP_ENDPOINT": "http://<toolkit-host>:4318",
           "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20<OTLP_INGEST_TOKEN>" },
  "token_note": "Ask an admin for the ingest token." }
```

`GET …/metrics?metric=<name>&range=<15m|1h|6h|24h>[&step=<seconds>]`

| Param | Allowed values |
|---|---|
| `metric` | `request_rate`, `error_ratio`, `latency_p50`, `latency_p95`, `latency_p99` |
| `range` | `15m`, `1h`, `6h`, `24h` |
| `step` | 15–3600 s; default chosen so the series has ≤ 300 points |

```json
{ "metric": "error_ratio", "unit": "ratio", "range": "1h", "step_seconds": 15,
  "status": "ok",
  "series": [{ "t": "2026-10-13T08:30:00Z", "v": 0.0 }, { "t": "2026-10-13T08:30:15Z", "v": 0.02 }] }
```

`status` ∈ `ok`, `no_data`, `no_traffic`. `503 PROMETHEUS_UNAVAILABLE` if the store cannot be queried.

### 5.4a Notification channels

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| GET | `/notification-channels` | M | List | `200` |
| POST | `/notification-channels` | A | Create `{type: "webhook"|"email", name, config}` | `201` |
| PATCH | `/notification-channels/{channel_id}` | A | Update/enable/disable | `200` |
| DELETE | `/notification-channels/{channel_id}` | A | Delete | `204` |
| POST | `/notification-channels/{channel_id}/test` | A | Send a test notification | `200` |

```jsonc
// POST /notification-channels (Admin only)
{
  "type": "webhook",
  "name": "Operations Slack",
  "config": { "url": "https://hooks.slack.com/services/T00/B00/X00" }
}

// GET /notification-channels & POST response (Maintainer / Admin)
// Note: config returns only masked host (and non-default port if present).
// Secret URLs, tokens, and credentials are encrypted at rest with AES-256-GCM
// using channel UUID as AAD, and are NEVER returned or logged.
{
  "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "type": "webhook",
  "name": "Operations Slack",
  "enabled": true,
  "config": { "host": "hooks.slack.com" },
  "created_at": "2026-10-24T12:00:00Z",
  "updated_at": "2026-10-24T12:00:00Z"
}

// PATCH /notification-channels/{id} (Admin only)
// extra="forbid", type cannot be changed, distinguishes omitted from null.
{
  "name": "Primary Ops Channel",
  "enabled": false
}

// POST /notification-channels/{id}/test (Admin only)
// Enforces a 5-second per-channel cooldown; returns 429 RATE_LIMITED on abuse.
// Sends payload with event="test" and alert_id=null.
// Response:
{
  "channel_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "delivery_id": "d13e9a55-b045-4df3-a55e-04d306b38c29",
  "status": "delivered",
  "error": null,
  "latency_ms": 142
}
```

**Security & Constraints**:
- `type="email"` returns `422 UNPROCESSABLE_ENTITY` (`"email channel is not enabled in this release"`).
- Target URLs must use `https://` (unless `ALLOW_PRIVATE_WEBHOOKS=true` is explicitly enabled in non-production environments).
- Embedded credentials (`user:pass@`) and private / loopback IP ranges are rejected at validation time. DNS lookups are bounded by a 2.0s timeout.
- Outbound requests enforce `max_redirects=0` to prevent redirect attacks leaking payloads or secret URLs across hops.
- Stored error messages in `notification_delivery.error` contain only sanitized exception class names and HTTP status codes (never URLs or response bodies).


### 5.5 Alert rules and alerts

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| POST | `/projects/{project_id}/alert-rules` | M | Create rule | `201` |
| GET | `/projects/{project_id}/alert-rules` | V | List | `200` |
| PATCH | `/alert-rules/{rule_id}` | M | Update/enable/disable | `200` |
| DELETE | `/alert-rules/{rule_id}` | M | Delete | `204` |
| GET | `/alerts` | V | List; filters `project_id`, `target_id`, `status`, `severity` | `200` |
| GET | `/alerts/{alert_id}` | V | Detail with evidence | `200` |
| GET | `/alerts/{alert_id}/deliveries` | V | List notification deliveries | `200` |
| POST | `/alerts/{alert_id}/acknowledge` | M | `firing → acknowledged` | `200` |
| POST | `/alerts/{alert_id}/resolve` | M | Manual resolve | `200` |

```jsonc
// POST /projects/{id}/alert-rules
{ "target_id": "…", "name": "High 5xx ratio", "type": "threshold",
  "metric": "error_ratio", "comparator": "gt", "threshold": 0.05,
  "window": "5m", "duration_seconds": 120, "resolve_after": 3,
  "severity": "high", "guidance": "Check recent deployments and upstream dependencies." }
// anomaly rule (Should)
{ "target_id": "…", "name": "Latency anomaly", "type": "anomaly",
  "metric": "latency_p95", "params": { "baseline_points": 60, "z_threshold": 3, "consecutive": 3 },
  "severity": "medium" }
// absence rule
{ "target_id": "…", "name": "No data", "type": "absence", "metric": "data_absent",
  "duration_seconds": 300, "severity": "high" }
```

```jsonc
// GET /alerts/{id}
{ "id": "…", "rule_id": "…", "target_id": "…", "status": "firing", "severity": "high",
  "first_seen_at": "2026-10-13T09:40:00Z", "last_seen_at": "2026-10-13T09:42:30Z", "occurrence_count": 6,
  "evidence": { "query": "<PromQL template name and rendered query>", "observed_value": 0.12,
                "threshold": 0.05, "window": "5m", "guidance": "Check recent deployments and upstream dependencies." },
  "acknowledged_by": null, "resolved_at": null }

// GET /alerts/{id}/deliveries (Viewer+)
// Channel names are projected for maintainers and admins, and masked to null for viewers.
[
  {
    "id": "d13e9a55-b045-4df3-a55e-04d306b38c29",
    "channel_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "channel_name": "Operations Slack",
    "event": "firing",
    "status": "delivered",
    "http_status": 200,
    "error": null,
    "attempted_at": "2026-10-24T12:00:05Z"
  }
]
```

`GET /alerts?limit=<1..100, default 50>&cursor=<opaque>[&project_id=<uuid>][&target_id=<uuid>][&status=<firing|acknowledged|resolved>][&severity=<critical|high|medium|low|info>]`

- **Filters:** `project_id`, `target_id`, `status`, and `severity` combine with `AND`. Unknown/non-existent `project_id` or `target_id` returns `200` with `items: []` (global collection filter). Malformed UUID, out-of-range `limit`, and invalid enum values return `422 VALIDATION_ERROR`. `status` and `severity` may be repeated (e.g. `?status=firing&status=acknowledged`).
- **Pagination & Sorting:** Ordered by newest `last_seen_at DESC, id DESC`. Next page cursor is opaque base64 encoding `(last_seen_at, id)`. Fetching `limit + 1` rows ensures `next_cursor` is null on the final page. *Trade-off:* because `last_seen_at` updates when a firing alert re-breaches, an active alert's occurrence bump moves it to the top of subsequent queries during active pagination.
- **Lifecycle & Archived Projects:** Alerts follow `firing → acknowledged → resolved`. Illegal transitions return `409 INVALID_TRANSITION`. Acknowledging an alert on an archived project returns `409 CONFLICT` (`Cannot acknowledge alert in an archived project`), whereas manual resolution (`POST /alerts/{id}/resolve`) is permitted on archived projects for operational cleanup of stuck firing alerts. Alerts of archived projects remain readable via `GET /alerts`.


### 5.6 Scans, jobs, dependencies

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| POST | `/projects/{project_id}/scans` | M | Start scan `{ref?, providers?}` | `202` |
| GET | `/projects/{project_id}/scans` | V | List scans (newest first) | `200` |
| GET | `/scans/{scan_id}` | V | Detail with provider runs and summary | `200` |
| GET | `/scans/{scan_id}/dependencies` | V | Inventory; filters `ecosystem`, `scope`, `q` | `200` |
| GET | `/jobs/{job_id}` | V | Job status | `200` |
| POST | `/jobs/{job_id}/cancel` | M | Cooperative cancel | `202` |

```jsonc
// POST /projects/{id}/scans  body (all optional)
{ "ref": "main", "providers": ["trivy", "osv", "registry", "semgrep"] }
// 202
{ "scan": { "id": "a1c2…", "status": "queued", "ref": "main" },
  "job":  { "id": "0b8f…", "type": "scan", "status": "queued" } }
// GET /scans/{id} (200, after completion)
{ "id": "a1c2…", "project_id": "…", "status": "partial", "ref": "main",
  "commit_sha": "<40-hex>", "started_at": "…", "finished_at": "…",
  "providers": [
    { "name": "trivy",    "status": "ok",     "duration_ms": 41200, "error": null },
    { "name": "osv",      "status": "failed", "duration_ms": 30000, "error": "timeout after 30000 ms" },
    { "name": "registry", "status": "ok",     "duration_ms": 8100,  "error": null },
    { "name": "semgrep",  "status": "ok",     "duration_ms": 52000, "error": null } ],
  "summary": { "dependencies": 312,
               "new": 2, "unchanged": 14, "resolved": 1,
               "by_type_severity": { "dependency_vulnerability": { "high": 2, "medium": 1 } } } }
```

Validation: `ref` must match `^[A-Za-z0-9._/-]{1,200}$` and must not contain `..` or start with `-`. Only one non-terminal scan per project at a time (`409 CONFLICT` otherwise).

### 5.7 Findings

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| GET | `/projects/{project_id}/findings` | V | Filters: `type`, `severity`, `status`, `scan_id`, `package`, `path`, `change` (`new\|unchanged\|resolved`), `q`; sort: `severity`, `first_seen_at`, `last_seen_at` | `200` |
| GET | `/findings/{finding_id}` | V | Detail with evidence and history | `200` |
| PATCH | `/findings/{finding_id}` | M | Triage `{status: "dismissed"\|"open", dismissal_reason?, note?}` | `200` |

```jsonc
// GET /findings/{id}
{ "id": "…", "project_id": "…", "type": "dependency_vulnerability",
  "severity": "high", "severity_source": "osv", "status": "open", "fingerprint": "<sha256-hex>",
  "title": "example-pkg@1.2.3 is affected by <ADVISORY-ID>",
  "subject": { "ecosystem": "npm", "name": "example-pkg", "version": "1.2.3", "scope": "transitive",
               "manifest_path": "package-lock.json" },
  "advisory": { "ids": ["<GHSA-or-CVE-id>"], "fixed_versions": ["1.2.9"], "references": ["https://osv.dev/…"] },
  "sources": ["trivy", "osv"],
  "evidence": [{ "id": "ev-1", "kind": "advisory_record", "source": "osv", "url": "https://osv.dev/…", "retrieved_at": "…" }],
  "first_seen_scan_id": "…", "last_seen_scan_id": "…", "change": "unchanged" }
```

Finding `type` ∈ `dependency_vulnerability`, `dependency_outdated`, `dependency_incompatibility`, `code_issue`. `severity` ∈ `critical, high, medium, low, info`, or `null` if unrated. `status` ∈ `open, dismissed, resolved` (`resolved` is system-set when absent from the newest completed scan). `dismissal_reason` ∈ `false_positive, accepted_risk, wont_fix` and is required when dismissing.

### 5.8 AI recommendations

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| POST | `/findings/{finding_id}/recommendations` | M | Request `{kind}` | `202` |
| GET | `/findings/{finding_id}/recommendations` | V | List for a finding | `200` |
| GET | `/recommendations/{recommendation_id}` | V | Detail | `200` |
| POST | `/recommendations/{recommendation_id}/feedback` | M | `{rating: "helpful"\|"not_helpful", comment?}` | `204` |

`kind` ∈ `library_alternative`, `upgrade_guidance`, `code_improvement`. Allowed combinations: vulnerability/outdated/incompatibility findings → `library_alternative`, `upgrade_guidance`; `code_issue` → `code_improvement`; otherwise `422`.

```jsonc
// GET /recommendations/{id} (200)
{ "id": "…", "finding_id": "…", "kind": "upgrade_guidance",
  "status": "completed", "validation_status": "partially_validated",
  "model": "<value of CLAUDE_MODEL>",
  "summary": "…",
  "claims": [
    { "claim_id": "c1", "type": "fixed_version", "text": "Upgrade to 1.2.9 resolves the advisory.",
      "evidence_refs": ["ev-1"], "validation": "supported", "validation_note": "Matches advisory fixed range." },
    { "claim_id": "c2", "type": "compatibility", "text": "No breaking changes expected.",
      "evidence_refs": [], "validation": "unsupported", "validation_note": "No evidence reference provided." } ],
  "alternatives": [],
  "suggested_steps": ["Update the lockfile through a reviewed fix proposal."],
  "proposed_patch": null,
  "confidence": "medium",
  "limitations": ["Reachability of the vulnerable code path was not analyzed."],
  "evidence": [{ "id": "ev-1", "kind": "advisory_record", "source": "osv", "url": "https://osv.dev/…", "retrieved_at": "…" }],
  "usage": { "input_tokens": 0, "output_tokens": 0 },
  "created_at": "…" }
```

`validation_status` ∈ `validated`, `partially_validated`, `rejected`. `claims[].validation` ∈ `supported, unsupported, unverifiable`. `confidence` is the model's qualitative statement, capped by validation outcome; it is **not** a calibrated probability. Unsupported claims are returned but flagged and visually de-emphasized by the UI. Errors: `409 AI_DISABLED`, `429 AI_BUDGET_EXCEEDED`.

### 5.9 Fix proposals

| Method | Path | Min role | Description | Success |
|---|---|---|---|---|
| POST | `/projects/{project_id}/fix-proposals` | M | Create from `{finding_ids: [uuid, …≤ 20]}` | `202` |
| GET | `/projects/{project_id}/fix-proposals` | V | List | `200` |
| GET | `/fix-proposals/{proposal_id}` | V | Detail incl. diff and validation | `200` |
| POST | `/fix-proposals/{proposal_id}/approve` | M | Approve and start PR creation | `202` |
| POST | `/fix-proposals/{proposal_id}/reject` | M | Reject `{reason?}` | `200` |
| POST | `/fix-proposals/{proposal_id}/cleanup` | M | Close PR and delete the Toolkit-created branch (Should) | `202` |

```jsonc
// GET /fix-proposals/{id}
{ "id": "…", "project_id": "…", "status": "ready",
  "finding_ids": ["…"], "base_commit_sha": "<40-hex>",
  "changes": [{ "ecosystem": "npm", "package": "example-pkg", "from_version": "1.2.3", "to_version": "1.2.9",
                "bump": "patch", "manifest_path": "package.json", "lockfile_path": "package-lock.json" }],
  "has_major_bump": false,
  "diff": "diff --git a/package-lock.json b/package-lock.json\n…",
  "validation": {
    "result": "passed",
    "baseline":    { "status": "passed", "exit_code": 0, "duration_s": 42, "output_tail": "…" },
    "post_change": { "status": "passed", "exit_code": 0, "duration_s": 44, "output_tail": "…" },
    "delta_scan":  { "resolved_finding_ids": ["…"], "new_findings": [] } },
  "risk_notes": ["Transitive dependency updated; lockfile-only change."],
  "approval": null, "pull_request": null, "created_at": "…" }
// POST /fix-proposals/{id}/approve
{ "acknowledge_unverified": false, "acknowledge_breaking_change": false, "comment": "Reviewed diff." }
// 202
{ "proposal": { "id": "…", "status": "approved" }, "job": { "id": "…", "type": "pr_creation", "status": "queued" } }
// later: GET /fix-proposals/{id} → pull_request
{ "pull_request": { "number": 12, "url": "https://github.com/example-org/example-repo/pull/12",
                    "draft": true, "branch": "toolkit/fix/<proposal-id>" } }
```

Rules: `validation.result` ∈ `passed, failed, unverified, not_run`. Approval requirements follow the matrix in [WORKFLOW §WF-06](WORKFLOW.md#wf-06-fix-proposal-approval-and-draft-pr). Approving without a required acknowledgment → `409 ACK_REQUIRED`; approving a proposal not in `ready` → `409 INVALID_TRANSITION`; approving as non-admin when `result = failed` → `403 FORBIDDEN`. If remediation is disabled → `409 REMEDIATION_DISABLED`. The API exposes **no** endpoint that merges a PR.

### 5.10 Audit log and operations

| Method | Path | Min role | Description |
|---|---|---|---|
| GET | `/audit-log` | A | Filters `actor_id`, `action`, `from`, `to` (Should, FR-AUTH-04) |
| GET | `/health` | public | Liveness: process is up |
| GET | `/ready` | public | Readiness: DB reachable; Prometheus and sandbox reported as `ok`/`degraded` |
| GET | `/metrics` | internal | Prometheus metrics of `api` and `worker` (NFR-REL-03) |

## 6. Validation rules

| Field | Rule |
|---|---|
| `email` | RFC-style address, ≤ 254 chars, case-insensitive uniqueness |
| `password` | 12–128 chars **[P]** |
| `project.name` | 1–100 chars, unique among non-archived projects; `description` ≤ 1,000 |
| `repository.url` | `^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?$` |
| `repository.token` | ≤ 255 chars; write-only |
| `target.service_name` | `^[A-Za-z0-9_.:-]{1,100}$`; unique per project+environment |
| `target.environment` | `^[a-z0-9-]{1,50}$` |
| `rule.window` | one of `1m, 5m, 15m` |
| `rule.duration_seconds` | between `ALERT_EVAL_INTERVAL_SECONDS` and 86,400 |
| `rule.threshold` | `error_ratio`: 0–1; `latency_p95`: > 0 and ≤ 600 (seconds); `request_rate`: ≥ 0 |
| `rule.params.z_threshold` | 1–10; `consecutive` 1–20; `baseline_points` 10–1,440 |
| `webhook.url` | `https` only by default; host must not resolve to private, loopback, or link-local ranges unless an admin sets an explicit allow flag (NFR-SEC-09) |
| `scan.ref` | see §5.6 |
| `finding_ids` | 1–20 UUIDs belonging to the same project, all of type `dependency_vulnerability` or `dependency_outdated` (and `dependency_incompatibility` only for upgrade plans) |
| `limit` | 1–100 |

## 7. Role–endpoint summary (test oracle for FR-AUTH-03)

| Capability | viewer | maintainer | admin |
|---|---|---|---|
| Read projects, targets, metrics, alerts, scans, findings, recommendations, proposals | ✔ | ✔ | ✔ |
| Create/modify projects, repository, targets, rules; ack/resolve alerts | ✖ | ✔ | ✔ |
| Trigger scans, AI jobs, fix proposals; approve/reject proposals | ✖ | ✔ | ✔ |
| Approve a proposal with `validation.result = failed` | ✖ | ✖ | ✔ |
| Manage users, notification channels, view audit log | ✖ | ✖ | ✔ |

## 8. Rate limits and quotas

| Scope | Limit (proposed) |
|---|---|
| `POST /auth/login` | 5 failures per 15 min per account + IP (NFR-SEC-04) |
| AI jobs | `AI_DAILY_REQUEST_CAP` per deployment per UTC day (FR-AI-10) |
| Scan creation | 1 active scan per project |
| General API | No global limit in MVP; reverse proxy may add one |
