"""Authentication: login throttling, refresh rotation with reuse detection, bootstrap."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from toolkit import audit
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode
from toolkit.core.security import (
    create_access_token,
    dummy_hash,
    hash_password,
    hash_token,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from toolkit.db.enums import UserRole
from toolkit.db.models import LoginAttempt, RefreshSession, User

log = logging.getLogger(__name__)

# Credential-stuffing guard across many accounts from one address (in addition to the
# documented per account+IP limit, NFR-SEC-04).
PER_IP_FAILURE_LIMIT = 20


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime
    user: User


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


def _check_throttle(db: Session, email: str, ip: str, now: datetime) -> None:
    s = get_settings()
    since = now - timedelta(seconds=s.login_window_seconds)
    pair_failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.email == email,
            LoginAttempt.ip == ip,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= since,
        )
    )
    ip_failures = db.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(LoginAttempt.ip == ip, LoginAttempt.success.is_(False), LoginAttempt.created_at >= since)
    )
    if (pair_failures or 0) >= s.login_max_failures or (ip_failures or 0) >= PER_IP_FAILURE_LIMIT:
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            "Too many failed sign-in attempts. Try again later.",
            headers={"Retry-After": str(s.login_window_seconds)},
        )


def login(db: Session, email: str, password: str, ip: str, now: datetime) -> IssuedTokens:
    email_n = normalize_email(email)
    _check_throttle(db, email_n, ip, now)
    user = find_user_by_email(db, email_n)
    ok = verify_password(user.password_hash if user else dummy_hash(), password)
    if not ok or user is None or not user.is_active:
        db.add(LoginAttempt(email=email_n, ip=ip, success=False, created_at=now))
        audit.record(
            db,
            "auth.login_failed",
            actor_id=user.id if user else None,
            resource_type="user",
            resource_id=user.id if user else None,
            metadata={"email": email_n},
            ip=ip,
        )
        db.commit()
        # Same message whether the account exists or not (TH-01).
        raise ApiError(ErrorCode.INVALID_CREDENTIALS)
    db.add(LoginAttempt(email=email_n, ip=ip, success=True, created_at=now))
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = now
    audit.record(db, "auth.login_succeeded", actor_id=user.id, resource_type="user", resource_id=user.id, ip=ip)
    return _issue(db, user, now, family_id=uuid.uuid4())


def _issue(db: Session, user: User, now: datetime, family_id: uuid.UUID) -> IssuedTokens:
    s = get_settings()
    access, ttl = create_access_token(user.id, now)
    refresh, refresh_hash = new_refresh_token()
    expires = now + timedelta(seconds=s.refresh_session_ttl_seconds)
    db.add(
        RefreshSession(
            user_id=user.id, token_hash=refresh_hash, family_id=family_id, expires_at=expires, created_at=now
        )
    )
    db.flush()
    return IssuedTokens(access, ttl, refresh, expires, user)


def refresh(db: Session, token: str | None, now: datetime) -> IssuedTokens:
    if not token:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "No refresh session.")
    session = db.scalar(select(RefreshSession).where(RefreshSession.token_hash == hash_token(token)).with_for_update())
    if session is None:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Refresh session not found.")
    if session.revoked_at is not None:
        if session.rotated:
            # A rotated token was presented again: assume theft, revoke every session (SECURITY §5).
            revoke_all_sessions(db, session.user_id, now)
            audit.record(
                db,
                "auth.refresh_reuse_detected",
                actor_id=session.user_id,
                resource_type="user",
                resource_id=session.user_id,
            )
            db.commit()
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Refresh session revoked.")
    if session.expires_at <= now:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Refresh session expired.")
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise ApiError(ErrorCode.UNAUTHENTICATED)
    session.revoked_at = now
    session.rotated = True
    return _issue(db, user, now, family_id=session.family_id)


def logout(db: Session, token: str | None, now: datetime) -> None:
    if not token:
        return
    db.execute(
        update(RefreshSession)
        .where(RefreshSession.token_hash == hash_token(token), RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_all_sessions(db: Session, user_id: uuid.UUID, now: datetime) -> None:
    db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def bootstrap_admin(db: Session) -> bool:
    """Create the first admin from ADMIN_BOOTSTRAP_* if no users exist (FR-AUTH-01).

    Serialized with an advisory lock so concurrent API replicas cannot both create one.
    Returns True when an admin was created.
    """
    s = get_settings()
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('toolkit.bootstrap_admin'))"))
    if db.scalar(select(func.count()).select_from(User)):
        return False
    password = s.admin_bootstrap_password.get_secret_value() if s.admin_bootstrap_password else ""
    if not s.admin_bootstrap_email or not password:
        log.warning("no users exist and ADMIN_BOOTSTRAP_EMAIL/PASSWORD are not set")
        return False
    if not 12 <= len(password) <= 128:
        log.error("ADMIN_BOOTSTRAP_PASSWORD must be 12-128 characters; bootstrap skipped")
        return False
    user = User(
        email=normalize_email(s.admin_bootstrap_email),
        display_name="Administrator",
        password_hash=hash_password(password),
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.add(user)
    db.flush()
    audit.record(db, "user.bootstrap_admin_created", actor_id=None, resource_type="user", resource_id=user.id)
    log.info("bootstrap admin created", extra={"user_id": str(user.id)})
    return True
