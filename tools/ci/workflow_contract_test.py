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
        if result.returncode == 0 or "evidence artifacts" not in (
            result.stdout + result.stderr
        ):
            raise AssertionError("Missing artifact upload was not rejected.")
        mutations = (
            (
                "            delivery,\n",
                "",
                "Integration shard missing: delivery",
            ),
            (
                "          - tasks\n",
                "",
                "E2E shard missing: tasks",
            ),
            (
                "needs: integration-shards\n    if: ${{ !cancelled()",
                "needs: integration-shards\n    if: ${{ always()",
                "summary check",
            ),
            (
                "needs: integration-shards",
                "needs: unit",
                "summary check",
            ),
            (
                'test "$RESULT" = success',
                'test "$RESULT" != failure',
                "summary check",
            ),
            (
                "if: inputs.cold_run == true && inputs.artifact_probe != true",
                "if: inputs.artifact_probe != true",
                "cold_run",
            ),
            (
                "docker system prune --all --volumes --force",
                "docker image ls",
                "Docker system state",
            ),
            (
                "./leonaid test-pilot-rehearsal --synthetic",
                "./leonaid test-unit",
                "synthetic dress rehearsal",
            ),
            (
                "LEONAID_PILOT_REHEARSAL_ARTIFACT_DIR",
                "REMOVED_REHEARSAL_ARTIFACT_DIR",
                "dress-rehearsal evidence",
            ),
            (
                "group: [krapfentaxi-orders, ",
                "group: [",
                "krapfentaxi-orders",
            ),
            (
                "krapfentaxi-migration, static]",
                "static]",
                "krapfentaxi-migration",
            ),
            (
                "    name: EmDash proof / ${{ matrix.group }}\n",
                "    name: EmDash proof / ${{ matrix.group }}\n"
                "    continue-on-error: true\n",
                "retry or ignore",
            ),
            (
                "  pull_request:\n",
                "  pull_request:\n    paths: [apps/campaign-site/**]\n",
                "path filters",
            ),
            (
                "needs: emdash-cases\n    if: ${{ !cancelled()",
                "needs: emdash-cases\n    if: ${{ always()",
                "EmDash summary check",
            ),
            (
                "needs.emdash-cases.result",
                "needs.emdash-cases.outputs.result",
                "EmDash summary check",
            ),
            (
                "run: sh tools/ci/free-runner-disk.sh wait",
                "run: true",
                "free runner disk",
            ),
            (
                "run: sh tools/ci/free-runner-disk.sh start",
                "run: true",
                "free runner disk",
            ),
        )
        for old, new, expected in mutations:
            broken.write_text(text.replace(old, new, 1), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(checker), str(broken)],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 or expected not in (
                result.stdout + result.stderr
            ):
                raise AssertionError(
                    f"Cold-run contract violation {expected!r} was not rejected."
                )
    print(
        "ci-workflow-contract-test: OK: required checks, shards, cold rehearsal and "
        "missing upload are checked"
    )


if __name__ == "__main__":
    main()
