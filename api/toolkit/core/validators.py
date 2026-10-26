"""Input grammars shared by API schemas, scanners and the remediation engine.

Every value that can end up in a PromQL template, a git or package-manager command, or a
registry URL is checked here first (NFR-SEC-06, FR-REM-08, TH-09).
"""

from __future__ import annotations

import re

from packaging.version import InvalidVersion, Version

SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
ENVIRONMENT_RE = re.compile(r"^[a-z0-9-]{1,50}$")
GITHUB_URL_RE = re.compile(r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)(?:\.git)?/?$")
GIT_REF_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FIX_BRANCH_RE = re.compile(r"^toolkit/fix/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# npm: optional scope, lowercase, url-safe characters, ≤ 214 chars.
NPM_NAME_RE = re.compile(r"^(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*$")
# PyPI (PEP 508 project name).
PYPI_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
DURATION_WINDOWS = ("1m", "5m", "15m")
PROMQL_DURATION_RE = re.compile(r"^[1-9][0-9]{0,4}[smh]$")


def is_valid_git_ref(ref: str) -> bool:
    return bool(GIT_REF_RE.match(ref)) and ".." not in ref and not ref.startswith("-") and not ref.endswith("/")


def is_valid_package_name(ecosystem: str, name: str) -> bool:
    if ecosystem == "npm":
        return len(name) <= 214 and bool(NPM_NAME_RE.match(name))
    if ecosystem == "pypi":
        return len(name) <= 200 and bool(PYPI_NAME_RE.match(name))
    return False


def is_valid_version(ecosystem: str, version: str) -> bool:
    if not version or len(version) > 100 or version.startswith("-"):
        return False
    if ecosystem == "npm":
        return bool(SEMVER_RE.match(version))
    if ecosystem == "pypi":
        try:
            Version(version)
        except InvalidVersion:
            return False
        return re.fullmatch(r"[A-Za-z0-9.!+_-]+", version) is not None
    return False


def normalize_pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_github_url(url: str) -> tuple[str, str] | None:
    m = GITHUB_URL_RE.match(url.strip())
    if not m:
        return None
    return m.group("owner"), m.group("name")


def is_valid_fix_branch(branch: str) -> bool:
    return bool(FIX_BRANCH_RE.match(branch))


TEST_COMMAND_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "npm test": ("npm", "test"),
    "npm run test": ("npm", "run", "test"),
    "pytest": ("python", "-m", "pytest"),
    "python -m pytest": ("python", "-m", "pytest"),
}


def allowed_test_argv(command: str) -> tuple[str, ...] | None:
    return TEST_COMMAND_ALLOWLIST.get(" ".join(command.split()))
