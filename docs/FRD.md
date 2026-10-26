# Functional Requirements Document (FRD)

> **Doc:** FRD.md · **Version:** 0.1 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** [PRD](PRD.md), [SRS](SRS.md), [WORKFLOW](WORKFLOW.md), [API_SPEC](API_SPEC.md)

**Ownership rule:** the FRD is the single source of truth for *functional* requirements (`FR-*`). The [SRS](SRS.md) owns non-functional requirements (`NFR-*`), interface requirements (`IF-*`), constraints (`CON-*`), and the traceability matrix. Every FR has a derived acceptance-test ID `AT-<FR-ID>` (e.g., `AT-FR-DEP-01`) defined in `TEST_STRATEGY.md` (batch 2).

Priority: **M** Must (MVP) · **S** Should · **C** Could (post-MVP) · **W** Won't (this release).

## 1. Roles

| Role | Capabilities |
|---|---|
| `admin` | Everything; manage users, credentials, notification channels, system settings. |
| `maintainer` | Create/edit projects, trigger scans/AI/fix proposals, approve fix proposals, manage alert rules, acknowledge alerts. |
| `viewer` | Read-only access to dashboards, findings, alerts, recommendations. |

## 2. User stories

| ID | As a… | I want to… | So that… | FRs |
|---|---|---|---|---|
| US-01 | admin | sign in and create accounts for teammates | the team can share one deployment | FR-AUTH-01..03 |
| US-02 | maintainer | create a project and connect my GitHub repository | I can scan it | FR-PRJ-01, 02 |
| US-03 | maintainer | register a running service and get instrumentation steps | metrics start flowing | FR-PRJ-03, 04, FR-MON-01 |
| US-04 | on-call engineer | see request rate, error ratio, and latency for a service | I understand its current health | FR-MON-02, 03 |
| US-05 | on-call engineer | be notified when error ratio or latency crosses a threshold | I can react before users complain | FR-ALR-01..05 |
| US-06 | on-call engineer | see the evidence behind an alert | I can judge whether it is real | FR-ALR-04 |
| US-07 | maintainer | scan a repository for vulnerable and outdated dependencies | I know my supply-chain risk | FR-DEP-01..05 |
| US-08 | maintainer | know when a scanner provider failed | I do not trust an incomplete "clean" result | FR-DEP-07 |
| US-09 | maintainer | see static-analysis findings with file and line | I can fix code issues | FR-SAST-01..03 |
| US-10 | maintainer | dismiss a false positive with a reason | noise does not return every scan | FR-SAST-04 |
| US-11 | maintainer | ask for a recommendation on a finding | I get alternatives or improvements | FR-AI-01..05 |
| US-12 | maintainer | see which evidence supports each AI claim | I can verify it | FR-AI-02..05 |
| US-13 | maintainer | have the Toolkit prepare a dependency fix and test it | I do not upgrade blindly | FR-REM-01..05 |
| US-14 | maintainer | review the diff and test report before anything is pushed | I stay in control | FR-REM-06 |
| US-15 | maintainer | get a draft PR I can merge or close on GitHub | the change goes through normal review | FR-REM-07 |
| US-16 | any user | see runtime and repo health on one page | I do not switch tools | FR-DSH-01 |
| US-17 | admin | run the Toolkit with AI turned off | I avoid external data sharing | FR-AI-06 |

## 3. Use cases

### UC-01 Onboard a project with repository and monitoring target
- **Actor:** maintainer. **Preconditions:** signed in; GitHub URL known; app can set environment variables.
- **Main flow:** (1) Create project. (2) Connect repository; system verifies access, detects default branch and ecosystems. (3) Register monitoring target; system shows snippet. (4) User configures the app; target status becomes `receiving`.
- **Alternatives:** 2a. Verification fails (`401/403/404`) → error shown, nothing stored. 4a. No samples within `TARGET_STALE_AFTER_SECONDS` → status stays `waiting` with troubleshooting hints.
- **Postconditions:** project has ≥ 1 of {repository, target}.

### UC-02 Detect and respond to an operational failure
- **Actor:** on-call engineer. **Main flow:** (1) Rule evaluation observes breach for the required duration. (2) Alert created `firing`; notification sent. (3) Engineer opens alert, reads evidence, acknowledges. (4) Condition clears; alert auto-resolves.
- **Alternatives:** 2a. Notification delivery fails → delivery record `failed`, alert still visible. 4a. Engineer resolves manually.

### UC-03 Scan a repository
- **Actor:** maintainer. **Main flow:** (1) Trigger scan (ref optional). (2) System queues job; returns `202`. (3) Worker clones, inventories, queries providers, runs Semgrep. (4) Findings normalized and compared with the previous scan. (5) Dashboard shows summary.
- **Alternatives:** 3a. A provider fails → scan `partial`, provider status shown. 3b. Timeout → scan `failed` with reason.

### UC-04 Obtain an evidence-grounded recommendation
- **Actor:** maintainer. **Main flow:** (1) Select a finding, request recommendation. (2) System builds evidence pack from stored data and registry metadata. (3) Claude returns structured JSON. (4) Validator checks schema, evidence references, and package/version existence. (5) UI shows recommendation, evidence, validation badge, limitations.
- **Alternatives:** 4a. Validation fails → recommendation stored as `rejected` with reasons; shown only in a collapsed "rejected output" panel. 1a. AI disabled → `409 AI_DISABLED`.

### UC-05 Fix a vulnerable dependency via draft PR
- **Actor:** maintainer. **Main flow:** (1) Choose findings, request fix proposal. (2) System generates deterministic change plan; sandbox runs baseline tests, applies change with scripts disabled, re-runs tests, re-scans. (3) Maintainer reviews diff + report, approves. (4) System pushes `toolkit/fix/<id>` and opens a draft PR. (5) Maintainer merges on GitHub.
- **Alternatives:** 2a. Baseline tests absent/failing → `validation_result = unverified`; approval requires explicit acknowledgment. 2b. Tests fail after change → `failed`; approval blocked unless admin overrides (FR-REM-12). 3a. Reject → proposal `rejected`.

## 4. Functional requirements

Acceptance criteria are written to be testable. "Seeded" refers to `examples/` fixtures.

### 4.1 Authentication and authorization (EP-01)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-AUTH-01 | On first start with no users, the system shall create an admin from bootstrap variables; afterwards only admins create users. | M | Bootstrap runs once; second start does not change credentials; non-admin `POST /users` returns `403`. |
| FR-AUTH-02 | Users shall authenticate with email and password and receive a short-lived access token and a refresh mechanism. | M | Wrong password returns `401 INVALID_CREDENTIALS`; expired access token returns `401`; refresh issues a new token; logout revokes the refresh session. |
| FR-AUTH-03 | The API shall enforce role permissions server-side on every endpoint. | M | Role–endpoint matrix in `API_SPEC.md` is covered by automated tests: viewer cannot mutate, maintainer cannot manage users. |
| FR-AUTH-04 | Security-relevant actions shall be written to an audit log. | S | Login success/failure, credential create/delete, scan trigger, fix approval, PR creation each produce an `audit_log` row with actor and timestamp. |

### 4.2 Projects and onboarding (EP-02)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-PRJ-01 | Maintainers shall create, view, edit, and archive projects. | M | CRUD via API/UI; archived projects are hidden by default and read-only. |
| FR-PRJ-02 | A maintainer shall connect one GitHub repository to a project, optionally with a token, and the system shall verify access and detect ecosystems from manifests. | M | Valid repo → `verified_at` set, `ecosystems` ⊆ {npm, pypi}; invalid URL → `422 VALIDATION_ERROR`; GitHub 401/403/404 for the repository or token → `422 REPO_ACCESS_DENIED` / `REPO_NOT_FOUND`; token stored encrypted, never returned by any endpoint. |
| FR-PRJ-03 | A maintainer shall register monitoring targets and receive generated onboarding instructions. | M | Response includes OTLP endpoint, required environment variables, and a token *reference* (not the token value unless the requester is an admin). |
| FR-PRJ-04 | The system shall display target status `waiting`, `receiving`, or `stale`. | M | Status derived from last sample time; transitions verified with a simulated sender. |
| FR-PRJ-05 | A project shall function with only a repository, only targets, or both. | M | Overview page renders the missing section as an empty state with a call to action, without errors. |
| FR-PRJ-06 | The system should provide a seeded demo project. | S | One command seeds a project linked to `examples/` fixtures. |

### 4.3 Live monitoring (EP-03)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-MON-01 | The collector shall accept OTLP metrics only with a valid ingest token. | M | Request without/with wrong token is rejected and writes nothing; valid token is accepted. |
| FR-MON-02 | The dashboard shall chart request rate, error ratio, latency p50/p95/p99, and target status for a selectable range (15 min, 1 h, 6 h, 24 h). | M | Charts match PromQL results for the seeded demo traffic within tolerance defined in `TEST_STRATEGY.md`. |
| FR-MON-03 | The system shall compute availability SLI and error ratio per window (formula in [TRD](TRD.md) §6.1). | M | Unit test with fixed counter series reproduces expected values. |
| FR-MON-04 | The monitoring engine shall evaluate alert rules every `ALERT_EVAL_INTERVAL_SECONDS`. | M | Evaluation timestamps spaced by the interval ±1 s in a test clock. |
| FR-MON-05 | The system should support z-score anomaly rules on request rate and latency with consecutive-breach confirmation (TRD §6.2). | S | Synthetic series with an injected step change triggers within \( N \cdot \Delta_{eval} \); stationary noise series does not. |
| FR-MON-06 | The system should support Prometheus scrape targets (`/metrics`). | S | A target in scrape mode appears in Prometheus targets and the dashboard. |
| FR-MON-07 | The dashboard could display runtime/host metrics when instrumentation provides them. | C | Not required for MVP. |
| FR-MON-08 | Traces and logs ingestion are not supported in this release. | W | Documented limitation. |

### 4.4 Alerting (EP-04)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-ALR-01 | Maintainers shall create, edit, enable/disable, and delete alert rules (`threshold`, `absence`; `anomaly` per FR-MON-05). | M | Validation rejects unknown metrics, non-positive durations, and thresholds outside metric range. |
| FR-ALR-02 | Alerts shall follow `firing → acknowledged → resolved`, auto-resolving after the condition is clear for `resolve_after` evaluations. | M | State-machine tests cover all transitions and illegal transitions (`409`). |
| FR-ALR-03 | There shall be at most one non-resolved alert per rule and target. | M | Repeated breaches update `last_seen_at` and `occurrence_count`, not create new alerts. |
| FR-ALR-04 | Each alert shall store evidence: PromQL used, observed value, threshold, evaluation window, and a static guidance text from the rule template. | M | Alert detail shows all five fields; none is empty. |
| FR-ALR-05 | The system shall send notifications through at least a generic webhook channel. | M | Test receiver gets a JSON payload on `firing` and `resolved`. |
| FR-ALR-06 | The system should rate-limit notifications (cooldown) and record delivery attempts. | S | Second notification within cooldown is suppressed and logged. |
| FR-ALR-07 | Silencing/maintenance windows could be supported. | C | Post-MVP. |
| FR-ALR-08 | A target with no samples for longer than `TARGET_STALE_AFTER_SECONDS` shall raise a `data_absent` alert if such a rule is enabled. | M | Stopping the demo app produces the alert; restart resolves it. |

### 4.5 Dependency scanning (EP-05)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-DEP-01 | A maintainer shall trigger an asynchronous scan of a repository at the default branch or a given ref; the scan shall record the commit SHA. | M | `POST …/scans` returns `202` with job ID; scan row stores resolved SHA. |
| FR-DEP-02 | The system shall inventory direct and transitive dependencies for npm and PyPI from manifests/lockfiles. | M | Seeded repo inventory equals expected list (name, version, ecosystem, scope, manifest path). |
| FR-DEP-03 | The system shall detect known vulnerabilities using Trivy and the OSV API and normalize them to findings with advisory IDs/aliases, severity, affected package/version, and fixed versions when provided. | M | Seeded vulnerable versions appear as findings; each has ≥ 1 advisory ID and a provenance list. |
| FR-DEP-04 | Findings from different providers describing the same package version and advisory (matched by alias set) shall be merged, retaining provenance. | M | Same CVE/GHSA from both providers yields one finding with two sources. |
| FR-DEP-05 | The system shall classify outdated dependencies by comparing the installed version with the latest stable version from the registry (patch/minor/major lag). | M | Seeded outdated packages classified correctly; registry failure marks provider `failed`, not "up to date". |
| FR-DEP-06 | The system should flag potential incompatibility: major-version change, declared runtime constraint mismatch (npm `engines`, PyPI `requires_python`), and registry-declared deprecation. Output is labeled heuristic. | S | Fixtures for each heuristic produce `dependency_incompatibility` findings with the rule name in evidence. |
| FR-DEP-07 | Each provider's outcome shall be recorded; if any provider fails the scan status shall be `partial` and the UI shall show which provider failed. | M | Fault-injected provider timeout yields `partial`; no "all clear" message is displayed. |
| FR-DEP-08 | The system should support scheduled rescans (default daily, configurable). | S | Scheduler enqueues scans; manual and scheduled scans use identical code paths. |
| FR-DEP-09 | After each scan the system shall label findings `new`, `unchanged`, or `resolved` relative to the previous completed scan of the same project. | M | Two consecutive scans with one dependency bumped show one `resolved`, others `unchanged`. |

### 4.6 Static analysis (EP-06)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-SAST-01 | The system shall run Semgrep on the cloned repository and convert results to `code_issue` findings (rule ID, severity, file, line range, message, bounded snippet). | M | Seeded insecure patterns reported with correct file and line. |
| FR-SAST-02 | The system should allow a repository-local rules directory in addition to default rule sets, with explicit user opt-in. | S | Opt-in flag required; rules loaded only when enabled. |
| FR-SAST-03 | Scans shall enforce a timeout, maximum file size, and default exclusions (`.git`, `node_modules`, `dist`, `build`, virtualenvs). | M | Oversized/excluded paths produce no findings; timeout yields failed provider run with reason. |
| FR-SAST-04 | Maintainers shall dismiss findings with reason (`false_positive`, `accepted_risk`, `wont_fix`); dismissals persist across scans via fingerprint. | S | Dismissed finding stays dismissed on rescan unless fingerprint changes. |

### 4.7 AI recommendations (EP-08)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-AI-01 | A maintainer shall request an AI recommendation of kind `library_alternative`, `upgrade_guidance`, or `code_improvement` for a specific finding as an asynchronous job. | M | Request for unsupported kind/finding combination returns `422`. |
| FR-AI-02 | The system shall construct an **evidence pack** exclusively from stored findings, advisory data, registry metadata, and a bounded code snippet; each item receives an evidence ID. | M | Pack contents logged by hash; no item without a source URL or stored record. |
| FR-AI-03 | The model shall be instructed to return JSON conforming to a schema in which every claim lists `evidence_refs`. | M | Non-conforming output is rejected after at most one repair attempt. |
| FR-AI-04 | The validator shall reject or downgrade recommendations containing: unknown evidence IDs, non-existent package names or versions (checked against registry), fixed-version claims contradicting advisory data, or patches that fail `git apply --check`. | M | Fault-injected hallucinated package yields `rejected`; all-valid output yields `validated`; mixed yields `partially_validated` with per-claim status. |
| FR-AI-05 | The UI shall show evidence links, validation badge, qualitative confidence, limitations, and an "AI-generated, advisory" label. | M | UI test asserts presence of all five elements. |
| FR-AI-06 | Secrets and obvious credentials shall be redacted from snippets before sending; if redaction is uncertain the snippet shall be omitted; AI shall be fully optional. | M | Seeded fake secret never appears in the outbound request body; `AI_ENABLED=false` leaves other features working. |
| FR-AI-07 | Library-alternative recommendations should include verifiable criteria from registry metadata (latest version, release date, license, repository URL, deprecation flag). | S | Each alternative lists these fields with source evidence IDs. |
| FR-AI-08 | Users should be able to rate a recommendation. | S | Feedback stored; no effect on validation. |
| FR-AI-09 | AI summarization of an alert strictly from alert evidence could be supported. | C | Post-MVP. |
| FR-AI-10 | The system shall enforce an input-size limit and a daily request cap and record token usage per job. | M | Over-cap request returns `429 AI_BUDGET_EXCEEDED`. |
| FR-AI-11 | Repository content and scanner text shall be treated as untrusted data: delimited in the prompt, never interpreted as instructions, and model output shall never be executed. | M | Injection fixtures (comments saying "ignore previous instructions") do not alter schema-valid output semantics in the golden test set. |

### 4.8 Automated remediation (EP-09)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-REM-01 | Maintainers shall request a fix proposal for selected dependency findings that have a known fixed version or a patch/minor update; the change plan is generated by deterministic code, not the LLM. | M | Plan lists package, from-version, to-version, manifest/lockfile paths. |
| FR-REM-02 | Proposals shall execute in an isolated sandbox: non-root, CPU/memory/time limits, no host mounts except an ephemeral workspace, no access to Toolkit secrets. | M | Sandbox test shows secrets and host paths are unreachable. |
| FR-REM-03 | Dependency resolution shall use allowlisted package-manager commands with lifecycle scripts disabled, preserve the lockfile format, and modify only manifest and lockfile paths. | M | Diff touching any other path aborts the proposal (`DIFF_SCOPE_VIOLATION`). |
| FR-REM-04 | The system shall run the repository's test command before (baseline) and after the change, the latter with networking disabled, and store both outcomes. | M | Both runs recorded with exit code, duration, and truncated output. |
| FR-REM-05 | The system shall re-scan after the change and confirm targeted findings are resolved and no new `critical`/`high` vulnerability is introduced. | M | Delta report stored in the proposal. |
| FR-REM-06 | The dashboard shall present the diff, validation report, and risk notes; no remote write shall occur before an explicit approval by a `maintainer` or `admin`. | M | Attempting PR creation without approval returns `409 APPROVAL_REQUIRED`. |
| FR-REM-07 | On approval the system shall push a branch named `toolkit/fix/<proposal-id>` and open a **draft** PR with evidence, test results, and risk notes; it shall never push to the default branch and never merge. | M | Integration test against a sandbox GitHub repository; branch protection violations impossible by construction (code rejects other branch names). |
| FR-REM-08 | Only allowlisted commands with validated arguments shall run; no model output shall be executed. | M | Fuzz test of package names/versions rejects shell metacharacters. |
| FR-REM-09 | Major-version upgrades should be marked high-risk, require an explicit acknowledgment, and be labeled in the PR. | S | Approval without acknowledgment returns `409 ACK_REQUIRED`. |
| FR-REM-10 | The system should record the base commit SHA and be able to close the PR and delete the branch it created. | S | Cleanup endpoint tested; never touches branches without the `toolkit/fix/` prefix. |
| FR-REM-11 | Applying LLM-suggested code patches could be supported later using the same validation path. | C | Post-MVP. |
| FR-REM-12 | If baseline tests are missing or failing, `validation_result` shall be `unverified`; approval shall require acknowledgment. If post-change tests fail, `validation_result = failed` and approval shall be blocked for `maintainer` (admin override recorded in the audit log). | M | Behavior verified for all three outcomes. |

### 4.9 Unified dashboard (EP-07)

| ID | Requirement | Pri | Acceptance criteria |
|---|---|---|---|
| FR-DSH-01 | The project overview shall show monitoring summary, open alerts, latest scan summary (counts by type/severity, provider status), and top findings. | M | Renders with data, with one side empty, and with both empty. |
| FR-DSH-02 | The findings explorer shall filter and sort by type, severity, status, package, and file with pagination. | M | Filters combine with AND semantics; page size ≤ 100. |
| FR-DSH-03 | A finding detail page shall show evidence, history across scans, recommendations, and fix proposals. | M | All sections present or have explicit empty states. |
| FR-DSH-04 | The alerts page shall list and filter alerts and show alert detail with actions. | M | Acknowledge/resolve from UI updates state. |
| FR-DSH-05 | Job progress (queued/running/terminal state with error summary) shall be visible for scans, AI jobs, and fix proposals. | M | UI polls and stops on terminal state. |
| FR-DSH-06 | Every data view shall have defined loading, empty, and error states. | M | Checked by component tests (see [UI_UX_SPEC](UI_UX_SPEC.md), batch 2). |
| FR-DSH-07 | A timeline of alerts, scans, and PR events could be shown; it shall not imply causation. | S | Events ordered by time only; tooltip states "temporal order only". |
| FR-DSH-08 | Findings export (JSON/CSV) could be offered. | C | Post-MVP. |

## 5. Requirement counts

| Priority | Count |
|---|---|
| Must | 50 |
| Should | 14 |
| Could | 5 |
| Won't | 1 |
| **Total** | **70** |

(Counted by script against the tables above on 2026-10-13; re-run after any edit.)
