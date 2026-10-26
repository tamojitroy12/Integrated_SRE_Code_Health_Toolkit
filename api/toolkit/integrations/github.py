"""GitHub provider adapter (COMP-10, IF-05).

The interface is deliberately minimal: read repository metadata, list the tree, read
files, create a ``toolkit/fix/<uuid>`` branch pointing at a new commit, open a *draft*
pull request, close it, and delete a branch the Toolkit created. There is no merge
method, no force-push and no way to write to an existing branch (DEC-011, TH-19, TH-20).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from toolkit.core.config import get_settings
from toolkit.core.http import HttpClient, UpstreamError, host_of
from toolkit.core.validators import is_valid_fix_branch, is_valid_git_ref

MANIFEST_FILES = {
    "package.json": "npm",
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "requirements.txt": "pypi",
    "pyproject.toml": "pypi",
    "poetry.lock": "pypi",
    "Pipfile.lock": "pypi",
    "uv.lock": "pypi",
}
EXCLUDED_DIRS = {"node_modules", ".git", "dist", "build", "venv", ".venv", "env", "vendor", "__pycache__"}


# Overridable in tests (httpx.MockTransport); None uses the network.
DEFAULT_TRANSPORT: httpx.BaseTransport | None = None


class GitHubError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        # kind: access_denied | not_found | upstream | invalid
        self.kind = kind
        self.status = status
        super().__init__(message)


class BranchNotAllowedError(GitHubError):
    def __init__(self, branch: str) -> None:
        super().__init__("invalid", f"branch {branch!r} is outside the toolkit/fix/ namespace")


@dataclass(frozen=True)
class RepoInfo:
    owner: str
    name: str
    default_branch: str
    private: bool
    archived: bool
    can_push: bool


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    draft: bool
    branch: str


def is_manifest_path(path: str) -> str | None:
    parts = path.split("/")
    if any(p in EXCLUDED_DIRS for p in parts[:-1]):
        return None
    filename = parts[-1]
    if filename in MANIFEST_FILES:
        return MANIFEST_FILES[filename]
    if filename.startswith("requirements") and filename.endswith(".txt"):
        return "pypi"
    return None


class GitHubClient:
    def __init__(
        self, token: str | None = None, *, transport: httpx.BaseTransport | None = None, timeout: float = 10.0
    ) -> None:
        s = get_settings()
        self.api = s.github_api_url.rstrip("/")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = HttpClient(
            allowed_hosts={host_of(self.api)},
            timeout=timeout,
            max_retries=2,
            transport=transport or DEFAULT_TRANSPORT,
            headers=headers,
        )
        self.authenticated = bool(token)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        ok: tuple[int, ...] = (200,),
        params: dict[str, Any] | None = None,
    ) -> Any:
        try:
            resp = self._http.request(
                method, f"{self.api}{path}", json=json, ok_statuses=ok, params=params, retry=method == "GET"
            )
        except UpstreamError as exc:
            if exc.status == 401:
                raise GitHubError("access_denied", "GitHub rejected the token (401).", 401) from exc
            if exc.status == 403:
                raise GitHubError("access_denied", "GitHub denied access (403).", 403) from exc
            if exc.status == 404:
                raise GitHubError("not_found", "Repository or resource not found (404).", 404) from exc
            if exc.status == 422:
                raise GitHubError("invalid", "GitHub rejected the request (422).", 422) from exc
            raise GitHubError("upstream", str(exc), exc.status) from exc
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ------------------------------------------------------------------ read path
    def get_repo(self, owner: str, name: str) -> RepoInfo:
        data = self._call("GET", f"/repos/{quote(owner)}/{quote(name)}")
        perms = data.get("permissions") or {}
        return RepoInfo(
            owner=data["owner"]["login"],
            name=data["name"],
            default_branch=data["default_branch"],
            private=bool(data.get("private")),
            archived=bool(data.get("archived")),
            can_push=self.authenticated and bool(perms.get("push")),
        )

    def branch_exists(self, owner: str, name: str, branch: str) -> bool:
        if not is_valid_git_ref(branch):
            return False
        try:
            self._call("GET", f"/repos/{quote(owner)}/{quote(name)}/branches/{quote(branch, safe='')}")
        except GitHubError as exc:
            if exc.kind == "not_found":
                return False
            raise
        return True

    def list_manifests(self, owner: str, name: str, ref: str) -> list[str]:
        if not is_valid_git_ref(ref):
            raise GitHubError("invalid", "invalid ref")
        data = self._call(
            "GET", f"/repos/{quote(owner)}/{quote(name)}/git/trees/{quote(ref, safe='')}", params={"recursive": "1"}
        )
        paths = [e["path"] for e in data.get("tree", []) if e.get("type") == "blob"]
        return sorted(p for p in paths if is_manifest_path(p))

    def resolve_sha(self, owner: str, name: str, ref: str) -> str:
        data = self._call("GET", f"/repos/{quote(owner)}/{quote(name)}/commits/{quote(ref, safe='')}")
        return str(data["sha"])

    def get_file(self, owner: str, name: str, path: str, ref: str) -> str | None:
        try:
            data = self._call("GET", f"/repos/{quote(owner)}/{quote(name)}/contents/{quote(path)}", params={"ref": ref})
        except GitHubError as exc:
            if exc.kind == "not_found":
                return None
            raise
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8")
        return None

    # ------------------------------------------------------------------ write path
    def create_fix_branch_with_files(
        self, owner: str, name: str, *, branch: str, base_sha: str, files: dict[str, str], message: str
    ) -> str:
        """Create blobs → tree → commit on top of ``base_sha`` and a *new* ref for it.

        Fails if the branch already exists (no overwrite). Returns the new commit SHA.
        """
        if not is_valid_fix_branch(branch):
            raise BranchNotAllowedError(branch)
        repo = f"/repos/{quote(owner)}/{quote(name)}"
        base_commit = self._call("GET", f"{repo}/git/commits/{base_sha}")
        tree_items = []
        for path, content in sorted(files.items()):
            blob = self._call("POST", f"{repo}/git/blobs", json={"content": content, "encoding": "utf-8"}, ok=(201,))
            tree_items.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        tree = self._call(
            "POST",
            f"{repo}/git/trees",
            json={"base_tree": base_commit["tree"]["sha"], "tree": tree_items},
            ok=(201,),
        )
        commit = self._call(
            "POST",
            f"{repo}/git/commits",
            json={"message": message, "tree": tree["sha"], "parents": [base_sha]},
            ok=(201,),
        )
        self._call("POST", f"{repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": commit["sha"]}, ok=(201,))
        return str(commit["sha"])

    def open_draft_pr(self, owner: str, name: str, *, branch: str, base: str, title: str, body: str) -> PullRequest:
        if not is_valid_fix_branch(branch):
            raise BranchNotAllowedError(branch)
        data = self._call(
            "POST",
            f"/repos/{quote(owner)}/{quote(name)}/pulls",
            json={
                "title": title,
                "head": branch,
                "base": base,
                "body": body,
                "draft": True,
                "maintainer_can_modify": False,
            },
            ok=(201,),
        )
        return PullRequest(int(data["number"]), str(data["html_url"]), bool(data.get("draft", True)), branch)

    def close_pr(self, owner: str, name: str, number: int) -> None:
        self._call("PATCH", f"/repos/{quote(owner)}/{quote(name)}/pulls/{int(number)}", json={"state": "closed"})

    def delete_fix_branch(self, owner: str, name: str, branch: str) -> None:
        if not is_valid_fix_branch(branch):
            raise BranchNotAllowedError(branch)
        try:
            self._call("DELETE", f"/repos/{quote(owner)}/{quote(name)}/git/refs/heads/{branch}", ok=(204,))
        except GitHubError as exc:
            if exc.kind not in ("not_found", "invalid"):
                raise


def clone_url(owner: str, name: str) -> str:
    return f"{get_settings().github_web_url.rstrip('/')}/{owner}/{name}.git"
