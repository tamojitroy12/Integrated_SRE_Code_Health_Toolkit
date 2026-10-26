# Workflows

> **Doc:** WORKFLOW.md · **Version:** 0.1 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** [FRD](FRD.md), [ARCHITECTURE](ARCHITECTURE.md), [API_SPEC](API_SPEC.md)

Workflow IDs (`WF-nn`) describe end-to-end behavior. The three product flows are separate and converge only in the dashboard (WF-07):

| ID | Workflow | Kind |
|---|---|---|
| WF-01 | Project onboarding (repository + monitoring target) | Interactive + async verification |
| WF-02 | Live telemetry collection | Continuous, push |
| WF-03 | Alert evaluation, notification, and lifecycle | Continuous loop |
| WF-04 | Repository scan (dependencies + static analysis) | Async job |
| WF-05 | AI-assisted recommendation | Async job |
| WF-06 | Fix proposal, approval, and draft PR | Async jobs + human gate |
| WF-07 | Convergence in the unified dashboard | Read-only composition |

## WF-01 Project onboarding

```mermaid
flowchart TD
    A["Maintainer creates project"] --> B{"Add repository?"}
    B -->|"yes"| C["POST repository: URL and optional token"]
    C --> D{"API verifies access and detects manifests"}
    D -->|"ok"| E["Repository stored: token encrypted, ecosystems set"]
    D -->|"fail"| F["Error REPO_ACCESS_DENIED or REPO_NOT_FOUND, nothing stored"]
    B -->|"no"| G{"Add monitoring target?"}
    E --> G
    G -->|"yes"| H["POST monitoring target: service_name, environment"]
    H --> I["Dashboard shows OTel env var snippet"]
    I --> J["User configures the app and deploys"]
    J --> K{"Samples received?"}
    K -->|"yes"| L["Status: receiving"]
    K -->|"no, within stale window"| M["Status: waiting for data, show troubleshooting"]
    G -->|"no"| N["Project exists with nothing connected: empty states shown"]
    L --> O["Project overview"]
    M --> O
    N --> O
```

**Rules.** A project may have a repository, targets, both, or neither (FR-PRJ-05). Tokens are write-only. Verification does not clone the repository; it calls GitHub metadata and contents endpoints with a 10-second timeout.

## WF-02 Live telemetry collection

```mermaid
sequenceDiagram
    participant App as Monitored app (OTel SDK)
    participant Col as OTel Collector
    participant Prom as Prometheus
    participant Eng as Monitoring Engine
    participant DB as PostgreSQL
    App->>Col: OTLP metrics with bearer token
    alt token invalid
        Col-->>App: rejected, nothing stored
    else token valid
        Col->>Prom: forward metrics (remote write)
    end
    loop every ALERT_EVAL_INTERVAL_SECONDS
        Eng->>Prom: allowlisted PromQL per target
        Prom-->>Eng: samples or empty result
        Eng->>DB: update target last_seen_at and status
    end
```

**Scope note.** Only metrics are collected. Target status is derived from the presence of recent samples for the target's `service_name`; it does not mean the application is healthy.

## WF-03 Alert evaluation, notification, and lifecycle

```mermaid
flowchart TD
    S["Evaluation tick"] --> Q["For each enabled rule and target: run allowlisted PromQL"]
    Q --> R{"Query succeeded?"}
    R -->|"no"| E1["Record evaluation_error, do not change alert state"]
    R -->|"yes"| V{"Condition violated?"}
    V -->|"yes"| C1["Increment consecutive breach counter"]
    C1 --> C2{"Breaches at least N and no open alert for rule+target?"}
    C2 -->|"yes"| F1["Create alert: firing, with evidence snapshot"]
    F1 --> N1["Send notifications, record deliveries"]
    C2 -->|"alert already open"| U1["Update last_seen_at and occurrence_count"]
    C2 -->|"not yet N"| W1["Wait"]
    V -->|"no"| D1["Increment consecutive clear counter, reset breach counter"]
    D1 --> D2{"Clear count at least resolve_after and alert open?"}
    D2 -->|"yes"| X1["Alert resolved automatically, notify resolved"]
    D2 -->|"no"| W2["Wait"]
```

```mermaid
stateDiagram-v2
    [*] --> firing
    firing --> acknowledged: user acknowledges
    firing --> resolved: auto-resolve or user resolves
    acknowledged --> resolved: auto-resolve or user resolves
    resolved --> [*]
```

**Evidence snapshot (FR-ALR-04):** PromQL used, observed value, threshold, evaluation window, guidance text. Illegal transitions return `409 INVALID_TRANSITION`. A new breach after `resolved` creates a **new** alert.

## WF-04 Repository scan

```mermaid
sequenceDiagram
    actor U as Maintainer
    participant API as api
    participant DB as PostgreSQL
    participant W as worker
    participant GH as GitHub
    participant T as Trivy
    participant O as OSV API
    participant R as Registries
    participant S as Semgrep
    U->>API: POST /projects/{id}/scans
    API->>DB: insert scan and job (queued)
    API-->>U: 202 with scan_id and job_id
    W->>DB: claim job (lease)
    W->>GH: shallow clone of ref, resolve commit SHA
    par Dependency inventory and vulnerabilities
        W->>T: filesystem scan (JSON)
        W->>O: batch query then fetch records by ID
        W->>R: latest version, license, deprecation
    and Static analysis
        W->>S: scan with default rules (JSON)
    end
    W->>W: normalize, merge by alias set, fingerprint
    W->>DB: store dependencies, findings, evidence, provider runs
    W->>DB: compare with previous scan (new, unchanged, resolved)
    W->>DB: scan status succeeded or partial, delete workspace
    U->>API: GET /scans/{id} (polling)
    API-->>U: status and summary
```

**Failure handling.** Each provider run is recorded (`ok`, `failed`, `skipped`) with an error summary. If any provider is `failed`, the scan ends `partial`; if the clone fails or the timeout is hit, `failed`. The UI never presents `partial` as a clean result (FR-DEP-07). Repository content is read-only data in this workflow; no repository code is executed.

## WF-05 AI-assisted recommendation

```mermaid
sequenceDiagram
    actor U as Maintainer
    participant API as api
    participant W as worker
    participant DB as PostgreSQL
    participant R as Registries
    participant C as Claude API
    U->>API: POST /findings/{id}/recommendations (kind)
    API->>API: check AI_ENABLED, daily cap, role
    API->>DB: insert recommendation (pending) and job
    API-->>U: 202
    W->>DB: load finding, advisory data, bounded snippet
    W->>R: fetch package metadata (for evidence)
    W->>W: build evidence pack, redact secrets, assign evidence IDs
    W->>C: instructions + delimited untrusted data + JSON schema
    C-->>W: structured JSON with evidence_refs
    W->>W: validate schema, evidence IDs, package/version existence, advisory consistency
    opt proposed patch present
        W->>W: git apply --check in sandbox
    end
    W->>DB: store recommendation with validation_status and per-claim results
    U->>API: GET /recommendations/{id}
    API-->>U: content, evidence, badge, limitations
```

**Decision rule.** `validated` requires every check to pass; any unsupported claim yields `partially_validated` (supported claims shown, unsupported hidden behind a warning) or `rejected` (all claims unsupported or schema failure after one repair attempt). The model has no tools and cannot trigger any action.

## WF-06 Fix proposal, approval, and draft PR

```mermaid
flowchart TD
    A["Maintainer selects dependency findings"] --> B["POST fix proposal (202)"]
    B --> C["Worker builds deterministic change plan"]
    C --> D{"Plan valid? (fixed version known, ecosystem supported, args pass validators)"}
    D -->|"no"| X1["Proposal failed with reason"]
    D -->|"yes"| E["Start sandbox: clone workspace"]
    E --> F["Baseline: install with scripts disabled, then run tests with network off"]
    F --> G["Apply change: lockfile-only resolution, scripts disabled"]
    G --> H{"Diff touches only manifest and lockfile paths?"}
    H -->|"no"| X2["Abort: DIFF_SCOPE_VIOLATION"]
    H -->|"yes"| I["Post-change tests with network off"]
    I --> J["Re-scan resulting lockfile (delta)"]
    J --> K["Compute validation_result: passed, failed, or unverified"]
    K --> L["Status ready: diff, report, risk notes shown"]
    L --> M{"Maintainer decision"}
    M -->|"reject"| Y1["Proposal rejected"]
    M -->|"approve (with acknowledgments if required)"| N["Approval recorded: user, time, acknowledgments"]
    N --> O["PR job: push toolkit/fix/id branch, open draft PR"]
    O --> P["Status pr_opened: link shown"]
    P --> Q["Human reviews and merges on GitHub (outside the Toolkit)"]
```

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> validating: worker claims
    pending --> failed: plan invalid
    validating --> ready: stages completed
    validating --> failed: sandbox or scope error
    ready --> approved: maintainer approves
    ready --> rejected: maintainer rejects
    approved --> pr_opened: PR created
    approved --> failed: GitHub error
    ready --> superseded: newer proposal for same findings
    pr_opened --> [*]
    rejected --> [*]
    failed --> [*]
    superseded --> [*]
```

**Approval gates (FR-REM-06, FR-REM-09, FR-REM-12).**

| `validation_result` | Major upgrade? | Approval possible? |
|---|---|---|
| `passed` | no | `maintainer` or `admin` |
| `passed` | yes | needs `acknowledge_breaking_change = true` |
| `unverified` (no or failing baseline tests) | any | needs `acknowledge_unverified = true` |
| `failed` | any | `admin` only, override recorded in audit log |

**Safety invariants:** only branch names starting with `toolkit/fix/` are accepted by COMP-10; draft PR only; no merge call exists in the adapter interface; the approval row must exist before the PR job starts.

**Rollback considerations.** The proposal stores the base commit SHA. Because the change is delivered as a PR, rollback before merge means closing the PR (FR-REM-10 can close it and delete the Toolkit-created branch). After a merge, rollback is a normal `git revert` performed by the team; the PR description includes the revert hint.

## WF-07 Convergence in the unified dashboard

```mermaid
flowchart LR
    U["User opens project overview"] --> A["GET /projects/{id}/overview"]
    A --> B["PostgreSQL: open alerts, latest scan, top findings, open proposals"]
    A --> C["Prometheus: current request rate, error ratio, p95, target status"]
    B --> D["Compose response with per-section status: ok, empty, or error"]
    C --> D
    D --> E["Render monitoring card, alerts card, scan card, findings card"]
    E --> F["User drills into alert, finding, recommendation, or proposal"]
```

**Rule:** each overview section reports its own status (`ok`, `empty`, `error`) so that a Prometheus outage cannot hide scan results, and vice versa (NFR-REL-05).

## Job lifecycle (all asynchronous work)

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: claimed with lease
    running --> succeeded
    running --> partial: some providers failed
    running --> failed: error or attempts exhausted
    running --> queued: lease expired, attempts below 3
    queued --> cancelled: user cancels
    running --> cancelled: user cancels
    succeeded --> [*]
    partial --> [*]
    failed --> [*]
    cancelled --> [*]
```

`partial` applies to scan jobs only. Job types: `scan`, `recommendation`, `fix_proposal`, `pr_creation`. Cancellation is cooperative: the worker checks the flag between stages and terminates sandbox containers it started.

## Error paths summary

| Situation | System behavior | User sees |
|---|---|---|
| Repo token lacks permission for push | PR job fails; proposal returns to `approved` with `pr_error` | Message naming the missing permission class, retry button |
| Registry returns 429/5xx | Retry with backoff; then provider `failed` | `partial` scan with provider list |
| Claude returns invalid JSON twice | Recommendation `rejected` (`SCHEMA_INVALID`) | "AI output could not be validated" with raw output hidden by default |
| Sandbox test command missing | `validation_result = unverified` | Warning + acknowledgment checkbox |
| Alert webhook returns non-2xx | Delivery `failed`, retried per cooldown policy | Delivery status on alert detail |
