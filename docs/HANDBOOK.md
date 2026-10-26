# Integrated SRE + Code Health Toolkit — Handbook

> **Doc:** HANDBOOK.md · **Version:** 0.1 · **Date:** 2026-10-25 · **Status:** Draft
> **Related:** [README](README.md), [ARCHITECTURE](ARCHITECTURE.md), [DEPLOYMENT](DEPLOYMENT.md), [API_SPEC](API_SPEC.md), [SECURITY](SECURITY.md), [TEST_STRATEGY](TEST_STRATEGY.md)

This handbook is the practical operating guide for the Integrated SRE + Code Health Toolkit.
It is organized by **user persona**. Jump to the section that matches your role:

| Persona | Section |
|---|---|
| End User / Viewer / On-Call Engineer | [§1 — End-User Guide](#1-end-user-guide-vieweron-call-engineer) |
| Maintainer | [§2 — Maintainer Guide](#2-maintainer-guide) |
| Administrator | [§3 — Admin Guide](#3-admin-guide) |
| Developer / Contributor | [§4 — Developer--Contributor Guide](#4-developer--contributor-guide) |
| DevOps / Operator | [§5 — DevOps--Operator Guide](#5-devops--operator-guide) |

---

## Terminology Quick Reference

| Term | Meaning |
|---|---|
| **Project** | The central entity linking an optional GitHub repository and one or more monitoring targets. |
| **Monitoring target** | A running service registered under a project (identified by `service_name` + `environment`). |
| **Alert rule** | A configured condition on a metric (`threshold`, `absence`). |
| **Alert** | A record that an alert rule's condition held long enough to fire. |
| **Notification channel** | A webhook endpoint that receives alert event payloads. |
| **OTLP** | OpenTelemetry Protocol — how your application sends metrics to the collector. |
| **Ingest token** | A shared bearer token your app must present to the OTLP collector. |

For the full glossary see [GLOSSARY.md](GLOSSARY.md).

---

## 1. End-User Guide (Viewer / On-Call Engineer)

### 1.1 What you can do

As a **viewer** you have read-only access to everything:

- Browse all projects and their health summaries.
- View monitoring charts: request rate, error ratio, and latency (p50 / p95 / p99).
- View active, acknowledged, and resolved alerts with full evidence snapshots.
- View alert rule definitions and notification delivery history.
- View job progress for background tasks.

You **cannot** create or edit any data. Write actions are hidden or disabled in the UI for viewer accounts.

---

### 1.2 Signing in

1. Open the dashboard at **http://localhost:3000** (or the URL your admin provided).
2. Enter your email address and password.
3. Click **Sign in**. On success you land on the **Projects** overview.

If you forget your password contact your administrator — self-service password reset is not yet implemented.

> **Session behavior.** Your access token is held in memory only; it is never written to browser storage. Closing the browser tab ends your session. Refreshing the page restores the session automatically via a secure cookie.

---

### 1.3 Navigating the dashboard

The persistent left sidebar lists navigation items; on mobile it collapses to a horizontal chip row at the top.

| Sidebar item | What it shows |
|---|---|
| **(project list)** | All active projects with monitoring status at a glance. |
| **Overview** | Per-project summary card: monitoring metrics, open alerts, and scan status. |
| **Monitoring** | Time-series charts for a selected target + target selector. |
| **Alerts** | Filterable list of alerts + alert detail route. |

Top-right of every page: **Ctrl+K / Cmd+K** opens the command palette for quick navigation.

---

### 1.4 Reading monitoring charts

Go to **Monitoring** inside a project.

1. Pick a **target** from the left-hand target list. Each entry shows the service name, environment, and current status (`receiving` / `waiting` / `stale`).
2. Pick a **time range**: `15 min`, `1 h`, `6 h`, or `24 h`.
3. Three chart cards load automatically and refresh every **15 seconds** (paused when the browser tab is hidden).

| Chart | Metrics |
|---|---|
| **Request Rate** | `req/s` over the selected window |
| **Error Ratio** | 5xx errors as a percentage of total requests |
| **Latency** | p50 (solid), p95 (dashed), p99 (dotted) in ms or s |

- A **gap** in a line means no traffic was recorded for that interval — it is not interpolated.
- A **"No traffic"** banner means the metric query returned zero-value samples (the service was running but handling no requests). This is different from "no data".
- A **"No data"** or **"Stale"** banner means the target has not sent samples recently.
- The **table view** toggle (accessible with keyboard) shows raw data points in a paginated table.

---

### 1.5 Reading alerts

Go to **Alerts** inside a project. Use the filter tabs to view **Active** (firing + acknowledged), **Resolved**, or **All**.

Each row shows:
- Rule name and severity badge.
- Current status: `firing` (red), `acknowledged` (amber), `resolved` (green).
- First seen, last seen, and occurrence count.

Click a row to open the **alert detail** page.

| Detail section | What it contains |
|---|---|
| **Evidence snapshot** | Observed value, threshold, comparator, window, PromQL used, guidance text. |
| **Status timeline** | Who acknowledged or resolved it and when. |
| **Notification deliveries** | Which channels were notified, delivery status, and any error summary. |

> **An empty alerts list does not prove the service is healthy.** It means no configured rule is currently breached.

#### Alert lifecycle

```
firing -> acknowledged -> resolved
```

- `firing` — condition has held long enough; notification(s) sent.
- `acknowledged` — an engineer has seen it (done manually, by a maintainer).
- `resolved` — condition has cleared (automatic) or engineer resolved manually.
- A new breach after resolution creates a **new** alert record.

---

## 2. Maintainer Guide

Maintainers can do everything a viewer can, plus create and edit data.

### 2.1 Onboarding a new project

#### Step 1 — Create a project

1. From the **Projects** page click **+ New project**.
2. Enter a project **name** (1–100 characters, must be unique among active projects) and an optional description.
3. Click **Create project**. You advance to the onboarding wizard.

The wizard is **resumable** — you can reload the page, navigate away, or return later, and it will pick up where you left off.

---

#### Step 2 — Connect a repository (optional)

1. Enter a **GitHub repository URL** (e.g. `https://github.com/org/repo`).
2. Enter a **Personal Access Token (PAT)** if the repository is private or if you plan to open fix PRs.
   - The field is write-only — the token is never displayed again after submission.
   - Fine-Grained PATs are supported for read-only access; Classic PATs are needed for branch/PR write operations.
3. Optionally expand **Advanced options** to override the default branch or select the test command.
4. Click **Connect**. The toolkit verifies access within 10 seconds.

| Outcome | What happens |
|---|---|
| Success | `verified_at` is set; detected ecosystems (`npm`, `pypi`) are shown. |
| `REPO_ACCESS_DENIED` | Token lacks permission or is wrong. Nothing is stored. |
| `REPO_NOT_FOUND` | URL does not resolve to a repository. Nothing is stored. |
| Timeout | GitHub did not respond in 10 s. Try again. |

You can skip this step and add a repository later in **Project Settings**.

---

#### Step 3 — Register a monitoring target (optional)

1. Enter a **service name** (`^[A-Za-z0-9_.:-]{1,100}$`) matching the `OTEL_SERVICE_NAME` your app exports.
2. Enter an **environment** label (`^[a-z0-9-]{1,50}$`, e.g. `production`, `staging`).
3. Optionally enable the **default alert rules** checkbox to provision three pre-built baseline rules:
   - High Error Ratio > 5%
   - High Latency P95 > 2 000 ms
   - Telemetry Stale > 5 minutes

You can skip this step and add targets later in **Project Settings**.

---

#### Step 4 — Instrument your application

After registering a target the wizard shows an **instrumentation snippet**:

```bash
OTEL_SERVICE_NAME=<your-service-name>
OTEL_METRICS_EXPORTER=otlp
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_ENDPOINT=http://<toolkit-host>:4318
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<OTLP_INGEST_TOKEN>
```

Add these to your application's environment. The OTLP ingest token is shown here **as a reference only** (viewers see a placeholder — contact your admin for the real value).

The wizard polls every **5 seconds** for the first sample. Once the target status changes to `receiving` the wizard completes. If no data arrives within **10 minutes**, an expandable troubleshooting checklist appears.

---

### 2.2 Managing a project

#### Project Settings (`/projects/<id>/settings`)

| Section | What you can do |
|---|---|
| **General** | Rename or update the project description. |
| **Connected repository** | View ecosystem info, re-verify the token, or disconnect the repository. |
| **Monitoring targets** | View snippet, edit target, add new target, delete target. |
| **Danger zone** | Archive the project (requires typing a confirmation). |

Archived projects are **read-only** — all data is preserved but no mutations are allowed.

---

### 2.3 Managing alert rules

Go to **Alerts -> Rules tab** inside a project.

#### Create a rule

1. Click **+ New rule**.
2. Select evaluation type: **Threshold** or **Absence**.
   - *Threshold*: fires when a metric exceeds or falls below a value for a duration.
   - *Absence*: fires when no data is received for a duration (useful for stale-target detection).
3. Choose a **metric** (`request_rate`, `error_ratio`, `latency_p95`, etc.).
4. Set **threshold**, **comparator** (`>`, `<`, `>=`, `<=`), **window** (the PromQL evaluation window), **duration** (>= 30 s, how long the condition must hold), and **severity**.
5. Click **Create**.

The **anomaly** rule type is listed but disabled — it will be available in a future phase.

#### Edit a rule

Click the edit icon on any rule row. Note:

- **Type** and **metric** are read-only after creation — create a new rule if you need to change them.
- Updating threshold or duration **resets evaluation counters** (the rule must re-confirm for the full duration before firing again).

#### Enable / disable a rule

Use the **toggle switch** in the rules table. A disabled rule is never evaluated.

---

### 2.4 Managing alerts (acknowledge / resolve)

On the **Alerts** list or detail page:

| Action | When to use |
|---|---|
| **Acknowledge** | You have seen the alert and are investigating. The alert stays visible. |
| **Resolve** | The incident is over. Resolving does **not** fix the root cause — if the condition still holds, the rule will re-fire and create a new alert. |

Both actions are available only to maintainers and admins.

---

### 2.5 Monitoring targets in Project Settings

Inside **Project Settings** under **Monitoring Targets**:

- **Add target**: Opens a form — same fields as the onboarding wizard.
- **View snippet**: Shows the OTLP environment variable block for the target.
- **Edit target**: Service name is immutable; environment can be changed.
- **Delete target**: Opens a confirmation dialog. Deleting removes the target and its alert history.

---

## 3. Admin Guide

Admins can do everything a maintainer can, plus manage users and notification channels.

### 3.1 Creating and managing users

> User management endpoints are available in the API (`POST /api/v1/users`, `PATCH /api/v1/users/{id}`, `DELETE /api/v1/users/{id}`).
> A dedicated Admin UI for user management is on the roadmap.

Use the **interactive API documentation** at `http://localhost:8000/docs` and authenticate with your admin account using the **Authorize** button (enter your JWT access token).

| Role | Capabilities |
|---|---|
| `admin` | Full access: create/edit/delete users, manage channels, all project operations. |
| `maintainer` | Create/edit projects, manage alert rules, trigger jobs, acknowledge/resolve alerts. |
| `viewer` | Read-only. |

**First-time bootstrap.** On the very first start, if no users exist, the system creates an admin from:

```dotenv
ADMIN_BOOTSTRAP_EMAIL=admin@example.com
ADMIN_BOOTSTRAP_PASSWORD=<your-password>
```

These variables should be **removed from `deploy/.env`** after the first login.

---

### 3.2 Managing notification channels

Go to **Admin -> Notification Channels** in the sidebar (admin-only link, hidden from other roles).

#### What is a notification channel?

A notification channel is a **webhook endpoint** that receives JSON payloads when alerts fire or resolve. Currently supported type: `webhook` (email support is planned).

#### List channels

The table shows each channel's name, type, masked destination hostname (e.g. `hooks.slack.com`), and enabled status. Full webhook URLs are **never displayed** — they are write-only.

#### Create a channel

1. Click **+ Add channel**.
2. Enter a **name** and the full **webhook URL** (must be HTTPS; embedded credentials in the URL are rejected).
3. Click **Save**. The URL is encrypted at rest using AES-256-GCM.

#### Edit / rotate a URL

Use the **Replace URL** modal on an existing channel to rotate the destination without exposing the current URL.

#### Test a channel

Click **Send test** on a channel row. A test event is dispatched immediately. The button is rate-limited to once per 5 seconds. Check delivery status in the **Alerts -> detail -> Deliveries** table.

#### Delete a channel

Deletion also removes **all delivery history** for that channel. The confirmation dialog warns you explicitly.

---

### 3.3 Rotating secrets

| Secret | How to rotate |
|---|---|
| `SECRET_KEY` | Update in `deploy/.env`, restart `api` and `worker`. All existing refresh sessions are invalidated (users must log in again). |
| `ENCRYPTION_KEY` | Requires re-encrypting stored repository tokens. See [SECURITY §7](SECURITY.md#7-secrets-management) for the multi-key `KeyRing` rotation procedure. |
| `OTLP_INGEST_TOKEN` | Update in `deploy/.env` and update every monitored app's `OTEL_EXPORTER_OTLP_HEADERS`. Restart `api`, `worker`, and `otel-collector`. |
| `POSTGRES_PASSWORD` | Update the PostgreSQL user password, update `DATABASE_URL` in `deploy/.env`, restart all services. |

Generate new random secrets with:

```bash
openssl rand -base64 32
```

---

### 3.4 Audit log

Security-relevant actions are written to the `audit_log` table (readable via `GET /api/v1/audit`, admin-only). Actions logged include: login success/failure, user create/delete, alert rule changes, alert acknowledgment/resolution, notification channel changes.

---

## 4. Developer & Contributor Guide

### 4.1 Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | `3.13` | Pinned in `api/.python-version` |
| Node.js | `22.x` | Pinned in `web/.nvmrc` |
| `uv` | Latest | Fast Python package manager ([install](https://docs.astral.sh/uv/)) |
| `npm` | Bundled with Node 22 | |
| Docker Engine + Compose v2 | Any recent | Required for integration tests and full stack |
| Git | Any | `core.autocrlf=input` recommended on Windows |

**Windows users:** use WSL2 and keep the repository inside the WSL filesystem to avoid CRLF issues in shell scripts.

---

### 4.2 Repository layout

```
.
+-- docs/                 # Documentation suite (18 spec files + this handbook)
+-- api/                  # Python package "toolkit" (FastAPI + worker)
|   +-- toolkit/
|   |   +-- api/          # Route handlers, middleware, dependencies
|   |   +-- core/         # Settings, security, crypto, clock, jobs, errors
|   |   +-- db/           # SQLAlchemy models, migrations (Alembic), session
|   |   +-- monitoring/   # Prometheus query engine, SLI calculation
|   |   +-- alerting/     # Alert manager, notification delivery
|   |   +-- integrations/ # GitHub adapter (read + write), HTTP client
|   +-- migrations/       # Alembic migrations (0001 ... 0004)
|   +-- tests/            # pytest test suites
+-- web/                  # Next.js 16 App Router dashboard
|   +-- app/              # Route segments and layouts
|   +-- components/       # UI primitives, charts, project wizard, alerts
|   +-- lib/              # API client, auth context, schema types
|   +-- tests/            # Vitest unit + component tests
|   +-- e2e/              # Playwright end-to-end + a11y tests
+-- deploy/               # Docker Compose stack, .env.example, collector/Prometheus configs
|   +-- spikes/           # Spike probe scripts (sp01, sp02)
+-- tools/                # Developer utilities (OpenAPI export, coverage, SP03/SP04)
+-- examples/
|   +-- demo-app/         # Instrumented sample service with fault injection
|   +-- vulnerable-repo/  # Seeded fixture: vulnerable packages, insecure code
+-- scripts/              # Helper scripts (smoke test, wait-for-health, etc.)
```

---

### 4.3 Backend setup

```bash
cd api

# Install all dependencies (including dev extras) into a local .venv
uv sync --extra dev

# Optional: activate venv (uv run works without activation)
# Linux / macOS / WSL:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\activate
```

#### Running the API server locally

Start backing services first:

```bash
# From repo root
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml \
  up -d postgres otel-collector prometheus
```

Then start the API:

```bash
cd api

# Apply migrations
uv run alembic upgrade head

# Start API with hot-reload
uv run uvicorn toolkit.api.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI: http://localhost:8000/docs

#### Running the worker locally

```bash
cd api
uv run python -m toolkit.worker
```

---

### 4.4 Frontend setup

```bash
cd web
npm ci              # Install locked dependencies
npm run dev         # Start Next.js dev server (port 3000)
```

The dev server proxies `/api/*` and operational routes (`/health`, `/docs`, `/metrics`) to `http://localhost:8000` via Next.js rewrites — no CORS setup is needed.

#### Regenerating TypeScript API types

Whenever the OpenAPI schema changes:

```bash
# From repo root — export the latest schema
python tools/export_openapi.py

# From web/ — regenerate TypeScript types
npm run openapi:generate
```

---

### 4.5 Running the full stack with Docker Compose

```bash
# From repo root
cp deploy/.env.example deploy/.env
# Edit deploy/.env: set POSTGRES_PASSWORD, SECRET_KEY, ENCRYPTION_KEY, OTLP_INGEST_TOKEN

docker compose -f deploy/docker-compose.yml up --build
```

With the **dev override** (exposes Prometheus on port 9090):

```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build
```

| Service | URL |
|---|---|
| Dashboard | http://localhost:3000 |
| API / Swagger | http://localhost:8000/docs |
| OTLP/HTTP ingestion | http://localhost:4318 |
| OTLP/gRPC ingestion | http://localhost:4317 |
| Prometheus UI (dev only) | http://localhost:9090 |

---

### 4.6 Running tests

#### 4.6.1 Backend — unit and integration tests

Integration tests require a running PostgreSQL instance:

```bash
# From repo root — start only postgres
docker compose -f deploy/docker-compose.yml up -d postgres
```

Then run tests:

```bash
cd api
uv sync --extra dev

# Run all tests (839 backend tests, 7 skipped by default)
uv run pytest

# Run with verbose output
uv run pytest -v

# Run only tests for a specific functional requirement
uv run pytest -m 'at("FR-PRJ-01")'
```

Quality gate commands:

```bash
# Lint check
uv run ruff check .

# Auto-fix lint issues
uv run ruff check --fix .

# Format check (no modification)
uv run ruff format --check .

# Auto-format
uv run ruff format .

# Static type checking (strict mypy)
uv run mypy toolkit tests

# OpenAPI drift check
uv run pytest tests/test_openapi_drift.py
```

#### 4.6.2 Backend — optional live tests (skipped by default in CI)

```bash
# Linux / macOS / WSL
export TEST_LIVE_GITHUB_REPO_URL_1="https://github.com/pallets/flask"
export TEST_LIVE_GITHUB_REPO_URL_2="https://github.com/expressjs/express"
export TEST_LIVE_GITHUB_TOKEN="ghp_..."   # optional
uv run pytest tests/test_github_adapter.py -m live

# Windows PowerShell
$env:TEST_LIVE_GITHUB_REPO_URL_1 = "https://github.com/pallets/flask"
$env:TEST_LIVE_GITHUB_REPO_URL_2 = "https://github.com/expressjs/express"
uv run pytest tests/test_github_adapter.py -m live
```

#### 4.6.3 Frontend — unit, component, and accessibility tests

```bash
cd web

# Run all Vitest tests (126 tests, 18 suites)
npm run test

# Watch mode
npm run test -- --watch

# Type check
npm run typecheck

# ESLint
npm run lint
```

#### 4.6.4 Playwright end-to-end tests

Requires the full Compose stack (see §4.5):

```bash
cd web

# Smoke suite + WCAG 2.1 AA axe audit
npm run test:e2e:smoke

# Individual suites
npx playwright test e2e/onboarding.spec.ts
npx playwright test e2e/alerts.spec.ts
npx playwright test e2e/monitoring.spec.ts

# Multi-browser nightly run (Chromium + Firefox + WebKit)
PLAYWRIGHT_ALL_BROWSERS=true npx playwright test
```

#### 4.6.5 Acceptance test traceability

```bash
# From repo root — coverage table for all 70 FRs (Must priority by default)
python tools/at_coverage.py

# Include Should-priority requirements
python tools/at_coverage.py --min-priority S

# Markdown output (used in CI step summary)
python tools/at_coverage.py --format markdown

# Fail CI if any Must FR is uncovered
python tools/at_coverage.py --fail-uncovered

# Show only uncovered requirements
python tools/at_coverage.py --uncovered-only
```

Current acceptance coverage: **46.0% (23 of 50 Must FRs covered)**.

#### 4.6.6 Detection-time acceptance harness

Tests alert system fault-detection latency (SM-03, SM-04, NFR-PERF-04):

```bash
# Hermetic unit tests (offline, no network, no containers)
uv run --project api pytest tests/test_detection_time_acceptance.py

# Simulate 10 runs (synthetic data, verifies bound formula)
python tools/accept/detection_time --simulate

# Simulate soak test (60 min, verifies zero spurious alerts)
python tools/accept/detection_time --simulate --soak 60m

# Live run against the full stack with demo-app
export DEMO_ADMIN_TOKEN="demo-secret-token"
docker compose -f deploy/docker-compose.yml --profile demo up -d demo-app

python tools/accept/detection_time \
  --api-url http://localhost:8000 \
  --api-user admin@example.com \
  --api-password "<admin-password>" \
  --project-id "<project-uuid>" \
  --target-id "<target-uuid>" \
  --demo-url http://localhost:8080 \
  --demo-admin-token "demo-secret-token" \
  --runs 10 \
  --register-channel \
  --webhook-host host.docker.internal
```

Results are saved to `docs/test-results/`.

---

### 4.7 Security scanning (the toolkit's own repository)

Run by CI automatically; also runnable locally:

```bash
# Trivy — vulnerabilities and secrets, CRITICAL severity
docker run --rm -v "${PWD}:/src" -w /src aquasec/trivy:0.75.0 fs \
  --scanners vuln,secret \
  --severity CRITICAL \
  --skip-dirs api/.venv,web/node_modules,deploy/spikes \
  --exit-code 1 .

# Semgrep SAST — fail on any finding
docker run --rm -v "${PWD}:/src" -w /src semgrep/semgrep:latest semgrep scan \
  --metrics=off \
  --error \
  --config="p/default" .
```

---

### 4.8 OpenAPI schema management

The committed `openapi.json` at the repo root is the single source of truth for the API contract. Update it whenever you add or change endpoints:

```bash
# Export current live schema (overwrites openapi.json)
python tools/export_openapi.py

# Check for drift without modifying (exits 1 if drifted; used in CI)
python tools/export_openapi.py --check
```

The `test_openapi_drift.py` test enforces zero drift on every PR.

---

### 4.9 Database migrations

```bash
cd api

# Apply all pending migrations
uv run alembic upgrade head

# Check current revision
uv run alembic current

# View migration history
uv run alembic history

# Generate a new migration (auto-detect model changes)
uv run alembic revision --autogenerate -m "describe-your-change"
```

Migration files: `api/migrations/versions/`. Follow the **forward-only policy** — never edit or delete committed migrations. Always back up the database before applying migrations to a production environment.

---

### 4.10 Using the examples directory

#### `examples/demo-app/`

An instrumented Python service that exports real OpenTelemetry metrics. Used for:
- End-to-end testing of the monitoring pipeline.
- **Fault injection** to test alert detection latency.

Start the demo app:

```bash
export DEMO_ADMIN_TOKEN="demo-secret-token"
docker compose -f deploy/docker-compose.yml --profile demo up -d demo-app
```

**Fault injection endpoints** (authenticated with `DEMO_ADMIN_TOKEN`):

```bash
# Inject 60% error rate + 500ms extra latency for 10 minutes
curl -s -X POST http://localhost:8080/admin/fault \
  -H "Authorization: Bearer $DEMO_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"error_rate": 0.6, "latency_seconds": 0.5, "ttl_seconds": 600}'

# Clear all faults immediately
curl -s -X POST http://localhost:8080/admin/clear \
  -H "Authorization: Bearer $DEMO_ADMIN_TOKEN"

# Check current fault state
curl -s http://localhost:8080/admin/status \
  -H "Authorization: Bearer $DEMO_ADMIN_TOKEN"
```

Bounds: `error_rate` in [0.0, 1.0]; `latency_seconds` <= 30; `ttl_seconds` <= 3600 (default 600).
The `/admin/*` and `/health` routes are **excluded from fault injection**.

---

#### `examples/vulnerable-repo/`

A seeded fixture used for dependency scan testing. **Do not deploy or publish as a real package.**

| Sub-directory | Content |
|---|---|
| `npm-app/` | Node.js app with seeded CVEs: `lodash@4.17.15` (CVE-2021-23337), `minimist@1.2.5` (CVE-2021-44906) |
| `python-app/` | Python app with seeded CVEs: `requests==2.25.0`, `flask==1.1.2`, `urllib3==1.26.4` |
| `broken-tests/` | Intentionally failing test suites for testing the `unverified` fix proposal path |

Each sub-directory also contains demo static analysis issues (weak hashing, SQL template strings) and a synthetic non-functional test secret `FAKE_KEY_DO_NOT_USE_0000`.

Verify the fixture manifest (checks declared CVEs match lockfiles):

```bash
python tools/verify_manifest.py examples/vulnerable-repo/fixture-manifest.json
```

---

### 4.11 Spike tooling (research scripts)

| Spike | Location | Purpose |
|---|---|---|
| SP-01 | `deploy/spikes/sp01/` | OTLP -> Prometheus path verification probes |
| SP-02 | `deploy/spikes/sp02/` | Sandbox container isolation probes (rootless DinD) |
| SP-03 | `tools/sp03/` | Trivy vs OSV comparison tooling against fixture manifest |
| SP-04 | `tools/sp04/` | GitHub write path permission matrix runner |

Each spike directory has a `README.md` with step-by-step instructions. Run offline unit tests for any spike:

```bash
uv run --project api pytest tests/test_spike_sp01.py    # SP-01
uv run --project api pytest tests/test_spike_sp02.py    # SP-02
uv run --project api pytest tests/test_sp03_trivy_runner.py \
  tests/test_sp03_osv_client.py tests/test_sp03_compare.py  # SP-03
uv run --project api pytest tests/test_github_write.py  # SP-04
```

---

## 5. DevOps & Operator Guide

### 5.1 Deployment modes

| Mode | When to use |
|---|---|
| Local development | Individual developer; services run natively or via Compose |
| Single-host Compose | Classroom / demo deployment (MVP target); >= 8 GB RAM |
| Hardened single host | Shared team use with TLS, Docker secrets, backups |

Kubernetes / multi-node is out of scope; see [ARCHITECTURE §9](ARCHITECTURE.md#9-scalability-and-limits).

---

### 5.2 First deployment

```bash
# 1. Clone the repository
git clone <repository-url> sre-toolkit
cd sre-toolkit

# 2. Create the environment file
cp deploy/.env.example deploy/.env
```

Edit `deploy/.env` — set **at minimum**:

```dotenv
POSTGRES_PASSWORD=<openssl rand -base64 32>
SECRET_KEY=<openssl rand -base64 32>
ENCRYPTION_KEY=<openssl rand -base64 32>
OTLP_INGEST_TOKEN=<openssl rand -base64 32>
ADMIN_BOOTSTRAP_EMAIL=admin@yourteam.com
ADMIN_BOOTSTRAP_PASSWORD=<strong-password>
```

```bash
# 3. Build and start the stack
docker compose -f deploy/docker-compose.yml up --build

# 4. Wait for services to be healthy (in another terminal)
python scripts/wait_for_health.py

# 5. Open the dashboard
# http://localhost:3000
```

After the first successful login, **remove** `ADMIN_BOOTSTRAP_EMAIL` and `ADMIN_BOOTSTRAP_PASSWORD` from `deploy/.env` and restart `api`.

---

### 5.3 Full configuration reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | no | `development` | `production` enables secure cookies and strict TLS assumptions |
| `PUBLIC_BASE_URL` | no | `http://localhost:3000` | Used for CORS and links |
| `CORS_ORIGINS` | no | `PUBLIC_BASE_URL` | Comma-separated allowlist |
| `DATABASE_URL` | yes | — | PostgreSQL DSN |
| `POSTGRES_PASSWORD` | yes (Compose) | — | Passed to the `postgres` service |
| `SECRET_KEY` | yes | — | >= 32 bytes; signs JWT access tokens |
| `ENCRYPTION_KEY` | yes | — | Exactly 32 bytes, base64; encrypts repository tokens and webhook URLs |
| `ADMIN_BOOTSTRAP_EMAIL` | first run only | — | Remove after first start |
| `ADMIN_BOOTSTRAP_PASSWORD` | first run only | — | Remove after first start |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `PROMETHEUS_URL` | yes | `http://prometheus:9090` | Where the API and worker run PromQL |
| `OTLP_INGEST_TOKEN` | yes | — | Bearer token for monitored apps |
| `ALERT_EVAL_INTERVAL_SECONDS` | no | `30` | Alert evaluation period (5–3600 s) |
| `ENABLE_MONITORING_LOOP` | no | `true` | Toggle background monitoring loop |
| `TARGET_STALE_AFTER_SECONDS` | no | `300` | Stale detection threshold |
| `WORKER_CONCURRENCY` | no | `2` | Parallel job slots (max 5) |
| `JOB_LEASE_SECONDS` | no | `1200` | Must exceed `SCAN_TIMEOUT_SECONDS` |
| `JOB_MAX_ATTEMPTS` | no | `3` | Retry limit before a job is marked `failed` |
| `SCAN_TIMEOUT_SECONDS` | no | `900` | Hard limit per scan job |
| `AI_ENABLED` | no | `true` | `false` disables all AI endpoints |
| `ANTHROPIC_API_KEY` | if AI on | — | Never logged or sent to the browser |
| `CLAUDE_MODEL` | no | `claude-sonnet-5-5` | Claude model identifier |
| `AI_DAILY_REQUEST_CAP` | no | `50` | Per-deployment daily cap on AI jobs |
| `REMEDIATION_ENABLED` | no | `false` | Master switch for sandbox fix proposals |
| `SANDBOX_DOCKER_HOST` | if remediation on | — | Address of the isolated sandbox Docker daemon |
| `ALLOW_PRIVATE_WEBHOOKS` | no | `false` | Admin opt-in for private-range webhook hosts |
| `SMTP_*` | no | — | Email notifications (planned) |

Generate secrets: `openssl rand -base64 32`

---

### 5.4 Upgrading

```bash
# 1. Back up the database
docker compose -f deploy/docker-compose.yml exec -T postgres \
  pg_dump -U toolkit -d toolkit -Fc > backup_$(date +%Y%m%d).dump

# 2. Pull new code
git pull

# 3. Rebuild images (the migrate service runs automatically on startup)
docker compose -f deploy/docker-compose.yml up --build -d

# 4. Verify health
python scripts/wait_for_health.py
```

Rollback: restore the database backup with `pg_restore` and restart with the previous image tags.

---

### 5.5 Hardened deployment checklist

- [ ] Reverse proxy (nginx, Caddy) in front of `web` and `api` with TLS; publish only port 443 (and 4318 for OTLP if needed from external apps).
- [ ] Set `APP_ENV=production`.
- [ ] Provide secrets through Docker secrets or a secrets manager rather than a plain `.env` file.
- [ ] Remove `ADMIN_BOOTSTRAP_*` variables after first start.
- [ ] Restrict `/metrics` to the internal network — do not expose it publicly.
- [ ] Set up PostgreSQL volume backups (daily `pg_dump`). Keep `ENCRYPTION_KEY` **separately** from backups.
- [ ] Set Prometheus retention appropriate to your team (default: 15 days).
- [ ] Enable automatic container restart policies.
- [ ] Set up log rotation for Docker logs.
- [ ] Keep images current: rebuild after dependency updates; review CI scanner outputs.

---

### 5.6 Resource sizing estimates

| Service | Memory | Notes |
|---|---|---|
| `web` | ~256 MB | Next.js standalone server |
| `api` | ~512 MB | FastAPI + SQLAlchemy |
| `worker` | 1–2 GB | Trivy and Semgrep peaks |
| `postgres` | ~512 MB | Grows with data |
| `otel-collector` | ~256 MB | `memory_limiter` processor enforced |
| `prometheus` | 512 MB+ | Grows with series count and retention |
| `sandbox-docker` + containers | 2 GB+ | Only if `REMEDIATION_ENABLED=true` |
| **Disk** | **>= 10 GB** | Trivy DB cache, Docker images, volumes |

Minimum recommended host: **8 GB RAM, 20 GB free disk**.

---

### 5.7 Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| Target stays `waiting for data` | App not exporting; wrong endpoint or token; clock skew | Check app env vars; check Collector logs for auth rejections; query Prometheus UI for any series with the `service_name` label |
| Collector rejects data (unauthenticated) | Token mismatch or incorrect `Authorization` header encoding | Compare `OTLP_INGEST_TOKEN`; ensure header is `Authorization=Bearer%20<token>` (percent-encoded space) |
| Series exist but charts show empty | Metric or label names differ from query templates | Inspect metric names in Prometheus UI at `/graph` |
| `no_traffic` banner instead of data | App is running but handling zero requests | Generate load against the application |
| Jobs stay `queued` | Worker down, DB unreachable, or concurrency = 0 | `docker compose logs worker`; check `toolkit_queue_depth` metric |
| Job repeatedly requeues | Lease shorter than job duration | Increase `JOB_LEASE_SECONDS` above `SCAN_TIMEOUT_SECONDS` |
| `409 CONFLICT` on project creation | A project with that name already exists (case-insensitive) | Choose a different name |
| `429 AI_BUDGET_EXCEEDED` | Daily AI request cap reached | Wait for next UTC day or raise `AI_DAILY_REQUEST_CAP` |
| AI endpoints return `409 AI_DISABLED` | `AI_ENABLED=false` or no API key | Set `ANTHROPIC_API_KEY` and `AI_ENABLED=true` |
| Fix proposal `SANDBOX_UNAVAILABLE` | `REMEDIATION_ENABLED=false` or sandbox daemon down | Check `sandbox-docker` health; verify `SANDBOX_DOCKER_HOST` |
| Approve returns `409 APPROVAL_REQUIRED` | Attempting PR creation without a recorded approval | Complete the approval flow in the UI |
| PR creation fails (`PR_PUSH_FAILED`) | Token lacks `contents:write` and `pull-requests:write` permissions | Re-verify the repository token in Project Settings |
| High memory on worker | Large repository or Semgrep scanning many files | Lower `WORKER_CONCURRENCY`; add vendor directories to exclusions |

---

### 5.8 Teardown

```bash
# Stop services (keeps volumes)
docker compose -f deploy/docker-compose.yml down

# Stop and delete ALL volumes (database, Prometheus, scanner cache)
docker compose -f deploy/docker-compose.yml down -v
```

> Take a database backup before using `-v` if the data matters.

---

### 5.9 Observability of the Toolkit itself

The API exposes Prometheus metrics at `/metrics` (internal network only — do **not** expose publicly):

| Metric | Description |
|---|---|
| `toolkit_api_up` | API process health (always 1 while running) |
| `toolkit_api_database_connected` | 1 if DB is reachable, 0 otherwise |
| `toolkit_api_info` | API version label |

Logs are JSON on stdout. Collect with:

```bash
docker compose logs -f api
docker compose logs -f worker
```

---

### 5.10 CI/CD pipeline overview

| Pipeline | Trigger | Steps |
|---|---|---|
| **PR** | Every pull request | Ruff lint, mypy, pytest (unit + integration vs. PostgreSQL service container), Vitest, ESLint, typecheck, Trivy, Semgrep, OpenAPI drift check, at_coverage report |
| **Nightly** | Scheduled | Full Playwright E2E (all browsers), `@live` suite (optional), reliability fault injection |
| **Release** | Tag push | Build and tag images, attach docs and checksums |

---

## Appendix A — Endpoints Quick Reference

| URL | Auth | Purpose |
|---|---|---|
| `http://localhost:3000` | Browser session cookie | Dashboard |
| `http://localhost:8000/health` | None | API liveness (always 200) |
| `http://localhost:8000/ready` | None | API readiness (checks DB connection) |
| `http://localhost:8000/docs` | Bearer token (Swagger Authorize button) | Interactive API documentation |
| `http://localhost:8000/openapi.json` | None | OpenAPI schema |
| `http://localhost:8000/metrics` | None (internal network only) | Prometheus metrics |
| `http://localhost:4318` | Bearer OTLP ingest token | OTLP/HTTP ingestion endpoint |
| `http://localhost:4317` | Bearer OTLP ingest token | OTLP/gRPC ingestion endpoint |
| `http://localhost:9090` | None (dev override only) | Prometheus UI |

---

## Appendix B — Documentation Index

| Document | Contents |
|---|---|
| [README](README.md) | Quick start, feature overview, prerequisites |
| [PRD](PRD.md) | Objectives, users, success criteria, MVP scope |
| [FRD](FRD.md) | Functional requirements (70 total), user stories, use cases |
| [SRS](SRS.md) | Non-functional requirements, interfaces, traceability matrix |
| [TRD](TRD.md) | Technology choices, algorithms, verification log |
| [ARCHITECTURE](ARCHITECTURE.md) | Components, boundaries, topology, decisions summary |
| [WORKFLOW](WORKFLOW.md) | End-to-end flows and state machines |
| [API_SPEC](API_SPEC.md) | REST endpoints, schemas, async job API |
| [DATA_MODEL](DATA_MODEL.md) | Entities, retention, sensitive data handling |
| [SECURITY](SECURITY.md) | Threat model, secrets, trust boundaries, RBAC |
| [AI_DESIGN](AI_DESIGN.md) | Evidence packs, grounding, validator, human review |
| [UI_UX_SPEC](UI_UX_SPEC.md) | Screen inventory, design system, interaction states |
| [TEST_STRATEGY](TEST_STRATEGY.md) | Test levels, acceptance catalog, AI evaluation |
| [DEPLOYMENT](DEPLOYMENT.md) | Compose configs, configuration reference, hardening |
| [TASKS](TASKS.md) | Implementation backlog with task IDs |
| [ROADMAP](ROADMAP.md) | Phases, capacity, risks |
| [GLOSSARY](GLOSSARY.md) | Terminology definitions |
| [DECISIONS](DECISIONS.md) | Architecture decision log |
| **HANDBOOK** | *This document* — operating guide per user persona |
