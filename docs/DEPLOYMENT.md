# Deployment

> **Doc:** DEPLOYMENT.md · **Version:** 0.2 · **Date:** 2026-10-13 · **Status:** Draft (**[P]**) · **Related:** [README](../README.md), [ARCHITECTURE §6](ARCHITECTURE.md#6-deployment-topology-docker-compose), [SECURITY](SECURITY.md), [TRD](TRD.md)

All configuration files below are **illustrative skeletons** for the team to adapt. Image tags and some keys must be pinned and validated at implementation time (`docker compose config`, `otelcol validate`). Items marked **[V]** were checked against official documentation on 2026-10-13 (see [TRD §9](TRD.md#9-verification-log)); **[A]** items were not.

## 1. Deployment modes

| Mode | Use | Notes |
|---|---|---|
| Local development | Each developer runs services natively or via Compose | Hot reload for `web` and `api` |
| Single-host Compose | Classroom/demo deployment (the MVP target) | One machine, ≥ 8 GB RAM **[A]** |
| Hardened single host | Shared team use | Reverse proxy with TLS, Docker secrets, backups (§7) |
| Kubernetes, multi-node | Out of scope | See [ARCHITECTURE §9](ARCHITECTURE.md#9-scalability-and-limits) |

## 2. Services

| Service | Image / build | Ports (host) | Networks | Volumes | Notes |
|---|---|---|---|---|---|
| `web` | Build `web/` | 3000 | frontend | none | Talks to `api` |
| `api` | Build `api/` (command: API server) | 8000 | frontend, backend, egress | none | Runs migrations via the `migrate` job (below) |
| `migrate` | Same image as `api` (one-shot) | none | backend | none | Runs the Alembic upgrade, then exits |
| `worker` | Same image as `api` (command: worker) | none (9100 internal metrics **[P]**) | backend, egress, sandbox | `trivy-cache`, `work-tmp` | Contains the Trivy and Semgrep CLIs |
| `postgres` | Pinned PostgreSQL image | none | backend | `pgdata` | Not published |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.163.1` **[V]** | 4317, 4318 | frontend (to receive from apps), backend | none | Bearer token auth, internal health_check on 13133, restart: unless-stopped |
| `prometheus` | `prom/prometheus:v3.13.4` **[V]** | none (9090 in development via `docker-compose.dev.yml`) | backend | `promdata` | 15d retention, remote-write receiver, wget healthcheck |
| `demo-app` | Build `examples/demo-app` | none | frontend | none | Optional Compose profile `demo` (T-03.03) |
| `sandbox-docker` | Isolated daemon (see §5); Compose profile `remediation` | none | sandbox | `sandbox-data` | Reachable only by `worker` |

Networks: `frontend` (published services), `backend` (`internal: true`: postgres, prometheus, collector↔prometheus), `egress` (default bridge, only for `api` and `worker` outbound calls), `sandbox` (`internal: true`: worker↔sandbox daemon).

### 2.1 Compose skeleton

```yaml
# deploy/docker-compose.yml (validated with `docker compose config`)
name: sre-code-health
services:
  postgres:
    image: postgres:17.3-alpine3.21
    environment: { POSTGRES_DB: toolkit, POSTGRES_USER: toolkit, POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set} }
    volumes: [pgdata:/var/lib/postgresql/data]
    networks: [backend]
    healthcheck: { test: ["CMD-SHELL", "pg_isready -U toolkit -d toolkit"], interval: 5s, timeout: 5s, retries: 5 }
  migrate:
    build: ../api
    command: ["alembic", "upgrade", "head"]
    env_file: .env
    depends_on: { postgres: { condition: service_healthy } }
    networks: [backend]
  api:
    build: ../api
    command: ["uvicorn", "toolkit.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
    env_file: .env
    ports: ["127.0.0.1:8000:8000"]
    depends_on: { migrate: { condition: service_completed_successfully } }
    networks: [frontend, backend, egress]
    healthcheck: { test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"], interval: 5s, timeout: 5s, retries: 5 }
  worker:
    build: ../api
    command: ["python", "-m", "toolkit.worker"]
    env_file: .env
    volumes: [trivy-cache:/var/cache/trivy, work-tmp:/work]
    depends_on: { migrate: { condition: service_completed_successfully } }
    networks: [backend, egress, sandbox]
  web:
    build: ../web
    ports: ["127.0.0.1:3000:3000"]
    environment: { API_BASE_URL: "http://api:8000" }
    networks: [frontend]
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.163.1
    restart: unless-stopped
    command: ["--config=/etc/otelcol-contrib/config.yaml"]
    environment: { OTLP_INGEST_TOKEN: ${OTLP_INGEST_TOKEN:?OTLP_INGEST_TOKEN must be set} }
    volumes: ["./otel-collector.yaml:/etc/otelcol-contrib/config.yaml:ro"]
    ports: ["127.0.0.1:4317:4317", "127.0.0.1:4318:4318"]
    networks: [frontend, backend]
    depends_on: { prometheus: { condition: service_healthy } }
  prometheus:
    image: prom/prometheus:v3.13.4
    restart: unless-stopped
    entrypoint: ["/bin/sh", "-c"]
    command:
      - >
        echo -n "$${METRICS_SCRAPE_TOKEN}" > /tmp/scrape_token &&
        exec /bin/prometheus
        --config.file=/etc/prometheus/prometheus.yml
        --web.enable-remote-write-receiver
        --storage.tsdb.retention.time=15d
    environment: { METRICS_SCRAPE_TOKEN: ${METRICS_SCRAPE_TOKEN:-test_scrape_token} }
    volumes: ["./prometheus.yml:/etc/prometheus/prometheus.yml:ro", "promdata:/prometheus"]
    networks: [backend]
    healthcheck: { test: ["CMD", "/bin/wget", "-q", "--tries=1", "-O-", "http://localhost:9090/-/ready"], interval: 5s, timeout: 5s, retries: 5 }
  demo-app:
    profiles: [demo]
    build: { context: ../examples/demo-app, dockerfile: Dockerfile }
    restart: unless-stopped
    environment:
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318
      OTEL_EXPORTER_OTLP_HEADERS: Authorization=Bearer%20${OTLP_INGEST_TOKEN:?OTLP_INGEST_TOKEN must be set}
      OTEL_SERVICE_NAME: demo-app
    networks: [frontend]
    depends_on: [otel-collector]
volumes: { pgdata: {}, promdata: {}, trivy-cache: {}, work-tmp: {} }
networks:
  frontend: {}
  egress: {}
  backend: { internal: true }
  sandbox: { internal: true }
```

In development, publish Prometheus' port 9090 on `127.0.0.1` using the override:
```bash
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d
```

### 2.2 OpenTelemetry Collector configuration

```yaml
# deploy/otel-collector.yaml
extensions:
  bearertokenauth:                       # [V] server-side token check per TRD §9 V-04
    scheme: Bearer
    token: ${env:OTLP_INGEST_TOKEN}
  health_check:                          # [V] internal health check extension
    endpoint: 0.0.0.0:13133
receivers:
  otlp:
    protocols:
      grpc: { endpoint: 0.0.0.0:4317, auth: { authenticator: bearertokenauth } }   # [V]
      http: { endpoint: 0.0.0.0:4318, auth: { authenticator: bearertokenauth } }   # [V]
processors:
  memory_limiter: { check_interval: 1s, limit_mib: 256 }   # [A] FIRST in pipeline
  batch: {}                                                  # [A] LAST in pipeline
exporters:
  prometheusremotewrite:                                     # [V] remote-write exporter
    endpoint: http://prometheus:9090/api/v1/write            # [V] remote-write receiver path
    resource_to_telemetry_conversion: { enabled: true }      # [V] turns service.name into service_name label
service:
  extensions: [bearertokenauth, health_check]
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheusremotewrite]
```

### 2.3 Prometheus configuration

```yaml
# deploy/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
scrape_configs:
  - job_name: prometheus
    static_configs: [{ targets: ["localhost:9090"] }]
  - job_name: toolkit-api
    authorization:
      type: Bearer
      credentials_file: /tmp/scrape_token
    static_configs: [{ targets: ["api:8000"] }]
  - job_name: toolkit-worker
    authorization:
      type: Bearer
      credentials_file: /tmp/scrape_token
    static_configs: [{ targets: ["worker:9100"] }]
```

Pushed application metrics arrive through remote write and need no scrape job. Scrape-mode targets (FR-MON-06, Should) would be added through generated file-based service discovery **[P]**. Prometheus has a native OTLP receiver flag as an alternative to the Collector **[V]**; see DEC-004.

## 3. Configuration reference

The README lists the essentials. Full list (all optional unless stated; defaults are proposals):

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | `production` enforces secure cookies and TLS assumptions |
| `PUBLIC_BASE_URL` | `http://localhost:3000` | Used for links and CORS |
| `CORS_ORIGINS` | `PUBLIC_BASE_URL` | Comma-separated allowlist |
| `DATABASE_URL`, `POSTGRES_PASSWORD` | none (required) | Database connection |
| `SECRET_KEY`, `ENCRYPTION_KEY` | none (required) | See [SECURITY §7](SECURITY.md#7-secrets-management) |
| `ADMIN_BOOTSTRAP_EMAIL`, `ADMIN_BOOTSTRAP_PASSWORD` | none | First start only; remove afterwards |
| `LOG_LEVEL` | `INFO` | Structured JSON logs |
| `PROMETHEUS_URL` | `http://prometheus:9090` | Query endpoint |
| `OTLP_INGEST_TOKEN` | none (required) | Shared with monitored apps |
| `ALERT_EVAL_INTERVAL_SECONDS` | `30` | \( \Delta_{eval} \) (bounds: 5–3600 s) |
| `ENABLE_MONITORING_LOOP` | `true` | Background monitoring loop toggle in worker |
| `TARGET_STALE_AFTER_SECONDS` | `300` | Stale threshold |
| `WORKER_CONCURRENCY` | `2` | Parallel jobs (design envelope ≤ 5) |
| `JOB_LEASE_SECONDS` | `1200` | Must exceed `SCAN_TIMEOUT_SECONDS` |
| `JOB_MAX_ATTEMPTS` | `3` | |
| `SCAN_TIMEOUT_SECONDS` | `900` | Hard limit per scan |
| `CLONE_MAX_MB` | `200` | Clone size cap |
| `SEMGREP_TIMEOUT_SECONDS`, `SEMGREP_MAX_FILE_BYTES` | `600`, `1000000` | Static-analysis limits **[A]** |
| `TRIVY_CACHE_DIR`, `TRIVY_SKIP_DB_UPDATE` | `/var/cache/trivy`, `false` | Offline use: pre-download then set to `true` **[V]** |
| `AI_ENABLED`, `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | see README | |
| `AI_DAILY_REQUEST_CAP`, `AI_MAX_INPUT_TOKENS`, `AI_MAX_OUTPUT_TOKENS` | `50`, `12000`, `2000` | |
| `REMEDIATION_ENABLED` | `false` | Master switch for sandbox use |
| `SANDBOX_DOCKER_HOST` | none | Address of the isolated daemon |
| `SANDBOX_STAGE_TIMEOUT_SECONDS`, `SANDBOX_MEMORY_MB`, `SANDBOX_CPUS`, `SANDBOX_PIDS_LIMIT` | `900`, `2048`, `2`, `512` | Per-container limits **[A]** |
| `ALLOW_PRIVATE_WEBHOOKS` | `false` | Admin opt-in for private-range webhook hosts |
| `RETENTION_*` | see [DATA_MODEL §7](DATA_MODEL.md#7-retention) | Retention overrides |
| `SMTP_*` | none | Email notifications (Should) |

## 4. Local development

| Component | Command (proposed) | Notes |
|---|---|---|
| Dependencies | `docker compose up postgres prometheus otel-collector` | Brings up backing services only |
| API | `uvicorn toolkit.api.main:app --reload` from `api/` | OpenAPI docs at `/docs` |
| Worker | `python -m toolkit.worker` | Needs `trivy` and `semgrep` on PATH (or run the worker in Compose) |
| Web | `npm run dev` from `web/` | Use a currently supported Node.js LTS |
| Tests | `pytest`; `npm test`; Playwright against the Compose stack | See [TEST_STRATEGY](TEST_STRATEGY.md) |
| Demo data | seed command (T-02.07) | Uses `examples/` |

Windows: use WSL2, keep the repository inside the WSL filesystem, and set `core.autocrlf=input` to avoid CRLF problems in shell scripts **[A]**.

## 5. Sandbox daemon (remediation, UD-03)

Remediation executes dependency installs and repository tests; it needs a container daemon that is **not** the host's. Candidate layouts (decision in `T-09.01`):

| Option | Idea | Concerns |
|---|---|---|
| A. Rootless Docker-in-Docker service | `sandbox-docker` container runs its own daemon; the worker connects over the `sandbox` network (TLS recommended) | The outer container may need relaxed security options to run a nested daemon; verify on Windows/macOS/Linux **[A]** |
| B. Rootless Podman service | API-compatible socket exposed on an internal network | Different tooling; team familiarity |
| C. Plan-only mode | `REMEDIATION_ENABLED=false`; proposals stop at the plan | FR-REM-02/04/05 unmet (ROADMAP §5 step 4) |

Requirements regardless of option: the daemon is attached only to the `sandbox` network, shares no volumes with other services, holds no secrets, and its storage is disposable (`docker compose down -v` removes it). Runner images (Node, Python) are pinned and built from minimal bases. Per-container settings are listed in [SECURITY §9.2](SECURITY.md#92-sandbox-profile).

## 6. Observability of the Toolkit itself

`api` and `worker` expose Prometheus metrics (NFR-REL-03, NFR-OBS-02). Proposed names:

| Metric | Type | Labels |
|---|---|---|
| `toolkit_http_requests_total`, `toolkit_http_request_duration_seconds` | counter, histogram | `route`, `method`, `status` |
| `toolkit_jobs_total`, `toolkit_job_duration_seconds` | counter, histogram | `type`, `status` |
| `toolkit_queue_depth` | gauge | `type` |
| `toolkit_provider_runs_total` | counter | `provider`, `status` |
| `toolkit_ai_requests_total`, `toolkit_ai_validation_total` | counters | `kind`, `validation_status` |
| `toolkit_alert_evaluations_total` | counter | `outcome` (`ok`, `query_error`) |
| `toolkit_sandbox_stage_total` | counter | `stage`, `status` |

Suggested self-alerts (configured as ordinary Prometheus rules or checked manually): queue depth growing for 10 minutes, job failure ratio above a threshold, provider failures, repeated `query_error` outcomes, AI daily cap reached. Logs are JSON on stdout; collect with `docker compose logs`. Optional dogfooding (Could): instrument the Toolkit API with OpenTelemetry and register it as a monitoring target of its own project.

## 7. Hardened single-host deployment

1. Put a reverse proxy in front of `web` and `api` with TLS; publish only 443 (and the OTLP port, ideally over TLS, to the networks where monitored apps live). Do not publish Prometheus or the sandbox daemon.
2. Set `APP_ENV=production`; provide secrets through Docker secrets or an equivalent mechanism rather than a plain `.env` file; remove `ADMIN_BOOTSTRAP_*` after first start.
3. Restrict `/metrics` to the internal network.
4. Set Prometheus and PostgreSQL volume backups: PostgreSQL with `pg_dump` in custom format (restore with `pg_restore`); keep `ENCRYPTION_KEY` separate from backups; Prometheus data is disposable (retention-limited) and not backed up by default.
5. Enable automatic container restarts; set log rotation.
6. Keep images current: rebuild on dependency updates after CI passes; review scanner outputs for the Toolkit's own images.

### Upgrades and migrations

Pull new code, rebuild, run the `migrate` service (Alembic forward-only, [DATA_MODEL §10](DATA_MODEL.md#10-migration-policy)), then restart `api` and `worker`. Take a database backup before upgrading. Rollback means restoring the backup and the previous image tags.

### Rotating secrets

Follow [SECURITY §7](SECURITY.md#7-secrets-management). After rotating `OTLP_INGEST_TOKEN`, update every monitored application's `OTEL_EXPORTER_OTLP_HEADERS`.

## 8. Resource sizing **[A]**

| Service | Rough memory | Notes |
|---|---|---|
| web | 256 MB | |
| api | 512 MB | |
| worker | 1–2 GB | Trivy and Semgrep peaks; clone workspace on disk |
| postgres | 512 MB | |
| otel-collector | 256 MB | `memory_limiter` set accordingly |
| prometheus | 512 MB+ | Grows with series count and retention |
| sandbox daemon + containers | 2 GB+ | `SANDBOX_MEMORY_MB` per container |
| Disk | ≥ 10 GB | Trivy DB cache, images, volumes |

These figures are planning estimates; measure on the reference environment in `T-10.03`.

## 9. CI/CD outline

| Pipeline | Steps |
|---|---|
| PR | Lint, type check, unit + integration tests, build images, Trivy and Semgrep on the Toolkit repository, contract test (Should) |
| Nightly | Full E2E, reliability scenarios, `@live` suite (optional) |
| Release (tag) | Build and tag images, generate license report (NFR-LIC-01), attach docs and checksums |

## 10. Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| Target stays `waiting for data` | App not exporting; wrong endpoint or token; clock skew | Verify env vars on the app; Collector logs for auth rejections; Prometheus UI for any series with the `service_name` |
| Collector rejects data (unauthenticated) | Token mismatch or encoding of the `Authorization` header value | Compare with `OTLP_INGEST_TOKEN`; test with a manual OTLP request **[A: header percent-encoding to confirm in demo-app]** |
| Series exist but charts empty | Metric or label names differ from `monitoring/queries.py` (UD-06) | Inspect names in Prometheus; adjust the query module; record in DECISIONS |
| `no_traffic` instead of data | App emits no requests in range | Generate load against the demo app |
| Scan ends `partial` | A provider failed | Scan detail shows which; check egress and timeouts; re-run |
| Trivy database download fails | No internet or registry rate limit | Pre-download into the cache volume (`--download-db-only`), set `TRIVY_SKIP_DB_UPDATE=true` **[V]** |
| OSV errors or slow | Large batch, transient failure, HTTP/1.1 large responses | Reduce parallelism; retry; see API doc limits **[V]** |
| Jobs stay `queued` | Worker down, DB unreachable, or concurrency 0 | `docker compose logs worker`; check `toolkit_queue_depth` |
| Job repeatedly restarts | Lease shorter than job duration | Increase `JOB_LEASE_SECONDS` above the scan timeout |
| Fix proposal `SANDBOX_UNAVAILABLE` | `REMEDIATION_ENABLED` false, daemon down, network misconfigured | Check `sandbox-docker` health and `SANDBOX_DOCKER_HOST` |
| Fix proposal `SDIST_BUILD_REQUIRED` | A Python package has no wheel | Choose another version or let an admin explicitly allow source builds |
| Approve returns `409 ACK_REQUIRED` / `APPROVAL_REQUIRED` | Acknowledgment missing or proposal not `ready` | Tick required boxes; check proposal status |
| PR creation fails (`PR_PUSH_FAILED`) | Token lacks write/PR permission, branch exists, repository archived | Re-verify repository; check token permissions |
| AI endpoints return `409 AI_DISABLED` | `AI_ENABLED=false` or no key | Set key and enable |
| `429 AI_BUDGET_EXCEEDED` | Daily cap reached | Wait for the next UTC day or raise the cap deliberately |
| High memory on worker | Large repository or Semgrep | Lower `WORKER_CONCURRENCY`; raise limits; exclude vendor directories |

## 11. Teardown

`docker compose down` stops services; `docker compose down -v` also deletes volumes (database, Prometheus data, scanner cache, sandbox storage). Export a backup first if the data matters.
