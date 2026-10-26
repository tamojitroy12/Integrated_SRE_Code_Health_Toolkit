"""Native dependency inventory from lockfiles and pinned manifests (FR-DEP-02).

The repository is read as data only; nothing in it is executed. This inventory feeds the
OSV and registry providers, so they keep working when Trivy fails (NFR-REL-02). Trivy's
own inventory is merged in by the orchestrator.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from toolkit.core.validators import is_valid_package_name, is_valid_version, normalize_pypi_name

EXCLUDED_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "venv",
    ".venv",
    "env",
    ".tox",
    "vendor",
    "__pycache__",
    "site-packages",
    ".next",
    "coverage",
}
MAX_MANIFEST_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class Dep:
    ecosystem: str
    name: str
    version: str
    scope: str  # direct | transitive
    manifest_path: str

    @property
    def purl(self) -> str:
        if self.ecosystem == "npm":
            return f"pkg:npm/{quote(self.name, safe='/')}@{quote(self.version)}"
        return f"pkg:pypi/{normalize_pypi_name(self.name)}@{quote(self.version)}"

    @property
    def key(self) -> tuple[str, str, str]:
        name = normalize_pypi_name(self.name) if self.ecosystem == "pypi" else self.name
        return (self.ecosystem, name, self.version)


@dataclass
class Inventory:
    deps: list[Dep] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, dep: Dep) -> None:
        if is_valid_package_name(dep.ecosystem, dep.name) and is_valid_version(dep.ecosystem, dep.version):
            self.deps.append(dep)

    def unique(self) -> list[Dep]:
        """De-duplicate by (ecosystem, name, version, manifest); 'direct' wins over 'transitive'."""
        best: dict[tuple[str, str, str, str], Dep] = {}
        for d in self.deps:
            k = (*d.key, d.manifest_path)
            if k not in best or (d.scope == "direct" and best[k].scope != "direct"):
                best[k] = d
        return sorted(best.values(), key=lambda d: (d.ecosystem, d.name.lower(), d.version, d.manifest_path))


def _walk(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if name in {"package-lock.json", "npm-shrinkwrap.json", "Pipfile.lock", "poetry.lock", "uv.lock"} or (
                name.startswith("requirements") and name.endswith(".txt")
            ):
                p = Path(dirpath) / name
                if not p.is_symlink():
                    found.append(p)
    return found


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def build_inventory(root: str | Path) -> Inventory:
    root = Path(root)
    inv = Inventory()
    for path in _walk(root):
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        if text is None:
            inv.warnings.append(f"{rel}: unreadable or too large")
            continue
        try:
            if path.name in ("package-lock.json", "npm-shrinkwrap.json"):
                parse_package_lock(text, rel, inv)
            elif path.name == "Pipfile.lock":
                parse_pipfile_lock(text, rel, inv)
            elif path.name in ("poetry.lock", "uv.lock"):
                parse_toml_lock(text, rel, inv, _pyproject_direct(path.parent))
            else:
                parse_requirements(text, rel, inv)
            inv.manifests.append(rel)
        except (ValueError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
            inv.warnings.append(f"{rel}: could not be parsed ({type(exc).__name__})")
    for pj in _package_json_without_lock(root):
        inv.warnings.append(f"{pj}: no lockfile; dependency versions are unresolved and were not scanned")
    return inv


def _package_json_without_lock(root: Path) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]
        if "package.json" in filenames and not {
            "package-lock.json",
            "npm-shrinkwrap.json",
            "yarn.lock",
            "pnpm-lock.yaml",
        } & set(filenames):
            out.append((Path(dirpath) / "package.json").relative_to(root).as_posix())
    return out


def parse_package_lock(text: str, rel: str, inv: Inventory) -> None:
    data = json.loads(text)
    packages = data.get("packages")
    if isinstance(packages, dict):  # lockfileVersion 2/3
        root_pkg = packages.get("", {})
        direct = (
            set(root_pkg.get("dependencies", {}))
            | set(root_pkg.get("devDependencies", {}))
            | set(root_pkg.get("optionalDependencies", {}))
        )
        for key, meta in packages.items():
            if not key or "node_modules/" not in key or meta.get("link"):
                continue
            name = meta.get("name") or key.rsplit("node_modules/", 1)[1]
            version = meta.get("version")
            if not isinstance(version, str):
                continue
            top_level = key.count("node_modules/") == 1 and key.startswith("node_modules/")
            scope = "direct" if top_level and name in direct else "transitive"
            inv.add(Dep("npm", name, version, scope, rel))
        return
    deps = data.get("dependencies", {})  # lockfileVersion 1

    def walk(tree: dict[str, dict[str, object]], depth: int) -> None:
        for name, meta in tree.items():
            version = meta.get("version")
            if isinstance(version, str):
                # v1 lockfiles hoist packages, so top level is the best available "direct" signal.
                inv.add(Dep("npm", name, version, "direct" if depth == 0 else "transitive", rel))
            nested = meta.get("dependencies")
            if isinstance(nested, dict):
                walk(nested, depth + 1)

    walk(deps, 0)


_REQ_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*===?\s*(?P<version>[^\s;#\\]+)")


def parse_requirements(text: str, rel: str, inv: Inventory) -> None:
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = _REQ_LINE.match(line)
        if m:
            inv.add(Dep("pypi", m.group("name"), m.group("version"), "direct", rel))


def parse_pipfile_lock(text: str, rel: str, inv: Inventory) -> None:
    data = json.loads(text)
    for section in ("default", "develop"):
        for name, meta in (data.get(section) or {}).items():
            version = str(meta.get("version", "")).lstrip("=")
            if version:
                inv.add(Dep("pypi", name, version, "direct", rel))


def _pyproject_direct(directory: Path) -> set[str]:
    pp = directory / "pyproject.toml"
    if not pp.is_file() or pp.is_symlink():
        return set()
    try:
        data = tomllib.loads(pp.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    names: set[str] = set()
    for spec in data.get("project", {}).get("dependencies", []) or []:
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", str(spec))
        if m:
            names.add(normalize_pypi_name(m.group(1)))
    for group in (data.get("project", {}).get("optional-dependencies", {}) or {}).values():
        for spec in group:
            m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", str(spec))
            if m:
                names.add(normalize_pypi_name(m.group(1)))
    poetry = data.get("tool", {}).get("poetry", {})
    for key in ("dependencies", "dev-dependencies"):
        names |= {normalize_pypi_name(n) for n in (poetry.get(key) or {}) if n.lower() != "python"}
    for group in (poetry.get("group") or {}).values():
        names |= {normalize_pypi_name(n) for n in (group.get("dependencies") or {})}
    return names


def parse_toml_lock(text: str, rel: str, inv: Inventory, direct: set[str]) -> None:
    data = tomllib.loads(text)
    for pkg in data.get("package", []) or []:
        name, version = pkg.get("name"), pkg.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            continue
        source = pkg.get("source") or {}
        if isinstance(source, dict) and (source.get("editable") or source.get("virtual")):
            continue  # the project itself
        scope = "direct" if normalize_pypi_name(name) in direct or not direct else "transitive"
        inv.add(Dep("pypi", name, version, scope, rel))
