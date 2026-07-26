#!/usr/bin/env python3
"""Check the stable, branch-protectable GitHub Actions job contract."""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED_JOBS = {
    "artifact-probe",
    "build",
    "contract",
    "e2e",
    "integration",
    "lint-types",
    "security",
    "unit",
}


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for job in sorted(REQUIRED_JOBS):
        if f"\n  {job}:\n" not in text:
            problems.append(f"Job fehlt: {job}")
    if text.count("actions/upload-artifact@") < len(REQUIRED_JOBS):
        problems.append("Nicht jeder Job veröffentlicht Beweisartefakte.")
    if text.count("if: always()") < len(REQUIRED_JOBS):
        problems.append("Nicht jeder Artefakt-Upload läuft auch nach Fehlern.")
    if "tools/ci/run-job.sh" not in text:
        problems.append("Gemeinsame Log-/Sanitizing-Hülle fehlt.")
    if "tools/ci/integration.sh" not in text or "tools/ci/e2e.sh" not in text:
        problems.append("Integration/E2E verwenden nicht die lokalen Testpfade.")
    if "ci-artifact-probe" not in text:
        problems.append("Absichtlich fehlschlagender Probe-Branch fehlt.")
    if "services:" in text:
        problems.append(
            "Workflow darf keine von Compose abweichenden Services definieren."
        )
    return problems


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/workflows/ci.yml")
    problems = check(path)
    if problems:
        for problem in problems:
            print(f"ci-workflow-contract: ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print("ci-workflow-contract: OK: acht getrennte Jobs und Failure-Artefakte")


if __name__ == "__main__":
    main()
