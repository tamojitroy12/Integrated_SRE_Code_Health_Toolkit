# Test Strategy

> **Doc:** TEST_STRATEGY.md · **Version:** 0.2 · **Date:** 2026-10-13 · **Status:** Draft (**[P]**) · **Related:** [FRD](FRD.md), [SRS](SRS.md), [SECURITY §12](SECURITY.md#12-verification-checklist-executed-in-t-1004), [AI_DESIGN](AI_DESIGN.md), [TASKS](TASKS.md)

## 1. Objectives and principles

1. **Every requirement is verifiable.** Each FR has an acceptance test `AT-<FR-ID>`; each NFR has `NT-<CAT>-nn` (catalogs in §8–9).
2. **No invented results.** Targets in the SRS/PRD are measured and recorded in a results log (`docs/test-results/`, created during EP-10); until then they are targets.
3. **Test the honest-failure paths.** Partial scans, rejected AI output, `unverified` fixes, and provider outages are tested as carefully as success paths.
4. **Safety invariants are automated** (SM-07): approval before PR, no push to default branch, no merge call, branch-name pattern, secrets never leaked.
5. **Deterministic by default.** External services are mocked with recorded fixtures in CI; a small `@live` suite runs manually or nightly against real services.

## 2. Test levels and tools

Tools are proposals **[P]**; verify availability and fit when adopted.

| Level | Scope | Proposed tools | Runs |
|---|---|---|---|
| Unit | Pure logic: SLI and z-score math, fingerprinting, normalizer, validators, state machines, argument validators | pytest; Vitest for frontend utilities | Every commit |
| Component (UI) | React components, loading/empty/error states, accessibility lint | Vitest + React Testing Library; axe | Every commit |
| Integration | API with real PostgreSQL; worker jobs; Collector→Prometheus path; adapters against mock servers; sandbox runner | pytest, httpx, an HTTP mocking library, Docker Compose test stack | Every PR |
| End-to-end | Browser flows across the full Compose stack with demo-app, vulnerable-repo, sandbox, test GitHub repo | Playwright | Every PR (smoke), nightly (full) |
| Contract | Generated OpenAPI equals [API_SPEC](API_SPEC.md) | OpenAPI diff / schema-based API test tool | Every PR (Should) |
| Security | Checklist SC-01…SC-15, fuzzing, scans of own repo | pytest, Trivy and Semgrep in CI, manual checklist | PR + before milestones |
| Reliability | Fault injection: kill worker, stop Prometheus, provider timeouts, lease expiry | Scripted Compose operations | Nightly + milestones |
| Performance | NFR-PERF checks | Python async script or a load tool | Before M5 |
| Acceptance | AT-* suite, demo script | Combination of the above | Before each milestone |
| AI evaluation | Golden set and seeded-bad outputs | Scripted evaluation + manual audit | When prompts/models change; before M3 and M5 |

### 2.1 Shared Test Infrastructure & Tooling (TASK T-10.01)

1. **Pytest Markers & Gating**:
   - `@pytest.mark.at("FR-XXX-nn")`: Links test functions to specific Functional Requirements.
   - `@pytest.mark.nt("CAT-nn")`: Links test functions to Non-Functional Requirements.
   - `@pytest.mark.live`: Gated tests calling real external services; skipped by default, opt-in via `--run-live` or `TEST_RUN_LIVE=1`.
   - `@pytest.mark.sandbox`: Tests requiring isolated container daemon runtime; skipped by default, but fails loudly if `REMEDIATION_ENABLED=true` or `--run-sandbox` is set and the sandbox daemon is unreachable.
2. **Traceability Tool (`tools/at_coverage`)**:
   - Parses `docs/FRD.md` to extract all 70 FRs and verifies count invariant (exits with code 2 if != 70).
   - Scans test suites for references and prints coverage tables.
   - Flags: `--min-priority {M,S,C,W}` (default: `M`), `--fail-uncovered` (exits with code 1 if uncovered), `--format {table,markdown,json}`, `--uncovered-only`.
3. **Injectable Time Source (`toolkit.core.clock`)**:
   - `Clock` protocol with `now()`, `time()`, `monotonic()`, `sleep()`.
   - `SystemClock`: Production operating-system-backed clock with aware UTC datetimes.
   - `FakeClock`: Test clock with deterministic starting point; `advance(seconds)` steps time without sleeping; `sleep(seconds)` advances clock instantly.
   - Pytest fixture: `fake_clock` provides a fresh `FakeClock` instance.
4. **PostgreSQL Isolation with Transaction Rollback (`db_session`)**:
   - Shared migrated database (`shared_migrated_database`) runs Alembic migrations once per test session.
   - `db_session` fixture opens a connection, begins an outer transaction, binds a session with savepoints (`join_transaction_mode="create_savepoint"`), and rolls back on teardown.
   - Guarantees sub-millisecond isolation with zero data pollution across tests.
5. **Local HTTP Mock Servers (`tests/mock_servers`)**:
   - Zero external dependencies using `http.server.ThreadingHTTPServer` bound explicitly to `127.0.0.1:0`.
   - `GitHubMockServer`: Serves canned fixtures from `tests/fixtures/github/` (repos, manifests, refs, PRs).
   - `PrometheusMockServer`: Serves `/api/v1/query`, `/api/v1/query_range`, `/api/v1/targets`, and `/-/ready`.
   - `WebhookReceiverServer`: Records incoming notifications with headers, JSON payloads, and aware UTC timestamps.
   - Stubs for `OSVMockServer`, `RegistryMockServer`, and `ClaudeMockServer` ready for future phases.
   - Pytest fixtures: `github_mock_server`, `prometheus_mock_server`, `webhook_receiver`.
6. **Compose Test Profile & Readiness Waiter (`deploy/docker-compose.yml`, `scripts/wait_for_health.py`)**:
   - Starts 6 services: `postgres`, `migrate`, `api`, `worker`, `otel-collector`, and `prometheus` (`docker compose --profile test up -d`).
   - Ports published on `127.0.0.1` only.
   - `scripts/wait_for_health.py` polls health endpoints (`/health`, `/ready`, `/-/ready`, OTLP port) with bounded backoff.
7. **Playwright E2E Harness & Accessibility Auditing (`web/e2e`)**:
   - Official `@axe-core/playwright` integration for automated accessibility checks.
   - Filtered by WCAG 2.1 AA tags: `['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']`.
   - Configured for Chromium smoke tests and multi-browser nightly matrix (`PLAYWRIGHT_ALL_BROWSERS=true`).
8. **Detection-Time Acceptance Tooling & Baselines (`tools/accept/detection_time.py`, TASK T-04.07)**:
   - Command-line acceptance harness measuring and validating alert system fault-detection latency bounds (SM-03, NT-PERF-04) and soak alert noise (SM-04).
   - Theoretical bound formula: $N = \lceil \text{duration\_seconds} / \Delta_{\text{eval}} \rceil$; $\text{Bound} = T_{\text{ingest}} + N \cdot \Delta_{\text{eval}}$. PromQL 5m rate window smoothing delay ($W_{\text{lag}} \approx 15$s at 100% fault rate) is accounted for in test provenance.
   - Execution modes:
     - `--simulate`: Synthetic traffic generator & mock API verification running fully offline without containers.
     - `--soak <duration>`: Continuous fault-free load execution verifying zero spurious alerts over extended windows (e.g., 60m).
     - Live execution: Injects real faults into `examples/demo-app` via authenticated endpoints (`POST /admin/fault`, `POST /admin/clear`) with constant-time bearer token check, bounded error rate, and TTL auto-expiry.
   - Webhook isolation: Registers run-specific webhook channel (`Acceptance-Detection-<uuid>`) with ephemeral receiver on port 0, single-channel isolation, and `finally` block cleanup.
   - Hermetic unit tests: 13 offline unit tests in `api/tests/test_detection_time_acceptance.py` marked `@pytest.mark.at("SM-03")`, `@pytest.mark.at("SM-04")`, and `@pytest.mark.at("NFR-PERF-04")`.
   - Baseline measurements: Committed test reports in `docs/test-results/` (`detection_time_report.md`, `detection_time_report.json`, `soak_report.md`, `soak_report.json`).

## 3. Environments and test data

| Environment | Composition | Notes |
|---|---|---|
| `unit` | No network, no containers | Must finish in minutes |
| `integration` | Compose profile `test`: postgres, prometheus, otel-collector, api, worker; mock servers for OSV, registries, GitHub, Claude | Recorded fixtures versioned in `tests/fixtures/` |
| `e2e` | Full stack + `examples/demo-app` + sandbox daemon (if UD-03 = go) + a dedicated GitHub test repository | Skips sandbox tests with an explicit marker when remediation is disabled |
| `live` | Real OSV, registries, GitHub test repo, Claude with a small budget | `@live` marker; never required for merge |

Test data rules: seeded vulnerable fixtures are **verified on osv.dev when created**, with advisory IDs recorded in the fixture manifest (not guessed); no real credentials in the repository (fake secrets are clearly synthetic); the GitHub test repository contains only disposable content; fixtures never include real customer code.

Fixtures: `examples/demo-app` (fault injection: 5xx rate, latency), `examples/vulnerable-repo` (npm + PyPI manifests with seeded vulnerable, outdated, and deprecated packages, insecure code patterns, a fake secret, and prompt-injection comments), `tests/fixtures/` (recorded provider responses, malformed model outputs, hostile-hook repository, oversized files).

## 4. Test ID scheme

| Prefix | Meaning |
|---|---|
| `AT-<FR-ID>` | Acceptance test for a functional requirement |
| `NT-<CAT>-nn` | Verification of non-functional requirement `NFR-<CAT>-nn` |
| `SC-nn` | Security checklist item ([SECURITY §12](SECURITY.md#12-verification-checklist-executed-in-t-1004)) |
| `AI-nn` | AI evaluation case (§7) |
| `RT-nn` | Reliability scenario (§6) |

Test functions carry their ID in the name or a marker (for example `@pytest.mark.at("FR-DEP-01")`), and CI produces a requirement-to-test coverage report from the markers.

## 5. Security testing

Execute the 15 checks in [SECURITY §12](SECURITY.md#12-verification-checklist-executed-in-t-1004). Additional automated cases: authorization matrix from [API_SPEC §7](API_SPEC.md#7-roleendpoint-summary-test-oracle-for-fr-auth-03) generated into tests; a response/log scanner that fails the build if any known secret value appears; fuzzing of package names, versions, refs, and URLs; hostile-string rendering in the UI; and SM-07 invariants (approval-before-PR, no default-branch push, no merge call).

## 6. Reliability and performance testing

| ID | Scenario | Expected behavior | Verifies |
|---|---|---|---|
| RT-01 | Kill worker during a scan | Lease expires, job requeued, scan completes, no duplicate findings | NFR-REL-01, NFR-REL-04 |
| RT-02 | Stop Prometheus | Monitoring sections show error state; scans, findings, AI continue; evaluation errors recorded; no alert state change | NFR-REL-05, FR-MON-04 |
| RT-03 | OSV timeout | Scan `partial`; provider `failed`; no resolved findings produced | FR-DEP-07, DATA_MODEL §6 |
| RT-04 | Registry 429/5xx | Backoff then provider `failed`; outdated not reported as "up to date" | FR-DEP-05 |
| RT-05 | Claude outage | AI job `failed` with reason; other features unaffected | NFR-REL-05 |
| RT-06 | Sandbox daemon down | Proposal fails `SANDBOX_UNAVAILABLE`; no remote write | FR-REM-02 |
| RT-07 | GitHub rejects push | Proposal returns to `approved` with `pr_error`; no retry loop | WORKFLOW WF-06 |
| RT-08 | Restart PostgreSQL | API recovers; in-flight jobs requeued | NFR-REL-01 |
| RT-09 | Webhook receiver down | Delivery `failed`; alert still visible | FR-ALR-05 |

Performance tests (T-10.03): NFR-PERF-01 with 10,000 seeded findings; NFR-PERF-02 with a fixture of ≤ 500 dependencies and ≤ 50,000 lines; NFR-PERF-03 median of 10 loads. Results are recorded with the hardware description; nothing is claimed beyond what is recorded.

## 7. AI evaluation

**Golden set (≥ 30 items, `AI-01`…).**

| Group | Count | Content |
|---|---|---|
| Upgrade guidance | ≥ 10 | Vulnerability findings with fixed versions in stored advisory data |
| Library alternative | ≥ 8 | Including ≥ 2 deprecated packages and ≥ 2 cases where no verifiable alternative exists (correct output: say so) |
| Code improvement | ≥ 8 | Semgrep findings with snippets |
| Adversarial | ≥ 4 | Injected instructions in code comments, advisory text, and package descriptions; bait to name a nonexistent package |

**Seeded-bad outputs (set \( B \), ≥ 15)** are hand-crafted model outputs: fabricated package, fabricated version, wrong fixed version, missing evidence refs, patch that does not apply, executable step, malformed JSON, schema-valid but unsupported compatibility claim presented as checkable.

**Metrics.** With \( U \) as defined in [AI_DESIGN §6.1](AI_DESIGN.md#61-status-derivation), and \( B_{flagged} \) the subset of \( B \) that the validator marks `rejected` or downgrades to `partially_validated` with the bad claim `unsupported`:

\[ \text{Catch} = \frac{\lvert B_{flagged} \rvert}{\lvert B \rvert}, \qquad U = \frac{N_{unsup \mid validated}}{N_{claims \mid validated}} \]

Targets (to be measured): \( U = 0 \) and \( \text{Catch} = 1 \) on the golden set and \( B \); any deviation is a defect. Also recorded without targets: schema-valid rate after one repair attempt, input/output tokens per request, latency.

**Audit protocol.** Two team members independently label each claim of each `validated` item as supported or unsupported by reading only the stored evidence; a third member resolves disagreements. CI uses recorded model outputs (deterministic); live runs with the real model are manual and budget-capped. Re-run the full set when `prompt_version` or `CLAUDE_MODEL` changes.

## 8. Acceptance test catalog (functional)

One row per FR (generated from [FRD](FRD.md) on 2026-10-13; regenerate after FRD edits). The pass condition is the acceptance-criteria cell of the cited FRD row.

| Test ID | Pri | Level | Environment / fixtures | Pass condition |
|---|---|---|---|---|
| AT-FR-AUTH-01 | M | Integration | Test DB; fake clock for token expiry | FRD §4.1, row FR-AUTH-01 |
| AT-FR-AUTH-02 | M | Integration | Test DB; fake clock for token expiry | FRD §4.1, row FR-AUTH-02 |
| AT-FR-AUTH-03 | M | Integration | Test DB; fake clock for token expiry | FRD §4.1, row FR-AUTH-03 |
| AT-FR-AUTH-04 | S | Integration | Test DB; fake clock for token expiry | FRD §4.1, row FR-AUTH-04 |
| AT-FR-PRJ-01 | M | Integration + E2E | GitHub mock server (and one real test repo in `@live`); demo-app | FRD §4.2, row FR-PRJ-01 |
| AT-FR-PRJ-02 | M | Integration + E2E | GitHub mock server (and one real test repo in `@live`); demo-app | FRD §4.2, row FR-PRJ-02 |
| AT-FR-PRJ-03 | M | Integration + E2E | GitHub mock server (and one real test repo in `@live`); demo-app | FRD §4.2, row FR-PRJ-03 |
| AT-FR-PRJ-04 | M | Integration + E2E | GitHub mock server (and one real test repo in `@live`); demo-app | FRD §4.2, row FR-PRJ-04 |
| AT-FR-PRJ-05 | M | Integration + E2E | GitHub mock server (and one real test repo in `@live`); demo-app | FRD §4.2, row FR-PRJ-05 |
| AT-FR-PRJ-06 | S | Integration + E2E | GitHub mock server (and one real test repo in `@live`); demo-app | FRD §4.2, row FR-PRJ-06 |
| AT-FR-MON-01 | M | Integration | Compose test stack (Collector, Prometheus); demo-app; fake clock | FRD §4.3, row FR-MON-01 |
| AT-FR-MON-02 | M | Integration | Compose test stack (Collector, Prometheus); demo-app; fake clock | FRD §4.3, row FR-MON-02 |
| AT-FR-MON-03 | M | Unit | Fixed counter series | FRD §4.3, row FR-MON-03 |
| AT-FR-MON-04 | M | Integration | Compose test stack (Collector, Prometheus); demo-app; fake clock | FRD §4.3, row FR-MON-04 |
| AT-FR-MON-05 | S | Unit | Synthetic series | FRD §4.3, row FR-MON-05 |
| AT-FR-MON-06 | S | Integration | Compose test stack (Collector, Prometheus); demo-app; fake clock | FRD §4.3, row FR-MON-06 |
| AT-FR-MON-07 | C | n/a | Could; not tested in MVP | FRD §4.3, row FR-MON-07 |
| AT-FR-MON-08 | W | n/a | Not supported in this release; documented limitation | FRD §4.3, row FR-MON-08 |
| AT-FR-ALR-01 | M | Integration | Fake clock; webhook mock; seeded Prometheus series | FRD §4.4, row FR-ALR-01 |
| AT-FR-ALR-02 | M | Unit + integration | State machine tables | FRD §4.4, row FR-ALR-02 |
| AT-FR-ALR-03 | M | Integration | Fake clock; webhook mock; seeded Prometheus series | FRD §4.4, row FR-ALR-03 |
| AT-FR-ALR-04 | M | Integration | Fake clock; webhook mock; seeded Prometheus series | FRD §4.4, row FR-ALR-04 |
| AT-FR-ALR-05 | M | Integration | Fake clock; webhook mock; seeded Prometheus series | FRD §4.4, row FR-ALR-05 |
| AT-FR-ALR-06 | S | Integration | Fake clock; webhook mock; seeded Prometheus series | FRD §4.4, row FR-ALR-06 |
| AT-FR-ALR-07 | C | n/a | Could; not tested in MVP | FRD §4.4, row FR-ALR-07 |
| AT-FR-ALR-08 | M | Integration | Fake clock; webhook mock; seeded Prometheus series | FRD §4.4, row FR-ALR-08 |
| AT-FR-DEP-01 | M | Integration | `examples/vulnerable-repo`; OSV and registry mocks (recorded) with `@live` variant | FRD §4.5, row FR-DEP-01 |
| AT-FR-DEP-02 | M | Integration | `examples/vulnerable-repo`; OSV and registry mocks (recorded) with `@live` variant | FRD §4.5, row FR-DEP-02 |
| AT-FR-DEP-03 | M | Integration | `examples/vulnerable-repo`; OSV and registry mocks (recorded) with `@live` variant | FRD §4.5, row FR-DEP-03 |
| AT-FR-DEP-04 | M | Unit | Overlapping provider outputs | FRD §4.5, row FR-DEP-04 |
| AT-FR-DEP-05 | M | Integration | `examples/vulnerable-repo`; OSV and registry mocks (recorded) with `@live` variant | FRD §4.5, row FR-DEP-05 |
| AT-FR-DEP-06 | S | Integration | `examples/vulnerable-repo`; OSV and registry mocks (recorded) with `@live` variant | FRD §4.5, row FR-DEP-06 |
| AT-FR-DEP-07 | M | Integration | `examples/vulnerable-repo`; OSV and registry mocks (recorded) with `@live` variant | FRD §4.5, row FR-DEP-07 |
| AT-FR-DEP-08 | S | Integration | `examples/vulnerable-repo`; OSV and registry mocks (recorded) with `@live` variant | FRD §4.5, row FR-DEP-08 |
| AT-FR-DEP-09 | M | Unit | Two scan result sets | FRD §4.5, row FR-DEP-09 |
| AT-FR-SAST-01 | M | Integration | `examples/vulnerable-repo` | FRD §4.6, row FR-SAST-01 |
| AT-FR-SAST-02 | S | Integration | `examples/vulnerable-repo` | FRD §4.6, row FR-SAST-02 |
| AT-FR-SAST-03 | M | Integration | `examples/vulnerable-repo` | FRD §4.6, row FR-SAST-03 |
| AT-FR-SAST-04 | S | Integration | `examples/vulnerable-repo` | FRD §4.6, row FR-SAST-04 |
| AT-FR-AI-01 | M | Integration + golden set | Claude mock with recorded outputs; registry mock; golden set (§7) | FRD §4.7, row FR-AI-01 |
| AT-FR-AI-02 | M | Integration + golden set | Claude mock with recorded outputs; registry mock; golden set (§7) | FRD §4.7, row FR-AI-02 |
| AT-FR-AI-03 | M | Unit | Recorded model outputs | FRD §4.7, row FR-AI-03 |
| AT-FR-AI-04 | M | Unit + integration | Seeded-bad outputs (§7) | FRD §4.7, row FR-AI-04 |
| AT-FR-AI-05 | M | Integration + golden set | Claude mock with recorded outputs; registry mock; golden set (§7) | FRD §4.7, row FR-AI-05 |
| AT-FR-AI-06 | M | Unit + integration | Fake-secret fixture | FRD §4.7, row FR-AI-06 |
| AT-FR-AI-07 | S | Integration + golden set | Claude mock with recorded outputs; registry mock; golden set (§7) | FRD §4.7, row FR-AI-07 |
| AT-FR-AI-08 | S | Integration + golden set | Claude mock with recorded outputs; registry mock; golden set (§7) | FRD §4.7, row FR-AI-08 |
| AT-FR-AI-09 | C | n/a | Could; not tested in MVP | FRD §4.7, row FR-AI-09 |
| AT-FR-AI-10 | M | Integration + golden set | Claude mock with recorded outputs; registry mock; golden set (§7) | FRD §4.7, row FR-AI-10 |
| AT-FR-AI-11 | M | Integration + golden set | Claude mock with recorded outputs; registry mock; golden set (§7) | FRD §4.7, row FR-AI-11 |
| AT-FR-REM-01 | M | Unit | Findings fixtures | FRD §4.8, row FR-REM-01 |
| AT-FR-REM-02 | M | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-02 |
| AT-FR-REM-03 | M | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-03 |
| AT-FR-REM-04 | M | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-04 |
| AT-FR-REM-05 | M | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-05 |
| AT-FR-REM-06 | M | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-06 |
| AT-FR-REM-07 | M | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-07 |
| AT-FR-REM-08 | M | Unit + fuzz | Argument validators | FRD §4.8, row FR-REM-08 |
| AT-FR-REM-09 | S | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-09 |
| AT-FR-REM-10 | S | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-10 |
| AT-FR-REM-11 | C | n/a | Could; not tested in MVP | FRD §4.8, row FR-REM-11 |
| AT-FR-REM-12 | M | Integration + E2E | Sandbox daemon; test GitHub repo; recorded registry responses | FRD §4.8, row FR-REM-12 |
| AT-FR-DSH-01 | M | Component + E2E | Seeded database; Playwright against full stack | FRD §4.9, row FR-DSH-01 |
| AT-FR-DSH-02 | M | Component + E2E | Seeded database; Playwright against full stack | FRD §4.9, row FR-DSH-02 |
| AT-FR-DSH-03 | M | Component + E2E | Seeded database; Playwright against full stack | FRD §4.9, row FR-DSH-03 |
| AT-FR-DSH-04 | M | Component + E2E | Seeded database; Playwright against full stack | FRD §4.9, row FR-DSH-04 |
| AT-FR-DSH-05 | M | Component + E2E | Seeded database; Playwright against full stack | FRD §4.9, row FR-DSH-05 |
| AT-FR-DSH-06 | M | Component + E2E | Seeded database; Playwright against full stack | FRD §4.9, row FR-DSH-06 |
| AT-FR-DSH-07 | S | Component + E2E | Seeded database; Playwright against full stack | FRD §4.9, row FR-DSH-07 |
| AT-FR-DSH-08 | C | n/a | Could; not tested in MVP | FRD §4.9, row FR-DSH-08 |

## 9. Verification catalog (non-functional)

Generated from [SRS §6](SRS.md#6-non-functional-requirements).

| Test ID | Pri | Requirement | Verification method |
|---|---|---|---|
| NT-PERF-01 | M | Read endpoints (excluding range queries > 24 h) respond with p95 ≤ 500 ms with 10,000 stored findings. | Load test script |
| NT-PERF-02 | M | A scan of ≤ 500 dependencies and ≤ 50,000 lines of code completes within 10 minutes, excluding the first scanner-database download. | Timed scan of fixture repo |
| NT-PERF-03 | S | Project overview loads within 3 s (median of 10 loads) on a local network with seeded data. | Browser performance test |
| NT-PERF-04 | M | Alert detection time satisfies \( T_{detect} \le T_{ingest} + N \cdot \Delta_{eval} \) (definitions in [TRD §6.2](TRD.md#62-anomaly-and-alert-timing)). | Fault injection (SM-03) |
| NT-REL-01 | M | Queued jobs survive process restarts. Running jobs hold a lease; if it expires the job is requeued, up to 3 attempts, then `failed`. | Kill-worker test |
| NT-REL-02 | M | Failure of one scan provider does not abort other providers (FR-DEP-07). | Fault injection |
| NT-REL-03 | M | `api` and `worker` expose liveness/readiness endpoints and Prometheus metrics about themselves. | Endpoint tests |
| NT-REL-04 | M | Re-processing a scan job does not create duplicate findings (unique `(scan_id, fingerprint)`). | Idempotency test |
| NT-REL-05 | M | If Prometheus is unavailable, monitoring views show an error state while scanning, findings, and AI continue to work; the reverse also holds. | Chaos test (stop container) |
| NT-SEC-01 | M | Passwords hashed with Argon2id; access tokens ≤ 15 minutes; refresh sessions ≤ 7 days and revocable **[P]**. | Unit + integration tests |
| NT-SEC-02 | M | Repository tokens and API keys are encrypted at rest or supplied only via environment; never logged, never returned by the API. | Log/response scanning test |
| NT-SEC-03 | M | In `production` mode the deployment requires TLS termination and secure cookie flags. | Config check |
| NT-SEC-04 | S | Login attempts are rate-limited (proposed: 5 failures per 15 minutes per account and IP). | Integration test |
| NT-SEC-05 | M | Sandbox containers run non-root, unprivileged, with CPU/memory/time limits and a default seccomp profile; network is disabled during test execution. | Sandbox escape-attempt checklist |
| NT-SEC-06 | M | All inputs validated by schemas; subprocess arguments built from allowlisted fragments, never by shell string interpolation. | Static analysis + fuzz test |
| NT-SEC-07 | S | The Toolkit's own CI scans its dependencies (Trivy) and source (Semgrep) and fails on `critical` findings. | CI configuration |
| NT-SEC-08 | M | Logs redact tokens, passwords, and `Authorization` headers. | Log review test |
| NT-SEC-09 | M | Outbound requests from API/worker go only to allowlisted hosts; webhook URLs reject private/loopback ranges unless an admin explicitly permits them. | SSRF test cases |
| NT-AI-01 | M | A recommendation is labeled `validated` only if every automated check in FR-AI-04 passes. | Golden-set audit (SM-06) |
| NT-AI-02 | M | Only the evidence pack and fixed instructions are sent to the model; no full repository or credentials. | Request-body inspection test |
| NT-USA-01 | M | A first-time user completes onboarding (UC-01) in ≤ 10 minutes using the README (SM-01). | Usability session |
| NT-USA-02 | S | Primary flows are keyboard-operable and use sufficient colour contrast (target: WCAG 2.1 AA) **[A]**. | Manual checklist + automated a11y lint |
| NT-MNT-01 | M | Backend core modules (scanning, alerting, AI validation, remediation) reach ≥ 70 % line coverage; CI runs lint and type checks. | CI report |
| NT-MNT-02 | S | OpenAPI generated from code matches [API_SPEC](API_SPEC.md) (contract test). | CI contract test |
| NT-OBS-01 | M | Logs are structured JSON with `request_id` or `job_id`. | Log schema test |
| NT-OBS-02 | S | Job counts, durations, and failures per type are exported as metrics. | Metrics endpoint test |
| NT-PORT-01 | M | `docker compose up` brings up the stack on Linux, macOS, and Windows with WSL2 **[A]**. | Fresh-machine run |
| NT-DATA-01 | S | Retention periods are configurable with defaults in [DATA_MODEL §7](DATA_MODEL.md#7-retention). | Retention job test |
| NT-DATA-02 | S | A documented backup/restore procedure exists for PostgreSQL. | Restore drill |
| NT-LIC-01 | S | A license inventory of direct dependencies is maintained; incompatible licenses are flagged (UD-01). | CI license report |
| NT-CAP-01 | M | Design envelope: ≤ 20 projects, ≤ 50 monitoring targets, ≤ 5 concurrent jobs per deployment. Larger loads are unsupported, not guaranteed. | Stated limit |

## 10. Entry and exit criteria

| Milestone | Exit criteria (tests) |
|---|---|
| M0 | CI green; spike outcomes recorded (UD-02, UD-03, UD-06); fixtures verified by a second member |
| M1 | AT-FR-AUTH-*, AT-FR-PRJ-01..05, AT-FR-MON-01..04, AT-FR-ALR-01..05, AT-FR-ALR-08 pass; SM-03 and SM-04 results recorded; RT-02 passes |
| M2 | AT-FR-DEP-01..05, 07, 09; AT-FR-SAST-01, 03; AT-FR-DSH-01..06 pass; SM-02 recorded; RT-03, RT-04 pass |
| M3 | AT-FR-AI-01..06, 10, 11 pass; SM-06 audit and \( \text{Catch} \) recorded; SC-11 passes |
| M4 | AT-FR-REM-01..08, 12 pass; SM-05, SM-07 verified; SC-07..SC-10 pass; RT-06, RT-07 pass |
| M5 | All Must AT-* and NT-* pass or have a recorded, accepted deviation; SC-01..SC-15 done; SM-01 usability session recorded |

**Quality gates for merging a PR:** unit + integration suites green; lint and type checks pass; no new `critical` finding in Trivy/Semgrep on the Toolkit repository; coverage for backend core modules not below the NFR-MNT-01 target; changed endpoints reflected in OpenAPI and API_SPEC.

## 11. Defects and flaky tests

Severity: **S1** safety invariant, security, or data-loss defect (blocks merge/release); **S2** a Must requirement fails; **S3** a Should requirement fails or a workaround exists; **S4** cosmetic. A test that fails intermittently is quarantined within one working day, tracked with an owner, and fixed or deleted within one week; quarantined tests are listed in the PR template. Sandbox-dependent tests use explicit markers and fail loudly (not silently skip) when run in an environment that claims remediation is enabled.

## 12. Measurement definitions

| Metric | Definition |
|---|---|
| Seeded-vulnerability recall (SM-02) | \( \text{Recall}_{dep} = \lvert D \cap S \rvert / \lvert S \rvert \), where \( S \) is the manifest of seeded vulnerable versions and \( D \) the set the Toolkit reports (matched by package, version, and advisory alias) |
| Detection time (SM-03) | \( T_{detect} = t_{alert} - t_{fault} \), with \( t_{fault} \) the logged injection time and \( t_{alert} \) the alert `first_seen_at`; compared with \( T_{ingest} + N \cdot \Delta_{eval} \) using measured \( T_{ingest} \) |
| Alert noise (SM-04) | Count of alerts created during a 60-minute constant-load, fault-free run |
| Backend coverage (NFR-MNT-01) | Line coverage of scanning, alerting, AI validation, and remediation packages from the CI coverage report |
