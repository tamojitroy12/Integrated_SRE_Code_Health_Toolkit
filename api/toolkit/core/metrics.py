"""Self-observability metrics for api and worker (NFR-REL-03, NFR-OBS-02, DEPLOYMENT §6)."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, Info

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter("toolkit_http_requests_total", "API requests", ["route", "method", "status"], registry=REGISTRY)
HTTP_DURATION = Histogram(
    "toolkit_http_request_duration_seconds",
    "API request duration",
    ["route", "method"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=REGISTRY,
)
JOBS = Counter("toolkit_jobs_total", "Finished jobs", ["type", "status"], registry=REGISTRY)
JOB_DURATION = Histogram(
    "toolkit_job_duration_seconds",
    "Job duration",
    ["type"],
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 900, 1800),
    registry=REGISTRY,
)
QUEUE_DEPTH = Gauge("toolkit_queue_depth", "Queued jobs", ["type"], registry=REGISTRY)
PROVIDER_RUNS = Counter("toolkit_provider_runs_total", "Scan provider runs", ["provider", "status"], registry=REGISTRY)
AI_REQUESTS = Counter("toolkit_ai_requests_total", "AI model calls", ["kind"], registry=REGISTRY)
AI_VALIDATION = Counter(
    "toolkit_ai_validation_total", "AI validation outcomes", ["kind", "validation_status"], registry=REGISTRY
)
ALERT_EVALUATIONS = Counter("toolkit_alert_evaluations_total", "Alert rule evaluations", ["outcome"], registry=REGISTRY)
NOTIFICATIONS = Counter("toolkit_notifications_total", "Notification delivery attempts", ["status"], registry=REGISTRY)
SANDBOX_STAGES = Counter("toolkit_sandbox_stage_total", "Sandbox stages", ["stage", "status"], registry=REGISTRY)
BUILD_INFO = Info("toolkit_build", "Build information", registry=REGISTRY)
