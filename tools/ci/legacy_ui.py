#!/usr/bin/env python3
"""Fail on UI code that predates the Leitsystem: Hugeicons, Base UI, old tokens.

The Leitsystem uses Lucide through @leonaid/ui's Icon adapter, native
dialogs/popovers and the token names of packages/ui/src/styles/leitsystem.css.
The names below are the old aliases from packages/ui/src/styles/tokens.css.

Runs in ./leonaid check. ``--report`` lists findings without failing.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

OLD_TOKENS = (
    "accent-foreground",
    "background",
    "danger-foreground",
    "danger-text",
    "destructive",
    "foreground",
    "info-text",
    "input",
    "motion-fast",
    "motion-standard",
    "muted",
    "primary",
    "primary-foreground",
    "radius-lg",
    "radius-md",
    "radius-sm",
    "ring",
    "shadow-md",
    "shadow-sm",
    "sidebar",
    "sidebar-accent",
    "sidebar-active",
    "sidebar-foreground",
    "sidebar-muted",
    "success",
    "success-text",
    "surface-muted",
    "warning",
    "warning-foreground",
    "warning-text",
)
OLD_PACKAGES = ("@hugeicons/", "@base-ui/react")
TOKEN_USE = re.compile(
    r"var\(\s*--("
    + "|".join(sorted(map(re.escape, OLD_TOKENS), key=len, reverse=True))
    + r")\s*[,)]"
)
TOKEN_DEFINITION = re.compile(
    r"^\s*--(" + "|".join(map(re.escape, OLD_TOKENS)) + r")\s*:"
)
IMPORT = re.compile(
    r"""(?:from\s+|import\s*\(\s*|import\s+)["']("""
    + "|".join(re.escape(name) for name in OLD_PACKAGES)
    + r""")[^"']*["']"""
)
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".astro"}
ROOTS = ("apps", "packages")
SKIPPED = {"node_modules", "dist", "build", ".astro", "test-results"}


def files(root: Path) -> Iterator[Path]:
    for top in ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if any(part in SKIPPED for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                yield path


def findings(root: Path) -> list[str]:
    result: list[str] = []
    for path in files(root):
        relative = path.relative_to(root)
        if path.name == "package.json":
            try:
                manifest = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for field in ("dependencies", "devDependencies", "peerDependencies"):
                for name in manifest.get(field, {}) or {}:
                    if name.startswith(OLD_PACKAGES):
                        result.append(f"{relative}: {field} lists {name}")
            continue
        if path.suffix not in SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for match in IMPORT.finditer(line):
                result.append(f"{relative}:{number}: imports {match.group(1)}")
            for match in TOKEN_USE.finditer(line):
                result.append(f"{relative}:{number}: old token --{match.group(1)}")
            if path.suffix == ".css" and TOKEN_DEFINITION.match(line):
                result.append(f"{relative}:{number}: defines old token {line.strip()}")
    return result


def main(argv: list[str]) -> int:
    report = "--report" in argv
    arguments = [value for value in argv if value != "--report"]
    root = Path(arguments[0] if arguments else ".").resolve()
    found = findings(root)
    stream = sys.stdout if report else sys.stderr
    for item in found:
        print(f"legacy-ui: {'FOUND' if report else 'ERROR'}: {item}", file=stream)
    if found and not report:
        print(
            "legacy-ui: FAILED: use Lucide via Icon from @leonaid/ui, native "
            "dialogs/popovers and the Leitsystem tokens (leitsystem.css)",
            file=sys.stderr,
        )
        return 1
    print(f"legacy-ui: {'REPORT' if report else 'OK'}: {len(found)} finding(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
