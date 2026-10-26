"""Hardened shallow clone of a repository ref (FR-DEP-01, TH-11).

* hooks disabled (``core.hooksPath`` points to an empty directory), no submodules,
  ``file://`` and other non-HTTPS protocols refused, symlinks checked out as plain files;
* the token is passed as an HTTP header via ``GIT_CONFIG_*`` environment variables, so it
  never appears in a URL, the process list or ``.git/config``;
* wall-clock timeout and a size cap; the workspace is always deleted by the caller.
"""

from __future__ import annotations

import base64
import os
import shutil
import stat
import tempfile
from pathlib import Path

from toolkit.core.errors import JobError, JobErrorCode
from toolkit.core.logging import redact
from toolkit.core.process import run
from toolkit.core.validators import SHA_RE, is_valid_git_ref


def _force_remove(func: object, path: str, _exc: object) -> None:
    """rmtree error handler: clear read-only bits (git objects on Windows) and retry."""
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)  # type: ignore[operator]
    except OSError:
        pass


def rmtree(path: Path | str) -> None:
    shutil.rmtree(path, onexc=_force_remove)


def _git_env(token: str | None, home: str, allow_file: bool) -> dict[str, str]:
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_LFS_SKIP_SMUDGE": "1",
        "GIT_ALLOW_PROTOCOL": "https:file" if allow_file else "https",
        "HOME": home,
    }
    pairs: list[tuple[str, str]] = [
        ("core.hooksPath", str(Path(home) / "no-hooks")),
        ("core.symlinks", "false"),
        ("core.fsmonitor", "false"),
        ("submodule.recurse", "false"),
        ("protocol.file.allow", "always" if allow_file else "never"),
        ("advice.detachedHead", "false"),
    ]
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        pairs.append(("http.extraHeader", f"Authorization: Basic {basic}"))
    env["GIT_CONFIG_COUNT"] = str(len(pairs))
    for i, (key, value) in enumerate(pairs):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


def dir_size_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(path, followlinks=False):
        for f in files:
            fp = Path(dirpath) / f
            try:
                if not fp.is_symlink():
                    total += fp.stat().st_size
            except OSError:
                continue
    return total


def clone_ref(
    url: str, ref: str, dest: Path, *, token: str | None, timeout: int, max_mb: int, allow_file_protocol: bool = False
) -> str:
    """Fetch ``ref`` (branch, tag or 40-hex SHA) at depth 1 into ``dest``. Returns the commit SHA."""
    if not (is_valid_git_ref(ref) or SHA_RE.match(ref)):
        raise JobError(JobErrorCode.CLONE_FAILED, "invalid ref")
    if not url.startswith("https://") and not (allow_file_protocol and url.startswith("file://")):
        raise JobError(JobErrorCode.CLONE_FAILED, "only https repository URLs are supported")
    dest.mkdir(parents=True, exist_ok=False)
    home = tempfile.mkdtemp(prefix="git-home-")
    (Path(home) / "no-hooks").mkdir()
    env = _git_env(token, home, allow_file_protocol)
    try:
        steps: list[list[str]] = [
            ["git", "init", "--quiet", str(dest)],
            [
                "git",
                "-C",
                str(dest),
                "fetch",
                "--quiet",
                "--depth=1",
                "--no-tags",
                "--no-recurse-submodules",
                "--",
                url,
                ref,
            ],
            ["git", "-C", str(dest), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
        ]
        deadline_each = max(10, timeout)
        for argv in steps:
            result = run(argv, timeout=deadline_each, env=env)
            if result.timed_out:
                raise JobError(JobErrorCode.CLONE_FAILED, f"clone timed out after {timeout}s")
            if not result.ok:
                msg = redact(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "git failed")
                if "couldn't find remote ref" in result.stderr or "not our ref" in result.stderr:
                    msg = f"ref {ref!r} not found in repository"
                raise JobError(JobErrorCode.CLONE_FAILED, msg[:300])
            if dir_size_bytes(dest) > max_mb * 1024 * 1024:
                raise JobError(JobErrorCode.CLONE_FAILED, f"repository exceeds the {max_mb} MB clone limit")
        sha = run(["git", "-C", str(dest), "rev-parse", "HEAD"], timeout=30, env=env)
        commit = sha.stdout.strip()
        if not SHA_RE.match(commit):
            raise JobError(JobErrorCode.CLONE_FAILED, "could not resolve commit SHA")
        # Repository metadata is not needed after checkout; drop it so scanners only see files.
        rmtree(dest / ".git") if (dest / ".git").exists() else None
        return commit
    finally:
        rmtree(home)


def cleanup(path: Path) -> None:
    if path.exists():
        rmtree(path)


def cleanup_orphans(work_dir: str, prefix: str = "scan-") -> int:
    """Delete workspaces left behind by a crashed worker (DATA_MODEL §7)."""
    root = Path(work_dir)
    if not root.is_dir():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.name.startswith(prefix) and child.is_dir():
            rmtree(child)
            removed += 1
    return removed
