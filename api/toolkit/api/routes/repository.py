"""/projects/{id}/repository endpoints (API_SPEC §5.3, FR-PRJ-02, WF-01)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import select

from toolkit import audit
from toolkit.api.deps import DB, ClockDep, Maintainer, Viewer, client_ip
from toolkit.api.schemas.common import Out, StrictModel, UtcDatetime
from toolkit.core.errors import ApiError, ErrorCode, not_found, validation_error
from toolkit.core.validators import TEST_COMMAND_ALLOWLIST, allowed_test_argv, is_valid_git_ref, parse_github_url
from toolkit.db.models import Credential, Repository
from toolkit.integrations.github import GitHubClient, GitHubError, is_manifest_path
from toolkit.services.credentials import load_token, store_token
from toolkit.services.projects import get_project

router = APIRouter(tags=["repository"])


class RepositoryIn(StrictModel):
    url: str = Field(max_length=300)
    token: str | None = Field(default=None, max_length=255)
    default_branch: str | None = Field(default=None, max_length=200)
    test_command: str | None = Field(default=None, max_length=50)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if parse_github_url(v) is None:
            raise ValueError("must be https://github.com/<owner>/<repo>")
        return v

    @field_validator("default_branch")
    @classmethod
    def _branch(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_git_ref(v):
            raise ValueError("invalid branch name")
        return v

    @field_validator("test_command")
    @classmethod
    def _test(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if allowed_test_argv(v) is None:
            raise ValueError(f"must be one of: {', '.join(TEST_COMMAND_ALLOWLIST)}")
        return " ".join(v.split())

    @field_validator("token")
    @classmethod
    def _token(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = "".join(v.split())
        return v or None


class RepositoryOut(Out):
    id: uuid.UUID
    provider: str
    owner: str
    name: str
    url: str
    default_branch: str
    ecosystems: list[str]
    manifests: list[str]
    has_token: bool
    can_open_prs: bool
    is_private: bool
    test_command: str | None
    verified_at: UtcDatetime | None


def _out(repo: Repository) -> RepositoryOut:
    return RepositoryOut(
        id=repo.id,
        provider=repo.provider,
        owner=repo.owner,
        name=repo.name,
        url=repo.url,
        default_branch=repo.default_branch,
        ecosystems=repo.ecosystems,
        manifests=repo.manifests,
        has_token=repo.credential_id is not None,
        can_open_prs=repo.can_open_prs,
        is_private=repo.is_private,
        test_command=repo.test_command,
        verified_at=repo.verified_at,
    )


def _verify(owner: str, name: str, token: str | None, branch: str | None) -> tuple[str, bool, bool, list[str]]:
    """Return (default_branch, private, can_push, manifests). Maps GitHub errors (FR-PRJ-02)."""
    try:
        with GitHubClient(token, timeout=10.0) as gh:
            info = gh.get_repo(owner, name)
            ref = branch or info.default_branch
            if branch and not gh.branch_exists(owner, name, branch):
                raise validation_error("default_branch", "branch not found in repository")
            manifests = gh.list_manifests(owner, name, ref)
    except GitHubError as exc:
        if exc.kind == "access_denied":
            raise ApiError(ErrorCode.REPO_ACCESS_DENIED, "GitHub denied access to the repository or token.") from exc
        if exc.kind == "not_found":
            raise ApiError(
                ErrorCode.REPO_NOT_FOUND,
                "Repository not found. Private repositories need a token with read access.",
            ) from exc
        raise ApiError(ErrorCode.UPSTREAM_ERROR, "GitHub could not be reached. Try again.") from exc
    return ref, info.private, info.can_push and not info.archived, manifests


def _ecosystems(manifests: list[str]) -> list[str]:
    found = {eco for path in manifests if (eco := is_manifest_path(path))}
    return sorted(found)


@router.put("/projects/{project_id}/repository", response_model=RepositoryOut)
def connect_repository(
    project_id: uuid.UUID, body: RepositoryIn, principal: Maintainer, db: DB, clock: ClockDep, request: Request
) -> RepositoryOut:
    project = get_project(db, project_id, writable=True, lock=True)
    parsed = parse_github_url(body.url)
    assert parsed is not None
    owner, name = parsed
    existing = db.scalar(select(Repository).where(Repository.project_id == project.id))
    token = body.token
    if token is None and existing is not None and existing.owner == owner and existing.name == name:
        token = load_token(db, existing.credential_id)  # keep the stored token on re-connect
    branch, private, can_push, manifests = _verify(owner, name, token, body.default_branch)
    now: datetime = clock.now()
    repo = existing or Repository(project_id=project.id)
    old_credential = repo.credential_id
    if body.token is not None:
        cred = store_token(db, body.token, principal.id)
        db.flush()
        repo.credential_id = cred.id
        audit.record(
            db,
            "repo.credential_created",
            actor_id=principal.id,
            resource_type="project",
            resource_id=project.id,
            ip=client_ip(request),
        )
    elif token is None:
        repo.credential_id = None
    repo.provider = "github"
    repo.owner, repo.name = owner, name
    repo.url = f"https://github.com/{owner}/{name}"
    repo.default_branch = branch
    repo.manifests = manifests
    repo.ecosystems = _ecosystems(manifests)
    repo.can_open_prs = can_push
    repo.is_private = private
    repo.test_command = body.test_command
    repo.verified_at = now
    if existing is None:
        db.add(repo)
    db.flush()
    if old_credential is not None and old_credential != repo.credential_id:
        db.query(Credential).filter(Credential.id == old_credential).delete()
    audit.record(
        db,
        "repo.connected",
        actor_id=principal.id,
        resource_type="project",
        resource_id=project.id,
        metadata={"repository": f"{owner}/{name}"},
        ip=client_ip(request),
    )
    return _out(repo)


@router.get("/projects/{project_id}/repository", response_model=RepositoryOut)
def get_repository(project_id: uuid.UUID, principal: Viewer, db: DB) -> RepositoryOut:
    get_project(db, project_id)
    repo = db.scalar(select(Repository).where(Repository.project_id == project_id))
    if repo is None:
        raise not_found("Repository")
    return _out(repo)


@router.post("/projects/{project_id}/repository/verify", response_model=RepositoryOut)
def verify_repository(project_id: uuid.UUID, principal: Maintainer, db: DB, clock: ClockDep) -> RepositoryOut:
    get_project(db, project_id, writable=True)
    repo = db.scalar(select(Repository).where(Repository.project_id == project_id).with_for_update())
    if repo is None:
        raise not_found("Repository")
    token = load_token(db, repo.credential_id)
    branch, private, can_push, manifests = _verify(repo.owner, repo.name, token, repo.default_branch)
    repo.default_branch = branch
    repo.manifests = manifests
    repo.ecosystems = _ecosystems(manifests)
    repo.can_open_prs = can_push
    repo.is_private = private
    repo.verified_at = clock.now()
    return _out(repo)


@router.delete("/projects/{project_id}/repository", status_code=204)
def disconnect_repository(project_id: uuid.UUID, principal: Maintainer, db: DB, request: Request) -> Response:
    get_project(db, project_id, writable=True)
    repo = db.scalar(select(Repository).where(Repository.project_id == project_id))
    if repo is None:
        raise not_found("Repository")
    cred_id = repo.credential_id
    db.delete(repo)
    db.flush()
    if cred_id is not None:
        db.query(Credential).filter(Credential.id == cred_id).delete()
        audit.record(
            db,
            "repo.credential_deleted",
            actor_id=principal.id,
            resource_type="project",
            resource_id=project_id,
            ip=client_ip(request),
        )
    audit.record(
        db,
        "repo.disconnected",
        actor_id=principal.id,
        resource_type="project",
        resource_id=project_id,
        ip=client_ip(request),
    )
    return Response(status_code=204)
