"""/auth endpoints (API_SPEC §5.1, SECURITY §5)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import EmailStr, Field

from toolkit.api.deps import DB, ClockDep, Viewer, client_ip, public_route
from toolkit.api.schemas.common import Out, StrictModel
from toolkit.core.config import get_settings
from toolkit.core.errors import ApiError, ErrorCode
from toolkit.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "toolkit_refresh"
COOKIE_PATH = "/api/v1/auth"
CSRF_HEADER = "x-requested-with"


class LoginIn(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(Out):
    id: uuid.UUID
    email: str
    display_name: str
    role: Literal["viewer", "maintainer", "admin"]


class TokenOut(Out):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: UserOut


def _require_csrf_header(request: Request) -> None:
    # Cookie-authenticated routes need a header that cross-site forms cannot set (TH-03).
    if not request.headers.get(CSRF_HEADER):
        raise ApiError(ErrorCode.FORBIDDEN, "Missing X-Requested-With header.")


def _set_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=max_age,
        path=COOKIE_PATH,
        httponly=True,
        secure=get_settings().is_production,
        samesite="strict",
    )


def _token_out(issued: auth_service.IssuedTokens) -> TokenOut:
    return TokenOut(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        user=UserOut.model_validate(issued.user),
    )


@router.post("/login", response_model=TokenOut, dependencies=[Depends(public_route)])
def login(body: LoginIn, request: Request, response: Response, db: DB, clock: ClockDep) -> TokenOut:
    issued = auth_service.login(db, body.email, body.password, client_ip(request), clock.now())
    _set_cookie(response, issued.refresh_token, get_settings().refresh_session_ttl_seconds)
    return _token_out(issued)


@router.post("/refresh", response_model=TokenOut, dependencies=[Depends(public_route)])
def refresh(request: Request, response: Response, db: DB, clock: ClockDep) -> TokenOut:
    _require_csrf_header(request)
    issued = auth_service.refresh(db, request.cookies.get(REFRESH_COOKIE), clock.now())
    _set_cookie(response, issued.refresh_token, get_settings().refresh_session_ttl_seconds)
    return _token_out(issued)


@router.post("/logout", status_code=204)
def logout(request: Request, principal: Viewer, db: DB, clock: ClockDep) -> Response:
    _require_csrf_header(request)
    auth_service.logout(db, request.cookies.get(REFRESH_COOKIE), clock.now())
    response = Response(status_code=204)
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


@router.get("/me", response_model=UserOut)
def me(principal: Viewer) -> UserOut:
    return UserOut.model_validate(principal.user)
