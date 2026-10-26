"""npm and PyPI registry metadata adapters (IF-04).

Used for latest stable versions (FR-DEP-05), incompatibility heuristics (FR-DEP-06), AI
evidence (FR-AI-07) and existence checks for model-named packages (VC-02/VC-03).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TypeVar, cast
from urllib.parse import quote

import httpx

from toolkit.core.config import get_settings
from toolkit.core.http import HttpClient, UpstreamError, host_of
from toolkit.core.validators import is_valid_package_name, is_valid_version, normalize_pypi_name
from toolkit.scanning.versions import compare, is_prerelease

T = TypeVar("T")


class PackageNotFound(Exception):  # noqa: N818
    pass


@dataclass
class PackageMeta:
    ecosystem: str
    name: str
    latest: str | None
    latest_released_at: str | None
    license: str | None
    repository_url: str | None
    deprecated: str | None  # npm deprecation message / PyPI "inactive" marker
    runtime_constraint: str | None  # npm engines.node / PyPI requires_python of latest
    first_released_at: str | None = None
    release_count: int | None = None
    versions: list[str] = field(default_factory=list)
    source_url: str = ""

    def evidence(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ecosystem": self.ecosystem,
            "latest_version": self.latest,
            "latest_released_at": self.latest_released_at,
            "first_released_at": self.first_released_at,
            "release_count": self.release_count,
            "license": self.license,
            "repository_url": self.repository_url,
            "deprecated": self.deprecated,
            "runtime_constraint": self.runtime_constraint,
        }


@dataclass
class VersionMeta:
    ecosystem: str
    name: str
    version: str
    exists: bool
    deprecated: str | None = None
    yanked: bool = False
    runtime_constraint: str | None = None
    released_at: str | None = None


def _repo_url(raw: Any) -> str | None:
    if isinstance(raw, dict):
        raw = raw.get("url")
    if not isinstance(raw, str):
        return None
    url = raw.removeprefix("git+").removesuffix(".git")
    if url.startswith("git://"):
        url = "https://" + url[len("git://") :]
    return url if url.startswith("https://") else None


class RegistryClient:
    """Thread-safe, per-scan cached registry client for both ecosystems."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        s = get_settings()
        self.npm = s.npm_registry_url.rstrip("/")
        self.pypi = s.pypi_url.rstrip("/")
        self._http = HttpClient(
            allowed_hosts={host_of(self.npm), host_of(self.pypi)},
            timeout=s.provider_http_timeout_seconds,
            max_retries=3,
            transport=transport,
        )
        self._cache: dict[tuple[str, str, str], Any] = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    def _cached(self, key: tuple[str, str, str], loader: Callable[[], T]) -> T:
        with self._lock:
            if key in self._cache:
                return cast(T, self._cache[key])
        value = loader()
        with self._lock:
            self._cache[key] = value
        return value

    def _get(self, url: str) -> dict[str, Any] | None:
        try:
            data: dict[str, Any] = self._http.get_json(url, ok_statuses=(200,))
        except UpstreamError as exc:
            if exc.status == 404:
                return None
            raise
        return data

    # ------------------------------------------------------------------ npm
    def _npm_name(self, name: str) -> str:
        return quote(name, safe="@") if not name.startswith("@") else "@" + quote(name[1:], safe="")

    def package(self, ecosystem: str, name: str) -> PackageMeta:
        if not is_valid_package_name(ecosystem, name):
            raise PackageNotFound(name)
        return self._cached(("pkg", ecosystem, name.lower()), lambda: self._load_package(ecosystem, name))

    def _load_package(self, ecosystem: str, name: str) -> PackageMeta:
        if ecosystem == "npm":
            url = f"{self.npm}/{self._npm_name(name)}"
            data = self._get(url)
            if data is None:
                raise PackageNotFound(name)
            latest = (data.get("dist-tags") or {}).get("latest")
            versions = data.get("versions") or {}
            times = data.get("time") or {}
            latest_doc = versions.get(latest, {}) if latest else {}
            stable = [v for v in versions if not is_prerelease("npm", v)]
            return PackageMeta(
                ecosystem="npm",
                name=name,
                latest=latest,
                latest_released_at=times.get(latest) if latest else None,
                license=_license(latest_doc.get("license") or data.get("license")),
                repository_url=_repo_url(latest_doc.get("repository") or data.get("repository")),
                deprecated=latest_doc.get("deprecated") if isinstance(latest_doc.get("deprecated"), str) else None,
                runtime_constraint=(latest_doc.get("engines") or {}).get("node")
                if isinstance(latest_doc.get("engines"), dict)
                else None,
                first_released_at=times.get("created"),
                release_count=len(stable),
                versions=list(versions)[-500:],
                source_url=f"https://www.npmjs.com/package/{name}",
            )
        url = f"{self.pypi}/pypi/{quote(name)}/json"
        data = self._get(url)
        if data is None:
            raise PackageNotFound(name)
        info = data.get("info") or {}
        releases: dict[str, list[dict[str, Any]]] = data.get("releases") or {}
        stable = [
            v
            for v, files in releases.items()
            if files and not is_prerelease("pypi", v) and not all(f.get("yanked") for f in files)
        ]
        latest = info.get("version")
        if latest and is_prerelease("pypi", latest) and stable:
            latest = max(stable, key=_pypi_sort_key)
        upload_times = sorted(
            f.get("upload_time_iso_8601") or f.get("upload_time") or ""
            for files in releases.values()
            for f in files
            if f.get("upload_time")
        )
        latest_files = releases.get(latest or "", [])
        classifiers = info.get("classifiers") or []
        inactive = "Development Status :: 7 - Inactive" in classifiers
        urls = info.get("project_urls") or {}
        repo = next(
            (
                u
                for k, u in urls.items()
                if k.lower() in ("source", "repository", "source code", "code", "github", "homepage")
                and isinstance(u, str)
                and u.startswith("https://")
            ),
            None,
        )
        return PackageMeta(
            ecosystem="pypi",
            name=info.get("name") or name,
            latest=latest,
            latest_released_at=(latest_files[0].get("upload_time_iso_8601") if latest_files else None),
            license=_license(info.get("license_expression") or info.get("license")),
            repository_url=repo,
            deprecated="Development Status :: 7 - Inactive" if inactive else None,
            runtime_constraint=info.get("requires_python") or None,
            first_released_at=upload_times[0] if upload_times else None,
            release_count=len(stable),
            versions=sorted(releases, key=_pypi_sort_key)[-500:],
            source_url=f"https://pypi.org/project/{normalize_pypi_name(name)}/",
        )

    def version(self, ecosystem: str, name: str, version: str) -> VersionMeta:
        if not is_valid_package_name(ecosystem, name) or not is_valid_version(ecosystem, version):
            return VersionMeta(ecosystem, name, version, exists=False)
        return self._cached(
            ("ver", ecosystem, f"{name.lower()}@{version}"),
            lambda: self._load_version(ecosystem, name, version),
        )

    def _load_version(self, ecosystem: str, name: str, version: str) -> VersionMeta:
        if ecosystem == "npm":
            data = self._get(f"{self.npm}/{self._npm_name(name)}/{quote(version)}")
            if data is None:
                return VersionMeta("npm", name, version, exists=False)
            dep = data.get("deprecated")
            engines = data.get("engines") if isinstance(data.get("engines"), dict) else {}
            return VersionMeta(
                "npm",
                name,
                version,
                exists=True,
                deprecated=dep if isinstance(dep, str) else None,
                runtime_constraint=engines.get("node") if engines else None,
            )
        data = self._get(f"{self.pypi}/pypi/{quote(name)}/{quote(version)}/json")
        if data is None:
            return VersionMeta("pypi", name, version, exists=False)
        files = data.get("urls") or []
        info = data.get("info") or {}
        return VersionMeta(
            "pypi",
            name,
            version,
            exists=True,
            yanked=bool(info.get("yanked")),
            deprecated=(f"yanked: {info.get('yanked_reason') or 'no reason given'}" if info.get("yanked") else None),
            runtime_constraint=info.get("requires_python") or None,
            released_at=files[0].get("upload_time_iso_8601") if files else None,
        )

    def latest_info(self, ecosystem: str, name: str) -> VersionMeta:
        """Metadata of the latest stable release, using the small npm ``/latest`` document.

        Full npm packuments can be tens of megabytes, so scans never download them; they are
        fetched only for AI evidence on a single package.
        """
        if not is_valid_package_name(ecosystem, name):
            raise PackageNotFound(name)

        def load() -> VersionMeta:
            if ecosystem == "npm":
                data = self._get(f"{self.npm}/{self._npm_name(name)}/latest")
                if data is None or not isinstance(data.get("version"), str):
                    raise PackageNotFound(name)
                dep = data.get("deprecated")
                engines = data.get("engines") if isinstance(data.get("engines"), dict) else {}
                return VersionMeta(
                    "npm",
                    name,
                    data["version"],
                    exists=True,
                    deprecated=dep if isinstance(dep, str) else None,
                    runtime_constraint=engines.get("node") if engines else None,
                )
            meta = self.package("pypi", name)
            if meta.latest is None:
                raise PackageNotFound(name)
            return VersionMeta(
                "pypi",
                name,
                meta.latest,
                exists=True,
                deprecated=meta.deprecated,
                runtime_constraint=meta.runtime_constraint,
                released_at=meta.latest_released_at,
            )

        return self._cached(("latest", ecosystem, name.lower()), load)

    def latest_stable(self, ecosystem: str, name: str) -> str | None:
        return self.latest_info(ecosystem, name).version


def _license(raw: Any) -> str | None:
    if isinstance(raw, dict):
        raw = raw.get("type")
    if not isinstance(raw, str) or not raw.strip():
        return None
    line = raw.strip().splitlines()[0]
    return line[:100]


def _pypi_sort_key(v: str) -> Any:
    from packaging.version import InvalidVersion, Version

    try:
        return (1, Version(v))
    except InvalidVersion:
        return (0, Version("0"))


def is_newer(ecosystem: str, current: str, candidate: str | None) -> bool:
    return candidate is not None and compare(ecosystem, current, candidate) == -1


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
