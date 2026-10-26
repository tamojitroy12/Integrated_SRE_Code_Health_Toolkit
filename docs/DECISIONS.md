# Decisions

> **Doc:** DECISIONS.md · **Version:** 0.2 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** [ARCHITECTURE](ARCHITECTURE.md), [TRD](TRD.md), [ROADMAP](ROADMAP.md)

This file records significant architectural and product decisions (`DEC-nnn`) and decisions the team still has to make (`UD-nn`). Status values: **Proposed** (documentation author's recommendation, not yet team-approved), **Accepted** (agreed by the team; none are accepted yet except where a requirement already forces it), **Superseded**. Changing a decision requires a new row; old rows are never deleted.

## 1. Decision log

| ID | Decision | Status | Revisit when |
|---|---|---|---|
| DEC-001 | Monorepo; one Python package `toolkit` provides both the API and the worker entrypoints | Proposed | Worker needs a different runtime |
| DEC-002 | PostgreSQL is the only relational store | Proposed | Never expected in MVP |
| DEC-003 | Job queue is a PostgreSQL table using `FOR UPDATE SKIP LOCKED` and leases | Proposed | > 5 concurrent jobs needed (NFR-CAP-01) |
| DEC-004 | OTLP metrics → OTel Collector → Prometheus; metrics only | Proposed | UD-06 spike result; traces needed |
| DEC-005 | Alert evaluation runs in the worker against Prometheus; no Alertmanager in MVP | Proposed | Need silencing/routing (FR-ALR-07) |
| DEC-006 | Trivy is the primary inventory + vulnerability source; OSV API is cross-check and advisory enrichment | Proposed | SP-03 spike shows one tool suffices |
| DEC-007 | Semgrep Community Edition engine is the static analyzer | Proposed | UD-01 licensing outcome |
| DEC-008 | Claude via the Anthropic SDK; AI is advisory; model id from `CLAUDE_MODEL` | Proposed | Budget (UD-05) or validator weakness |
| DEC-009 | GitHub only; fine-grained personal access token | Proposed | UD-02 spike result |
| DEC-010 | Remediation executes only in a dedicated, isolated container daemon | Proposed | UD-03 spike result |
| DEC-011 | The Toolkit never merges; draft PRs are created only after recorded human approval | **Accepted** (forced by FR-REM-06/07, SM-07) | Never |
| DEC-012 | MVP ecosystems are npm and PyPI | Proposed | Team capacity |
| DEC-013 | Local accounts (Argon2id, JWT access + refresh) with global roles `viewer/maintainer/admin` | Proposed | Need SSO |
| DEC-014 | Single-tenant deployment; one deployment-wide OTLP ingest token | Proposed | Need per-target tokens |
| DEC-015 | Next.js App Router + TypeScript; job status via polling (not WebSockets/SSE) | Proposed | UX needs live push |
| DEC-016 | Team size is 4 students, 14 weeks, focus factor f = 0.4 (~15h/wk); capacity is ~112 person-days; align scope using ROADMAP §5 cut ladder (npm first, defer PyPI remediation) | **Accepted** | Never |

## 2. Decision records

Each record: **Context → Decision → Rationale → Trade-offs → Alternatives**.

### DEC-001 Monorepo with one Python package
- **Context:** Small team; API and worker share models, adapters, and validators.
- **Decision:** `api/toolkit/` is one package; `api` and `worker` are two commands from one image.
- **Rationale:** One dependency set, one test suite, no cross-service contracts to version.
- **Trade-offs:** API and worker scale together; a bug in a shared module affects both.
- **Alternatives:** Separate services (more isolation, more overhead); Node worker (splits languages).

### DEC-002 PostgreSQL
- **Context:** Relational data with JSON evidence, partial unique indexes (FR-ALR-03), concurrent job claiming.
- **Decision:** PostgreSQL only.
- **Rationale:** Partial indexes, JSONB, `SKIP LOCKED`, wide student familiarity.
- **Trade-offs:** One more container than SQLite.
- **Alternatives:** SQLite (weak concurrency for queue + API); MySQL (no partial indexes).

### DEC-003 Postgres-backed job queue
- **Context:** Durable async jobs needed (NFR-REL-01); capacity is small (NFR-CAP-01).
- **Decision:** `job` table, `SELECT … FOR UPDATE SKIP LOCKED`, leases with a reaper, max 3 attempts.
- **Rationale:** No broker to run, secure, or monitor; transactional enqueue with the business row.
- **Trade-offs:** Polling latency (≈ seconds); not suited to high throughput.
- **Alternatives:** Redis + RQ/Arq/Celery (extra service, more failure modes).

### DEC-004 OTLP → Collector → Prometheus, metrics only
- **Context:** The brief names OpenTelemetry and Prometheus. Alerts need request-rate, error-ratio, and latency series.
- **Decision:** Apps push OTLP metrics with a bearer token to the Collector; the Collector forwards to Prometheus by remote write; the Prometheus remote-write receiver must be enabled **[V]**.
- **Rationale:** Collector is the single authentication/validation point and leaves room for traces/logs later. Remote write preserves sample timestamps better than scrape-based export for push sources **[A]**.
- **Trade-offs:** Three moving parts; metric/label-name translation is version-sensitive (UD-06).
- **Alternatives:** Prometheus native OTLP receiver (fewer components; the flag exists **[V]** but there is no built-in auth in front of it **[A]**); Collector Prometheus exporter + scrape (simpler, holds series for an expiry period).

### DEC-005 In-app alert evaluation
- **Context:** Alerts need lifecycle, evidence snapshots, and dashboard integration.
- **Decision:** The worker runs allowlisted PromQL every \( \Delta_{eval} \) and manages alert state in PostgreSQL.
- **Rationale:** One source of truth for alert state/evidence; no Alertmanager routing configuration for students to learn.
- **Trade-offs:** We re-implement a small subset of Alertmanager (dedupe, resolve); no inhibition/silencing in MVP.
- **Alternatives:** Prometheus alerting rules + Alertmanager webhook into the API.

### DEC-006 Trivy primary, OSV cross-check
- **Context:** Both tools can match packages to advisories; they differ in data sources and fix-version detail.
- **Decision:** Run both; merge by advisory alias set; keep provenance per finding (FR-DEP-03/04).
- **Rationale:** Two sources reduce missed findings and expose disagreements; OSV supplies full advisory records and ranges **[V]**.
- **Trade-offs:** Normalization effort; duplicates must be merged correctly.
- **Alternatives:** OSV-Scanner alone (evaluate in SP-03); Trivy alone (simpler, single source).

### DEC-007 Semgrep CE
- **Context:** Multi-language static analysis with JSON output.
- **Decision:** Use the CE engine (LGPL 2.1 **[V]**) with rules selected under UD-01.
- **Rationale:** Declarative rules, low setup effort.
- **Trade-offs:** Semgrep-maintained rules are under a license that bars use in competing products/SaaS **[V]**; legal fit for the course project is the team's call.
- **Alternatives:** Opengrep; own rule set; other linters per language.

### DEC-008 Claude, advisory only
- **Context:** The brief requires LLM recommendations grounded in evidence.
- **Decision:** Anthropic SDK; no tools given to the model; output is validated data; model id from configuration.
- **Rationale:** Smallest attack surface; swapping models is a config change.
- **Trade-offs:** The model cannot fetch more evidence itself; the Toolkit must assemble the pack.
- **Alternatives:** Tool-using agent (rejected: violates CON-05); local model (resource-heavy).

### DEC-009 GitHub with fine-grained PAT
- **Context:** Need clone, branch, draft PR.
- **Decision:** Fine-grained PAT, scoped to selected repositories, stored encrypted.
- **Rationale:** Least setup effort for students; per-repo scoping.
- **Trade-offs:** Tokens are tied to a person and expire; a GitHub App has better least-privilege and rotation.
- **Alternatives:** GitHub App (UD-02), OAuth app.

### DEC-010 Isolated container daemon for remediation
- **Context:** Remediation runs untrusted dependency installs and tests (CON-06).
- **Decision:** Separate, isolated Docker daemon reachable only by the worker over an internal network; never the host socket.
- **Rationale:** Mounting the host Docker socket is equivalent to host root.
- **Trade-offs:** Highest implementation risk in the project (UD-03); may be infeasible on some laptops.
- **Alternatives:** Rootless Podman; gVisor/Firecracker (too heavy); plan-only mode (no execution).

### DEC-011 No merging; approval gate
- **Decision:** No merge capability exists in the Git adapter; PRs are drafts; an approval row precedes any push.
- **Rationale:** Direct requirement (project brief; FR-REM-06/07; SM-07).
- **Trade-offs:** Slower than full automation, intentionally.

### DEC-012 npm and PyPI only
- **Decision:** Two ecosystems cover most student projects; each needs its own parser, registry adapter, and sandbox pipeline.
- **Trade-offs:** Java, Go, Rust, etc. unsupported.

### DEC-013 Local authentication, global roles
- **Decision:** Email/password, Argon2id, short-lived JWT + revocable refresh session; three global roles.
- **Trade-offs:** No per-project permissions, no SSO.

### DEC-014 Single tenant, one ingest token
- **Decision:** One deployment = one team. The Collector validates one shared token; targets are distinguished by `service_name` + `environment`.
- **Trade-offs:** A leaked token lets anyone send metrics for any service name; mitigated by rotation (documented in DEPLOYMENT) and network placement. Per-target tokens are post-MVP.

### DEC-015 Next.js with polling
- **Decision:** App Router, TypeScript; poll `GET /jobs/{id}` (see [API_SPEC §4](API_SPEC.md#4-asynchronous-jobs)).
- **Rationale:** Polling is stateless, simple to test, and adequate for jobs lasting seconds to minutes.
- **Alternatives:** Vite SPA (also acceptable); SSE/WebSockets later.

### DEC-016 Team size, capacity, and scope cut
- **Context:** The team consists of 4 students working over a 14-week term with an average commitment of ~15 hours/week per student (focus factor \( f = 0.4 \)). Total available capacity is \( C = 4 \times 14 \times 5 \times 0.4 = 112 \) person-days against an estimated full Must scope of 205 person-days.
- **Decision:** Formally adopt the capacity boundary of 112 person-days and execute the scope-cut ladder from [ROADMAP §5](ROADMAP.md#5-scope-cut-ladder): prioritize core telemetry monitoring and npm dependency vulnerability scanning/remediation; defer PyPI remediation pipeline (`T-09.06`) and non-essential Should/Could tasks to maintain quality and high test coverage.
- **Rationale:** Aligns scope with realistic team capacity while preserving all core course demonstration objectives.
- **Trade-offs:** PyPI automated remediation is deferred in favor of npm full-stack remediation.

## 3. Unresolved decisions (need team input)

Owners and dates are **proposals**; the team sets the real ones. Phases are defined in [ROADMAP](ROADMAP.md).

| ID | Question | Options | Recommendation | Needed by | Status |
|---|---|---|---|---|---|
| UD-01 | Project license, and how to comply with Semgrep rule licensing | (a) Own license MIT/Apache-2.0 + use Semgrep CE with rules for internal use only; (b) write own rules/use permissively licensed rule sets; (c) switch to Opengrep | Choose (a) for the course project, document the restriction, and revisit before any commercial hosting. Not legal advice; ask the course supervisor if unsure. | End of Phase 0 | Unresolved |
| UD-02 | GitHub authentication model | Fine-grained PAT vs GitHub App | PAT for MVP; record GitHub App as post-MVP | End of SP-04 (Phase 0) | Unresolved |
| UD-03 | Sandbox runtime | Rootless Docker-in-Docker; rootless Podman; no execution (plan-only) | Run SP-02 on every team laptop; if any common platform fails, ship plan-only mode and flag `REMEDIATION_ENABLED=false` | End of Phase 0 (go/no-go) | Unresolved |
| UD-04 | Demo hosting | Local laptop only; a single cloud VM | Local laptop with recorded fallback demo | Phase 4 | Unresolved |
| UD-05 | Claude model tier and budget cap | Mid-tier default vs smaller/cheaper tier | Start with the default in `CLAUDE_MODEL`; set `AI_DAILY_REQUEST_CAP`; measure token use on the golden set before choosing | Phase 3 | Unresolved |
| UD-06 | Prometheus ingestion path and label names | Collector remote write; Collector exporter + scrape; native OTLP receiver | Run SP-01; pick the path that yields stable `service_name` labels and clean staleness behavior | End of Phase 0 | Unresolved |
| UD-07 | Test-command discovery for fix validation | User-specified only; auto-detect (`npm test`, `pytest`); both | User-specified with allowlisted patterns, auto-detect as a suggestion | Phase 4 start | Unresolved |
| UD-08 | Team size and calendar | 4–5 people, 14 weeks assumed | Confirmed: 4 students, 14 weeks, f = 0.4, 112 person-days. Scope cut ladder adopted per DEC-016. | Week 1 | **Resolved (DEC-016)** |

## 4. Superseded decisions

None.
