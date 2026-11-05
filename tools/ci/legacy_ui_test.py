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
    "packages/ui/src/a.tsx": 'import { Search } from "lucide-react";\n',
    "packages/ui/src/a.css": ".a { color: var(--text-2); background: var(--surface-2); }\n"
    ".b { color: var(--text-muted-x, red); }\n",
    "apps/web/src/b.css": ".c { border-radius: var(--r-md); --primary-ish: 1; }\n",
    "apps/web/package.json": '{"dependencies": {"lucide-react": "1.60.0"}}\n',
    "apps/web/node_modules/x/y.tsx": 'import x from "@hugeicons/react";\n',
    "tools/elsewhere.css": ".d { color: var(--foreground); }\n",
}
DIRTY = {
    "packages/features/src/x.tsx": 'import { Search01Icon } from "@hugeicons/core-free-icons";\n',
    "packages/features/src/y.tsx": 'import { Menu } from "@base-ui/react/menu";\n',
    "apps/web/src/z.css": ".z { color: var(--foreground); }\n",
    "apps/web/src/w.css": ".w { box-shadow: var( --shadow-sm ); }\n",
    "apps/pwa/src/v.css": ".v { color: var(--muted, #555); }\n",
    "packages/ui/src/t.css": ":root {\n  --sidebar: var(--rail-bg);\n}\n",
    "packages/ui/package.json": '{"dependencies": {"@hugeicons/react": "1.1.9"}}\n',
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
            report = run(root, "--report")
            if report.returncode != 0 or relative not in report.stdout:
                print(f"legacy-ui-test: FAILED: --report did not list {relative}")
                return 1
    print(
        "legacy-ui-test: OK: Lucide and Leitsystem tokens pass; Hugeicons, Base UI, "
        "old token use and definitions and old dependencies are rejected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
