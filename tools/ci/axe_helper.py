#!/usr/bin/env python3
"""Fail when a browser spec builds its own axe scan instead of the helper.

tests/e2e/axe.mjs waits for running animations before axe measures colours
(a popover fade made a 14.5:1 label read 4.39:1). A spec that calls
``new AxeBuilder`` itself skips that wait and brings the flake back.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HELPER = Path("tests/e2e/axe.mjs")
DIRECT = re.compile(r"\bnew\s+AxeBuilder\b|from\s+[\"']@axe-core/playwright[\"']")
SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".mts"}


def findings(root: Path) -> list[str]:
    result: list[str] = []
    directory = root / "tests" / "e2e"
    if not directory.is_dir():
        return result
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(root)
        if relative == HELPER or path.suffix not in SUFFIXES or not path.is_file():
            continue
        if any(part in {"node_modules", "test-results"} for part in relative.parts):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if DIRECT.search(line):
                result.append(f"{relative}:{number}: {line.strip()[:80]}")
    return result


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    found = findings(root)
    if found:
        for item in found:
            print(f"axe-helper: ERROR: {item}", file=sys.stderr)
        print(
            "axe-helper: FAILED: scan with analyzeAccessibility(page, { include, tags }) "
            f"from {HELPER}; it waits for animations before axe measures contrast",
            file=sys.stderr,
        )
        return 1
    print("axe-helper: OK: every browser spec scans through tests/e2e/axe.mjs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
