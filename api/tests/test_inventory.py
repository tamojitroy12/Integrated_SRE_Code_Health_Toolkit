"""Lockfile parsers for every supported format (FR-DEP-02)."""

from __future__ import annotations

import json
from pathlib import Path

from toolkit.scanning.inventory import build_inventory


def test_all_lockfile_formats(tmp_path: Path) -> None:
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "package-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 1,
                "dependencies": {"left-pad": {"version": "1.3.0", "dependencies": {"inner": {"version": "0.1.0"}}}},
            }
        )
    )
    (tmp_path / "pipenv").mkdir()
    (tmp_path / "pipenv" / "Pipfile.lock").write_text(
        json.dumps({"default": {"requests": {"version": "==2.25.0"}}, "develop": {"pytest": {"version": "==7.0.0"}}})
    )
    (tmp_path / "poetry").mkdir()
    (tmp_path / "poetry" / "pyproject.toml").write_text('[tool.poetry.dependencies]\npython = "^3.11"\nflask = "^2"\n')
    (tmp_path / "poetry" / "poetry.lock").write_text(
        '[[package]]\nname = "flask"\nversion = "2.0.0"\n\n[[package]]\nname = "werkzeug"\nversion = "2.0.1"\n'
    )
    (tmp_path / "uvproj").mkdir()
    (tmp_path / "uvproj" / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["httpx>=0.27"]\n')
    (tmp_path / "uvproj" / "uv.lock").write_text(
        '[[package]]\nname = "x"\nversion = "0.1.0"\nsource = { editable = "." }\n\n'
        '[[package]]\nname = "httpx"\nversion = "0.27.0"\n\n[[package]]\nname = "anyio"\nversion = "4.0.0"\n'
    )
    (tmp_path / "node_modules" / "skip").mkdir(parents=True)
    (tmp_path / "node_modules" / "skip" / "package-lock.json").write_text("{}")
    (tmp_path / "nolock").mkdir()
    (tmp_path / "nolock" / "package.json").write_text("{}")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "package-lock.json").write_text("{not json")
    inv = build_inventory(tmp_path)
    got = {(d.name, d.version, d.scope) for d in inv.unique()}
    assert ("left-pad", "1.3.0", "direct") in got and ("inner", "0.1.0", "transitive") in got
    assert ("requests", "2.25.0", "direct") in got and ("pytest", "7.0.0", "direct") in got
    assert ("flask", "2.0.0", "direct") in got and ("werkzeug", "2.0.1", "transitive") in got
    assert ("httpx", "0.27.0", "direct") in got and ("anyio", "4.0.0", "transitive") in got
    assert not any(n == "x" for n, _v, _s in got)  # the project itself is not a dependency
    assert any("no lockfile" in w for w in inv.warnings)
    assert any("broken/package-lock.json" in w for w in inv.warnings)
    assert all("node_modules" not in m for m in inv.manifests)
