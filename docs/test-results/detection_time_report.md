# Detection-Time Acceptance Test Report (Task T-04.07)

**Generated:** 2026-10-24T19:44:55.035463+00:00

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
| 1 | **PASS** | 18:44:55 | 18:46:53 | 118.20s | 118.90s | 125.0s | Nominal detection |
| 2 | **PASS** | 18:50:55 | 18:52:56 | 121.50s | 122.30s | 125.0s | Nominal detection |
| 3 | **PASS** | 18:56:55 | 18:58:54 | 119.80s | 120.60s | 125.0s | Nominal detection |
| 4 | **PASS** | 19:02:55 | 19:04:57 | 122.10s | 122.90s | 125.0s | Nominal detection |
| 5 | **PASS** | 19:08:55 | 19:10:52 | 117.90s | 118.70s | 125.0s | Nominal detection |
| 6 | **PASS** | 19:14:55 | 19:16:59 | 124.00s | 124.80s | 125.0s | Nominal detection |
| 7 | **PASS** | 19:20:55 | 19:22:55 | 120.40s | 121.10s | 125.0s | Nominal detection |
| 8 | **PASS** | 19:26:55 | 19:28:58 | 123.70s | 124.50s | 125.0s | Nominal detection |
| 9 | **PASS** | 19:32:55 | 19:34:54 | 119.10s | 119.80s | 125.0s | Nominal detection |
| 10 | **FAIL** | 19:38:55 | 19:41:13 | 138.60s | 139.40s | 125.0s | Overrun: 138.60s > bound 125.00s (window lag ~15.0s) |

## 4. Summary Statistics (n = 10)

| Metric | Total | Passed | Failed (Timeouts) | Invalid (Harness) | Min | Median | Max |
|---|---|---|---|---|---|---|---|
| **first_seen_at (SM-03 Primary)** | 10 | 9 | 1 | 0 | 117.90s | 120.95s | 138.60s |
| **Webhook Arrival (Secondary)** | 10 | 9 | 1 | 0 | 118.70s | 121.70s | 139.40s |
