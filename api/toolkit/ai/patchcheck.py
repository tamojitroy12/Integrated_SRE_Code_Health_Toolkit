"""VC-07: does a proposed patch apply to the scanned commit? (``git apply --check``)

The patch is checked against a fresh hardened clone of the scanned commit. ``git apply
--check`` only reads files; no repository code is executed, so this runs in the worker.
"""

from __future__ import annotations

import socket
import tempfile
import uuid
from pathlib import Path

from toolkit.core.config import get_settings
from toolkit.core.errors import JobError
from toolkit.core.process import run
from toolkit.scanning.clone import cleanup, clone_ref


def make_checker(url: str, commit_sha: str, token: str | None):  # type: ignore[no-untyped-def]
    def check(_target: str, patch: str) -> bool | None:
        s = get_settings()
        workspace = Path(s.work_dir) / f"scan-{socket.gethostname()[:30]}-patch-{uuid.uuid4()}"
        try:
            try:
                clone_ref(
                    url, commit_sha, workspace, token=token, timeout=s.clone_timeout_seconds, max_mb=s.clone_max_mb
                )
            except JobError:
                return None
            with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8") as fh:
                fh.write(patch if patch.endswith("\n") else patch + "\n")
                patch_file = fh.name
            try:
                result = run(
                    ["git", "apply", "--check", "--", patch_file],
                    timeout=30,
                    cwd=str(workspace),
                    env={"GIT_CONFIG_NOSYSTEM": "1"},
                )
            finally:
                Path(patch_file).unlink(missing_ok=True)
            return result.ok
        finally:
            cleanup(workspace)

    return check
