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
import os
from pathlib import Path
import re
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
    "tools/pilot_cms/",
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


SOURCE_SUFFIXES = {".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".jsx", ".astro"}
# Static and dynamic imports/re-exports with a relative specifier.
RELATIVE_IMPORT = re.compile(
    r"""(?:\bfrom|\bimport|\bimport\s*\()\s*['"](\.{1,2}/[^'"]+)['"]"""
)


def workspaces(root: Path) -> dict[str, tuple[str, set[str], bool]]:
    """Map workspace directory -> (package name, internal dependencies, has check).

    `has check` is true when the package defines its own typecheck/check script.
    """
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
        checked = bool({"typecheck", "check"} & set(data.get("scripts", {})))
        result[manifest.parent.relative_to(root).as_posix()] = (
            data["name"],
            names,
            checked,
        )
    return result


def relative_edges(root: Path, directories: list[str]) -> set[tuple[str, str]]:
    """(importer, imported) workspace pairs linked by a relative import.

    Such imports (e.g. campaign-site importing apps/public sources) are not
    declared in package.json but still make the importer's typecheck depend
    on the imported workspace.
    """
    edges = set()
    for directory in directories:
        base = root / directory
        for folder, subfolders, files in os.walk(base):
            subfolders[:] = [
                name
                for name in subfolders
                if name not in {"node_modules", "dist", ".astro"}
            ]
            for name in files:
                if Path(name).suffix not in SOURCE_SUFFIXES:
                    continue
                source = Path(folder) / name
                text = source.read_text(encoding="utf-8", errors="replace")
                for specifier in RELATIVE_IMPORT.findall(text):
                    target = os.path.normpath(source.parent / specifier)
                    relative = os.path.relpath(target, root).replace(os.sep, "/")
                    for other in directories:
                        if other != directory and relative.startswith(other + "/"):
                            edges.add((directory, other))
    return edges


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
    # Close over dependents: declared @leonaid/* dependencies plus relative
    # imports across workspace directories.
    by_name = {name: directory for directory, (name, _, _) in packages.items()}
    depends_on = {
        directory: {by_name[name] for name in dependencies if name in by_name}
        for directory, (_, dependencies, _) in packages.items()
    }
    for importer, imported in relative_edges(root, sorted(packages)):
        depends_on[importer].add(imported)
    grew = True
    while grew:
        grew = False
        for directory, dependencies in depends_on.items():
            if directory not in selected and dependencies & selected:
                selected.add(directory)
                grew = True
    # Fail safe: a selected workspace with its own check that this table does
    # not know yet (a new app or package) selects every check.
    if any(
        packages[directory][2] and directory not in SCRIPTS for directory in selected
    ):
        selected = set(packages) | set(SCRIPTS)
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
