"""Server-side authorization on every route (FR-AUTH-03, SECURITY §6, SC-01)."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from tests.conftest import Users

GUARDS = {"require_viewer", "require_maintainer", "require_admin", "public_route"}
PUBLIC = {
    ("/api/v1/auth/login", "POST"),
    ("/api/v1/auth/refresh", "POST"),
    ("/health", "GET"),
    ("/ready", "GET"),
    ("/metrics", "GET"),
}
ADMIN_ONLY = {
    ("/api/v1/users", "GET"),
    ("/api/v1/users", "POST"),
    ("/api/v1/users/{user_id}", "PATCH"),
    ("/api/v1/notification-channels", "POST"),
    ("/api/v1/notification-channels/{channel_id}", "PATCH"),
    ("/api/v1/notification-channels/{channel_id}", "DELETE"),
    ("/api/v1/notification-channels/{channel_id}/test", "POST"),
    ("/api/v1/audit-log", "GET"),
}
VIEWER_GETS_DENIED = {
    ("/api/v1/notification-channels", "GET"),
    ("/api/v1/monitoring-targets/{target_id}/onboarding", "GET"),
}


def _all_routes(app: Any) -> list[tuple[str, str, APIRoute]]:
    """Effective (prefixed) routes, including those inside included routers."""
    from fastapi.routing import iter_route_contexts

    found: list[tuple[str, str, APIRoute]] = []
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if isinstance(route, APIRoute):
            for m in ctx.methods or route.methods:
                found.append((ctx.path, m, route))
    return found


def _dep_names(route: APIRoute) -> set[str]:
    names: set[str] = set()
    stack = [route.dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            names.add(getattr(d.call, "__name__", ""))
        stack.extend(d.dependencies)
    return names


@pytest.mark.at("FR-AUTH-03")
def test_every_route_declares_exactly_one_guard(app: Any) -> None:
    routes = _all_routes(app)
    api_routes = [(p, m, r) for p, m, r in routes if p.startswith("/api/") or p in ("/health", "/ready", "/metrics")]
    assert len(api_routes) > 60
    for path, method, route in api_routes:
        guards = _dep_names(route) & GUARDS
        assert guards, f"{method} {path} has no role guard"
        if (path, method) in PUBLIC:
            assert "public_route" in guards, f"{method} {path} should be public"
        else:
            assert "public_route" not in guards, f"{method} {path} must not be public"
        if (path, method) in ADMIN_ONLY:
            assert "require_admin" in guards, f"{method} {path} must be admin-only"


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


@pytest.mark.at("FR-AUTH-03")
def test_viewer_cannot_mutate_anything(app: Any, client: TestClient, users: Users) -> None:
    headers = users.headers("viewer")
    checked = 0
    for path, method, _route in _all_routes(app):
        if not path.startswith("/api/v1") or (path, method) in PUBLIC or method in ("GET", "HEAD"):
            continue
        if path in ("/api/v1/auth/logout",):
            continue
        r = client.request(method, _fill(path), headers={**headers, "X-Requested-With": "t"}, json={})
        assert r.status_code == 403, f"viewer got {r.status_code} on {method} {path}"
        checked += 1
    assert checked > 30
    for path, _method in VIEWER_GETS_DENIED:
        assert client.get(_fill(path), headers=headers).status_code == 403


@pytest.mark.at("FR-AUTH-03")
def test_maintainer_cannot_use_admin_routes(app: Any, client: TestClient, users: Users) -> None:
    headers = users.headers("maintainer")
    for path, method in ADMIN_ONLY:
        r = client.request(method, _fill(path), headers=headers, json={})
        assert r.status_code == 403, f"maintainer got {r.status_code} on {method} {path}"


def test_unauthenticated_requests_are_rejected(app: Any, client: TestClient) -> None:
    for path, method, _r in _all_routes(app):
        if not path.startswith("/api/v1") or (path, method) in PUBLIC:
            continue
        r = client.request(method, _fill(path), json={})
        assert r.status_code == 401, f"{method} {path} returned {r.status_code}"


def test_no_merge_endpoint_exists(app: Any) -> None:
    for path, _m, _r in _all_routes(app):
        assert "merge" not in path.lower()
