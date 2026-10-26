"""Recorded-provider fakes for scan tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from toolkit.integrations.osv import OsvClient
from toolkit.integrations.registry import RegistryClient
from toolkit.scanning import semgrep as semgrep_mod
from toolkit.scanning import trivy as trivy_mod

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[2]
VULN_REPO = REPO_ROOT / "examples" / "vulnerable-repo"


def osv_transport(fail: bool = False) -> httpx.MockTransport:
    recorded = json.loads((FIXTURES / "osv" / "querybatch.json").read_text())
    by_pkg = {
        ("lodash", "4.17.15"): recorded["results"][0],
        ("minimist", "1.2.5"): recorded["results"][1],
        ("pyyaml", "5.3.1"): recorded["results"][2],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ReadTimeout("osv timeout")
        if request.url.path == "/v1/querybatch":
            body = json.loads(request.content)
            results = [by_pkg.get((q["package"]["name"].lower(), q["version"]), {}) for q in body["queries"]]
            return httpx.Response(200, json={"results": results})
        if request.url.path.startswith("/v1/vulns/"):
            vid = request.url.path.rsplit("/", 1)[1]
            path = FIXTURES / "osv" / f"{vid}.json"
            return httpx.Response(200, json=json.loads(path.read_text())) if path.exists() else httpx.Response(404)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


NPM_LATEST = {
    "lodash": "4.17.21",
    "minimist": "1.2.8",
    "axios": "1.7.9",
    "express": "4.21.2",
    "jsonwebtoken": "9.0.2",
    "node-fetch": "3.3.2",
    "request": "2.88.2",
}
PYPI_LATEST = {
    "flask": "3.1.0",
    "jinja2": "3.1.5",
    "pyyaml": "6.0.2",
    "requests": "2.32.3",
    "urllib3": "2.3.0",
    "django": "5.1.4",
    "pytest": "8.3.4",
}


def registry_transport(fail: bool = False) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(503)
        path = request.url.path
        host = request.url.host
        if host == "registry.npmjs.org":
            parts = path.strip("/").split("/")
            name = parts[0]
            if name not in NPM_LATEST:
                return httpx.Response(404)
            if len(parts) == 2 and parts[1] == "latest":
                doc: dict[str, Any] = {"name": name, "version": NPM_LATEST[name], "license": "MIT"}
                if name == "request":
                    doc["deprecated"] = (
                        "request has been deprecated, see https://github.com/request/request/issues/3142"
                    )
                if name == "node-fetch":
                    doc["engines"] = {"node": ">=18"}
                if name == "jsonwebtoken":
                    doc["engines"] = {"node": ">=12"}
                return httpx.Response(200, json=doc)
            if len(parts) == 2:
                doc = {"name": name, "version": parts[1]}
                if name == "request":
                    doc["deprecated"] = "request has been deprecated"
                return httpx.Response(200, json=doc)
            return httpx.Response(
                200,
                json={
                    "name": name,
                    "dist-tags": {"latest": NPM_LATEST[name]},
                    "versions": {NPM_LATEST[name]: {"license": "MIT"}},
                    "time": {"created": "2012-04-23T00:00:00Z"},
                },
            )
        if host == "pypi.org":
            parts = path.strip("/").split("/")  # pypi/<name>[/<version>]/json
            name = parts[1].lower()
            if name not in PYPI_LATEST:
                return httpx.Response(404)
            if len(parts) == 4:
                return httpx.Response(
                    200,
                    json={
                        "info": {"name": name, "version": parts[2], "yanked": False},
                        "urls": [{"upload_time_iso_8601": "2020-01-01T00:00:00Z"}],
                    },
                )
            latest = PYPI_LATEST[name]
            return httpx.Response(
                200,
                json={
                    "info": {
                        "name": name,
                        "version": latest,
                        "license": "BSD",
                        "requires_python": ">=3.9",
                        "classifiers": [],
                        "project_urls": {"Source": f"https://github.com/example/{name}"},
                    },
                    "releases": {latest: [{"upload_time_iso_8601": "2024-01-01T00:00:00Z"}]},
                },
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def fake_trivy(path: str, _timeout: int) -> trivy_mod.TrivyResult:
    """Recorded Trivy output, filtered to the package versions actually present in the checkout."""
    from toolkit.scanning.inventory import build_inventory

    present = {(d.name.lower(), d.version) for d in build_inventory(path).deps}
    result = trivy_mod.parse(json.loads((FIXTURES / "trivy.json").read_text()))
    result.deps = [d for d in result.deps if (d.name.lower(), d.version) in present or d.name == "qs"]
    result.vulns = [v for v in result.vulns if (v.name.lower(), v.version) in present or v.name == "qs"]
    result.version = "0.58.2"
    return result


def failing_trivy(_path: str, _timeout: int) -> trivy_mod.TrivyResult:
    raise trivy_mod.TrivyError("trivy database unavailable")


def fake_semgrep(_repo: Path, _timeout: int) -> semgrep_mod.SemgrepResult:
    return semgrep_mod.parse(json.loads((FIXTURES / "semgrep.json").read_text()))


def osv_factory(fail: bool = False) -> Any:
    return lambda: OsvClient(transport=osv_transport(fail))


def registry_factory(fail: bool = False) -> Any:
    return lambda: RegistryClient(transport=registry_transport(fail))
