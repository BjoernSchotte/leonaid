#!/usr/bin/env python3
"""Prove the axe-helper guard with real files in a temporary tree."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "axe_helper.py"


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(root)],
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
    helper = {
        "tests/e2e/axe.mjs": 'import AxeBuilder from "@axe-core/playwright";\n'
        "export const scan = (page) => new AxeBuilder({ page }).analyze();\n",
    }
    clean = {
        **helper,
        "tests/e2e/list.spec.mjs": 'import { analyzeAccessibility } from "./axe.mjs";\n'
        "// AxeBuilder is only named in this comment.\n",
        "tools/other.mjs": "new AxeBuilder({ page });\n",
        "tests/e2e/node_modules/pkg/index.mjs": "new AxeBuilder({ page });\n",
    }
    dirty_cases = {
        "tests/e2e/direct.spec.mjs": "const r = await new AxeBuilder({ page }).analyze();\n",
        "tests/e2e/import.spec.mjs": "import AxeBuilder from '@axe-core/playwright';\n",
        "tests/e2e/nested/deep.spec.ts": "new  AxeBuilder({ page })\n",
        "tests/e2e/dynamic.spec.mjs": 'const { default: A } = await import("@axe-core/playwright");\n',
        "tests/e2e/require.spec.cjs": "const A = require(`@axe-core/playwright`);\n",
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        write(root, clean)
        result = run(root)
        if result.returncode != 0:
            print(f"axe-helper-test: FAILED: clean tree rejected:\n{result.stderr}")
            return 1
    for relative, content in dirty_cases.items():
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root, {**clean, relative: content})
            result = run(root)
            if result.returncode == 0 or relative not in result.stderr:
                print(f"axe-helper-test: FAILED: {relative} was not rejected")
                return 1
            if "analyzeAccessibility" not in result.stderr:
                print("axe-helper-test: FAILED: message does not name the helper")
                return 1
    print(
        "axe-helper-test: OK: helper and comments pass; direct AxeBuilder, "
        "direct import and nested specs are rejected"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
