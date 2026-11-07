#!/usr/bin/env python3
"""Select what ./leonaid check-fast checks for a list of changed paths.

Usage: fast_plan.py ROOT CHANGED PLAN. CHANGED lists changed repository paths
(one per line); PLAN receives one `typecheck <scripts...>` line and one
`prettier <path>` line per file to format-check. Workspace dependencies come from each package.json, so
a change in a package also typechecks every package that depends on it. A
root manifest/lockfile/tsconfig change or "ALL" selects every package.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

# Root script per workspace directory; typecheck:ui covers both ui tsconfigs.
SCRIPTS = {
    "packages/api-client": "typecheck:api-client",
    "packages/ui": "typecheck:ui",
    "packages/features": "typecheck:features",
    "apps/web": "typecheck:web",
    "apps/pwa": "typecheck:pwa",
    "apps/public": "typecheck:public",
    "apps/campaign-site": "typecheck:campaign-site",
    "apps/docs": "typecheck:docs",
}
ROOT_INPUTS = {"package.json", "bun.lock", "tsconfig.json", "tsconfig.base.json"}
# Same scope as the full check's prettier call.
PRETTIER_SCOPE = (
    ".github/",
    "apps/campaign-site/",
    "apps/public/",
    "apps/pwa/",
    "apps/web/",
    "packages/api-client/",
    "packages/features/",
    "packages/ui/",
    "tools/emdash_spike/",
    "tests/contract/",
    "tests/e2e/",
)
PRETTIER_FILES = {"package.json", "playwright.config.mjs", ".prettierrc.json"}
PRETTIER_SUFFIXES = {
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".mts",
    ".cts",
    ".tsx",
    ".json",
    ".css",
    ".md",
    ".mdx",
    ".yml",
    ".yaml",
    ".html",
    ".astro",
}


def workspaces(root: Path) -> dict[str, tuple[str, set[str]]]:
    """Map workspace directory -> (package name, internal dependency names)."""
    result = {}
    for manifest in sorted(
        [*root.glob("apps/*/package.json"), *root.glob("packages/*/package.json")]
    ):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        names = {
            name
            for field in ("dependencies", "devDependencies", "peerDependencies")
            for name in data.get(field, {})
            if name.startswith("@leonaid/")
        }
        result[manifest.parent.relative_to(root).as_posix()] = (data["name"], names)
    return result


def plan(root: Path, changed: list[str]) -> tuple[list[str], list[str]]:
    packages = workspaces(root)
    if "ALL" in changed or any(path in ROOT_INPUTS for path in changed):
        selected = set(packages)
    else:
        selected = {
            directory
            for directory in packages
            for path in changed
            if path.startswith(directory + "/")
        }
    # Close over dependents: a package that depends on a selected one.
    by_name = {name: directory for directory, (name, _) in packages.items()}
    grew = True
    while grew:
        grew = False
        for directory, (_, dependencies) in packages.items():
            if directory not in selected and any(
                by_name.get(dependency) in selected for dependency in dependencies
            ):
                selected.add(directory)
                grew = True
    scripts = [SCRIPTS[d] for d in SCRIPTS if d in selected]
    prettier = sorted(
        path
        for path in changed
        if (root / path).is_file()
        and (
            path in PRETTIER_FILES
            or (
                path.startswith(PRETTIER_SCOPE)
                and Path(path).suffix in PRETTIER_SUFFIXES
            )
        )
    )
    return scripts, prettier


def main() -> int:
    root, changed_file, plan_file = (Path(argument) for argument in sys.argv[1:4])
    changed = [
        line.strip()
        for line in (root / changed_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    scripts, prettier = plan(root, changed)
    lines = [f"typecheck {' '.join(scripts)}".rstrip()]
    lines += [f"prettier {path}" for path in prettier]
    (root / plan_file).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
