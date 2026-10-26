"""Version parsing and comparison for npm (SemVer 2.0) and PyPI (PEP 440)."""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Literal

from packaging.version import InvalidVersion, Version

from toolkit.core.validators import SEMVER_RE

Bump = Literal["patch", "minor", "major", "none", "unknown"]


@functools.total_ordering
@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int
    pre: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> SemVer | None:
        m = SEMVER_RE.match(value.strip().lstrip("v=").strip())
        if not m:
            return None
        pre = tuple(m.group("pre").split(".")) if m.group("pre") else ()
        return cls(int(m.group("major")), int(m.group("minor")), int(m.group("patch")), pre)

    @property
    def is_prerelease(self) -> bool:
        return bool(self.pre)

    def _key(self) -> tuple[int, int, int, int, tuple[tuple[int, int | str], ...]]:
        # A version without prerelease sorts after any prerelease of the same core.
        pre_key = tuple((0, int(p)) if p.isdigit() else (1, p) for p in self.pre)
        return (self.major, self.minor, self.patch, 0 if self.pre else 1, pre_key)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return self._key() < other._key()


def parse(ecosystem: str, value: str) -> SemVer | Version | None:
    if ecosystem == "npm":
        return SemVer.parse(value)
    try:
        return Version(value)
    except InvalidVersion:
        return None


def compare(ecosystem: str, a: str, b: str) -> int | None:
    """-1 / 0 / 1, or None if either side cannot be parsed."""
    pa, pb = parse(ecosystem, a), parse(ecosystem, b)
    if pa is None or pb is None:
        return None
    if pa < pb:  # type: ignore[operator,unused-ignore]
        return -1
    if pa == pb:
        return 0
    return 1


def is_prerelease(ecosystem: str, value: str) -> bool:
    v = parse(ecosystem, value)
    if v is None:
        return False
    return bool(v.is_prerelease)


def _parts(v: SemVer | Version) -> tuple[int, int, int]:
    if isinstance(v, SemVer):
        return (v.major, v.minor, v.patch)
    rel = (*v.release, 0, 0, 0)
    return (rel[0], rel[1], rel[2])


def bump(ecosystem: str, current: str, target: str) -> Bump:
    """Lag classification between two versions (FR-DEP-05)."""
    a, b = parse(ecosystem, current), parse(ecosystem, target)
    if a is None or b is None:
        return "unknown"
    if not a < b:  # type: ignore[operator,unused-ignore]
        return "none"
    ma, mb = _parts(a), _parts(b)
    if mb[0] != ma[0]:
        return "major"
    if ma[0] == 0 and ecosystem == "npm" and mb[1] != ma[1]:
        # In 0.x SemVer, a minor bump is breaking by convention.
        return "major"
    if mb[1] != ma[1]:
        return "minor"
    return "patch"


def pick_fix_version(ecosystem: str, installed: str, fixed_versions: list[str]) -> str | None:
    """Smallest fixed version greater than the installed one, preferring the same major line."""
    candidates = [f for f in fixed_versions if compare(ecosystem, installed, f) == -1]
    if not candidates:
        return None
    parsed = sorted(((parse(ecosystem, c), c) for c in candidates), key=lambda x: x[0])  # type: ignore[arg-type,return-value]
    inst = parse(ecosystem, installed)
    assert inst is not None
    same_major = [c for p, c in parsed if p is not None and _parts(p)[0] == _parts(inst)[0]]
    return same_major[0] if same_major else parsed[0][1]


_RANGE_SPLIT = re.compile(r"\s*,\s*")


def split_fixed_versions(raw: str | None) -> list[str]:
    """Trivy reports ``FixedVersion`` as a comma-separated list."""
    if not raw:
        return []
    return [v.strip() for v in _RANGE_SPLIT.split(raw) if v.strip()]
