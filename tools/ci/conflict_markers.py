#!/usr/bin/env python3
"""Fail when a merge left conflict markers in tracked-looking text files.

A stray marker in a document or script still parses in many formats (Markdown
renders it as text), so neither builds nor linters reliably catch it.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# A marker is seven identical characters at the start of a line, followed by
# a space and a label or by the end of the line. "=======" alone is too common
# in prose and text art to be decisive, so only the three labelled kinds count.
MARKER = re.compile(r"^(<{7}|>{7}|\|{7})(?: |$)")
SKIPPED_DIRECTORIES = {
    ".git",
    ".venv",
    ".cache",
    ".local",
    ".claude",
    ".artifacts",
    ".scratch",
    "node_modules",
    "dist",
    "build",
    ".astro",
    "test-results",
    "playwright-report",
}
MAX_BYTES = 2_000_000


def findings(root: Path) -> list[str]:
    result: list[str] = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(
            name for name in subdirectories if name not in SKIPPED_DIRECTORIES
        )
        for name in sorted(files):
            path = Path(directory) / name
            try:
                if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if MARKER.match(line):
                    result.append(f"{path.relative_to(root)}:{number}: {line[:40]}")
    return result


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    found = findings(root)
    if found:
        for finding in found:
            print(f"conflict-markers: ERROR: {finding}", file=sys.stderr)
        return 1
    print("conflict-markers: OK: no merge conflict markers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
