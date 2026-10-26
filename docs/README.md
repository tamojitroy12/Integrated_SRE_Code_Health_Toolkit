# Integrated SRE + Code Health Toolkit

> **Doc:** README.md · **Version:** 0.1 · **Date:** 2026-10-13 · **Status:** Draft (documentation suite complete: 18 files)

A lightweight, open-source toolkit with **one dashboard** for three jobs that small teams usually solve with separate tools:

1. **Monitor** running applications (OpenTelemetry → Prometheus), detect anomalies and failures, and raise actionable alerts.
2. **Scan** repositories for outdated, vulnerable, and potentially incompatible dependencies (Trivy + OSV) and for static code issues (Semgrep), then propose **reviewable fix pull requests**.
3. **Advise**: an LLM (Claude API) recommends library alternatives and code improvements *only* from scanner findings and verifiable evidence. Unsupported claims are rejected before display.

Live monitoring and static repository analysis are **independent pipelines**. They meet in a shared **Project** view; the toolkit never claims that a metric anomaly is caused by a particular code defect, nor that a static finding proves runtime failure (see [ARCHITECTURE.md](docs/ARCHITECTURE.md) §Boundaries).

> **Implementation status:** no application code exists yet. Commands in this README describe the *intended* interface and become valid as the EP-01 tasks in [TASKS.md](docs/TASKS.md) are completed.

## Documentation conventions

| Label | Meaning |
|---|---|
| **[V]** | Verified against an official source on the stated access date (see [TRD.md](docs/TRD.md) §Verification log). |
| **[P]** | Proposed design decision (may change; tracked in [DECISIONS.md](docs/DECISIONS.md), ID `DEC-nnn`). |
| **[A]** | Assumption that the team must confirm. |
| **[U]** | Unresolved decision (ID `UD-nn`). |

Priorities use MoSCoW: **M**ust (MVP), **S**hould (MVP if time permits), **C**ould (post-MVP), **W**on't (this release). Mathematical notation uses `\( ... \)` and `\[ ... \]`; if your Markdown viewer does not render this form, read the formulas as plain text.

## MVP feature summary

| Area | MVP (Must) | Later (Should/Could) |
|---|---|---|
| Monitoring | OTLP metrics ingestion, request rate / error ratio / latency charts, threshold alerts, stale-target detection | Z-score anomaly rules, Prometheus scrape mode, runtime/host metrics |
| Dependency scanning | npm + PyPI inventory, vulnerabilities (Trivy + OSV), outdated versions | Incompatibility heuristics, scheduled rescans, more ecosystems |
| Static analysis | Semgrep scan with default rule sets | Custom rule directories, triage persistence polish |
| AI advice | Evidence-grounded recommendations with validation gate | Alternative-library criteria, feedback loop, alert summaries |
| Remediation | Sandboxed dependency-fix proposals → human approval → draft PR on GitHub | Major-upgrade confirmation flow, rollback helpers |
| Dashboard | Project overview, findings explorer, alerts, job progress | Activity timeline, exports |

Full scope: [PRD.md](docs/PRD.md). Requirements: [FRD.md](docs/FRD.md), [SRS.md](docs/SRS.md).

## Prerequisites

| Requirement | Notes |
|---|---|
| Docker Engine + Docker Compose v2 | Runs every service. Windows users: WSL2 **[A]**. |
| Git | To clone this repository. |
| GitHub account + fine-grained personal access token | Needed only for private repositories and fix PRs **[P]** (DEC-009). |
| Anthropic API key | Optional. The toolkit is fully functional with `AI_ENABLED=false`. |
| ≥ 8 GB RAM, ≥ 10 GB free disk | Resource estimate for the full stack plus scanner databases **[A]**; confirm during EP-01. |

For development without containers you additionally need an actively supported Node.js LTS release and a currently supported Python 3 release:
- **Node.js**: Pinned to `22.x` (Active LTS) in [`web/.nvmrc`](file:///d:/Minor%20Project/web/.nvmrc).
- **Python**: Pinned to `3.13` in [`api/.python-version`](file:///d:/Minor%20Project/api/.python-version).

### Tool and Action Version Pinning Rationale

In accordance with `NFR-SEC-07` and supply chain security best practices, all CI actions, linters, test frameworks, and scanners are strictly pinned to exact versions or patch releases to ensure deterministic builds and avoid pipeline breaks from unverified upstream changes:

| Component | Pinned Version | Rationale |
|---|---|---|
| `actions/checkout` | `v4.2.2` | Pinned patch release prevents unexpected breaking changes in workspace checkout. |
| `actions/setup-node` | `v4.2.0` | Pinned patch release ensures consistent Node 22 runtime and package caching. |
| `actions/setup-python` | `v5.4.0` | Pinned patch release guarantees exact CPython 3.13 installation in CI. |
| `astral-sh/setup-uv` | `v5.3.0` | Pinned patch release enables deterministic execution of `uv` package management. |
| `aquasecurity/setup-trivy` | `v0.2.2` (`v0.58.2`) | Pinned action and Trivy binary ensures repeatable vulnerability and secret scanning logic. |
| `semgrep` | `1.180.0` | Pinned pip installation guarantees stable static analysis rules and zero syntax regressions. |
| Python dependencies | `api/uv.lock` | Fully pinned cryptographic lockfile for ruff (`0.17.0`), mypy (`2.4.0`), and pytest (`9.1.1`). |
| Node.js dependencies | `web/package-lock.json` | Fully pinned lockfile for Next.js (`16.4.0`), Vitest (`5.0.4`), ESLint (`9.x`), and TypeScript (`5.x`). |

## Quick start (target workflow)

```bash
git clone <repository-url> sre-code-health-toolkit
cd sre-code-health-toolkit
cp deploy/.env.example deploy/.env        # then edit secrets (see Configuration)
docker compose -f deploy/docker-compose.yml up --build
```

| Endpoint | Purpose |
|---|---|
| http://localhost:3000 | Dashboard (`web`) |
| http://localhost:8000/docs | Interactive API documentation (`api`, generated by FastAPI) |
| http://localhost:4318 | OTLP/HTTP ingestion (`otel-collector`) |
| http://localhost:9090 | Prometheus UI (development only; do not expose publicly) |

## Configuration

All settings are environment variables in `deploy/.env`. Full reference: [DEPLOYMENT.md](docs/DEPLOYMENT.md).

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | no | `development` | `development` or `production`. |
| `DATABASE_URL` | yes | compose default | PostgreSQL connection string. |
| `SECRET_KEY` | yes | none | ≥ 32 random bytes; signs access tokens. |
| `ENCRYPTION_KEY` | yes | none | 32 random bytes (base64); encrypts stored repository tokens. |
| `ADMIN_BOOTSTRAP_EMAIL` / `ADMIN_BOOTSTRAP_PASSWORD` | first run | none | Creates the first `admin` user if no users exist. |
| `PROMETHEUS_URL` | yes | `http://prometheus:9090` | Where the API/worker run PromQL. |
| `OTLP_INGEST_TOKEN` | yes | none | Bearer token monitored apps must present to the collector. |
| `ALERT_EVAL_INTERVAL_SECONDS` | no | `30` | Alert evaluation period \(\Delta_{eval}\). |
| `TARGET_STALE_AFTER_SECONDS` | no | `300` | No samples for this long ⇒ target is `stale`. |
| `SCAN_TIMEOUT_SECONDS` | no | `900` | Hard limit per scan job. |
| `AI_ENABLED` | no | `true` | If `false`, all AI endpoints return `409 AI_DISABLED`. |
| `ANTHROPIC_API_KEY` | if AI on | none | Never logged, never sent to the browser. |
| `CLAUDE_MODEL` | no | `claude-sonnet-5-5` | Model identifier; verify against current Claude API docs **[A]**. |
| `AI_DAILY_REQUEST_CAP` | no | `50` | Per-deployment daily cap on AI jobs **[P]**. |
| `SANDBOX_DOCKER_HOST` | if remediation on | none | Address of the *dedicated* sandbox Docker daemon (never the host socket). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | no | none | Enables email notifications (Should). |

Generate secrets with `openssl rand -base64 32`.

## Usage walk-through

1. **Sign in** with the bootstrap admin account; create users for teammates (`maintainer` / `viewer`).
2. **Create a project** (name + description).
3. **Connect a repository** (GitHub URL; optional token). The toolkit verifies access and detects npm / PyPI manifests.
4. **Register a monitoring target** (`service_name`, environment). The dashboard shows an onboarding snippet. Add these standard OpenTelemetry variables to the monitored app **[A: header encoding to be verified in the demo app]**:

   ```bash
   OTEL_SERVICE_NAME=demo-api
   OTEL_METRICS_EXPORTER=otlp
   OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
   OTEL_EXPORTER_OTLP_ENDPOINT=http://<toolkit-host>:4318
   OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<OTLP_INGEST_TOKEN>
   ```

   Status moves `waiting for data → receiving` once the first sample arrives.
5. **Run a scan.** A background job inventories dependencies, queries Trivy/OSV and registries, and runs Semgrep. Progress is visible on the Scans page.
6. **Review findings** in the explorer; dismiss false positives with a reason.
7. **Request an AI recommendation** for a finding. Read the evidence links and validation badge before acting.
8. **Create a fix proposal** for dependency findings. Review the diff and sandbox test report, then **approve**. The toolkit opens a *draft* pull request on a `toolkit/fix/...` branch. **You merge it in GitHub; the toolkit never merges.**

## Deployment

Local/classroom deployment uses the provided Compose file. Production-like hardening (TLS reverse proxy, secret management, backups, Prometheus retention) is described in [DEPLOYMENT.md](docs/DEPLOYMENT.md) and [SECURITY.md](docs/SECURITY.md). Hosting target for the demo is undecided (**UD-04**).

## Repository layout (proposed)

```text
.
├── README.md
├── docs/                    # this documentation suite
├── web/                     # Next.js dashboard (COMP-01)
├── api/                     # Python package "toolkit": FastAPI app + worker entrypoints
│   └── toolkit/{api,core,db,monitoring,alerting,scanning,ai,remediation,integrations}/
├── deploy/                  # docker-compose.yml, .env.example, otel-collector and prometheus configs
├── tools/                   # developer utilities and offline manifest verifier
└── examples/
    ├── demo-app/            # instrumented sample service with injectable faults
    └── vulnerable-repo/     # seeded dependency and code issues for demos/tests
```

## Documentation index

| Document | Purpose |
|---|---|
| [PRD](docs/PRD.md) | Objectives, users, success criteria, MVP scope, feasibility |
| [FRD](docs/FRD.md) | Functional requirements, user stories, use cases |
| [SRS](docs/SRS.md) | Non-functional requirements, interfaces, traceability matrix |
| [TRD](docs/TRD.md) | Technology choices, algorithms, verification log |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, boundaries, topology, decisions summary |
| [WORKFLOW](docs/WORKFLOW.md) | End-to-end flows and state machines |
| [API_SPEC](docs/API_SPEC.md) | REST endpoints, schemas, async jobs |
| [DATA_MODEL](docs/DATA_MODEL.md) | Entities, retention, sensitive data |
| [SECURITY](docs/SECURITY.md) | Threat model, secrets, repository access, secure remediation, prompt injection |
| [AI_DESIGN](docs/AI_DESIGN.md) | Grounding, evidence packs, validation, human review |
| [UI_UX_SPEC](docs/UI_UX_SPEC.md) | Information architecture, screens, states, interactions |
| [TEST_STRATEGY](docs/TEST_STRATEGY.md) | Test levels, acceptance and NFR test catalogs, AI evaluation |
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Compose layout, configuration, operations, troubleshooting |
| [TASKS](docs/TASKS.md) | Dependency-aware backlog with task IDs |
| [ROADMAP](docs/ROADMAP.md) | Phases, capacity check, cut ladder, risks |
| [GLOSSARY](docs/GLOSSARY.md) | Terminology |
| [DECISIONS](docs/DECISIONS.md) | Decision log and unresolved decisions |

Suggested reading order for newcomers: README → PRD → ARCHITECTURE → WORKFLOW → FRD → the document for your area.

## Known limitations (by design)

- Metrics-only telemetry in the MVP; traces and logs are out of scope.
- Only npm and PyPI ecosystems and GitHub-hosted repositories (DEC-012, DEC-009).
- Incompatibility detection is heuristic; passing sandbox tests is *evidence*, not proof, of compatibility.
- AI output is advisory. It cannot trigger commands, edits, or merges.
- Single-tenant deployment with global roles (DEC-013, DEC-014).

## License

Project license is undecided (**UD-01**). Semgrep-maintained rules carry their own license terms that restrict use in competing SaaS offerings **[V]**; see [TRD.md](docs/TRD.md) §Licensing.
