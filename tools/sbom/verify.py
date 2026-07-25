#!/usr/bin/env python3
"""Validate generated CycloneDX artifacts without third-party packages."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1])
    expected = {
        "python.cdx.json",
        "frontend.cdx.json",
        "container-python.cdx.json",
        "container-node.cdx.json",
        "container-twenty.cdx.json",
        "container-postgres.cdx.json",
        "container-redis.cdx.json",
        "container-rustfs.cdx.json",
        "container-mailpit.cdx.json",
        "container-caddy.cdx.json",
        "container-typst.cdx.json",
        "container-playwright.cdx.json",
        "container-listmonk.cdx.json",
        "container-otel.cdx.json",
    }
    actual = {path.name for path in root.glob("*.cdx.json")}
    missing = sorted(expected - actual)
    if missing:
        print(f"sbom-verify: ERROR: missing artifacts: {missing}", file=sys.stderr)
        return 1
    for name in sorted(expected):
        path = root / name
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"sbom-verify: ERROR: {name}: {error}", file=sys.stderr)
            return 1
        if document.get("bomFormat") != "CycloneDX":
            print(f"sbom-verify: ERROR: {name}: not CycloneDX", file=sys.stderr)
            return 1
        components = document.get("components")
        if not isinstance(components, list) or not components:
            print(f"sbom-verify: ERROR: {name}: no components", file=sys.stderr)
            return 1
    print(f"sbom-verify: OK: {len(expected)} non-empty CycloneDX documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
