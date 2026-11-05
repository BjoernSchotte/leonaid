#!/usr/bin/env python3
"""Prove the legacy-UI guard with real files in a temporary tree."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

CHECKER = Path(__file__).resolve().parent / "legacy_ui.py"


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


CLEAN = {
    "packages/ui/src/a.tsx": 'import { Search } from "lucide-react";\n'
    'element.style.setProperty("--meter", "0.4");\n'
    'const zone = "--zone-soft";\n',
    "packages/ui/src/a.css": ".a { color: var(--text-2); background: var(--surface-2); }\n"
    ".b { color: var(--text-muted-x, red); --primary-ish: 1; }\n",
    "apps/web/src/b.scss": ".c { border-radius: var(--r-md); }\n",
    "apps/docs/src/page.md": "Use `--text` and `--accent`; the shadow is `--shadow-1`.\n",
    "apps/web/package.json": '{"dependencies": {"lucide-react": "1.60.0"},'
    ' "overrides": {"zod": "4.6.7"}}\n',
    "apps/web/node_modules/x/y.tsx": 'import x from "@hugeicons/react";\n',
    "tools/elsewhere.css": ".d { color: var(--foreground); }\n",
    # The contrast test names the old aliases to prove they stay undefined.
    "packages/ui/src/styles/contrast.test.ts": 'const removed = { "--primary": "--accent" };\n',
}
DIRTY = {
    # M1: the packages in any string literal.
    "packages/features/src/import.tsx": 'import { Search01Icon } from "@hugeicons/core-free-icons";\n',
    "packages/features/src/base-ui.tsx": 'import { Menu } from "@base-ui/react/menu";\n',
    "packages/features/src/require.cjs": 'const icons = require("@hugeicons/react");\n',
    "packages/features/src/import-equals.ts": 'import icons = require("@hugeicons/core-free-icons");\n',
    "packages/features/src/dynamic.ts": "const menu = await import('@base-ui/react/menu');\n",
    "packages/features/src/mock.test.tsx": 'vi.mock("@base-ui/react/dialog", () => ({}));\n',
    "packages/features/src/jest.test.tsx": "jest.mock(`@hugeicons/react`);\n",
    "packages/features/src/side-effect.ts": 'import "@hugeicons/core-free-icons";\n',
    # Token uses, also across lines and with fallbacks.
    "apps/web/src/use.css": ".z { color: var(--foreground); }\n",
    "apps/web/src/spaced.css": ".w { box-shadow: var( --shadow-sm ); }\n",
    "apps/pwa/src/fallback.css": ".v { color: var(--muted, #555); }\n",
    "apps/web/src/sidebar.css": ".s { color: var(--sidebar-foreground); }\n",
    "apps/web/src/multiline.css": ".m {\n  color: var(\n    --primary\n  );\n}\n",
    "apps/web/src/inline.tsx": "const style = 'color: var(--surface-muted)';\n",
    # M2: definitions, also several on one line.
    "packages/ui/src/define.css": ":root {\n  --sidebar: var(--rail-bg);\n}\n",
    "packages/ui/src/one-line.css": "a{--sidebar:red}\n",
    "packages/ui/src/after-semicolon.css": "b{color:red;--radius-md:4px}\n",
    # M3: more file types and dependency fields.
    "apps/public/src/page.html": '<p style="color: var(--primary)">x</p>\n',
    "apps/public/src/icon.svg": '<svg><path style="fill: var(--muted)"/></svg>\n',
    "apps/docs/src/guide.mdx": '<span style={{ color: "var(--foreground)" }} />\n',
    "apps/web/src/theme.scss": ".t { color: var(--warning-text); }\n",
    "apps/public/src/layout.astro": "<style>\n:root { --ring: blue; }\n</style>\n",
    "packages/ui/package.json": '{"dependencies": {"@hugeicons/react": "1.1.9"}}\n',
    "apps/pwa/package.json": '{"optionalDependencies": {"@base-ui/react": "1.6.0"}}\n',
    "apps/docs/package.json": '{"overrides": {"some-lib": {"@hugeicons/react": "1.1.9"}}}\n',
    "packages/surveys/package.json": '{"resolutions": {"@base-ui/react": "1.6.0"}}\n',
    # Final review M3: the root manifest, and manifests that cannot be parsed.
    "package.json": '{"devDependencies": {"@hugeicons/react": "1.1.9"}}\n',
    "apps/web/broken/package.json": '{"dependencies": {\n',
    # M4: old names set or read from JavaScript.
    "packages/features/src/set.ts": 'node.style.setProperty("--primary", "red");\n',
    "packages/features/src/read.ts": "getComputedStyle(node).getPropertyValue('--muted');\n",
}


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write(root, CLEAN)
        result = run(root)
        if result.returncode != 0:
            print(f"legacy-ui-test: FAILED: clean tree rejected:\n{result.stderr}")
            return 1
    for relative, content in DIRTY.items():
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, {**CLEAN, relative: content})
            result = run(root)
            if result.returncode == 0 or relative not in result.stderr:
                print(f"legacy-ui-test: FAILED: {relative} was not rejected")
                return 1
            if (
                "lucide-react" not in result.stderr
                or "leitsystem.css" not in result.stderr
            ):
                print(
                    "legacy-ui-test: FAILED: the message does not name the replacements"
                )
                return 1
            report = run(root, "--report")
            if report.returncode != 0 or relative not in report.stdout:
                print(f"legacy-ui-test: FAILED: --report did not list {relative}")
                return 1
    with tempfile.TemporaryDirectory() as directory:
        # Line numbers point at the token, also inside a multi-line var().
        root = Path(directory)
        write(
            root,
            {
                **CLEAN,
                "apps/web/src/lines.css": "a{}\nb{}\n.m{color:var(\n --primary)}\n",
            },
        )
        result = run(root)
        if "apps/web/src/lines.css:3:" not in result.stderr:
            print("legacy-ui-test: FAILED: wrong line number for a multi-line var()")
            return 1
    print(
        f"legacy-ui-test: OK: clean tree passes; {len(DIRTY)} dirty cases rejected "
        "(require/mock/dynamic imports, multi-line var(), one-line definitions, "
        "html/svg/mdx/scss/astro, optional/override/resolution dependencies, "
        "setProperty strings)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
