# Integrated SRE + Code Health Toolkit

A self-hosted, single-tenant toolkit with **one dashboard** for three jobs:

1. **Monitor** running services (OpenTelemetry → Collector → Prometheus), evaluate alert rules, and notify.
2. **Scan** GitHub repositories for vulnerable, outdated and incompatible dependencies (Trivy + OSV + npm/PyPI
   registries) and risky code (Semgrep), and propose reviewable fix PRs from a sandbox. The toolkit never merges.
3. **Advise** with evidence-grounded Claude recommendations that are validated mechanically before display.

The specification lives in [`docs/`](docs/); [`log.md`](log.md) records how it was built, every decision where
the docs were silent, and what was verified.

## Architecture at a glance

| Component | Where | Notes |
|---|---|---|
| API | `api/toolkit/api` (FastAPI, `/api/v1`) | Stateless; scale by replicas. JWT access token in memory, rotating HttpOnly refresh cookie. |
| Worker | `api/toolkit/worker` (same image) | PostgreSQL job queue (`SKIP LOCKED`, leases, heartbeats, reaper). Monitoring/alerting loop is leader-elected via an advisory lock, so any number of workers can run. Notifications use an outbox. |
| Web | `web/` (Next.js 16, React 19, Tailwind 4) | Same-origin `/api/*` proxy to the API; CSP headers; dark/light/high-contrast themes. |
| Database | PostgreSQL 17 | Alembic migrations; audit log is append-only (trigger). |
| Telemetry | OTel Collector (bearer auth) → Prometheus remote-write | Only metrics are ingested. |
| Remediation sandbox | `docker:dind` on an internal network (`--profile remediation`) | Optional; disabled by default. |

Backend modules: `core` (config, crypto, SSRF guard, argv-only subprocess runner, log redaction), `db`, `monitoring`,
`alerting`, `jobs`, `scanning`, `integrations` (GitHub, OSV, registries), `ai`, `remediation`, `scheduler`,
`retention`, `cli`.

## Run with Docker Compose

```bash
cp deploy/.env.example deploy/.env
# Fill the required values (instructions are in the file):
#   POSTGRES_PASSWORD, SECRET_KEY, OTLP_INGEST_TOKEN, METRICS_SCRAPE_TOKEN  ->  openssl rand -hex 32
#   ENCRYPTION_KEY                                                         ->  openssl rand -base64 32
#   ADMIN_BOOTSTRAP_PASSWORD (first admin; remove after first start)
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
python scripts/wait_for_health.py
```

| URL | Purpose |
|---|---|
| <http://localhost:3000> | Dashboard (sign in with `ADMIN_BOOTSTRAP_EMAIL` / `ADMIN_BOOTSTRAP_PASSWORD`) |
| <http://localhost:8000/health>, `/ready` | Liveness / readiness (database, Prometheus, AI, remediation) |
| <http://localhost:8000/docs> | OpenAPI UI (when `API_DOCS_ENABLED=true`) |
| `http://localhost:4318` / `:4317` | OTLP HTTP / gRPC ingest (`Authorization: Bearer $OTLP_INGEST_TOKEN`) |

Optional profiles:

- `--profile demo` starts `examples/demo-app` (instrumented service with fault injection on `:8080`, set
  `DEMO_ADMIN_TOKEN`). Register it in the UI as service `demo-app`, environment `dev`.
- `--profile remediation` starts the sandbox daemon; also set `REMEDIATION_ENABLED=true`.
- AI: set `AI_ENABLED=true` and `ANTHROPIC_API_KEY`. Evidence sent to the API is redacted and capped
  (`AI_DAILY_REQUEST_CAP`).
- `deploy/docker-compose.dev.yml` additionally publishes Prometheus and PostgreSQL on localhost.

Operations (inside the `api` or `worker` container): `toolkit migrate`, `toolkit create-user`,
`toolkit seed-demo [--repo URL]`, `toolkit retention`, `toolkit hard-delete-project`.

## Development and tests

Backend (Python 3.13, `uv`). Tests need a PostgreSQL 17 server; the suite creates and migrates its own
`toolkit_test` database (default `127.0.0.1:55432`, override with `TEST_DATABASE_URL`):

```bash
docker run -d --name toolkit-pg-dev -e POSTGRES_USER=toolkit -e POSTGRES_PASSWORD=toolkit \
  -p 127.0.0.1:55432:5432 postgres:17.6-alpine3.22
cd api
uv sync                      # includes the dev group
uv run ruff check . && uv run ruff format --check .
uv run mypy toolkit
uv run pytest --cov=toolkit  # --run-live: real OSV/registries/collector; --run-sandbox: remediation sandbox
```

Web (Node 22):

```bash
cd web
npm ci
npm run lint && npm run typecheck && npm test && npm run build
E2E_PASSWORD=... npx playwright test   # against a running stack; includes axe accessibility checks
```

Visual review: capture every screen in both themes at desktop and mobile widths into `web/test-results/screens/`
(`SCREENS_IDS` is JSON with the ids of a project that has data: project, target, alert, finding, scan):

```bash
cd web && SCREENSHOTS=1 E2E_PASSWORD=... SCREENS_IDS='{"project":"…",…}' npx playwright test e2e/screens.spec.ts --project=chromium
```

Whole-stack smoke test (stack started with `--profile demo`): logs in, registers the demo app, waits for data,
injects a 5xx fault, measures alert detection time, checks auto-resolve, scans a public repository with all
providers, then archives its project (`--keep` to leave it):

```bash
python scripts/smoke_e2e.py --email admin@example.com --password "$ADMIN_BOOTSTRAP_PASSWORD" \
  --demo-token "$DEMO_ADMIN_TOKEN" [--repo https://github.com/<owner>/<repo>]
```

Repository tools:

```bash
python tools/at_coverage.py [--fail-uncovered]              # requirement → test traceability (FRD)
python tools/verify_manifest.py examples/vulnerable-repo/fixture-manifest.json
cd api && uv run python ../tools/export_openapi.py [--check]  # regenerate / drift-check openapi.json
```

CI (`.github/workflows/ci.yml`) runs all of the above except the live and E2E suites, builds the images, and scans
this repository with Trivy and Semgrep (failing on critical findings).

## Version pinning

| Item | Version |
|---|---|
| Python / Node | 3.13 (`api/.python-version`) / 22 (`web/.nvmrc`) |
| Locked dependencies | `api/uv.lock`, `web/package-lock.json` |
| GitHub Actions | `actions/checkout@v4.2.2`, `actions/setup-node@v4.2.0`, `actions/setup-python@v5.4.0`, `astral-sh/setup-uv@v5.3.0` |
| Scanners (toolkit image and CI) | Trivy `0.75.0`, Semgrep `1.180.0` |
| Runtime images | `postgres:17.6-alpine3.22`, `otel/opentelemetry-collector-contrib:0.163.1`, `prom/prometheus:v3.13.4`, `docker:28.5.2-dind` |

## Repository layout

```
api/        backend package `toolkit` (API + worker), Alembic migrations, tests
web/        Next.js dashboard, Vitest unit tests, Playwright E2E
deploy/     docker-compose.yml, Collector and Prometheus config, .env.example
examples/   demo-app (instrumented service) and vulnerable-repo (seeded scan fixture)
scripts/    wait_for_health.py, smoke_e2e.py
tools/      traceability, fixture manifest and OpenAPI export utilities
docs/       product, design and operations documentation
```
