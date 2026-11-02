#!/usr/bin/env python3
"""Check the stable, branch-protectable GitHub Actions job contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_JOBS = {
    "artifact-probe",
    "build",
    "contract",
    "e2e",
    "emdash-cases",
    "emdash-proofs",
    "golden-journey",
    "integration",
    "integration-shards",
    "lint-types",
    "pilot-cold-rehearsal",
    "security",
    "unit",
}

# Editor load race (PR #37) and Caddy body drain (PR #38) were only visible here.
EMDASH_GROUPS = ("krapfentaxi-orders", "krapfentaxi-migration", "static")

JOB_HEADER = re.compile(r"(?m)^  ([a-z0-9-]+):\n")


def job_block(text: str, job: str) -> str:
    marker = f"  {job}:\n"
    start = text.find(marker)
    if start < 0:
        return ""
    following = JOB_HEADER.search(text, start + len(marker))
    return text[start : following.start() if following else len(text)]


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for job in sorted(REQUIRED_JOBS):
        if f"\n  {job}:\n" not in text:
            problems.append(f"Job fehlt: {job}")
    # Summaries have no test output; their matrix legs publish evidence.
    evidence_jobs = len(REQUIRED_JOBS - {"integration", "emdash-proofs"})
    if text.count("actions/upload-artifact@") < evidence_jobs:
        problems.append("Nicht jeder Job veröffentlicht Beweisartefakte.")
    if text.count("if: always()") < evidence_jobs:
        problems.append("Nicht jeder Artefakt-Upload läuft auch nach Fehlern.")
    if "tools/ci/run-job.sh" not in text:
        problems.append("Gemeinsame Log-/Sanitizing-Hülle fehlt.")
    if "tools/ci/integration.sh" not in text or "tools/ci/e2e.sh" not in text:
        problems.append("Integration/E2E verwenden nicht die lokalen Testpfade.")
    if "ci-artifact-probe" not in text:
        problems.append("Absichtlich fehlschlagender Probe-Branch fehlt.")
    cold = job_block(text, "pilot-cold-rehearsal")
    if "if: inputs.cold_run == true" not in cold:
        problems.append("Finale Generalprobe ist nicht exklusiv an cold_run gebunden.")
    if "docker system prune --all --volumes --force" not in cold:
        problems.append("Cold-Run leert Docker-Systemzustand und Caches nicht.")
    if "./leonaid test-pilot-rehearsal --synthetic" not in cold:
        problems.append(
            "Cold-Run führt die vollständige synthetische Generalprobe nicht aus."
        )
    if "LEONAID_PILOT_REHEARSAL_ARTIFACT_DIR" not in cold:
        problems.append(
            "Cold-Run veröffentlicht den sanitizten Generalprobenbeleg nicht."
        )
    if "services:" in text:
        problems.append(
            "Workflow darf keine von Compose abweichenden Services definieren."
        )
    integration = job_block(text, "integration")
    for required in (
        "needs: integration-shards",
        "if: ${{ !cancelled()",
        "needs.integration-shards.result",
        'test "$RESULT" = success',
    ):
        if required not in integration:
            problems.append("Integration-Sammelcheck muss alle Shards verlangen.")
    problems.extend(check_emdash(text))
    return problems


def check_emdash(text: str) -> list[str]:
    """EmDash regressions surfaced only in these proofs; keep them gating."""
    problems: list[str] = []
    cases = job_block(text, "emdash-cases")
    for group in EMDASH_GROUPS:
        if not re.search(rf"group: \[[^\]]*\b{re.escape(group)}\b", cases):
            problems.append(f"EmDash-Proof-Gruppe fehlt: {group}")
    if "sh tools/ci/emdash.sh" not in cases or "tools/ci/run-job.sh" not in cases:
        problems.append("EmDash-Proofs laufen nicht über tools/ci/emdash.sh.")
    if "paths:" in text or "paths-ignore:" in text:
        problems.append("Pflicht-CI darf keine Pfadfilter verwenden.")
    if "continue-on-error" in cases or re.search(r"(?i)retry", cases):
        problems.append(
            "EmDash-Proofs dürfen Fehler nicht wiederholen oder ignorieren."
        )
    summary = job_block(text, "emdash-proofs")
    for required in (
        "needs: emdash-cases",
        "if: ${{ !cancelled()",
        "needs.emdash-cases.result",
        'test "$RESULT" = success',
    ):
        if required not in summary:
            problems.append("EmDash-Sammelcheck muss alle Proof-Gruppen verlangen.")
    return problems


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else ".github/workflows/ci.yml")
    problems = check(path)
    if problems:
        for problem in problems:
            print(f"ci-workflow-contract: ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print(
        "ci-workflow-contract: OK: Pflichtchecks, Integration-Shards, Cold-Rehearsal "
        "und Failure-Artefakte"
    )


if __name__ == "__main__":
    main()
