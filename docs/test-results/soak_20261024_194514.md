# Detection-Time Acceptance Test Report (Task T-04.07)

**Generated:** 2026-10-24T19:45:14.533122+00:00

## 1. Environment & Provenance

| Parameter | Value | Provenance / Notes |
|---|---|---|
| **Git Commit** | `HEAD` | HEAD reference |
| **OS Platform** | `win32` | Host runtime environment |
| **Python Version** | `3.13.1` | Pinned interpreter |
| **API Base URL** | `http://localhost:8000` | Dashboard & alerting backend |
| **Demo App URL** | `http://localhost:8080` | Monitored test service |
| **T_ingest (SP-01)** | `5.0s` | Measured pipeline ingestion delay from Spike SP-01 (collector -> Prometheus remote-write) |
| **Delta_eval** | `30.0s` | Application configuration ALERT_EVAL_INTERVAL_SECONDS (default: 30s) |
| **Rule Duration** | `120s` | Threshold duration from active rule |
| **Rule Window** | `5m` | Rate vector sliding window |
| **Resolve After** | `3 ticks` | Consecutive clear evaluations |
| **Traffic Rate** | `5.0 req/s` | Generated steady load by test script |
| **Export Interval** | `5000ms` | Demo app OTel periodic metric reader |

## 2. Theoretical Bound vs. Rate-Window Lag

Per TRD §6.2 and SM-03, the bound is defined as: `Bound = T_ingest + N * delta_eval`.
- For duration = 120s and delta_eval = 30.0s:
  - `N = ceil(120 / 30.0) = 4`
  - `Bound = 5.0 + (4 * 30.0) = 125.0s`

> [!NOTE]
> **Rate-Window Smoothing Lag (TRD §6.2 note [A]):**
> The PromQL `error_ratio` template uses a sliding rate window (e.g. `5m` / 300s). At 100% injected 5xx error rate,
> the ratio `sum(rate(...5xx...)) / sum(rate(...))` starts at 0.0 and rises linearly, requiring approximately
> `0.05 * 300s = 15s` simply to cross the 0.05 breach threshold. Combined with loop cadence alignment,
> real detection time can reach ~135s-145s.

## 3. Detection-Time Run Results

| Run | Status | t_fault (UTC) | t_alert (first_seen) | T_detect (first_seen) | T_detect (webhook) | Bound | Notes |
|---|---|---|---|---|---|---|---|

## 4. Summary Statistics (n = 10)

| Metric | Total | Passed | Failed (Timeouts) | Invalid (Harness) | Min | Median | Max |
|---|---|---|---|---|---|---|---|
| **first_seen_at (SM-03 Primary)** | 0 | 0 | 0 | 0 | N/A | N/A | N/A |
| **Webhook Arrival (Secondary)** | 0 | 0 | 0 | 0 | N/A | N/A | N/A |

## 5. Soak Run Results (SM-04 Alert Noise)

- **Status:** **PASS**
- **Duration:** 3600.0s
- **Requests Sent:** 18000
- **Alerts Created:** 0 (SM-04 Expected: 0)
- **Webhook Deliveries Received:** 0
- **Notes:** Zero alerts created expected for SM-04 (healthy constant load)
