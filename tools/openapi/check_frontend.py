#!/usr/bin/env python3
"""Enforce the generated API client as the only frontend transport boundary."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path

SOURCE_SUFFIXES = {".astro", ".js", ".jsx", ".ts", ".tsx"}
IGNORED_DIRECTORIES = {".astro", "dist", "node_modules"}
DIRECT_API_FETCH = re.compile(
    r"\bfetch\s*\(\s*[`'\"][^`'\"]*/api/(?:v\d+/)?",
    re.MULTILINE,
)
GENERATED_IMPORT = re.compile(
    r"\b(?:from|import\s*\()\s*[('\"]+[^'\"]*"
    r"(?:openapi\.json|api-client/src/generated|api-client/generated)",
)


def violations(
    paths: Iterable[Path], *, independent_client: Path | None = None
) -> list[str]:
    problems: list[str] = []
    for root in paths:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if any(part in IGNORED_DIRECTORIES for part in path.parts):
                continue
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8")
            transport_text = text
            if independent_client is not None:
                # The packed consumer has its own backend. Exempt only reviewed
                # routes in these exact adapter files, never LeonAid's /api/v1.
                demo = independent_client.parent
                routes = {
                    independent_client: r"([\"'])/api/(?:participation|diagnostics)\1",
                    demo / "editor.tsx": r"([\"'])/api/editor\1",
                    demo / "exports.tsx": (
                        r"(?:([\"'])/api/(?:exports|export-source)\1|"
                        r"`/api/exports/\$\{encodeURIComponent\(id\)\}(?:/download)?`)"
                    ),
                }
                if path in routes:
                    transport_text = re.sub(
                        r"\bfetch\s*\(\s*" + routes[path],
                        "independentTransport(",
                        text,
                    )
            if DIRECT_API_FETCH.search(transport_text):
                problems.append(f"{path}: direkter API-fetch statt @leonaid/api-client")
            if GENERATED_IMPORT.search(text):
                problems.append(
                    f"{path}: generiertes Transportartefakt direkt importiert"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    problems = violations(
        (
            root / "apps",
            root / "packages/features",
            root / "packages/ui",
        ),
        independent_client=root / "apps/surveys-demo/client.tsx",
    )
    if problems:
        for problem in problems:
            print(f"frontend-api-boundary: ERROR: {problem}", file=sys.stderr)
        return 1
    print("frontend-api-boundary: OK: Transportzugriffe laufen über api-client")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
