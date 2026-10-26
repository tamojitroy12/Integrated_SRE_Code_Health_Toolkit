"""Unversioned operational endpoints: /health, /ready, /metrics (NFR-REL-03, SECURITY §6.1)."""

from __future__ import annotations

import hmac
import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from toolkit import __version__
from toolkit.api.deps import DB, public_route
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode
from toolkit.core.metrics import QUEUE_DEPTH, REGISTRY
from toolkit.db.session import ping
from toolkit.jobs.queue import queue_depth
from toolkit.monitoring.prometheus import PrometheusClient

router = APIRouter(tags=["operations"])


@router.get("/health", dependencies=[Depends(public_route)])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", dependencies=[Depends(public_route)])
def ready(db: DB) -> JSONResponse:
    s = get_settings()
    db_ok = ping(db)
    prom = PrometheusClient(timeout=2.0)
    try:
        prom_ok = prom.ready()
    finally:
        prom.close()
    body = {
        "status": "ok" if db_ok else "unavailable",
        "checks": {
            "database": "ok" if db_ok else "failed",
            "prometheus": "ok" if prom_ok else "degraded",
            "ai": "ok" if s.ai_available else "disabled",
            "remediation": "enabled" if s.remediation_enabled else "disabled",
        },
        "version": __version__,
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


def _metrics_allowed(request: Request) -> bool:
    token = get_settings().metrics_scrape_token.get_secret_value()
    if token:
        header = request.headers.get("authorization", "")
        return hmac.compare_digest(header, f"Bearer {token}")
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host == "testclient"
    return ip.is_private or ip.is_loopback


@router.get("/metrics", dependencies=[Depends(public_route)], include_in_schema=False)
def metrics(request: Request, db: DB) -> Response:
    """Internal only: scrape token or private network (never expose through a public proxy)."""
    if not _metrics_allowed(request):
        raise ApiError(ErrorCode.FORBIDDEN, "Metrics are only available on the internal network.")
    depth: dict[str, Any] = queue_depth(db)
    for job_type in ("scan", "recommendation", "fix_proposal", "pr_creation", "pr_cleanup"):
        QUEUE_DEPTH.labels(job_type).set(depth.get(job_type, 0))
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
