# Implementation Backlog (Tasks)

> **Doc:** TASKS.md · **Version:** 0.2 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** [SRS §9–10](SRS.md#9-epics), [ROADMAP](ROADMAP.md), [TEST_STRATEGY](TEST_STRATEGY.md)

Task IDs are `T-<epic>.<nn>`. Every task has a deliverable, a measurable completion criterion ("Done when"), dependencies, and the requirements it implements. The table is dependency-ordered inside each epic; cross-epic dependencies are explicit. Spikes (`SP-nn`) are tasks whose output is a decision, not code.

**Sizes (team estimates, [A]):** S ≈ 1 person-day, M ≈ 2–3, L ≈ 4–6, XL ≈ 7–10. For capacity planning the ROADMAP uses midpoints S=1, M=2.5, L=5, XL=8 person-days. These are guesses with large uncertainty, not measurements.

**Priority:** M Must, S Should, C Could (not committed). **Phase:** P0–P5 as defined in [ROADMAP §2](ROADMAP.md#2-phases-and-milestones).

**Definition of done (all tasks):** code reviewed by a second member; tests for the behavior added; lint/type checks pass; documentation or OpenAPI updated if an interface changed; no new `critical` finding in CI scans.

**Generation note:** the tables below were generated from one task list and checked by script on 2026-10-13: IDs unique, every dependency exists, the dependency graph is acyclic, no task is scheduled in an earlier phase than a dependency, and every non-Won't FR appears in at least one task.


## EP-01 Platform foundation

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-01.01 | **Repo scaffold and CI.** Monorepo layout (`web/`, `api/`, `deploy/`, `examples/`); CI runs lint, type check, tests, Trivy and Semgrep on this repo. **Done when** CI is green on a PR and fails on a seeded critical finding. | — | NFR-MNT-01, NFR-SEC-07 | M | M | P0 |
| T-01.02 | **Compose skeleton.** `deploy/docker-compose.yml` with `web`, `api`, `worker`, `postgres`; `.env.example`. **Done when** `docker compose up` yields reachable `/health` and the web page on a clean machine. | T-01.01 | NFR-PORT-01 | M | M | P0 |
| T-01.03 | **Database layer and baseline migration.** SQLAlchemy models + Alembic for `user`, `refresh_session`, `project`, `job`, `audit_log`. **Done when** migrations apply to an empty DB and roll forward twice idempotently. | T-01.02 | DATA_MODEL §2.1–2.4 | M | M | P0 |
| T-01.04 | **Authentication.** Bootstrap admin, login, refresh, logout, `/auth/me`; Argon2id; JWT. **Done when** AT-FR-AUTH-01 and AT-FR-AUTH-02 pass. | T-01.03 | FR-AUTH-01, FR-AUTH-02, NFR-SEC-01 | M | M | P0 |
| T-01.05 | **RBAC enforcement.** Role guard dependency applied to every route; role-endpoint test generated from API_SPEC §7. **Done when** AT-FR-AUTH-03 passes for every route. | T-01.04 | FR-AUTH-03 | M | S | P1 |
| T-01.06 | **Job queue framework.** Enqueue, claim with `SKIP LOCKED`, lease, reaper, cancel flag, worker loop. **Done when** killing the worker mid-job leads to requeue and completion within lease time + 1 poll (NFR-REL-01 test). | T-01.03 | NFR-REL-01, NFR-CAP-01 | M | M | P0 |
| T-01.07 | **Logging, health and self-metrics.** JSON logs with `request_id`/`job_id`, redaction filter, `/health`, `/ready`, `/metrics` for api and worker. **Done when** log-redaction test finds no token in captured logs. | T-01.02 | NFR-OBS-01, NFR-SEC-08, NFR-REL-03 | M | M | P1 |
| T-01.08 | **Secret encryption helper.** AES-256-GCM encrypt/decrypt with `key_id`; key from `ENCRYPTION_KEY`. **Done when** round-trip and wrong-key tests pass and no plaintext is persisted. | T-01.01 | NFR-SEC-02 | M | S | P0 |
| T-01.09 | **Audit log writer and endpoint.** `audit_log` writes from auth, credential, scan, approval, PR events; `GET /audit-log`. **Done when** each listed action produces a row. | T-01.05 | FR-AUTH-04 | S | S | P5 |
| T-01.10 | **Login rate limiting.** 5 failures / 15 min per account+IP. **Done when** sixth attempt returns `429 RATE_LIMITED`. | T-01.04 | NFR-SEC-04 | S | S | P5 |
| T-01.11 | **Safe subprocess and outbound HTTP helpers.** argv-only runner with timeout and output cap; HTTP client with host allowlist and private-range blocking. **Done when** shell-metacharacter and SSRF test cases are rejected. | T-01.01 | NFR-SEC-06, NFR-SEC-09, CON-09 | M | M | P0 |

## EP-02 Projects and onboarding

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-02.01 | **Project API.** CRUD + archive. **Done when** AT-FR-PRJ-01 API tests pass. | T-01.05 | FR-PRJ-01 | M | S | P1 |
| T-02.02 | **GitHub adapter (read path).** Verify repo/token, default branch, manifest detection via contents API, 10 s timeout. **Done when** public and private fixture repos verify; bad token maps to `REPO_ACCESS_DENIED`. | T-01.08, T-01.11 | FR-PRJ-02, IF-05 | M | M | P0 |
| T-02.03 | **Repository endpoints.** PUT/GET/verify/DELETE with encrypted credential. **Done when** AT-FR-PRJ-02 passes and no response or log contains the token. | T-02.01, T-02.02 | FR-PRJ-02 | M | M | P1 |
| T-02.04 | **Monitoring target API and onboarding.** CRUD + `/onboarding` instructions. **Done when** AT-FR-PRJ-03 passes. | T-02.01 | FR-PRJ-03 | M | S | P1 |
| T-02.05 | **Target status derivation.** `waiting/receiving/stale` from last-sample time. **Done when** simulated sender drives all three transitions (AT-FR-PRJ-04). | T-03.04, T-03.05 | FR-PRJ-04 | M | S | P1 |
| T-02.06 | **Onboarding UI.** Repository form, target form, snippet with copy button, status badge. **Done when** a first-time tester completes UC-01 from the README (SM-01 rehearsal). | T-07.01, T-02.03, T-02.04 | FR-PRJ-01, FR-PRJ-02, FR-PRJ-03, FR-PRJ-04 | M | M | P1 |
| T-02.07 | **Seed demo project command.** CLI seeds a project linked to `examples/` fixtures. **Done when** a clean DB plus one command shows demo data. | T-03.01, T-05.01, T-02.04 | FR-PRJ-06 | S | S | P5 |

## EP-03 Telemetry ingestion and monitoring views

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-03.01 | **Demo app with injectable faults.** Small instrumented HTTP service; endpoints to inject 5xx rate and latency. **Done when** SM-03/SM-04 scenarios can be run by script. | — | SM-03, SM-04 | M | M | P0 |
| T-03.02 | **Spike SP-01: OTLP → Prometheus path.** Working Collector→Prometheus config; documented final metric and label names; staleness behavior measured. **Done when** UD-06 is decided and `monitoring/queries.py` names are confirmed. | T-01.02, T-03.01 | UD-06, DEC-004 | M | M | P0 |
| T-03.03 | **Collector auth and Prometheus config.** Bearer-token auth on the OTLP receiver; Prometheus remote-write receiver enabled; retention set. **Done when** requests without the token write nothing (AT-FR-MON-01). | T-03.02 | FR-MON-01, IF-01 | M | S | P1 |
| T-03.04 | **Prometheus client, query templates, metrics endpoint.** Allowlisted templates, input validators, `/monitoring-targets/{id}/metrics`, SLI computation. **Done when** AT-FR-MON-02 and AT-FR-MON-03 pass against seeded series. | T-03.02, T-01.05, T-02.04 | FR-MON-02, FR-MON-03, IF-02 | M | M | P1 |
| T-03.05 | **Monitoring loop.** Worker evaluates rules every `ALERT_EVAL_INTERVAL_SECONDS`; updates target status; records evaluation errors. **Done when** AT-FR-MON-04 passes with a fake clock. | T-01.06, T-03.04 | FR-MON-04 | M | M | P1 |
| T-03.06 | **Monitoring charts UI.** Target detail with 4 charts, ranges, `no_data`/`no_traffic`/error states. **Done when** AT-FR-MON-02 UI check passes. | T-07.01, T-03.04 | FR-MON-02, FR-DSH-06 | M | M | P1 |
| T-03.07 | **Z-score anomaly evaluator.** Rolling baseline, \( k \), \( N \) parameters. **Done when** AT-FR-MON-05 synthetic series pass. | T-03.05 | FR-MON-05 | S | M | P5 |
| T-03.08 | **Prometheus scrape mode.** Generate scrape targets from DB; UI option. **Done when** a `/metrics` demo target appears (AT-FR-MON-06). | T-03.03 | FR-MON-06 | S | M | P5 |
| T-03.09 | **Host/runtime metrics display.** Show CPU/memory series when instrumentation provides them. Not committed for MVP. | T-03.06 | FR-MON-07 | C | M | P5 |

## EP-04 Alerting and notifications

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-04.01 | **Alert rule CRUD and validation.** Endpoints + validators from API_SPEC §6. **Done when** AT-FR-ALR-01 passes. | T-02.04, T-03.04 | FR-ALR-01 | M | S | P1 |
| T-04.02 | **Alert manager.** Dedupe index, lifecycle, evidence snapshot, auto-resolve, absence rule. **Done when** AT-FR-ALR-02/03/04/08 pass. | T-04.01, T-03.05 | FR-ALR-02, FR-ALR-03, FR-ALR-04, FR-ALR-08 | M | L | P1 |
| T-04.03 | **Alert endpoints.** List/detail/acknowledge/resolve with transition checks. **Done when** illegal transitions return `409`. | T-04.02 | FR-ALR-02, FR-DSH-04 | M | S | P1 |
| T-04.04 | **Webhook channel and deliveries.** Encrypted channel config, URL validation, delivery records. **Done when** AT-FR-ALR-05 passes and private-range URLs are rejected. | T-04.02, T-01.11, T-01.08 | FR-ALR-05, NFR-SEC-09 | M | M | P1 |
| T-04.05 | **Cooldown and email channel.** Suppression window; SMTP sender. **Done when** AT-FR-ALR-06 passes. | T-04.04 | FR-ALR-06 | S | S | P5 |
| T-04.06 | **Alerts and rules UI.** Lists, detail with evidence, ack/resolve, rule form. **Done when** AT-FR-DSH-04 passes. | T-07.01, T-04.03 | FR-DSH-04, FR-ALR-01 | M | M | P1 |
| T-04.07 | **Detection-time acceptance test.** Script injects 10 faults and measures \( T_{detect} \). **Done when** results are recorded against SM-03 and SM-04. | T-03.01, T-04.02 | SM-03, SM-04, NFR-PERF-04 | M | S | P1 |
| T-04.08 | **Silencing and maintenance windows.** Rule-scoped silences. Not committed for MVP. | T-04.02 | FR-ALR-07 | C | M | P5 |

## EP-05 Dependency scanning

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-05.01 | **Vulnerable-repo fixture.** npm and PyPI manifests with ≥ 10 seeded vulnerable versions, each confirmed on osv.dev at creation (advisory IDs kept in the fixture manifest), plus outdated and one deprecated package. **Done when** the manifest is reviewed by a second member. | — | SM-02 | M | M | P0 |
| T-05.02 | **Spike SP-03: Trivy and OSV.** Run both against the fixture; record JSON shapes, fix-version coverage, disagreements; evaluate OSV-Scanner as an alternative. **Done when** DEC-006 is confirmed or revised. | T-05.01 | DEC-006 | M | M | P0 |
| T-05.03 | **Clone service.** Shallow clone, hooks disabled, no submodules, size/time caps, cleanup on exit and on startup. **Done when** a malicious-hook fixture does not execute. | T-01.11, T-02.02 | FR-DEP-01 | M | M | P2 |
| T-05.04 | **Scan orchestration.** Scan/job/provider-run lifecycle, `partial` status, one active scan per project, SHA recording. **Done when** AT-FR-DEP-01 and AT-FR-DEP-07 pass. | T-01.06, T-05.03, T-02.03 | FR-DEP-01, FR-DEP-07 | M | L | P2 |
| T-05.05 | **Trivy adapter and inventory parser.** `trivy fs --format json --scanners vuln` argv, parser for npm/PyPI inventory and vulnerabilities. **Done when** AT-FR-DEP-02 passes on the fixture. | T-05.02, T-05.04 | FR-DEP-02, FR-DEP-03, IF-07 | M | L | P2 |
| T-05.06 | **OSV adapter.** Batch query, hydrate by ID, pagination, backoff, cache by `(id, modified)`. **Done when** fixture vulnerabilities resolve to full records and a forced timeout yields provider `failed`. | T-05.02, T-05.04 | FR-DEP-03, IF-03 | M | L | P2 |
| T-05.07 | **Registry adapters.** npm and PyPI metadata: latest, release date, license, deprecation, runtime constraints, existence check. **Done when** each field is parsed for fixture packages. | T-05.04, T-01.11 | FR-DEP-05, IF-04 | M | M | P2 |
| T-05.08 | **Normalizer and scan diff.** Alias-set merge, fingerprint, severity mapping, new/unchanged/resolved, no resolution on partial scans. **Done when** AT-FR-DEP-04 and AT-FR-DEP-09 pass. | T-05.05, T-05.06 | FR-DEP-03, FR-DEP-04, FR-DEP-09, NFR-REL-04 | M | L | P2 |
| T-05.09 | **Outdated classifier.** Patch/minor/major lag. **Done when** AT-FR-DEP-05 passes including registry-failure case. | T-05.07, T-05.05 | FR-DEP-05 | M | S | P2 |
| T-05.10 | **Incompatibility heuristics.** Major bump, `engines`, `requires_python`, deprecation. **Done when** AT-FR-DEP-06 fixtures pass. | T-05.09 | FR-DEP-06 | S | M | P5 |
| T-05.11 | **Scan and dependency endpoints.** `POST/GET scans`, `GET dependencies`, jobs endpoints. **Done when** API_SPEC §5.6 contract test passes. | T-05.04 | FR-DEP-01, FR-DSH-05 | M | M | P2 |
| T-05.12 | **Scheduled rescans.** Daily cron enqueue sharing the manual path. **Done when** AT-FR-DEP-08 passes. | T-05.11 | FR-DEP-08 | S | S | P5 |

## EP-06 Static analysis

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-06.01 | **Semgrep adapter.** Argv with metrics off, JSON output, rule set choice per UD-01, exclusions, timeout, file-size cap. **Done when** AT-FR-SAST-01 and AT-FR-SAST-03 pass. | T-05.04, T-05.03 | FR-SAST-01, FR-SAST-03, IF-08 | M | L | P2 |
| T-06.02 | **Snippet extraction and redaction.** Bounded snippet (≤ 31 lines, ≤ 4 KB), secret-pattern redaction before storage. **Done when** seeded fake secret is absent from stored evidence. | T-06.01 | FR-SAST-01, FR-AI-06 | M | M | P2 |
| T-06.03 | **Custom rules opt-in.** Repository-local rules loaded only when enabled. **Done when** AT-FR-SAST-02 passes. | T-06.01 | FR-SAST-02 | S | S | P5 |
| T-06.04 | **Finding triage.** `PATCH /findings/{id}` dismiss/reopen with reasons; persistence by fingerprint. **Done when** AT-FR-SAST-04 passes. | T-05.08 | FR-SAST-04 | S | S | P3 |

## EP-07 Unified dashboard and findings

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-07.01 | **Web foundation.** Next.js app, typed API client generated from OpenAPI, session handling, layout, shared loading/empty/error components. **Done when** all three states render in a component test. | T-01.04 | FR-DSH-06 | M | L | P1 |
| T-07.02 | **Project list and overview endpoint.** `GET /projects`, `GET /projects/{id}/overview` with per-section status. **Done when** one backend down still returns the other section (NFR-REL-05). | T-02.01, T-03.04, T-05.11, T-04.03 | FR-DSH-01, FR-PRJ-05, NFR-REL-05 | M | M | P2 |
| T-07.03 | **Overview UI.** Monitoring, alerts, scan, findings cards with empty states. **Done when** AT-FR-DSH-01 and AT-FR-PRJ-05 pass. | T-07.01, T-07.02 | FR-DSH-01, FR-PRJ-05 | M | M | P2 |
| T-07.04 | **Findings explorer.** Filters, sorting, pagination (API + UI). **Done when** AT-FR-DSH-02 passes with 10,000 seeded findings (NFR-PERF-01). | T-05.08, T-07.01 | FR-DSH-02, NFR-PERF-01 | M | L | P2 |
| T-07.05 | **Finding detail.** Evidence, history, recommendation and proposal panels. **Done when** AT-FR-DSH-03 passes. | T-07.04, T-06.02 | FR-DSH-03 | M | M | P2 |
| T-07.06 | **Job progress UI.** Polling hook, stage display, error summary, cancel. **Done when** AT-FR-DSH-05 passes. | T-07.01, T-05.11 | FR-DSH-05 | M | S | P2 |
| T-07.07 | **Activity timeline.** Time-ordered events with the "temporal order only" note. **Done when** AT-FR-DSH-07 passes. | T-07.03 | FR-DSH-07 | S | S | P5 |
| T-07.08 | **Findings export.** JSON/CSV export. **Done when** AT-FR-DSH-08 passes. Not committed for MVP. | T-07.04 | FR-DSH-08 | C | S | P5 |

## EP-08 AI recommendations

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-08.01 | **Evidence pack builder.** Bounded pack from stored data, evidence IDs, content hash. **Done when** AT-FR-AI-02 passes. | T-05.08, T-06.02, T-05.07 | FR-AI-02 | M | M | P3 |
| T-08.02 | **Redaction module.** Shared secret-pattern redaction with unit tests; omits snippet when uncertain. **Done when** AT-FR-AI-06 passes. | T-06.02 | FR-AI-06, NFR-AI-02 | M | S | P3 |
| T-08.03 | **Claude client wrapper.** Official SDK, timeouts, usage capture, size limit, daily cap, `AI_ENABLED`. **Done when** AT-FR-AI-10 passes and `AI_ENABLED=false` returns `409`. | T-01.11 | FR-AI-10, FR-AI-06, IF-06 | M | M | P3 |
| T-08.04 | **Prompt and schema.** Versioned prompt, JSON schema, delimited untrusted data, one repair attempt. **Done when** AT-FR-AI-03 passes. | T-08.03, T-08.01 | FR-AI-03, FR-AI-11 | M | M | P3 |
| T-08.05 | **Validator.** Schema, evidence IDs, registry existence, advisory consistency, patch check hook, status derivation. **Done when** AT-FR-AI-04 passes for hallucinated, mixed, and valid outputs. | T-08.04, T-05.07 | FR-AI-04 | M | L | P3 |
| T-08.06 | **Recommendation job and endpoints.** Async job, list/detail endpoints. **Done when** AT-FR-AI-01 passes. | T-08.05, T-01.06 | FR-AI-01 | M | M | P3 |
| T-08.07 | **Recommendation UI.** Evidence links, badge, confidence, limitations, AI label. **Done when** AT-FR-AI-05 passes. | T-08.06, T-07.05 | FR-AI-05 | M | M | P3 |
| T-08.08 | **Golden set and audit script.** ≥ 30 items incl. adversarial; seeded-bad outputs; scripted metrics. **Done when** SM-06 is measured and recorded. | T-08.06 | SM-06, NFR-AI-01 | M | M | P3 |
| T-08.09 | **Alternative-library criteria.** Registry-derived criteria in `library_alternative`. **Done when** AT-FR-AI-07 passes. | T-08.06 | FR-AI-07 | S | S | P5 |
| T-08.10 | **Recommendation feedback.** Rating endpoint and UI. **Done when** AT-FR-AI-08 passes. | T-08.06 | FR-AI-08 | S | S | P5 |
| T-08.11 | **Injection fixtures.** Hostile comments/advisory text/package descriptions in tests. **Done when** golden-set semantics are unchanged (AT-FR-AI-11). | T-08.04 | FR-AI-11 | M | S | P3 |
| T-08.12 | **AI alert summary.** Summarize an alert strictly from its evidence snapshot. Not committed for MVP. | T-08.06, T-04.02 | FR-AI-09 | C | M | P5 |

## EP-09 Automated remediation

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-09.01 | **Spike SP-02: sandbox runtime.** Run isolated daemon + non-root container with limits on every team OS; document go/no-go. **Done when** UD-03 is decided. | T-01.02 | UD-03, DEC-010 | M | L | P0 |
| T-09.02 | **Spike SP-04: GitHub write path.** Test repo; PAT permission matrix; branch and draft-PR creation; branch-name enforcement. **Done when** UD-02 is decided. | T-02.02 | UD-02, DEC-009 | M | M | P0 |
| T-09.03 | **Sandbox orchestrator.** Create container, limits, stage runner, network on/off per stage, cleanup, secret-free environment. **Done when** AT-FR-REM-02 passes. | T-09.01, T-01.11 | FR-REM-02, NFR-SEC-05 | M | L | P4 |
| T-09.04 | **Change-plan generator.** Deterministic plan from findings; name/version validators. **Done when** AT-FR-REM-01 and AT-FR-REM-08 pass. | T-05.08 | FR-REM-01, FR-REM-08 | M | M | P4 |
| T-09.05 | **npm pipeline.** Baseline, lockfile-only apply with scripts disabled, scope check, post-change tests with network off. **Done when** AT-FR-REM-03/04/12 pass on the fixture. | T-09.03, T-09.04 | FR-REM-03, FR-REM-04, FR-REM-12 | M | XL | P4 |
| T-09.06 | **PyPI pipeline.** Pinned `requirements.txt` update, equivalent stages. **Done when** the same ATs pass for PyPI. | T-09.05 | FR-REM-03, FR-REM-04, FR-REM-12 | M | L | P4 |
| T-09.07 | **Delta re-scan.** Re-scan result lockfile; resolved/new findings. **Done when** AT-FR-REM-05 passes. | T-09.05, T-05.05 | FR-REM-05 | M | M | P4 |
| T-09.08 | **Proposal endpoints and gates.** State machine, approval matrix, audit entries. **Done when** AT-FR-REM-06 passes and `APPROVAL_REQUIRED` cannot be bypassed. | T-09.04, T-01.05 | FR-REM-06, FR-REM-12 | M | L | P4 |
| T-09.09 | **Git write path.** Branch regex, push, draft PR with evidence body, cleanup. **Done when** AT-FR-REM-07 passes against the test repo. | T-09.02, T-09.08 | FR-REM-07, FR-REM-10 | M | L | P4 |
| T-09.10 | **Fix proposal UI.** Diff viewer, validation report, approval dialog with acknowledgments. **Done when** all approval-matrix rows are exercised in E2E. | T-07.01, T-09.08 | FR-REM-06, FR-REM-09 | M | L | P4 |
| T-09.11 | **Remediation safety tests.** Argument fuzz, scope violation, approval-bypass, sandbox escape checklist. **Done when** SM-07 invariants hold in CI. | T-09.09 | SM-07, NFR-SEC-05, NFR-SEC-06 | M | M | P4 |
| T-09.12 | **Major-bump acknowledgment.** `ACK_REQUIRED` flow and PR label. **Done when** AT-FR-REM-09 passes. | T-09.08 | FR-REM-09 | S | S | P5 |
| T-09.13 | **LLM patch application.** Apply validated suggested patches through the same pipeline. Not committed for MVP. | T-09.05, T-08.06 | FR-REM-11 | C | L | P5 |

## EP-10 Hardening, documentation, demo

| ID | Task and completion criterion | Depends on | Implements | Pri | Size | Phase |
|---|---|---|---|---|---|---|
| T-10.01 | **Test infrastructure.** Fixture loaders, mock servers for OSV/registries/GitHub/Claude, Playwright harness. **Done when** one E2E test runs in CI. | T-01.02 | NFR-MNT-01 | M | M | P1 |
| T-10.02 | **Acceptance suite.** Implement every `AT-<FR-ID>` for Must requirements. **Done when** the suite is green and mapped in TEST_STRATEGY §8. | T-10.01 | All Must FRs | M | XL | P5 |
| T-10.03 | **Performance checks.** Scripts for NFR-PERF-01/02/03. **Done when** results are recorded (not assumed). | T-07.04, T-05.04 | NFR-PERF-01, NFR-PERF-02, NFR-PERF-03 | M | M | P5 |
| T-10.04 | **Security review.** Execute SECURITY §12 checklist; fix findings. **Done when** all items are checked or accepted as residual risk. | T-09.11 | NFR-SEC-01..09 | M | M | P5 |
| T-10.05 | **Docs and usability verification.** Fresh-machine README run, OpenAPI contract test, 3-person usability session. **Done when** SM-01 recorded. | T-10.02 | NFR-USA-01, NFR-PORT-01, NFR-MNT-02 | M | M | P5 |
| T-10.06 | **License inventory.** Generated dependency license report; Semgrep rule-license decision recorded. **Done when** UD-01 is closed. | T-06.01 | NFR-LIC-01, UD-01 | S | S | P5 |
| T-10.07 | **Retention job and backup drill.** Daily retention job; documented `pg_dump` restore drill. **Done when** a restore succeeds on a clean host. | T-05.04 | NFR-DATA-01, NFR-DATA-02 | S | M | P5 |
| T-10.08 | **Demo rehearsal.** Scripted demo covering SM-01..SM-07 with a recorded fallback. **Done when** two dry runs succeed. | T-10.05, T-02.07 | SM-01..SM-07 | M | S | P5 |

## Summary (computed)

| Priority | Tasks | Estimated person-days (midpoints) |
|---|---|---|
| Must | 71 | 205 |
| Should | 16 | 22 |
| Could | 5 | 13.5 |
| **Total** | **92** | **240.5** |

Capacity comparison and scope-cut ladder: [ROADMAP §4–5](ROADMAP.md#4-capacity-check).

## Critical path (Must tasks, by estimated effort)

T-01.01 → T-01.02 → T-01.03 → T-01.04 → T-01.05 → T-02.01 → T-02.03 → T-05.04 → T-05.05 → T-05.08 → T-09.04 → T-09.08 → T-09.09 → T-09.11 → T-10.04

Sum along the path: 47 person-days of sequential work. Delays on these tasks delay the demo; they should be assigned first and pair-reviewed. Task `T-09.01` (sandbox spike) is not on this path by effort but is the largest *uncertainty* and runs in Phase 0.

## Requirement → task map (reverse traceability)

| FR | Pri | Tasks |
|---|---|---|
| FR-AUTH-01 | M | T-01.04 |
| FR-AUTH-02 | M | T-01.04 |
| FR-AUTH-03 | M | T-01.05 |
| FR-AUTH-04 | S | T-01.09 |
| FR-PRJ-01 | M | T-02.01, T-02.06 |
| FR-PRJ-02 | M | T-02.02, T-02.03, T-02.06 |
| FR-PRJ-03 | M | T-02.04, T-02.06 |
| FR-PRJ-04 | M | T-02.05, T-02.06 |
| FR-PRJ-05 | M | T-07.02, T-07.03 |
| FR-PRJ-06 | S | T-02.07 |
| FR-MON-01 | M | T-03.03 |
| FR-MON-02 | M | T-03.04, T-03.06 |
| FR-MON-03 | M | T-03.04 |
| FR-MON-04 | M | T-03.05 |
| FR-MON-05 | S | T-03.07 |
| FR-MON-06 | S | T-03.08 |
| FR-MON-07 | C | T-03.09 |
| FR-MON-08 | W | — (Won't, documented limitation) |
| FR-ALR-01 | M | T-04.01, T-04.06 |
| FR-ALR-02 | M | T-04.02, T-04.03 |
| FR-ALR-03 | M | T-04.02 |
| FR-ALR-04 | M | T-04.02 |
| FR-ALR-05 | M | T-04.04 |
| FR-ALR-06 | S | T-04.05 |
| FR-ALR-07 | C | T-04.08 |
| FR-ALR-08 | M | T-04.02 |
| FR-DEP-01 | M | T-05.03, T-05.04, T-05.11 |
| FR-DEP-02 | M | T-05.05 |
| FR-DEP-03 | M | T-05.05, T-05.06, T-05.08 |
| FR-DEP-04 | M | T-05.08 |
| FR-DEP-05 | M | T-05.07, T-05.09 |
| FR-DEP-06 | S | T-05.10 |
| FR-DEP-07 | M | T-05.04 |
| FR-DEP-08 | S | T-05.12 |
| FR-DEP-09 | M | T-05.08 |
| FR-SAST-01 | M | T-06.01, T-06.02 |
| FR-SAST-02 | S | T-06.03 |
| FR-SAST-03 | M | T-06.01 |
| FR-SAST-04 | S | T-06.04 |
| FR-AI-01 | M | T-08.06 |
| FR-AI-02 | M | T-08.01 |
| FR-AI-03 | M | T-08.04 |
| FR-AI-04 | M | T-08.05 |
| FR-AI-05 | M | T-08.07 |
| FR-AI-06 | M | T-06.02, T-08.02, T-08.03 |
| FR-AI-07 | S | T-08.09 |
| FR-AI-08 | S | T-08.10 |
| FR-AI-09 | C | T-08.12 |
| FR-AI-10 | M | T-08.03 |
| FR-AI-11 | M | T-08.04, T-08.11 |
| FR-REM-01 | M | T-09.04 |
| FR-REM-02 | M | T-09.03 |
| FR-REM-03 | M | T-09.05, T-09.06 |
| FR-REM-04 | M | T-09.05, T-09.06 |
| FR-REM-05 | M | T-09.07 |
| FR-REM-06 | M | T-09.08, T-09.10 |
| FR-REM-07 | M | T-09.09 |
| FR-REM-08 | M | T-09.04 |
| FR-REM-09 | S | T-09.10, T-09.12 |
| FR-REM-10 | S | T-09.09 |
| FR-REM-11 | C | T-09.13 |
| FR-REM-12 | M | T-09.05, T-09.06, T-09.08 |
| FR-DSH-01 | M | T-07.02, T-07.03 |
| FR-DSH-02 | M | T-07.04 |
| FR-DSH-03 | M | T-07.05 |
| FR-DSH-04 | M | T-04.03, T-04.06 |
| FR-DSH-05 | M | T-05.11, T-07.06 |
| FR-DSH-06 | M | T-03.06, T-07.01 |
| FR-DSH-07 | S | T-07.07 |
| FR-DSH-08 | C | T-07.08 |
