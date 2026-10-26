"""Password hashing (Argon2id), access tokens (JWT) and opaque refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from toolkit.core.config import get_settings

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "sre-code-health-toolkit"


@lru_cache(maxsize=1)
def _hasher() -> PasswordHasher:
    s = get_settings()
    return PasswordHasher(
        time_cost=s.argon2_time_cost,
        memory_cost=s.argon2_memory_kib,
        parallelism=s.argon2_parallelism,
        type=Type.ID,
    )


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher().check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """Hash verified when the user does not exist, so timing does not reveal accounts."""
    return hash_password(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    jti: str
    expires_at: datetime


class TokenError(Exception):
    def __init__(self, expired: bool) -> None:
        self.expired = expired
        super().__init__("expired" if expired else "invalid")


def _signing_key() -> str:
    key = get_settings().secret_key.get_secret_value()
    if not key:
        raise RuntimeError("SECRET_KEY is not configured")
    return key


def create_access_token(user_id: uuid.UUID, now: datetime) -> tuple[str, int]:
    ttl = get_settings().access_token_ttl_seconds
    payload = {
        "sub": str(user_id),
        "jti": secrets.token_hex(8),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        "iss": JWT_ISSUER,
        "typ": "access",
    }
    return jwt.encode(payload, _signing_key(), algorithm=JWT_ALGORITHM), ttl


def decode_access_token(token: str, now: datetime) -> AccessClaims:
    try:
        payload = jwt.decode(
            token,
            _signing_key(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["sub", "exp", "jti", "iss"], "verify_exp": False, "verify_iat": False},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(expired=False) from exc
    if payload.get("typ") != "access":
        raise TokenError(expired=False)
    # Expiry is checked against the injectable clock rather than the OS clock.
    if int(payload["exp"]) <= int(now.timestamp()):
        raise TokenError(expired=True)
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except ValueError as exc:
        raise TokenError(expired=False) from exc
    return AccessClaims(user_id, str(payload["jti"]), datetime.fromtimestamp(payload["exp"], tz=now.tzinfo))


def new_refresh_token() -> tuple[str, str]:
    """Return (opaque token for the cookie, SHA-256 hex stored in the database)."""
    token = secrets.token_urlsafe(48)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
