#!/usr/bin/env python3
"""Prove the conflict-marker guard with real files in a temporary tree."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "conflict_markers.py"


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    clean_cases = {
        "docs/setext.md": "Title\n=======\n\nText with ======= inside.\n",
        "notes.txt": "a <<<<<<< not at line start\n<<<<<<<<< eight is not a marker\n",
        "node_modules/pkg/x.md": "<<<<<<< HEAD\n",
        "image.bin": None,
    }
    dirty_cases = {
        "docs/page.md": "text\n||||||| 387fe47\n",
        "script.sh": "<<<<<<< HEAD\necho a\n=======\necho b\n>>>>>>> branch\n",
        "bare.py": ">>>>>>>\n",
    }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative, content in clean_cases.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                path.write_bytes(b"\xff\xfe<<<<<<< HEAD\n\x00")
            else:
                path.write_text(content, encoding="utf-8")
        result = run(root)
        if result.returncode != 0:
            print(f"conflict-markers-test: clean tree rejected: {result.stderr}")
            return 1
        for relative, content in dirty_cases.items():
            path = root / relative
            path.write_text(content, encoding="utf-8")
            result = run(root)
            if result.returncode == 0 or relative not in result.stderr:
                print(f"conflict-markers-test: {relative} was not reported")
                return 1
            path.unlink()
    print(
        "conflict-markers-test: OK: labelled markers fail, prose and vendored files pass"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
