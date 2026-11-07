#!/usr/bin/env python3
"""Prove the base-path literal guard with real files in a temporary tree."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

CHECKER = Path(__file__).resolve().parent / "base_path_literals.py"

CLEAN = {
    "packages/ui/src/lib/base-paths.ts": 'export const ADMIN_BASE = "/admin/";\n',
    "src/leonaid/platform/base_paths.py": 'ADMIN_BASE = "/admin/"\n',
    "packages/features/src/link.tsx": "const href = `${ADMIN_BASE}orders`;\n",
    "packages/features/src/helper.ts": 'const href = adminHref("actions");\n',
    "packages/features/src/comment.tsx": '// Links "/admin/orders" through adminHref.\n',
    "packages/features/src/block.tsx": "/**\n * `/admin/surveys/<id>` view.\n */\n",
    "packages/features/src/list.test.tsx": 'expect(href).toBe("/admin/orders");\n',
    "apps/public/src/lib/__tests__/x.ts": 'const a = "/app/";\n',
    "apps/web/node_modules/lib/index.js": 'location.href = "/admin/";\n',
    "apps/docs/src/content/page.astro": '<a href="/admin/">x</a>\n',
    "src/leonaid/entrypoints/fastapi/schemas.py": (
        'path: str = Field(examples=["/app/", "/admin/system"])\n'
    ),
    "src/leonaid/application/identity.py": "# Lands on '/admin/system'.\n",
    "tests/e2e/flow.spec.mjs": 'await page.goto("/admin/");\n',
    "apps/campaign-site/src/closed-bootstrap.ts": (
        'const bootstrapDirectory = "/app/bootstrap-state";\n'
    ),
    # A prefix that only looks alike.
    "packages/features/src/apps.ts": 'const path = "/apps/list";\n',
}
DIRTY = {
    "packages/features/src/double.tsx": 'window.location.assign("/admin/actions");\n',
    "packages/features/src/single.ts": "const path = '/app/sponsors';\n",
    "packages/features/src/template.tsx": "const href = `/admin/orders/${id}`;\n",
    "packages/features/src/jsx.tsx": '<a href="/app/">Akquise</a>\n',
    "apps/public/src/components/Page.astro": '<a href="/admin/">Verwaltung</a>\n',
    "apps/web/index.html": '<script src="/admin/theme-init.js"></script>\n',
    "src/leonaid/application/links.py": 'path = "/admin/orders"\n',
    "apps/pwa/src/start.mjs": "location.href = '/app/';\n",
}


def run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(root), *extra],
        capture_output=True,
        text=True,
        check=False,
    )


def write(root: Path, files: dict[str, str]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write(root, CLEAN)
        clean = run(root)
        if clean.returncode != 0:
            print(clean.stdout + clean.stderr, file=sys.stderr)
            print(
                "base-path-literals-test: ERROR: clean tree rejected", file=sys.stderr
            )
            return 1
        write(root, DIRTY)
        dirty = run(root)
        if dirty.returncode == 0:
            print(
                "base-path-literals-test: ERROR: dirty tree accepted", file=sys.stderr
            )
            return 1
        for relative in DIRTY:
            if f"{relative}:1:" not in dirty.stdout:
                print(dirty.stdout, file=sys.stderr)
                print(
                    f"base-path-literals-test: ERROR: {relative} not reported",
                    file=sys.stderr,
                )
                return 1
        for relative in CLEAN:
            if relative in dirty.stdout:
                print(
                    f"base-path-literals-test: ERROR: {relative} reported",
                    file=sys.stderr,
                )
                return 1
        report = run(root, "--report")
        if report.returncode != 0 or f"{len(DIRTY)} finding(s)" not in report.stdout:
            print(report.stdout + report.stderr, file=sys.stderr)
            print("base-path-literals-test: ERROR: --report failed", file=sys.stderr)
            return 1
    print(
        "base-path-literals-test: OK: literals found, constants, comments and tests pass"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
