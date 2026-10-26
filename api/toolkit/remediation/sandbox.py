"""Sandbox runtime client (COMP-14, IF-09, SECURITY §9.2, NFR-SEC-05).

Talks only to the dedicated sandbox Docker daemon at ``SANDBOX_DOCKER_HOST`` — never the
host socket. Every container is non-root, unprivileged, has all capabilities dropped,
``no-new-privileges``, the default seccomp profile, a read-only root filesystem, CPU/memory/
PID limits and a wall-clock timeout. Networking is per stage: on for dependency resolution
(scripts disabled), **off** for test execution. No Toolkit secrets enter the sandbox.
"""

from __future__ import annotations

import io
import logging
import tarfile
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from toolkit.core.config import get_settings
from toolkit.core.logging import redact

log = logging.getLogger(__name__)

LABEL = "toolkit.sandbox"
SANDBOX_UID = "10001:10001"
WORKDIR = "/work"
OUTPUT_TAIL_BYTES = 8 * 1024
HELPER_IMAGE = "busybox:1.37.0"


class SandboxUnavailable(Exception):  # noqa: N818
    pass


@dataclass(frozen=True)
class StageResult:
    exit_code: int | None
    output_tail: str
    duration_s: float
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class SandboxRuntime(Protocol):
    def create_workspace(self) -> str: ...
    def upload(self, workspace: str, root: Path) -> None: ...
    def run(self, workspace: str, image: str, argv: Sequence[str], *, network: bool, timeout: int) -> StageResult: ...
    def read_files(self, workspace: str, paths: Sequence[str]) -> dict[str, str | None]: ...
    def write_files(self, workspace: str, files: dict[str, str]) -> None: ...
    def destroy(self, workspace: str) -> None: ...


def tail(text: str) -> str:
    data = redact(text).encode("utf-8", errors="replace")
    return data[-OUTPUT_TAIL_BYTES:].decode("utf-8", errors="replace")


def _tar_directory(root: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                continue  # never carry symlinks into the sandbox
            arcname = path.relative_to(root).as_posix()
            info = tar.gettarinfo(str(path), arcname=arcname)
            info.uid = info.gid = 10001
            info.uname = info.gname = ""
            if path.is_file():
                with path.open("rb") as fh:
                    tar.addfile(info, fh)
            elif path.is_dir():
                tar.addfile(info)
    return buf.getvalue()


def _tar_files(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for rel, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            info.uid = info.gid = 10001
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class DockerSandbox:
    """Docker Engine API implementation over the isolated daemon."""

    def __init__(self, docker_host: str | None = None) -> None:
        import docker
        from docker.errors import DockerException

        s = get_settings()
        host = docker_host or s.sandbox_docker_host
        if not s.remediation_enabled or not host:
            raise SandboxUnavailable("remediation sandbox is not configured")
        if host.startswith("unix://") and "docker.sock" in host and not host.endswith("sandbox.sock"):
            # Guard against pointing the worker at the host daemon (CON-06).
            raise SandboxUnavailable("refusing to use a local Docker socket as the sandbox")
        try:
            self.client = docker.DockerClient(base_url=host, timeout=60)
            self.client.ping()
        except DockerException as exc:
            raise SandboxUnavailable(f"sandbox daemon unreachable: {type(exc).__name__}") from exc
        self._errors = DockerException

    def _container_kwargs(self, workspace: str, network: bool) -> dict[str, Any]:
        s = get_settings()
        return {
            "user": SANDBOX_UID,
            "working_dir": WORKDIR,
            "volumes": {workspace: {"bind": WORKDIR, "mode": "rw"}},
            "read_only": True,
            "tmpfs": {"/tmp": "rw,size=512m,mode=1777"},  # noqa: S108 - container-local tmpfs
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "privileged": False,
            "mem_limit": f"{s.sandbox_memory_mb}m",
            "memswap_limit": f"{s.sandbox_memory_mb}m",
            "nano_cpus": int(s.sandbox_cpus * 1e9),
            "pids_limit": s.sandbox_pids_limit,
            "network_mode": "bridge" if network else "none",
            "environment": {
                "HOME": "/tmp",  # noqa: S108 - container-local tmpfs
                "CI": "1",
                "npm_config_cache": "/tmp/.npm",  # noqa: S108
                "npm_config_update_notifier": "false",
                "PIP_CACHE_DIR": "/tmp/pip",  # noqa: S108
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            "labels": {LABEL: "1", f"{LABEL}.workspace": workspace},
            "detach": True,
        }

    def create_workspace(self) -> str:
        name = f"toolkit-ws-{uuid.uuid4().hex[:16]}"
        self.client.volumes.create(name=name, labels={LABEL: "1"})
        # Make the volume writable for the unprivileged sandbox user.
        self._helper(name, ["chown", "10001:10001", WORKDIR])
        return name

    def _helper(self, workspace: str, argv: list[str]) -> None:
        c = self.client.containers.run(
            HELPER_IMAGE,
            argv,
            volumes={workspace: {"bind": WORKDIR, "mode": "rw"}},
            network_mode="none",
            cap_drop=["ALL"],
            cap_add=["CHOWN"],
            security_opt=["no-new-privileges"],
            labels={LABEL: "1"},
            detach=True,
        )
        try:
            c.wait(timeout=60)
        finally:
            c.remove(force=True)

    def _holder(self, workspace: str) -> Any:
        return self.client.containers.create(
            HELPER_IMAGE,
            ["true"],
            volumes={workspace: {"bind": WORKDIR, "mode": "rw"}},
            network_mode="none",
            labels={LABEL: "1"},
            user=SANDBOX_UID,
        )

    def upload(self, workspace: str, root: Path) -> None:
        holder = self._holder(workspace)
        try:
            holder.put_archive(WORKDIR, _tar_directory(root))
        finally:
            holder.remove(force=True)

    def write_files(self, workspace: str, files: dict[str, str]) -> None:
        holder = self._holder(workspace)
        try:
            holder.put_archive(WORKDIR, _tar_files(files))
        finally:
            holder.remove(force=True)

    def read_files(self, workspace: str, paths: Sequence[str]) -> dict[str, str | None]:
        holder = self._holder(workspace)
        out: dict[str, str | None] = {}
        try:
            for rel in paths:
                try:
                    stream, _stat = holder.get_archive(f"{WORKDIR}/{rel}")
                except self._errors:
                    out[rel] = None
                    continue
                raw = b"".join(stream)
                with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
                    member = next((m for m in tar.getmembers() if m.isfile()), None)
                    fh = tar.extractfile(member) if member else None
                    out[rel] = fh.read().decode("utf-8", errors="replace") if fh else None
        finally:
            holder.remove(force=True)
        return out

    def run(self, workspace: str, image: str, argv: Sequence[str], *, network: bool, timeout: int) -> StageResult:
        started = time.monotonic()
        container = self.client.containers.run(image, list(argv), **self._container_kwargs(workspace, network))
        timed_out = False
        exit_code: int | None = None
        try:
            try:
                result = container.wait(timeout=timeout)
                exit_code = int(result.get("StatusCode", -1))
            except Exception:
                timed_out = True
                container.kill()
            logs = container.logs(stdout=True, stderr=True, tail=400).decode("utf-8", errors="replace")
        finally:
            container.remove(force=True)
        return StageResult(exit_code, tail(logs), round(time.monotonic() - started, 2), timed_out)

    def destroy(self, workspace: str) -> None:
        for c in self.client.containers.list(all=True, filters={"label": f"{LABEL}.workspace={workspace}"}):
            c.remove(force=True)
        try:
            self.client.volumes.get(workspace).remove(force=True)
        except self._errors:
            log.warning("could not remove sandbox volume", extra={"volume": workspace})

    def reap_orphans(self, older_than_seconds: int = 3600) -> int:
        """Remove labelled containers/volumes left by a crashed worker (TH-15)."""
        from datetime import UTC, datetime

        removed = 0
        now = datetime.now(UTC)
        for c in self.client.containers.list(all=True, filters={"label": LABEL}):
            created = str(c.attrs.get("Created", ""))[:26].rstrip("Z")
            try:
                age = (now - datetime.fromisoformat(created).replace(tzinfo=UTC)).total_seconds()
            except ValueError:
                age = older_than_seconds + 1
            # Only old containers: other workers may be running stages right now.
            if age > older_than_seconds:
                c.remove(force=True)
                removed += 1
        for v in self.client.volumes.list(filters={"label": LABEL}):
            created = str(v.attrs.get("CreatedAt", ""))[:19]
            try:
                age = (now - datetime.fromisoformat(created).replace(tzinfo=UTC)).total_seconds()
            except ValueError:
                continue
            if age <= older_than_seconds:
                continue  # a live job may be between stages
            try:
                v.remove()  # fails while a container still uses the volume
            except self._errors:
                continue
        return removed
