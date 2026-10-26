"""The single place where external processes are started (TRD §10.2, NFR-SEC-06).

Commands are argument vectors only; ``shell=True`` is never used. Output is capped and
the process group is killed on timeout so scanners cannot outlive their job.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_SHELL_META = set(";|&$`<>\n\r\0")


class UnsafeArgumentError(ValueError):
    pass


@dataclass(frozen=True)
class ProcessResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    truncated: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def check_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if not argv:
        raise UnsafeArgumentError("empty argument vector")
    for arg in argv:
        if not isinstance(arg, str):
            raise UnsafeArgumentError("arguments must be strings")
        if "\0" in arg:
            raise UnsafeArgumentError("NUL byte in argument")
    return tuple(argv)


def contains_shell_meta(value: str) -> bool:
    return any(c in _SHELL_META for c in value)


def run(
    argv: Sequence[str],
    *,
    timeout: float,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    max_output_bytes: int = 64 * 1024 * 1024,
    inherit_env: bool = False,
) -> ProcessResult:
    """Run ``argv`` with a timeout. The environment is minimal unless ``inherit_env``."""
    args = check_argv(argv)
    base_env: dict[str, str] = {}
    if inherit_env:
        base_env.update(os.environ)
    else:
        for key in ("PATH", "HOME", "SYSTEMROOT", "TEMP", "TMP", "LANG", "SSL_CERT_FILE", "TZ"):
            if key in os.environ:
                base_env[key] = os.environ[key]
    if env:
        base_env.update(env)

    started = time.monotonic()
    popen_kwargs: dict[str, object] = {}
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        args,
        cwd=cwd,
        env=base_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **popen_kwargs,  # type: ignore[call-overload]
    )
    timed_out = False
    try:
        out_b, err_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out_b, err_b = proc.communicate()
    duration_ms = int((time.monotonic() - started) * 1000)
    truncated = len(out_b) > max_output_bytes or len(err_b) > max_output_bytes
    return ProcessResult(
        argv=args,
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=out_b[:max_output_bytes].decode("utf-8", errors="replace"),
        stderr=err_b[-max_output_bytes:].decode("utf-8", errors="replace"),
        duration_ms=duration_ms,
        timed_out=timed_out,
        truncated=truncated,
    )


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform != "win32":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass
