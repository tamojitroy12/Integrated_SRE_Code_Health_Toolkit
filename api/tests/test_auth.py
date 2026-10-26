"""Authentication and user management (FR-AUTH-01/02/04, NFR-SEC-01/04)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.conftest import Users, set_env
from toolkit.core.clock import FakeClock
from toolkit.db.models import AuditLog, RefreshSession, User
from toolkit.services.auth import bootstrap_admin

CSRF = {"X-Requested-With": "toolkit"}


def login(client: TestClient, email: str, password: str = "correct horse battery"):  # type: ignore[no-untyped-def]
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


@pytest.mark.at("FR-AUTH-01")
def test_bootstrap_creates_admin_once(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    db.query(User).delete()
    set_env(monkeypatch, admin_bootstrap_email="Boot@Example.edu", admin_bootstrap_password="bootstrap-pass-123")
    assert bootstrap_admin(db) is True
    admin = db.scalar(select(User).where(User.email == "boot@example.edu"))
    assert admin is not None and admin.role == "admin"
    first_hash = admin.password_hash
    set_env(monkeypatch, admin_bootstrap_password="another-password-456")
    assert bootstrap_admin(db) is False  # second start does not change credentials
    db.refresh(admin)
    assert admin.password_hash == first_hash


@pytest.mark.at("FR-AUTH-01")
def test_non_admin_cannot_create_users(client: TestClient, users: Users) -> None:
    body = {"email": "new@example.edu", "display_name": "New", "role": "viewer", "initial_password": "x" * 12}
    assert client.post("/api/v1/users", json=body, headers=users.headers("maintainer")).status_code == 403
    r = client.post("/api/v1/users", json=body, headers=users.headers("admin"))
    assert r.status_code == 201 and "password" not in r.text
    assert client.post("/api/v1/users", json=body, headers=users.headers("admin")).status_code == 409


@pytest.mark.at("FR-AUTH-02")
@pytest.mark.nt("SEC-01")
def test_login_refresh_logout_flow(client: TestClient, users: Users, db: Session) -> None:
    user = users.make("viewer", email="viewer@example.edu")
    r = login(client, "VIEWER@example.edu")
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] <= 900 and body["user"]["role"] == "viewer"
    cookie = r.headers["set-cookie"]
    assert (
        "HttpOnly" in cookie
        and "SameSite=strict" in cookie.replace("Strict", "strict")
        and "Path=/api/v1/auth" in cookie
    )
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["id"] == str(user.id)

    # Refresh needs the custom header (CSRF guard) and rotates the token.
    assert client.post("/api/v1/auth/refresh").status_code == 403
    old_refresh = client.cookies.get("toolkit_refresh")
    r2 = client.post("/api/v1/auth/refresh", headers=CSRF)
    assert r2.status_code == 200
    assert client.cookies.get("toolkit_refresh") != old_refresh

    r3 = client.post("/api/v1/auth/logout", headers={**CSRF, "Authorization": f"Bearer {r2.json()['access_token']}"})
    assert r3.status_code == 204
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401


@pytest.mark.at("FR-AUTH-02")
def test_wrong_password_uniform_error(client: TestClient, users: Users, db: Session) -> None:
    users.make("viewer", email="a@example.edu")
    wrong = login(client, "a@example.edu", "nope-nope-nope")
    missing = login(client, "missing@example.edu", "nope-nope-nope")
    assert wrong.status_code == missing.status_code == 401
    assert wrong.json()["error"]["code"] == missing.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message"] == missing.json()["error"]["message"]
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.login_failed")) == 2


@pytest.mark.at("FR-AUTH-02")
def test_expired_access_token(client: TestClient, users: Users, clock: FakeClock) -> None:
    headers = users.headers("viewer")
    clock.advance(901)
    r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_garbage_token_and_deactivated_user(client: TestClient, users: Users, db: Session) -> None:
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401
    user = users.make("viewer")
    headers = users.headers(user)
    user.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


@pytest.mark.nt("SEC-01")
def test_refresh_reuse_revokes_all_sessions(client: TestClient, users: Users, db: Session) -> None:
    user = users.make("viewer", email="reuse@example.edu")
    login(client, "reuse@example.edu")
    stolen = client.cookies.get("toolkit_refresh")
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 200
    # Attacker replays the rotated token.
    client.cookies.clear()
    client.cookies.set("toolkit_refresh", stolen)
    assert client.post("/api/v1/auth/refresh", headers=CSRF).status_code == 401
    active = db.scalar(
        select(func.count())
        .select_from(RefreshSession)
        .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
    )
    assert active == 0


@pytest.mark.nt("SEC-04")
def test_login_rate_limited_after_five_failures(client: TestClient, users: Users) -> None:
    users.make("viewer", email="rl@example.edu")
    for _ in range(5):
        assert login(client, "rl@example.edu", "wrong-password-x").status_code == 401
    sixth = login(client, "rl@example.edu", "correct horse battery")
    assert sixth.status_code == 429 and sixth.json()["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in sixth.headers


def test_user_admin_patch_and_last_admin_guard(client: TestClient, users: Users, db: Session) -> None:
    admin = users.get("admin")
    h = users.headers("admin")
    db.query(User).filter(User.role == "admin", User.id != admin.id).delete()
    db.commit()
    r = client.patch(f"/api/v1/users/{admin.id}", json={"role": "viewer"}, headers=h)
    assert r.status_code == 409
    v = users.make("viewer")
    r = client.patch(f"/api/v1/users/{v.id}", json={"role": "maintainer", "display_name": "Promoted"}, headers=h)
    assert r.status_code == 200 and r.json()["role"] == "maintainer"
    r = client.patch(f"/api/v1/users/{v.id}", json={"password": "short"}, headers=h)
    assert r.status_code == 422
    listed = client.get("/api/v1/users?limit=1", headers=h).json()
    assert len(listed["items"]) == 1 and listed["next_cursor"]
    assert client.get(f"/api/v1/users?cursor={listed['next_cursor']}", headers=h).status_code == 200


@pytest.mark.at("FR-AUTH-04")
def test_audit_log_endpoint_admin_only(client: TestClient, users: Users) -> None:
    users.make("viewer", email="aud@example.edu")
    login(client, "aud@example.edu", "bad-password-1")
    assert client.get("/api/v1/audit-log", headers=users.headers("maintainer")).status_code == 403
    r = client.get("/api/v1/audit-log?action=auth.", headers=users.headers("admin"))
    assert r.status_code == 200
    assert any(i["action"] == "auth.login_failed" for i in r.json()["items"])
