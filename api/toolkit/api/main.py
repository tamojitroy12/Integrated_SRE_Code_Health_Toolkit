"""FastAPI application factory (COMP-02)."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from toolkit import __version__
from toolkit.api.routes import (
    alerts,
    auth,
    channels,
    findings,
    fix_proposals,
    misc,
    ops,
    projects,
    recommendations,
    repository,
    scans,
    targets,
    users,
)
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode
from toolkit.core.logging import configure_logging, request_id_var
from toolkit.core.metrics import BUILD_INFO, HTTP_DURATION, HTTP_REQUESTS

log = logging.getLogger("toolkit.api")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
API_PREFIX = "/api/v1"


def _error_body(code: str, message: str, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or [], "request_id": request_id_var.get()}}


def reject_unknown_query_params(request: Request) -> None:
    """Unsupported query parameters → 400 BAD_REQUEST (API_SPEC §3)."""
    route = request.scope.get("route")
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return
    allowed: set[str] = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        allowed.update(p.alias for p in d.query_params)
        stack.extend(d.dependencies)
    unknown = sorted(set(request.query_params.keys()) - allowed)
    if unknown:
        raise ApiError(
            ErrorCode.BAD_REQUEST,
            "Unsupported query parameter.",
            details=[{"field": k, "issue": "unsupported query parameter"} for k in unknown],
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    from toolkit.db.session import session_scope
    from toolkit.services.auth import bootstrap_admin

    BUILD_INFO.info({"version": __version__, "component": "api"})
    try:
        with session_scope() as db:
            bootstrap_admin(db)
    except Exception:
        log.exception("admin bootstrap failed; the API will start without it")
    yield


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(
        title="SRE + Code Health Toolkit API",
        version=__version__,
        docs_url="/docs" if s.api_docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.api_docs_enabled else None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        token = request_id_var.set(rid)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            elapsed = time.perf_counter() - started
            route = request.scope.get("route")
            template = getattr(route, "path", "unmatched")
            HTTP_REQUESTS.labels(template, request.method, str(status)).inc()
            HTTP_DURATION.labels(template, request.method).observe(elapsed)
            if template not in ("/health", "/metrics"):
                # Bodies and query strings are never logged (NFR-SEC-08, DATA_MODEL §8).
                log.info(
                    "request",
                    extra={
                        "method": request.method,
                        "route": template,
                        "status": status,
                        "duration_ms": round(elapsed * 1000, 1),
                        "user_id": getattr(request.state, "user_id", None),
                    },
                )
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        if not request.url.path.startswith("/docs"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if s.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID", "Idempotency-Key"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            _error_body(exc.code.value, exc.message, exc.details), status_code=exc.status, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
            msg = str(err.get("msg", "invalid")).removeprefix("Value error, ")
            if err.get("type") == "extra_forbidden":
                msg = "unknown field"
            details.append({"field": ".".join(loc) or "body", "issue": msg})
        malformed = any(e.get("type") == "json_invalid" for e in exc.errors())
        if malformed:
            return JSONResponse(_error_body("BAD_REQUEST", "Malformed JSON body.", details), status_code=400)
        return JSONResponse(_error_body("VALIDATION_ERROR", "Request validation failed.", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "BAD_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN"}.get(
            exc.status_code, "BAD_REQUEST"
        )
        message = "Resource not found." if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(_error_body(code, message), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"error": type(exc).__name__})
        return JSONResponse(_error_body("INTERNAL_ERROR", "An unexpected error occurred."), status_code=500)

    api = APIRouter(prefix=API_PREFIX, dependencies=[Depends(reject_unknown_query_params)])
    for module in (
        auth,
        users,
        projects,
        repository,
        targets,
        alerts,
        channels,
        scans,
        findings,
        recommendations,
        fix_proposals,
        misc,
    ):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(ops.router)
    _import_job_handlers()
    return app


def _import_job_handlers() -> None:
    """Import modules that register job terminal hooks (used by cancel-before-start in the API)."""
    import toolkit.ai.service
    import toolkit.remediation.pipeline
    import toolkit.remediation.pr
    import toolkit.scanning.orchestrator  # noqa: F401


app = create_app()
