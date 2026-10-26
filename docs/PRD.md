# Product Requirements Document (PRD)

> **Doc:** PRD.md · **Version:** 0.1 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** [FRD](FRD.md), [SRS](SRS.md), [ARCHITECTURE](ARCHITECTURE.md), [README](../README.md)

Label legend (**[V]**, **[P]**, **[A]**, **[U]**) and MoSCoW priorities are defined in the [README](../README.md#documentation-conventions).

## 1. Product overview

The **Integrated SRE + Code Health Toolkit** (the "Toolkit") is a self-hosted, open-source system that gives small engineering teams one dashboard for:

- **Runtime health** of running applications (metrics, anomaly detection, alerts).
- **Repository health** (dependency vulnerabilities, outdated and potentially incompatible dependencies, static code issues).
- **Evidence-grounded AI advice** and **human-approved, sandbox-validated fix pull requests**.

The project description supplied by the team is the source of truth for *intent*. Nothing in this suite asserts that any capability already exists.

## 2. Problem statement

Smaller teams, student groups, and open-source maintainers typically juggle separate tools for application monitoring, dependency auditing, and code-quality analysis. Comprehensive commercial platforms can be expensive or restrictive **[A: team experience, not independently measured]**. The result is fragmented visibility, duplicated setup effort, and findings that are noticed late or never acted upon.

## 3. Target users (illustrative personas)

| ID | Persona | Context | Primary needs |
|---|---|---|---|
| P-01 | Student team developer | 3–6 people, one deployed course project, shared GitHub repo | Quick setup, visible alerts when the demo breaks, clear list of risky dependencies |
| P-02 | Open-source maintainer | Part-time, several repos, limited time | Low-noise vulnerability findings, reviewable fix PRs instead of manual upgrades |
| P-03 | Small-team on-call engineer ("SRE-lite") | Owns uptime of 1–5 services without a dedicated platform team | Actionable alerts with evidence, one place to see runtime and repo health |
| P-04 | Project admin | Installs and operates the Toolkit | Simple deployment, secret handling, user management |

## 4. User problems and value proposition

| Problem | Toolkit response | Goal |
|---|---|---|
| Tool sprawl and duplicated onboarding | One **Project** entity linking an optional repository and optional monitoring targets | G-01, G-05 |
| Alerts without context | Alerts carry the query, observed value, threshold, window, and static guidance text | G-02 |
| Long vulnerability lists with no path to fix | Findings → deterministic fix proposals → validated draft PRs | G-03 |
| LLM advice that may be invented | Evidence packs, structured output, validation gate, human review | G-04 |
| Fear of automated changes | No auto-merge, least-privilege tokens, sandboxing, explicit approval | G-03, G-04 |

**Value proposition:** *"Connect an app and a repo in minutes; see runtime and code health side by side; fix what is fixable through reviewed pull requests, with AI advice you can verify."*

## 4a. Goals

| ID | Goal |
|---|---|
| G-01 | Unified visibility of runtime and repository health per project. |
| G-02 | Actionable detection of operational failures. |
| G-03 | Trustworthy dependency hygiene with reviewable, validated fix PRs. |
| G-04 | AI recommendations grounded in verifiable evidence. |
| G-05 | Low barrier to entry: `docker compose up`, standard OpenTelemetry configuration. |
| G-06 | Scope that a 4-member student team can implement, test, and demonstrate within a 14-week term (~112 person-days capacity per DEC-016). |

## 5. Success criteria

The values below are **targets to be measured during acceptance testing**, not results. No benchmark outcome is claimed.

| ID | Metric | Definition / formula | Target | Method |
|---|---|---|---|---|
| SM-01 | Time to first metric | Minutes from fresh deployment to first chart for the demo app | ≤ 10 min for ≥ 3 evaluators unaided | Usability session |
| SM-02 | Seeded-vulnerability recall | \( \text{Recall}_{dep} = \frac{\lvert D \cap S \rvert}{\lvert S \rvert} \), where \( S \) is the set of seeded vulnerable dependency versions (each confirmed on osv.dev before testing, \( \lvert S \rvert \ge 10 \)) and \( D \) the set the Toolkit reports | ≥ 0.90 | Scan `examples/vulnerable-repo` |
| SM-03 | Fault detection time | \( T_{detect} \le T_{ingest} + N \cdot \Delta_{eval} \), where \( T_{ingest} \) is export interval plus pipeline delay, \( N \) the consecutive-evaluation confirmation count, \( \Delta_{eval} \) the evaluation interval | Holds for 10 injected 5xx faults | Fault injection in demo app |
| SM-04 | Alert noise | Count of alerts fired with default rules during a 60-minute healthy, constant-load run | 0 | Soak run |
| SM-05 | Validated fix PR | Fix PRs opened with `validation_result = passed` on demo repos | ≥ 1 for npm and ≥ 1 for PyPI | End-to-end test |
| SM-06 | Grounding integrity | Recommendations with `validation_status = validated` that contain an unsupported claim, on a manually audited golden set (≥ 30 items) | 0 | Manual audit + automated checks |
| SM-07 | Safety invariants | PRs created without a recorded human approval; pushes to a default branch; merges performed by the Toolkit | 0 / 0 / 0 | Integration tests + audit log review |

## 6. MVP scope

### 6.1 In scope (Must)

1. Local accounts with roles `admin`, `maintainer`, `viewer` (DEC-013).
2. Projects; GitHub repository connection; monitoring target registration with onboarding snippet.
3. OTLP metrics ingestion (token-protected) → Prometheus; charts for request rate, error ratio, latency percentiles, target status.
4. Threshold alert rules; alert lifecycle (`firing → acknowledged → resolved`); webhook notification.
5. On-demand repository scans for **npm** and **PyPI**: inventory, vulnerabilities (Trivy + OSV), outdated versions; Semgrep code findings.
6. Unified dashboard: project overview, findings explorer, finding detail, alerts, job progress.
7. AI recommendations (library alternatives, upgrade guidance, code improvement) with evidence pack, schema validation, and validation badge; AI can be disabled.
8. Dependency fix proposals generated deterministically (not by the LLM), validated in an isolated sandbox, approved by a human, delivered as a **draft** GitHub PR.

### 6.2 Should (included if schedule allows)

Z-score anomaly rules; Prometheus scrape mode; email notifications and cooldowns; incompatibility heuristics; scheduled rescans; custom Semgrep rule directory; major-upgrade confirmation; seeded demo project; activity timeline; findings export.

### 6.3 Out of scope for the first release

| Item | Reason |
|---|---|
| Distributed tracing and log ingestion | Adds storage/backends and UI; metrics suffice for the stated alert goals. |
| Automatic root-cause analysis linking metrics to code | Not supportable by evidence; explicitly avoided. |
| LLM-generated code patches applied automatically | Needs the same validation path as dependency fixes; deferred (FR-REM-11, Could). |
| Auto-merge of any change | Violates safety invariant SM-07. |
| Ecosystems beyond npm/PyPI; Git hosts beyond GitHub | Effort (DEC-012, DEC-009). |
| Multi-tenant SaaS, SSO/OIDC, billing | Single-tenant self-hosting only (DEC-014). |
| Container image / IaC / secret scanning in the UI | Trivy can do this, but it widens the UI and test scope. |
| High-availability deployment, horizontal worker autoscaling | Not needed for the course scope. |
| Mobile apps | Web dashboard only. |

## 7. Feasibility assessment (team estimates, **[A]**)

Difficulty: L/M/H. Effort: relative size S/M/L/XL, not calendar time.

| Subsystem | Difficulty | Effort | Major dependency / risk | MVP stance |
|---|---|---|---|---|
| Auth, projects, RBAC | L | M | Security mistakes in session handling | Must |
| Dashboard (Next.js) | M | L | Many views; consistent loading/error states | Must |
| OTLP → Prometheus pipeline | M | M | Version-sensitive metric/label naming (UD-06) | Must |
| Threshold alerting + lifecycle | M | M | Correct dedupe and auto-resolve | Must |
| Z-score anomaly rules | M | S | Tuning, false positives | Should |
| Dependency scan (Trivy + OSV + registries) | M | L | Output normalization, provider failures, rate limits | Must |
| Semgrep integration | L–M | M | Rule licensing (UD-01), scan time | Must |
| AI Advisor + validation | M–H | L | Prompt injection, cost, validation coverage | Must |
| Remediation sandbox | **H** | XL | Safe container runtime (UD-03), flaky tests | Must, with spike first |
| GitHub PR creation | M | M | Token scopes, branch rules | Must |
| Scheduling, exports, timeline | L | S | None | Should/Could |

**Resource assumptions [A]:** 4–5 students; one development laptop each with Docker; one shared GitHub organization with a test repository; an Anthropic API key with a small budget (UD-05); no paid infrastructure required for local demo.

## 8. Dependencies and constraints

- External services: OSV.dev API, npm and PyPI registries, GitHub API, Anthropic API (optional), Trivy vulnerability database distribution. Each can fail or rate-limit; the Toolkit must report partial results explicitly (FR-DEP-07).
- Open-source licensing must be compatible; Semgrep-maintained rules restrict use in competing products or SaaS offerings **[V]** (UD-01).
- The stack is provisional; alternatives are evaluated in [TRD](TRD.md) and `DECISIONS.md`.

## 9. Product risks (top five; detail in `ROADMAP.md`)

1. Sandbox runtime proves infeasible on team machines (UD-03).
2. Metric naming/label differences between OTel, Collector, and Prometheus break queries (UD-06).
3. AI validation misses a class of unsupported claim.
4. Scope creep beyond the Must list.
5. External API changes or rate limits during demo.

## 10. Open questions

See `UD-01`…`UD-07` in `DECISIONS.md` (batch 2); `UD-08` resolved under DEC-016 (4 members, 14 weeks, f = 0.4). Summary: license, GitHub auth model, sandbox runtime, demo hosting, Claude model/budget, Prometheus ingestion path, test-command discovery.
