#!/usr/bin/env python3
"""Prove tools/ci/run-job.sh: exit status, summary, failure context, sanitizer.

Needs Docker (the sanitizer runs in the pinned Python image), so it runs in
the Security job (tools/ci/security.sh), not in the stdlib checks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/ci/run-job.sh"


def run(directory: Path, *command: str) -> int:
    env = {**os.environ, "LEONAID_CI_ARTIFACT_DIR": str(directory)}
    return subprocess.run(
        ["bash", str(SCRIPT), "run-job-test", *command],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def main() -> int:
    failures: list[str] = []
    base = ROOT / ".artifacts/ci" / f"run-job-test-{os.getpid()}"
    try:
        failed = base / "failed"
        status = run(failed, "sh", "-c", "echo visible; exit 3")
        summary = (failed / "summary.txt").read_text(encoding="utf-8")
        if status != 3 or "status=3\n" not in summary:
            failures.append(f"exit status not kept: {status} {summary!r}")
        if "visible" not in (failed / "command.log").read_text(encoding="utf-8"):
            failures.append("command output not captured")
        if not (failed / "docker-containers.txt").exists():
            failures.append("failure context (docker-containers.txt) missing")

        passed = base / "passed"
        if run(passed, "true") != 0 or (passed / "docker-containers.txt").exists():
            failures.append("a green command must exit 0 without failure context")

        # An artifact type the sanitizer refuses: everything is deleted, 70.
        planted = base / "planted"
        status = run(planted, "sh", "-c", f"printf x > '{planted}/evidence.bin'")
        left = sorted(path.name for path in planted.iterdir())
        if status != 70 or left != ["SANITIZATION-FAILED.txt"]:
            failures.append(f"sanitizer failure not fail-closed: {status} {left}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    for failure in failures:
        print(f"run-job-test: ERROR: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("run-job-test: OK: status kept, summary, failure context, sanitizer exit 70")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
