#!/usr/bin/env python3
"""Fail on literal "/admin/" or "/app/" base paths outside the constants.

specs/multi-domain §6.7: the base paths of the two member apps live in
packages/ui/src/lib/base-paths.ts (ADMIN_BASE, PWA_BASE, adminHref, pwaHref)
and src/leonaid/platform/base_paths.py. Code builds its links from them, so a
later change of a base path is one edit and not a hunt through every screen.

A finding is a string literal (``"``, ``'`` or a template literal) that starts
with ``/admin/`` or ``/app/`` in a script, markup or Python file under apps/,
packages/ or src/leonaid/. Comment lines and tests do not count. Exceptions
are listed in ALLOWED with the reason.

Runs in ./leonaid check. ``--report`` lists findings without failing.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

LITERAL = re.compile(r"""["'`]/(?:admin|app)/""")
ROOTS = ("apps", "packages", "src/leonaid")
SUFFIXES = {
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".astro",
    ".html",
    ".py",
}
SKIPPED = {
    "node_modules",
    "dist",
    "build",
    ".astro",
    "test-results",
    "coverage",
    "__tests__",
    "__pycache__",
}
# The documentation site writes about the paths; it builds no links to them.
SKIPPED_TREES = (Path("apps/docs"),)
ALLOWED = {
    # The definitions themselves.
    Path("packages/ui/src/lib/base-paths.ts"),
    Path("src/leonaid/platform/base_paths.py"),
    # A SHA-256-pinned backport into the vendored EmDash editor bundle; its
    # exact bytes are reviewed, so it cannot import the constants.
    Path("apps/campaign-site/emdash-editor-patch.mjs"),
    # Directories inside the campaign-site container (WORKDIR /app), no URLs.
    Path("apps/campaign-site/src/auth/leonaid-auth.ts"),
    Path("apps/campaign-site/src/closed-bootstrap.ts"),
    Path("apps/campaign-site/src/cms-maintenance.mjs"),
}
COMMENT_PREFIXES = ("//", "/*", "*", "#", "<!--")


def _is_test(path: Path) -> bool:
    name = path.name
    return ".test." in name or ".spec." in name or name.startswith("test_")


def files(root: Path) -> Iterator[Path]:
    for top in ROOTS:
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            relative = path.relative_to(root)
            if any(part in SKIPPED for part in relative.parts):
                continue
            if any(relative.is_relative_to(tree) for tree in SKIPPED_TREES):
                continue
            if path.is_file() and path.suffix.lower() in SUFFIXES:
                yield path


def _line_findings(line: str, suffix: str) -> bool:
    stripped = line.strip()
    if stripped.startswith(COMMENT_PREFIXES):
        return False
    # OpenAPI examples document a response; they build no link.
    if suffix == ".py" and "examples=" in stripped:
        return False
    return LITERAL.search(line) is not None


def findings(root: Path) -> list[str]:
    result: list[str] = []
    for path in files(root):
        relative = path.relative_to(root)
        if relative in ALLOWED or _is_test(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            # An unreadable source must not pass silently.
            result.append(f"{relative}: cannot be read ({error})")
            continue
        suffix = path.suffix.lower()
        for number, line in enumerate(text.splitlines(), start=1):
            if _line_findings(line, suffix):
                result.append(
                    f"{relative}:{number}: literal base path; use ADMIN_BASE/"
                    "PWA_BASE, adminHref()/pwaHref() or platform.base_paths"
                )
    return result


def main(argv: list[str]) -> int:
    report = "--report" in argv
    arguments = [item for item in argv if item != "--report"]
    root = Path(arguments[0] if arguments else ".").resolve()
    found = findings(root)
    for item in found:
        print(f"base-path-literals: {item}")
    if found and not report:
        print(
            f"base-path-literals: ERROR: {len(found)} literal base path(s)",
            file=sys.stderr,
        )
        return 1
    print(f"base-path-literals: OK: {len(found)} finding(s) reported" if report
          else "base-path-literals: OK: links use the base-path constants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
