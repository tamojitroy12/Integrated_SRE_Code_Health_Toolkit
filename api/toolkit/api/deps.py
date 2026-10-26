"""Request dependencies: database session, clock, authentication and role guards.

Every route declares exactly one of ``public_route``, ``require_viewer``,
``require_maintainer`` or ``require_admin``; tests/test_rbac.py enforces this inventory
(SECURITY §6, FR-AUTH-03).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from toolkit.core.clock import Clock, system_clock
from toolkit.core.errors import ApiError, ErrorCode
from toolkit.core.security import TokenError, decode_access_token
from toolkit.db.enums import UserRole
from toolkit.db.models import User
from toolkit.db.session import get_session_factory


def get_db() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def get_clock() -> Clock:
    return system_clock


DB = Annotated[Session, Depends(get_db)]
ClockDep = Annotated[Clock, Depends(get_clock)]


@dataclass(frozen=True)
class Principal:
    user: User

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def role(self) -> UserRole:
        return UserRole(self.user.role)

    def at_least(self, role: UserRole) -> bool:
        return self.role.rank >= role.rank


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(ErrorCode.UNAUTHENTICATED, headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


def get_principal(request: Request, db: DB, clock: ClockDep) -> Principal:
    token = _bearer(request)
    try:
        claims = decode_access_token(token, clock.now())
    except TokenError as exc:
        code = ErrorCode.TOKEN_EXPIRED if exc.expired else ErrorCode.UNAUTHENTICATED
        raise ApiError(code, headers={"WWW-Authenticate": "Bearer"}) from exc
    # Role and is_active are read from the database on every request (TH-02).
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise ApiError(ErrorCode.UNAUTHENTICATED, headers={"WWW-Authenticate": "Bearer"})
    request.state.user_id = str(user.id)
    return Principal(user)


def _require(role: UserRole) -> Callable[..., Principal]:
    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.at_least(role):
            raise ApiError(ErrorCode.FORBIDDEN)
        return principal

    dependency.__name__ = f"require_{role.value}"
    dependency.required_role = role  # type: ignore[attr-defined]
    return dependency


require_viewer = _require(UserRole.VIEWER)
require_maintainer = _require(UserRole.MAINTAINER)
require_admin = _require(UserRole.ADMIN)


def public_route() -> None:
    """Marker dependency for routes that intentionally need no authentication."""


Viewer = Annotated[Principal, Depends(require_viewer)]
Maintainer = Annotated[Principal, Depends(require_maintainer)]
Admin = Annotated[Principal, Depends(require_admin)]


def client_ip(request: Request) -> str:
    """Client address, honouring X-Forwarded-For only for the configured proxy hops."""
    from toolkit.core.config import get_settings

    hops = get_settings().trusted_proxy_count
    forwarded = request.headers.get("x-forwarded-for")
    if hops and forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[max(0, len(parts) - hops)][:64]
    return (request.client.host if request.client else "unknown")[:64]
