#!/usr/bin/env python3
"""Prove that the workflow contract rejects a missing evidence upload."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    checker = root / "tools/ci/workflow_contract.py"
    workflow = root / ".github/workflows/ci.yml"
    subprocess.run([sys.executable, str(checker), str(workflow)], check=True)
    with tempfile.TemporaryDirectory() as temporary:
        broken = Path(temporary) / "ci.yml"
        text = workflow.read_text(encoding="utf-8")
        broken.write_text(
            text.replace("actions/upload-artifact@", "actions/removed-artifact@", 1),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(checker), str(broken)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 or "Beweisartefakte" not in (
            result.stdout + result.stderr
        ):
            raise AssertionError("Fehlender Artefakt-Upload wurde nicht abgewiesen.")
    print("ci-workflow-contract-test: OK: fehlender Upload wird abgewiesen")


if __name__ == "__main__":
    main()
