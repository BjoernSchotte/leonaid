#!/usr/bin/env python3
"""Fail on UI code that predates the Leitsystem: Hugeicons, Base UI, old tokens.

The Leitsystem renders icons from ``lucide-react``, uses native <dialog> and
popover elements, and styles with the token names of
packages/ui/src/styles/leitsystem.css. The old token names below were the
aliases of packages/ui/src/styles/tokens.css; they are gone and stay gone.

Checked in apps/ and packages/:
- the packages as any string literal: ``import``/``from``, ``require()``,
  dynamic ``import()``, ``vi.mock()``/``jest.mock()``, ``import x = require()``;
- package.json dependency fields, including optional dependencies, overrides
  and resolutions;
- old token uses ``var(--name)``, also across lines, and definitions
  ``--name:``, also several on one line (``a{--sidebar:red}``);
- old token names as JavaScript strings (``style.setProperty("--primary")``).

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
DEPENDENCY_FIELDS = (
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
    "bundledDependencies",
    "bundleDependencies",
    "overrides",
    "resolutions",
)

# Longest first, and a name must end where the token ends: "--primary" must
# not match "--primary-ish".
_NAMES = "|".join(sorted(map(re.escape, OLD_TOKENS), key=len, reverse=True))
TOKEN_USE = re.compile(rf"var\(\s*--({_NAMES})(?![\w-])\s*[,)]", re.S)
TOKEN_DEFINITION = re.compile(rf"(?:^|[;{{\s])--({_NAMES})(?![\w-])\s*:", re.M)
TOKEN_STRING = re.compile(rf"""["'`]--({_NAMES})["'`]""")
PACKAGE_STRING = re.compile(
    r"""["'`]("""
    + "|".join(re.escape(name) for name in OLD_PACKAGES)
    + r""")[^"'`\s]*["'`]"""
)

SCRIPT_SUFFIXES = {
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".vue",
    ".svelte",
}
STYLE_SUFFIXES = {".css", ".scss", ".sass", ".less"}
MARKUP_SUFFIXES = {".astro", ".html", ".htm", ".svg", ".md", ".mdx"}
ROOTS = ("apps", "packages")
SKIPPED = {"node_modules", "dist", "build", ".astro", "test-results", "coverage"}
# The contrast test names the old aliases to prove they stay undefined.
ALLOWED = {Path("packages/ui/src/styles/contrast.test.ts")}


def files(root: Path) -> Iterator[Path]:
    # The workspace root manifest holds the shared devDependencies.
    if (root / "package.json").is_file():
        yield root / "package.json"
    for top in ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if any(part in SKIPPED for part in path.relative_to(root).parts):
                continue
            if path.is_file():
                yield path


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _dependency_names(value: object) -> Iterator[str]:
    """Package names of a dependency field; overrides may nest objects."""

    if isinstance(value, dict):
        for name, nested in value.items():
            yield str(name)
            yield from _dependency_names(nested)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                yield item


def _manifest_findings(path: Path, relative: Path) -> list[str]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        # An unreadable manifest must not pass silently.
        return [f"{relative}: package.json cannot be parsed ({error})"]
    if not isinstance(manifest, dict):
        return [f"{relative}: package.json is not a JSON object"]
    result: list[str] = []
    for field in DEPENDENCY_FIELDS:
        for name in _dependency_names(manifest.get(field)):
            if name.startswith(OLD_PACKAGES):
                result.append(f"{relative}: {field} lists {name}")
    return result


def _source_findings(text: str, relative: Path, suffix: str) -> list[str]:
    result: list[str] = []
    for match in PACKAGE_STRING.finditer(text):
        result.append(f"{relative}:{_line(text, match.start())}: uses {match.group(1)}")
    for match in TOKEN_USE.finditer(text):
        result.append(
            f"{relative}:{_line(text, match.start())}: old token --{match.group(1)}"
        )
    if (
        suffix in STYLE_SUFFIXES
        or suffix in MARKUP_SUFFIXES
        or suffix in {".vue", ".svelte"}
    ):
        for match in TOKEN_DEFINITION.finditer(text):
            result.append(
                f"{relative}:{_line(text, match.start(1))}: "
                f"defines old token --{match.group(1)}"
            )
    if suffix in SCRIPT_SUFFIXES or suffix in MARKUP_SUFFIXES:
        for match in TOKEN_STRING.finditer(text):
            result.append(
                f"{relative}:{_line(text, match.start())}: "
                f"old token --{match.group(1)} in a string"
            )
    return result


def findings(root: Path) -> list[str]:
    result: list[str] = []
    for path in files(root):
        relative = path.relative_to(root)
        if relative in ALLOWED:
            continue
        if path.name == "package.json":
            result.extend(_manifest_findings(path, relative))
            continue
        suffix = path.suffix.lower()
        if suffix not in SCRIPT_SUFFIXES | STYLE_SUFFIXES | MARKUP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        result.extend(_source_findings(text, relative, suffix))
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
            "legacy-ui: FAILED: render icons from lucide-react, use native "
            "<dialog>/popover elements and the Leitsystem tokens of "
            "packages/ui/src/styles/leitsystem.css (--text, --accent, --r-md, ...)",
            file=sys.stderr,
        )
        return 1
    print(f"legacy-ui: {'REPORT' if report else 'OK'}: {len(found)} finding(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
