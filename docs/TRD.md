# Technical Requirements Document (TRD)

> **Doc:** TRD.md · **Version:** 0.1 · **Date:** 2026-10-13 · **Status:** Draft · **Related:** [ARCHITECTURE](ARCHITECTURE.md), [SRS](SRS.md), [API_SPEC](API_SPEC.md), [DATA_MODEL](DATA_MODEL.md)

The proposed stack is **provisional**. Each choice below is marked **[P]** and linked to a decision ID (`DEC-nnn`, detailed in `DECISIONS.md`, batch 2). Only claims marked **[V]** were checked against an official source in this documentation pass; everything else must be verified at the start of the relevant epic (see §9).

## 1. Technology summary

| Layer | Choice | Status | Rationale | Alternatives considered | Effort |
|---|---|---|---|---|---|
| Frontend | Next.js (App Router) + TypeScript; Tailwind CSS; a chart library such as Recharts | [P] DEC-015 | Team familiarity expected; SSR not essential, so a plain React SPA would also work | Vite + React SPA (simpler, fewer moving parts) | M |
| Backend API | FastAPI (Python) + Pydantic + SQLAlchemy + Alembic | [P] DEC-001 | Python ecosystem fits scanners, AI SDK, and subprocess orchestration; OpenAPI generated automatically | Node/NestJS (would split languages) | M |
| Worker | Same Python package (`toolkit`), separate entrypoint | [P] DEC-001, DEC-003 | One codebase, shared models | Celery/RQ/Arq with Redis (extra service) | M |
| Job queue | PostgreSQL table with `SELECT … FOR UPDATE SKIP LOCKED`, leases | [P] DEC-003 | No extra infrastructure; durable; adequate for ≤ 5 concurrent jobs (NFR-CAP-01) | Redis + RQ/Arq | S |
| Relational DB | PostgreSQL | [P] DEC-002 | Strong consistency, JSONB for evidence | SQLite (simpler, weaker concurrency) | S |
| Telemetry protocol | OpenTelemetry (OTLP), metrics only | [P] DEC-004 | Vendor-neutral standard; SDKs in many languages | Prometheus client libraries only | M |
| Telemetry gateway | OpenTelemetry Collector with bearer-token auth, forwarding to Prometheus | [P] DEC-004, UD-06 | Central auth/validation point; future traces/logs | Prometheus native OTLP receiver (fewer components, no built-in auth) | M |
| Time-series store | Prometheus | [P] DEC-004 | De facto open-source standard; PromQL | VictoriaMetrics (not evaluated in depth) | S |
| Alert evaluation | In-app engine querying Prometheus HTTP API | [P] DEC-005 | Alert records, lifecycle, and evidence live in our DB and UI; avoids Alertmanager routing config | Prometheus rules + Alertmanager webhook | M |
| Dependency vulnerabilities | Trivy (primary: inventory + vulnerabilities) and OSV API (cross-check + advisory details) | [P] DEC-006 | Two independent sources reduce misses; OSV exposes fixed ranges and aliases **[V]** | OSV-Scanner CLI as a single tool (evaluate in EP-05 spike) | L |
| Static analysis | Semgrep Community Edition engine | [P] DEC-007, UD-01 | Multi-language, JSON output, declarative rules | Opengrep or own rule set (licensing hedge) | M |
| LLM | Claude via Anthropic Python SDK; model from `CLAUDE_MODEL` | [P] DEC-008, UD-05 | Strong structured-output behavior expected; configurable | Local open models (resource-heavy) | M |
| Git provider | GitHub REST API; fine-grained PAT | [P] DEC-009, UD-02 | Simplest for students | GitHub App (better least-privilege, more setup) | M |
| Sandbox | Dedicated, isolated Docker daemon (e.g., rootless Docker-in-Docker) reachable only over an internal network | [P] DEC-010, UD-03 | Avoids mounting host Docker socket | Podman rootless; gVisor/Firecracker (high effort) | **XL** |
| Auth | Local accounts, Argon2id, JWT access token + refresh session | [P] DEC-013 | No external IdP needed | OIDC/SSO (post-MVP) | M |
| Packaging | Docker Compose | [P] | Single-command local deployment | Kubernetes (out of scope) | S |

## 2. Version policy

- Exact versions are **not** fixed in this document (they change faster than documentation). At project start, the team pins versions in lockfiles (`package-lock.json`, `uv.lock` or `requirements.txt` with hashes) and lists the pinned runtime versions in `README.md` §Prerequisites. **[A]**
- Prefer actively supported LTS runtimes. Check support status on the vendors' release pages before pinning.
- Dependabot-style updates for the Toolkit's own dependencies are encouraged but must pass CI (NFR-SEC-07).

## 3. Telemetry pipeline (EP-03)

```text
Monitored app (OTel SDK) --OTLP/HTTP + bearer--> OTel Collector --remote write--> Prometheus
                                                         ^                           |
                                                  token validated here         PromQL (API/worker)
```

- **Identification:** a monitoring target is identified by the resource attribute `service.name` (stored as `service_name`) and an `environment` label. After translation to Prometheus these appear as labels whose exact names depend on the Collector/Prometheus translation settings **[A]**; the spike in EP-03 must confirm names such as `service_name` and metric names such as `http_server_request_duration_seconds_*` (UD-06). Until verified, all queries live in one module (`monitoring/queries.py`) so they change in one place.
- **Authentication:** one deployment-wide ingest token validated by the Collector (DEC-014). Per-target tokens are a post-MVP improvement.
- **Metrics used:** the HTTP server request-duration histogram (count, sum, buckets) with status-code attribute. Applications not emitting it show an empty state with instructions (AS-01).
- **Exporter details:** the Collector's Prometheus remote-write exporter preserves sample timestamps better than scrape-based export for push sources **[A, to verify]**; it requires Prometheus to enable its remote-write receiver (`--web.enable-remote-write-receiver`, endpoint `/api/v1/write`) **[V]**. The alternative (Collector Prometheus exporter + scrape) is simpler but holds series for an expiry period, which can delay staleness detection.

## 4. Query templates (allowlisted)

The API never forwards user-supplied PromQL (IF-02). Templates (illustrative; labels pending UD-06):

| Name | PromQL template |
|---|---|
| `request_rate` | `sum(rate(http_server_request_duration_seconds_count{service_name="$svc"}[$win]))` |
| `error_ratio` | `sum(rate(http_server_request_duration_seconds_count{service_name="$svc",http_response_status_code=~"5.."}[$win])) / sum(rate(http_server_request_duration_seconds_count{service_name="$svc"}[$win]))` |
| `latency_p95` | `histogram_quantile(0.95, sum by (le) (rate(http_server_request_duration_seconds_bucket{service_name="$svc"}[$win])))` |
| `data_absent` | `absent_over_time(http_server_request_duration_seconds_count{service_name="$svc"}[$stale])` |

`$svc`, `$win`, `$stale` are validated against `^[A-Za-z0-9_.:-]{1,100}$` and duration grammar before substitution.

## 5. Scanner integrations (EP-05, EP-06)

### 5.1 Pipeline

1. **Clone** (worker): shallow clone of the requested ref with hooks disabled, submodules not fetched, size and time limits. Workspace is an ephemeral directory deleted when the job ends.
2. **Trivy**: `trivy fs` with `--format json` and an explicit `--scanners vuln` (the documented default also enables secret scanning, which the Toolkit deliberately avoids) **[V]**; the scanner database comes from Trivy's default OCI repository `ghcr.io/aquasecurity/trivy-db` (EXT-07), can be pre-downloaded (`--download-db-only`) and reused offline (`--skip-db-update`, `--cache-dir`) **[V]**. Exact flags are fixed in code as an argument vector and documented in `DEPLOYMENT.md`.
3. **OSV**: for each `(ecosystem, name, version)` from the inventory, call the **batch query** endpoint (batches of ≤ 1,000 queries), which returns vulnerability IDs and modified timestamps; fetch each full record via the **vulnerability-by-ID** endpoint and cache by `(id, modified)` **[V]**. Handle `next_page_token` pagination; apply timeouts, exponential backoff, bounded parallelism. The documentation states no API rate limit currently, but clients must still be defensive **[V]**.
4. **Registry metadata**: npm and PyPI JSON metadata for latest stable version, release date, license, deprecation, `engines` / `requires_python`, and existence checks **[A, endpoints to verify]**.
5. **Semgrep**: JSON output, metrics disabled, timeout, max target file size, default excludes (FR-SAST-03).
6. **Normalize** to `finding` rows (types in [DATA_MODEL](DATA_MODEL.md)); merge duplicates by alias set (FR-DEP-04); compute `fingerprint`; compare with previous scan (FR-DEP-09).

### 5.2 Fingerprint

\[ \text{fingerprint} = \operatorname{SHA256}\big(\text{type} \,\Vert\, \text{rule\_or\_advisory\_key} \,\Vert\, \text{subject\_key} \big) \]

where `rule_or_advisory_key` is the lowest-sorted advisory ID in the alias set (vulnerabilities), the Semgrep rule ID (code issues), or a fixed heuristic name (outdated/incompatibility), and `subject_key` is `ecosystem:name:version` for dependencies or `path:normalized_snippet_hash` for code. Line numbers are deliberately excluded so findings survive unrelated edits.

### 5.3 Severity mapping

Severity values are `critical, high, medium, low, info`. Advisory severity is taken from the source (CVSS-derived label when present). When the source provides none, no severity is invented: the field is `null` and the UI shows "unrated". Semgrep severities map `ERROR→high`, `WARNING→medium`, `INFO→low` **[A]**. Outdated findings: `info` (patch/minor lag) or `low` (major lag) **[P]**.

### 5.4 Licensing note

Semgrep's engine is LGPL 2.1, while Semgrep-maintained rules are under the Semgrep Rules License v.1.0, available for internal business use; vendors cannot use them in competing products or SaaS offerings **[V]**. A self-hosted, non-commercial student project is likely within "internal use", but this is **not legal advice**; the team should confirm and decide UD-01 (alternatives: write own rules, use third-party rule sets with permissive licenses, or evaluate Opengrep).

## 6. Algorithms and formulas

### 6.1 Reliability metrics

Over a window \( W \), let \( R_{total} \) be the number of server requests observed and \( R_{5xx} \) the number with an HTTP status code in the 500–599 range. Define

\[ \text{ErrorRatio}_W = \frac{R_{5xx}}{R_{total}}, \qquad \text{SLI}_{avail,W} = 1 - \text{ErrorRatio}_W \]

with \( R_{total} = 0 \Rightarrow \) undefined (shown as "no traffic", never as 100 % available). 4xx responses are excluded from errors because they typically indicate client behavior **[P]**; the definition is configurable per rule in a later release. Latency percentiles are estimated from histogram buckets by the Prometheus `histogram_quantile` function, so their accuracy is bounded by bucket boundaries **[A]**.

### 6.2 Anomaly and alert timing

*Threshold rule:* fire when the metric \( x_t \) violates the comparator for at least `duration` seconds, i.e. for \( N = \lceil \text{duration} / \Delta_{eval} \rceil \) consecutive evaluations. Auto-resolve after `resolve_after` consecutive non-violating evaluations.

*Z-score anomaly rule (Should, FR-MON-05):* for series \( x_t \), baseline window of \( B \) samples before \( t \),

\[ \mu_t = \frac{1}{B}\sum_{i=1}^{B} x_{t-i}, \qquad \sigma_t = \sqrt{\frac{1}{B-1}\sum_{i=1}^{B}(x_{t-i}-\mu_t)^2}, \qquad z_t = \frac{x_t-\mu_t}{\max(\sigma_t,\ \varepsilon)} \]

An anomaly is flagged when \( \lvert z_t \rvert > k \) for \( N \) consecutive evaluations. Parameters: \( B \) (default 60 evaluation points), \( k \) (default 3), \( N \) (default 3), \( \varepsilon \) a small floor (default 1e-9; for rates a floor relative to \( \mu_t \) should be tuned). These are **starting values to be tuned on the demo app**, not validated defaults. The method assumes roughly stable baselines and will under-perform for strongly seasonal traffic **[A]**.

*Detection time bound:* \[ T_{detect} \le T_{ingest} + N \cdot \Delta_{eval} \]
where \( T_{ingest} \) = metric export interval + pipeline delay + Prometheus availability delay, \( \Delta_{eval} \) = evaluation interval (`ALERT_EVAL_INTERVAL_SECONDS`), \( N \) as above. A range-vector window in PromQL (e.g., `[5m]`) adds smoothing delay, which must be added to \( T_{ingest} \) when comparing against SM-03 **[A]**.

## 7. AI integration (summary; details in `AI_DESIGN.md`, batch 2)

- Official Anthropic SDK; model identifier from `CLAUDE_MODEL`; no API key in the browser.
- Structured JSON output validated with Pydantic; at most one automatic repair attempt.
- The model receives only an evidence pack; it has **no tools** in the MVP (no code execution, no network, no repository access).
- Validators call registries (package/version existence), compare against stored advisory data, and run `git apply --check` for any proposed patch in the sandbox.

## 8. Remediation execution (EP-09)

| Stage | Network | Scripts | Allowed commands (fixed argument vectors) |
|---|---|---|---|
| Baseline tests | off after dependency install | per repo test command | `npm ci --ignore-scripts` then `npm test` / `pip install` into venv then `pytest` (see UD-07) |
| Apply change | on, registry allowlist **[A: needs egress proxy or accepted risk]** | disabled (`--ignore-scripts` for npm; wheels-only / no build isolation bypass for pip where feasible) | `npm install <pkg>@<version> --package-lock-only --ignore-scripts`; `pip install --dry-run`/`pip-compile`-style resolution **[A: finalize in spike]** |
| Post-change tests | **off** | per repo test command | same as baseline |
| Re-scan | n/a (read-only) | n/a | Trivy/OSV on resulting lockfile |
| PR creation | host-side worker only | n/a | GitHub REST calls; branch `toolkit/fix/<proposal-id>` |

Constraints: package name matches ecosystem grammar; version matches PEP 440 / SemVer; diff scope limited to manifest and lockfile paths; wall-clock limit per stage; output truncated. **Known limitation:** disabling lifecycle scripts can break packages needing install-time builds; such cases yield `unverified` or `failed`, never a silent pass. Python resolution without a lockfile is weaker than npm's; MVP supports `requirements.txt` with pinned versions and (Should) `poetry.lock`/`uv.lock` **[A]**.

## 9. Verification log

Access date for all rows: **2026-10-13**.

| # | Claim | Status | Source |
|---|---|---|---|
| V-01 | OSV exposes a batch query endpoint returning vulnerability IDs per query in input order, a single-query endpoint, and a fetch-by-ID endpoint; batch limited to 1,000 queries; results can paginate with `next_page_token`; no documented API rate limit | **Verified** (secondary summaries consistent with official doc paths; official pages not fetched directly) | https://google.github.io/osv.dev/post-v1-querybatch/ · https://google.github.io/osv.dev/post-v1-query/ · https://google.github.io/osv.dev/get-v1-vulns/ |
| V-02 | Semgrep CE engine is LGPL 2.1; Semgrep-maintained rules are under Semgrep Rules License v.1.0; vendors cannot use them in competing products/SaaS | **Verified** | https://docs.semgrep.dev/licensing · https://semgrep.dev/docs/faq/overview |
| V-03 | OTLP default ports 4317 (gRPC) / 4318 (HTTP); standard `OTEL_*` exporter environment variables | Not yet verified in this pass | https://opentelemetry.io/docs/ |
| V-04 | The OTLP receiver can authenticate both HTTP and gRPC clients with the `bearertokenauth` extension (extension listed under `service.extensions`, referenced as the receiver's `authenticator`). Prometheus remote-write *exporter* keys and resource-to-label conversion are a separate claim | Auth: **Verified** (documentation mirrors; upstream README not fetched). Exporter keys: not yet verified | https://opentelemetry.io/docs/collector/ · https://docs.redhat.com/en/documentation/red_hat_build_of_opentelemetry/3.8/html/configuring_the_collector/otel-collector-extensions |
| V-05 | Prometheus remote-write receiver is enabled by `--web.enable-remote-write-receiver` and listens at `/api/v1/write`; retention defaults to 15 days when no retention setting is given; a native OTLP receiver flag (`--web.enable-otlp-receiver`) exists; the latest docs mark the `--storage.tsdb.retention.time` *flag* as deprecated in favor of a config-file field (version-dependent). OTel→Prometheus name/label translation not verified | **Verified** (flags, endpoint, default retention); translation **not yet verified** | https://prometheus.io/docs/operating/storage/ · https://prometheus.io/docs/prometheus/latest/command-line/prometheus/ |
| V-06 | `trivy fs` supports `--format json`, `--scanners`, `--skip-db-update`, `--cache-dir`, `--download-db-only`; documented default scanners include `vuln` **and** `secret`, so the Toolkit must pass `--scanners vuln` explicitly; the default DB repository is `ghcr.io/aquasecurity/trivy-db` | **Verified** against CLI reference pages (v0.39/v0.43) and secondary guides; re-check against the pinned version | https://trivy.dev/v0.43/docs/references/configuration/cli/trivy_rootfs |
| V-07 | npm registry and PyPI JSON metadata fields (`deprecated`, `engines`, `requires_python`) | Not yet verified | https://docs.npmjs.com/ · https://docs.pypi.org/api/json/ |
| V-08 | GitHub fine-grained PAT permissions for creating branches and draft PRs | Not yet verified | https://docs.github.com/en/rest |
| V-09 | Anthropic SDK structured-output and model identifiers | Not yet verified; model string `claude-sonnet-5-5` taken from Anthropic product information available to the author | https://docs.claude.com/ |
| V-10 | Rootless Docker-in-Docker feasibility on Windows/macOS dev machines | Not yet verified; spike required (UD-03) | https://docs.docker.com/ |

Each "Not yet verified" row maps to a verification task at the start of its epic in `TASKS.md` (batch 2).

## 10. Implementation constraints

1. All external calls go through `integrations/` adapters with timeouts, retries, and typed errors; no scattered HTTP calls.
2. Subprocess execution only through one helper that takes an argument vector (never `shell=True`).
3. All Prometheus queries built in `monitoring/queries.py`.
4. All LLM calls built in `ai/client.py` and pass through the validator before persistence as `validated`.
5. Feature flags: `AI_ENABLED`, `REMEDIATION_ENABLED` (disables sandbox use entirely).
6. Idempotent migrations (Alembic); no manual schema edits.
