"""/users endpoints, admin only (API_SPEC §5.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from toolkit import audit
from toolkit.api.deps import DB, Admin, ClockDep, client_ip
from toolkit.api.pagination import decode_cursor, encode_cursor
from toolkit.api.schemas.common import Out, Page, StrictModel, UtcDatetime
from toolkit.core.errors import ApiError, ErrorCode, not_found
from toolkit.core.security import hash_password
from toolkit.db.models import User
from toolkit.services.auth import find_user_by_email, normalize_email, revoke_all_sessions

router = APIRouter(prefix="/users", tags=["users"])

RoleLit = Literal["viewer", "maintainer", "admin"]


class UserAdminOut(Out):
    id: uuid.UUID
    email: str
    display_name: str
    role: RoleLit
    is_active: bool
    created_at: UtcDatetime
    last_login_at: UtcDatetime | None


class UserCreate(StrictModel):
    email: EmailStr = Field(max_length=254)
    display_name: str = Field(min_length=1, max_length=100)
    role: RoleLit
    initial_password: str = Field(min_length=12, max_length=128)


class UserPatch(StrictModel):
    role: RoleLit | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=128)


@router.get("", response_model=Page[UserAdminOut])
def list_users(
    principal: Admin,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: str | None = None,
) -> Page[UserAdminOut]:
    q = select(User).order_by(User.created_at, User.id)
    if cursor:
        created, uid = decode_cursor(cursor, 2)
        q = q.where((User.created_at > created) | ((User.created_at == created) & (User.id > uid)))
    rows = list(db.scalars(q.limit(limit + 1)))
    nxt = encode_cursor([rows[limit - 1].created_at, rows[limit - 1].id]) if len(rows) > limit else None
    return Page(items=[UserAdminOut.model_validate(u) for u in rows[:limit]], next_cursor=nxt)


@router.post("", response_model=UserAdminOut, status_code=201)
def create_user(body: UserCreate, principal: Admin, db: DB, request: Request) -> UserAdminOut:
    email = normalize_email(body.email)
    if find_user_by_email(db, email):
        raise ApiError(ErrorCode.CONFLICT, "A user with this email already exists.")
    user = User(
        email=email,
        display_name=body.display_name,
        role=body.role,
        password_hash=hash_password(body.initial_password),
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ApiError(ErrorCode.CONFLICT, "A user with this email already exists.") from exc
    audit.record(
        db,
        "user.created",
        actor_id=principal.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"role": body.role},
        ip=client_ip(request),
    )
    return UserAdminOut.model_validate(user)


def _active_admins(db: DB) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) or 0


@router.patch("/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: uuid.UUID, body: UserPatch, principal: Admin, db: DB, clock: ClockDep, request: Request
) -> UserAdminOut:
    user = db.get(User, user_id, with_for_update=True)
    if user is None:
        raise not_found("User")
    changes: dict[str, object] = {}
    demoting = body.role is not None and body.role != "admin" and user.role == "admin"
    deactivating = body.is_active is False and user.is_active and user.role == "admin"
    if (demoting or deactivating) and _active_admins(db) <= 1:
        raise ApiError(ErrorCode.CONFLICT, "The last active admin cannot be demoted or deactivated.")
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role
    if body.display_name is not None:
        user.display_name = body.display_name
    now: datetime = clock.now()
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
        if not body.is_active:
            revoke_all_sessions(db, user.id, now)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        revoke_all_sessions(db, user.id, now)
        changes["password_reset"] = True
    audit.record(
        db,
        "user.updated",
        actor_id=principal.id,
        resource_type="user",
        resource_id=user.id,
        metadata=changes,
        ip=client_ip(request),
    )
    db.flush()
    return UserAdminOut.model_validate(user)
