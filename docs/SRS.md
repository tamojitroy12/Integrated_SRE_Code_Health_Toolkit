# Software Requirements Specification (SRS)

> **Doc:** SRS.md · **Version:** 0.1 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** [PRD](PRD.md), [FRD](FRD.md), [ARCHITECTURE](ARCHITECTURE.md), [TRD](TRD.md)

## 1. Purpose and scope

This SRS specifies the system-level requirements of the Integrated SRE + Code Health Toolkit: constraints, external interfaces, non-functional requirements, and the traceability matrix. **Functional requirements are owned by the [FRD](FRD.md)** and are incorporated here by reference to avoid duplicate, diverging text. Together the FRD and SRS form the requirements baseline.

Scope boundaries: see [PRD §6](PRD.md#6-mvp-scope). Terms: `GLOSSARY.md` (batch 2).

## 2. Identifier scheme

| Prefix | Meaning | Owner |
|---|---|---|
| `G-`, `SM-`, `P-` | Goals, success metrics, personas | PRD |
| `US-`, `UC-`, `FR-<AREA>-nn` | Stories, use cases, functional requirements | FRD |
| `NFR-<CAT>-nn`, `IF-nn`, `CON-nn`, `AS-nn` | Non-functional, interface, constraint, assumption | SRS |
| `COMP-nn`, `EXT-nn` | Internal component, external system | ARCHITECTURE |
| `EP-nn` | Implementation epic | SRS §9 |
| `DEC-nnn`, `UD-nn` | Decision, unresolved decision | DECISIONS (batch 2) |
| `AT-<FR-ID>` | Acceptance test for an FR | TEST_STRATEGY (batch 2) |

## 3. Overall description

### 3.1 Product perspective

The Toolkit is a self-hosted web application with background workers. It consumes telemetry from monitored applications (**EXT-01**) and source code from GitHub (**EXT-04**), uses public advisory and registry data (**EXT-02**, **EXT-03**), and optionally calls the Anthropic API (**EXT-05**). Context diagram: [ARCHITECTURE §2](ARCHITECTURE.md#2-system-context).

### 3.2 User classes

`admin`, `maintainer`, `viewer` (see [FRD §1](FRD.md#1-roles)).

### 3.3 Operating environment

Linux containers orchestrated by Docker Compose; developer machines on Linux, macOS, or Windows with WSL2 **[A]**. Browser support: current releases of Chromium-based browsers, Firefox, and Safari **[A]**.

### 3.4 Constraints

| ID | Constraint |
|---|---|
| CON-01 | Only open-source components may be required for core functionality; Claude API usage is optional (`AI_ENABLED`). |
| CON-02 | MVP ecosystems: npm and PyPI only (DEC-012). Git host: GitHub only (DEC-009). |
| CON-03 | MVP telemetry: OpenTelemetry **metrics** only (DEC-004). |
| CON-04 | Single-tenant deployment; global roles (DEC-013, DEC-014). |
| CON-05 | LLM output is advisory data. It shall not be executed, and it shall not authorize any write to a remote repository. |
| CON-06 | Code from scanned repositories shall be executed **only** inside the sandbox (COMP-14), never in the API or worker process. |
| CON-07 | Browser clients never receive third-party secrets (repository tokens, API keys, ingest token unless the admin requests it). |
| CON-08 | Semgrep-maintained rules are subject to Semgrep Rules License v.1.0, which restricts use in competing products/SaaS **[V]**; the Toolkit is distributed for self-hosted internal use pending UD-01. |
| CON-09 | Outbound network access from API/worker is limited to an allowlist (OSV, registries, GitHub, Anthropic, Trivy DB source, configured webhooks/SMTP). |
| CON-10 | The project is delivered by a student team with limited time; features beyond the Must list are not committed (see [PRD §7](PRD.md#7-feasibility-assessment-team-estimates-a)). |

### 3.5 Assumptions

| ID | Assumption | Impact if false |
|---|---|---|
| AS-01 | Monitored apps can be instrumented with standard OpenTelemetry SDKs/env vars and emit HTTP server metrics. | Charts empty; fall back to Prometheus scrape mode (FR-MON-06). |
| AS-02 | Target repositories have a runnable test command. | Fix proposals become `unverified` (FR-REM-12). |
| AS-03 | A dedicated, isolated container runtime can be provisioned on team machines (UD-03). | Remediation limited to proposal-only (no execution) or deferred. |
| AS-04 | Public APIs (OSV, registries, GitHub, Anthropic) stay available and keep documented behavior during the term. | Provider `failed` states; demo uses cached fixtures. |
| AS-05 | Team has 4 members for 14 weeks at f = 0.4, capacity 112 person-days (DEC-016 / UD-08 resolved). | Re-scoped per `ROADMAP.md` §5 cut ladder (prioritize npm, defer PyPI remediation). |

## 4. External interface requirements

| ID | Interface | Direction | Protocol / format | Requirement |
|---|---|---|---|---|
| IF-01 | OTLP ingestion (COMP-12) | EXT-01 → Toolkit | OTLP/HTTP (port 4318) and OTLP/gRPC (4317); bearer token | Reject unauthenticated requests (FR-MON-01). |
| IF-02 | Prometheus HTTP API (COMP-13) | API/worker → Prometheus | HTTP JSON (`query`, `query_range`) | Queries built only from allowlisted templates; no user-supplied raw PromQL in MVP. |
| IF-03 | OSV API (EXT-02) | worker → OSV | HTTPS JSON: batch query, then fetch full records by ID, with pagination handling **[V]** | Timeouts, retries with backoff, bounded parallelism. |
| IF-04 | Package registries (EXT-03) | worker → npm / PyPI | HTTPS JSON metadata **[A: endpoints verified at EP-05 start]** | Used for latest version, release date, license, deprecation, runtime constraints, and package existence checks. |
| IF-05 | GitHub REST API (EXT-04) | API/worker → GitHub | HTTPS JSON; fine-grained PAT | Operations limited to: read repo metadata, clone, create branch/ref, create/close draft PR, delete own branch. |
| IF-06 | Anthropic Messages API (EXT-05) | worker → Anthropic | HTTPS JSON via official SDK | Optional; structured output; evidence pack only. |
| IF-07 | Trivy CLI | worker → subprocess | CLI with JSON output | Fixed argument vector; timeout; stderr captured. |
| IF-08 | Semgrep CLI | worker → subprocess | CLI with JSON output; telemetry/metrics disabled | Fixed argument vector; timeout; file-size cap. |
| IF-09 | Sandbox container API (COMP-14) | worker → isolated Docker daemon | Docker Engine API over an internal network | Never the host Docker socket (CON-06, UD-03). |
| IF-10 | Notification endpoints (EXT-06) | Toolkit → webhook / SMTP | HTTPS JSON; SMTP | URL validation and SSRF protection (NFR-SEC-09). |
| IF-11 | Northbound REST API | web / scripts → api | HTTPS JSON under `/api/v1` | Defined in [API_SPEC](API_SPEC.md); OpenAPI generated from code must match it. |
| IF-12 | Browser UI | user → web | HTTPS | Responsive down to 1024 px width for MVP **[A]**. |

No dedicated hardware interfaces exist.

## 5. Functional requirements (by reference)

70 requirements across nine areas are defined in the [FRD](FRD.md): AUTH (4), PRJ (6), MON (8), ALR (8), DEP (9), SAST (4), AI (11), REM (12), DSH (8).

## 6. Non-functional requirements

"Target" values are design targets to be measured during acceptance testing; they are not claimed results. Reference environment for performance targets: 4 vCPU, 8 GB RAM, SSD, all services on one host **[A]**.

| ID | Requirement | Verification | Pri |
|---|---|---|---|
| NFR-PERF-01 | Read endpoints (excluding range queries > 24 h) respond with p95 ≤ 500 ms with 10,000 stored findings. | Load test script | M |
| NFR-PERF-02 | A scan of ≤ 500 dependencies and ≤ 50,000 lines of code completes within 10 minutes, excluding the first scanner-database download. | Timed scan of fixture repo | M |
| NFR-PERF-03 | Project overview loads within 3 s (median of 10 loads) on a local network with seeded data. | Browser performance test | S |
| NFR-PERF-04 | Alert detection time satisfies \( T_{detect} \le T_{ingest} + N \cdot \Delta_{eval} \) (definitions in [TRD §6.2](TRD.md#62-anomaly-and-alert-timing)). | Fault injection (SM-03) | M |
| NFR-REL-01 | Queued jobs survive process restarts. Running jobs hold a lease; if it expires the job is requeued, up to 3 attempts, then `failed`. | Kill-worker test | M |
| NFR-REL-02 | Failure of one scan provider does not abort other providers (FR-DEP-07). | Fault injection | M |
| NFR-REL-03 | `api` and `worker` expose liveness/readiness endpoints and Prometheus metrics about themselves. | Endpoint tests | M |
| NFR-REL-04 | Re-processing a scan job does not create duplicate findings (unique `(scan_id, fingerprint)`). | Idempotency test | M |
| NFR-REL-05 | If Prometheus is unavailable, monitoring views show an error state while scanning, findings, and AI continue to work; the reverse also holds. | Chaos test (stop container) | M |
| NFR-SEC-01 | Passwords hashed with Argon2id; access tokens ≤ 15 minutes; refresh sessions ≤ 7 days and revocable **[P]**. | Unit + integration tests | M |
| NFR-SEC-02 | Repository tokens and API keys are encrypted at rest or supplied only via environment; never logged, never returned by the API. | Log/response scanning test | M |
| NFR-SEC-03 | In `production` mode the deployment requires TLS termination and secure cookie flags. | Config check | M |
| NFR-SEC-04 | Login attempts are rate-limited (proposed: 5 failures per 15 minutes per account and IP). | Integration test | S |
| NFR-SEC-05 | Sandbox containers run non-root, unprivileged, with CPU/memory/time limits and a default seccomp profile; network is disabled during test execution. | Sandbox escape-attempt checklist | M |
| NFR-SEC-06 | All inputs validated by schemas; subprocess arguments built from allowlisted fragments, never by shell string interpolation. | Static analysis + fuzz test | M |
| NFR-SEC-07 | The Toolkit's own CI scans its dependencies (Trivy) and source (Semgrep) and fails on `critical` findings. | CI configuration | S |
| NFR-SEC-08 | Logs redact tokens, passwords, and `Authorization` headers. | Log review test | M |
| NFR-SEC-09 | Outbound requests from API/worker go only to allowlisted hosts; webhook URLs reject private/loopback ranges unless an admin explicitly permits them. | SSRF test cases | M |
| NFR-AI-01 | A recommendation is labeled `validated` only if every automated check in FR-AI-04 passes. | Golden-set audit (SM-06) | M |
| NFR-AI-02 | Only the evidence pack and fixed instructions are sent to the model; no full repository or credentials. | Request-body inspection test | M |
| NFR-USA-01 | A first-time user completes onboarding (UC-01) in ≤ 10 minutes using the README (SM-01). | Usability session | M |
| NFR-USA-02 | Primary flows are keyboard-operable and use sufficient colour contrast (target: WCAG 2.1 AA) **[A]**. | Manual checklist + automated a11y lint | S |
| NFR-MNT-01 | Backend core modules (scanning, alerting, AI validation, remediation) reach ≥ 70 % line coverage; CI runs lint and type checks. | CI report | M |
| NFR-MNT-02 | OpenAPI generated from code matches [API_SPEC](API_SPEC.md) (contract test). | CI contract test | S |
| NFR-OBS-01 | Logs are structured JSON with `request_id` or `job_id`. | Log schema test | M |
| NFR-OBS-02 | Job counts, durations, and failures per type are exported as metrics. | Metrics endpoint test | S |
| NFR-PORT-01 | `docker compose up` brings up the stack on Linux, macOS, and Windows with WSL2 **[A]**. | Fresh-machine run | M |
| NFR-DATA-01 | Retention periods are configurable with defaults in [DATA_MODEL §7](DATA_MODEL.md#7-retention). | Retention job test | S |
| NFR-DATA-02 | A documented backup/restore procedure exists for PostgreSQL. | Restore drill | S |
| NFR-LIC-01 | A license inventory of direct dependencies is maintained; incompatible licenses are flagged (UD-01). | CI license report | S |
| NFR-CAP-01 | Design envelope: ≤ 20 projects, ≤ 50 monitoring targets, ≤ 5 concurrent jobs per deployment. Larger loads are unsupported, not guaranteed. | Stated limit | M |

## 7. Data requirements

Entities, schemas, retention, and sensitive-data handling are specified in [DATA_MODEL](DATA_MODEL.md). Time-series data lives only in Prometheus; relational data lives only in PostgreSQL.

## 8. Quality attribute priorities

1. Safety of automated changes (SM-07) over feature breadth.
2. Honest reporting (partial results, `unverified`, rejected AI output) over appearing complete.
3. Simplicity of deployment and implementation over scalability.

## 9. Epics

| Epic | Name | FR areas |
|---|---|---|
| EP-01 | Platform foundation (repo, CI, Compose, DB, auth, jobs framework) | AUTH |
| EP-02 | Projects and onboarding | PRJ |
| EP-03 | Telemetry ingestion and monitoring views | MON |
| EP-04 | Alerting and notifications | ALR |
| EP-05 | Dependency scanning | DEP |
| EP-06 | Static analysis | SAST |
| EP-07 | Unified dashboard and findings | DSH |
| EP-08 | AI recommendations | AI |
| EP-09 | Automated remediation | REM |
| EP-10 | Hardening, documentation, demo | NFR-* |

## 10. Traceability matrix (FR → components → epic → acceptance test)

Component IDs are defined in [ARCHITECTURE §3](ARCHITECTURE.md#3-components). Task-level traceability (`T-…` → FR) is maintained in `TASKS.md` (batch 2); this matrix stops at epic level so the two documents cannot disagree on task numbering.

<!-- MATRIX:BEGIN (generated from FRD.md by script 2026-10-13; regenerate after FRD edits) -->
| FR | Pri | Components | Epic | Acceptance test |
|---|---|---|---|---|
| FR-AUTH-01 | M | COMP-02, COMP-11 | EP-01 | AT-FR-AUTH-01 |
| FR-AUTH-02 | M | COMP-02, COMP-11 | EP-01 | AT-FR-AUTH-02 |
| FR-AUTH-03 | M | COMP-02, COMP-11 | EP-01 | AT-FR-AUTH-03 |
| FR-AUTH-04 | S | COMP-02, COMP-11 | EP-01 | AT-FR-AUTH-04 |
| FR-PRJ-01 | M | COMP-01, COMP-02, COMP-11 | EP-02 | AT-FR-PRJ-01 |
| FR-PRJ-02 | M | COMP-01, COMP-02, COMP-10, COMP-11 | EP-02 | AT-FR-PRJ-02 |
| FR-PRJ-03 | M | COMP-01, COMP-02, COMP-12 | EP-02 | AT-FR-PRJ-03 |
| FR-PRJ-04 | M | COMP-02, COMP-04, COMP-13 | EP-02 | AT-FR-PRJ-04 |
| FR-PRJ-05 | M | COMP-01, COMP-02, COMP-11 | EP-02 | AT-FR-PRJ-05 |
| FR-PRJ-06 | S | COMP-02, COMP-03 | EP-02 | AT-FR-PRJ-06 |
| FR-MON-01 | M | COMP-12 | EP-03 | AT-FR-MON-01 |
| FR-MON-02 | M | COMP-01, COMP-02, COMP-13 | EP-03 | AT-FR-MON-02 |
| FR-MON-03 | M | COMP-02, COMP-04, COMP-13 | EP-03 | AT-FR-MON-03 |
| FR-MON-04 | M | COMP-03, COMP-04, COMP-13 | EP-03 | AT-FR-MON-04 |
| FR-MON-05 | S | COMP-04, COMP-13 | EP-03 | AT-FR-MON-05 |
| FR-MON-06 | S | COMP-02, COMP-13 | EP-03 | AT-FR-MON-06 |
| FR-MON-07 | C | COMP-01 | EP-03 | AT-FR-MON-07 |
| FR-MON-08 | W | n/a (not supported) | EP-03 | AT-FR-MON-08 |
| FR-ALR-01 | M | COMP-04, COMP-08, COMP-11 | EP-04 | AT-FR-ALR-01 |
| FR-ALR-02 | M | COMP-04, COMP-08, COMP-11 | EP-04 | AT-FR-ALR-02 |
| FR-ALR-03 | M | COMP-04, COMP-08, COMP-11 | EP-04 | AT-FR-ALR-03 |
| FR-ALR-04 | M | COMP-04, COMP-08, COMP-11 | EP-04 | AT-FR-ALR-04 |
| FR-ALR-05 | M | COMP-08 | EP-04 | AT-FR-ALR-05 |
| FR-ALR-06 | S | COMP-08, COMP-11 | EP-04 | AT-FR-ALR-06 |
| FR-ALR-07 | C | COMP-04, COMP-08, COMP-11 | EP-04 | AT-FR-ALR-07 |
| FR-ALR-08 | M | COMP-04, COMP-08, COMP-13 | EP-04 | AT-FR-ALR-08 |
| FR-DEP-01 | M | COMP-02, COMP-03, COMP-10, COMP-11 | EP-05 | AT-FR-DEP-01 |
| FR-DEP-02 | M | COMP-03, COMP-05, COMP-11 | EP-05 | AT-FR-DEP-02 |
| FR-DEP-03 | M | COMP-03, COMP-05, COMP-11 | EP-05 | AT-FR-DEP-03 |
| FR-DEP-04 | M | COMP-03, COMP-05, COMP-11 | EP-05 | AT-FR-DEP-04 |
| FR-DEP-05 | M | COMP-03, COMP-05 | EP-05 | AT-FR-DEP-05 |
| FR-DEP-06 | S | COMP-03, COMP-05, COMP-11 | EP-05 | AT-FR-DEP-06 |
| FR-DEP-07 | M | COMP-03, COMP-05, COMP-11 | EP-05 | AT-FR-DEP-07 |
| FR-DEP-08 | S | COMP-03, COMP-05, COMP-11 | EP-05 | AT-FR-DEP-08 |
| FR-DEP-09 | M | COMP-03, COMP-05, COMP-11 | EP-05 | AT-FR-DEP-09 |
| FR-SAST-01 | M | COMP-03, COMP-06, COMP-11 | EP-06 | AT-FR-SAST-01 |
| FR-SAST-02 | S | COMP-03, COMP-06, COMP-11 | EP-06 | AT-FR-SAST-02 |
| FR-SAST-03 | M | COMP-03, COMP-06, COMP-11 | EP-06 | AT-FR-SAST-03 |
| FR-SAST-04 | S | COMP-03, COMP-06, COMP-11 | EP-06 | AT-FR-SAST-04 |
| FR-AI-01 | M | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-01 |
| FR-AI-02 | M | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-02 |
| FR-AI-03 | M | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-03 |
| FR-AI-04 | M | COMP-07, COMP-10, COMP-14 | EP-08 | AT-FR-AI-04 |
| FR-AI-05 | M | COMP-01, COMP-07 | EP-08 | AT-FR-AI-05 |
| FR-AI-06 | M | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-06 |
| FR-AI-07 | S | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-07 |
| FR-AI-08 | S | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-08 |
| FR-AI-09 | C | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-09 |
| FR-AI-10 | M | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-10 |
| FR-AI-11 | M | COMP-03, COMP-07, COMP-11 | EP-08 | AT-FR-AI-11 |
| FR-REM-01 | M | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-01 |
| FR-REM-02 | M | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-02 |
| FR-REM-03 | M | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-03 |
| FR-REM-04 | M | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-04 |
| FR-REM-05 | M | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-05 |
| FR-REM-06 | M | COMP-01, COMP-02, COMP-09 | EP-09 | AT-FR-REM-06 |
| FR-REM-07 | M | COMP-09, COMP-10 | EP-09 | AT-FR-REM-07 |
| FR-REM-08 | M | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-08 |
| FR-REM-09 | S | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-09 |
| FR-REM-10 | S | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-10 |
| FR-REM-11 | C | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-11 |
| FR-REM-12 | M | COMP-03, COMP-09, COMP-10, COMP-14 | EP-09 | AT-FR-REM-12 |
| FR-DSH-01 | M | COMP-01, COMP-02 | EP-07 | AT-FR-DSH-01 |
| FR-DSH-02 | M | COMP-01, COMP-02 | EP-07 | AT-FR-DSH-02 |
| FR-DSH-03 | M | COMP-01, COMP-02 | EP-07 | AT-FR-DSH-03 |
| FR-DSH-04 | M | COMP-01, COMP-02 | EP-07 | AT-FR-DSH-04 |
| FR-DSH-05 | M | COMP-01, COMP-02, COMP-03 | EP-07 | AT-FR-DSH-05 |
| FR-DSH-06 | M | COMP-01, COMP-02 | EP-07 | AT-FR-DSH-06 |
| FR-DSH-07 | S | COMP-01, COMP-02 | EP-07 | AT-FR-DSH-07 |
| FR-DSH-08 | C | COMP-01, COMP-02 | EP-07 | AT-FR-DSH-08 |
<!-- MATRIX:END -->

### NFR traceability (summary)

| NFR group | Primary components | Epic |
|---|---|---|
| PERF | COMP-02, COMP-03, COMP-13 | EP-10 |
| REL | COMP-02, COMP-03, COMP-11 | EP-01, EP-10 |
| SEC | COMP-02, COMP-03, COMP-09, COMP-14 | EP-01, EP-09, EP-10 |
| AI | COMP-07 | EP-08 |
| USA, PORT, MNT, OBS, DATA, LIC, CAP | cross-cutting | EP-01, EP-10 |

## 11. Change control

Requirement IDs are never reused. A removed requirement keeps its row marked `Withdrawn`. Changes to Must requirements need team agreement and an entry in `DECISIONS.md`.
