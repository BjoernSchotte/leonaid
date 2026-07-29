#!/usr/bin/env python3
"""Positive and negative filesystem tests for PILOT-050 evidence."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], expected: str, success: bool) -> None:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    output = result.stdout + result.stderr
    if (result.returncode == 0) != success or expected not in output:
        raise AssertionError(
            f"unexpected contract result ({result.returncode}):\n{output}"
        )


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    contract = root / "tools/pilot_rehearsal/contract.py"
    commit = "a" * 40
    started = "2026-07-29T08:00:00Z"
    finished = "2026-07-29T09:00:00Z"
    steps = (
        "user-admin,crm-import-golden,mail-relay,pilot-deployment,"
        "pilot-backup,pilot-alerting,pilot-legal-config,pilot-release"
    )

    with tempfile.TemporaryDirectory() as temporary:
        evidence = Path(temporary) / "summary.json"
        run(
            [
                sys.executable,
                str(contract),
                "write",
                "--output",
                str(evidence),
                "--status",
                "passed",
                "--release-commit",
                commit,
                "--started-at",
                started,
                "--finished-at",
                finished,
                "--completed",
                steps,
            ],
            "pilot-rehearsal-evidence: OK",
            True,
        )
        run(
            [sys.executable, str(contract), "verify", str(evidence)],
            "external gate boundary verified",
            True,
        )

        payload = json.loads(evidence.read_text(encoding="utf-8"))
        payload["productionReadiness"] = True
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        run(
            [sys.executable, str(contract), "verify", str(evidence)],
            "must not claim production readiness",
            False,
        )

        payload["productionReadiness"] = False
        payload["externalGates"][0]["status"] = "passed"
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        run(
            [sys.executable, str(contract), "verify", str(evidence)],
            "external gates must remain explicitly open",
            False,
        )

        payload["externalGates"][0]["status"] = "open"
        payload["completedSteps"] = ["mail-relay"]
        payload["status"] = "failed"
        payload["failedStep"] = "user-admin"
        evidence.write_text(json.dumps(payload), encoding="utf-8")
        run(
            [sys.executable, str(contract), "verify", str(evidence)],
            "not an exact ordered prefix",
            False,
        )

    print(
        "pilot-rehearsal-contract-test: OK: positive evidence and three "
        "fail-closed drifts passed"
    )


if __name__ == "__main__":
    main()
