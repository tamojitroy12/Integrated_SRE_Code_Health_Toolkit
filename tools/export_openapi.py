#!/usr/bin/env python3
"""Export the OpenAPI document generated from code to openapi.json (or --check for drift).

Run with the backend environment:  cd api && uv run python ../tools/export_openapi.py [--check]
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "openapi.json"


def generate() -> str:
    os.environ.setdefault("SECRET_KEY", "export-only-not-a-secret-0000000000000")
    os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"0" * 32).decode())
    sys.path.insert(0, str(ROOT / "api"))
    from toolkit.api.main import create_app

    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    spec = generate()
    if "--check" in sys.argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != spec:
            print("openapi.json is out of date; run tools/export_openapi.py", file=sys.stderr)
            return 1
        print("openapi.json is up to date")
        return 0
    OUT.write_text(spec, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
