#!/usr/bin/env python3
"""Check the stable, branch-protectable GitHub Actions job contract.

Two tiers: pull requests run the cheap gates plus the stack suites
tools/ci/select_suites.py selects; merge_group, push, schedule and dispatch
run everything. One aggregate gate per workflow is the required check.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import select_suites  # noqa: E402

REQUIRED_JOBS = {
    "artifact-probe",
    "build",
    "contract",
    "e2e",
    "emdash-cases",
    "emdash-proofs",
    "flake-summary",
    "gate",
    "golden-journey",
    "integration",
    "integration-shards",
    "lint-types",
    "pilot-cold-rehearsal",
    "security",
    "select",
    "unit",
}
# Jobs without own test output: summaries, selector, gate, nightly report.
NO_EVIDENCE = {"integration", "emdash-proofs", "select", "gate", "flake-summary"}
# Not part of the gate: dispatch-only probes and the post-gate report.
OUTSIDE_GATE = {"gate", "pilot-cold-rehearsal", "artifact-probe", "flake-summary"}

# Editor load race (PR #37) and Caddy body drain (PR #38) were only visible here.
EMDASH_GROUPS = ("krapfentaxi-orders", "krapfentaxi-migration", "static")

# Proofs that run nowhere else; dropping a shard silently stops the proof.
INTEGRATION_SHARDS = ("delivery",)
# Module browser proofs; each module's journeys run only in its own leaf.
E2E_SHARDS = ("tasks", "materials", "knowledge", "inbox")

# Workflows whose gate is a required check. Each must run on pull_request
# and merge_group, must not use path filters and must end in its gate.
GATED_WORKFLOWS = {
    "ci.yml": "CI gate",
    "surveys.yml": "Survey gate",
    "api-contract.yml": "API contract gate",
    "pins.yml": "Dependency pins gate",
}
# Required without a gate: a single always-running job.
UNGATED_REQUIRED = {"docs.yml": "Bilingual site artifact"}

# The only commands tools/ci/retry-infra.sh may wrap; tests are never retried.
RETRYABLE = re.compile(
    r"tools/ci/retry-infra\.sh (?:\./leonaid bootstrap|sh tools/ci/bootstrap-prefetch\.sh"
    r" (?:toolchains|seed|browser|\"\$1\")|docker pull \"\$[A-Z_]+\")"
)
# Composite-action steps whose failure is retried once by the next steps.
FIRST_ATTEMPTS = {
    ".github/actions/build-cache/action.yml": "bake",
    ".github/actions/test-fixture/action.yml": "restore",
}

JOB_HEADER = re.compile(r"(?m)^  ([a-z0-9-]+):\n")


def job_block(text: str, job: str) -> str:
    marker = f"\n  {job}:\n"
    start = text.find(marker)
    if start < 0:
        return ""
    start += 1
    following = JOB_HEADER.search(text, start + len(marker) - 1)
    return text[start : following.start() if following else len(text)]


def jobs_of(text: str) -> list[str]:
    body = text[text.find("\njobs:\n") :]
    return JOB_HEADER.findall(body)


def needs_of(block: str) -> set[str]:
    inline = re.search(r"(?m)^    needs: \[([^\]]*)\]$", block)
    if inline:
        return {item.strip() for item in inline.group(1).split(",") if item.strip()}
    single = re.search(r"(?m)^    needs: ([a-z0-9-]+)$", block)
    if single:
        return {single.group(1)}
    listed = re.search(r"(?m)^    needs:\n((?:      - [a-z0-9-]+\n)+)", block)
    if listed:
        return set(re.findall(r"- ([a-z0-9-]+)", listed.group(1)))
    return set()


def triggers(text: str) -> str:
    start = text.find("\non:\n")
    end = text.find("\npermissions:", start)
    return text[start:end] if start >= 0 else ""


def check(path: Path) -> list[str]:
    """Contract of ci.yml (the text-mutation tests target this file)."""
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    for job in sorted(REQUIRED_JOBS):
        if f"\n  {job}:\n" not in text:
            problems.append(f"Job missing: {job}")
    # Summaries have no test output; their matrix legs publish evidence.
    evidence_jobs = len(REQUIRED_JOBS - NO_EVIDENCE)
    if text.count("actions/upload-artifact@") < evidence_jobs:
        problems.append("Not every job publishes evidence artifacts.")
    if text.count("if: always()") < evidence_jobs:
        problems.append("Not every artifact upload also runs after failures.")
    if "tools/ci/run-job.sh" not in text:
        problems.append("Shared log/sanitizing wrapper is missing.")
    if "tools/ci/integration.sh" not in text or "tools/ci/e2e.sh" not in text:
        problems.append("Integration/E2E do not use the local test paths.")
    if "ci-artifact-probe" not in text:
        problems.append("Intentionally failing probe branch is missing.")
    cold = job_block(text, "pilot-cold-rehearsal")
    if "if: inputs.cold_run == true" not in cold:
        problems.append("Final dress rehearsal is not bound exclusively to cold_run.")
    if "docker system prune --all --volumes --force" not in cold:
        problems.append("Cold run does not clear Docker system state and caches.")
    if "./leonaid test-pilot-rehearsal --synthetic" not in cold:
        problems.append("Cold run does not execute the full synthetic dress rehearsal.")
    if "LEONAID_PILOT_REHEARSAL_ARTIFACT_DIR" not in cold:
        problems.append(
            "Cold run does not publish the sanitized dress-rehearsal evidence."
        )
    if "services:" in text:
        problems.append("Workflow must not define services that differ from Compose.")
    problems.extend(
        check_summary(text, "integration", "integration-shards", "integration")
    )
    problems.extend(check_summary(text, "e2e-summary", "e2e", "E2E"))
    problems.extend(check_summary(text, "emdash-proofs", "emdash-cases", "EmDash"))
    problems.extend(check_summary(text, "golden-journey", "golden-parts", "Golden"))
    shards = job_block(text, "integration-shards")
    if "shard: ${{ fromJSON(needs.select.outputs.integration) }}" not in shards:
        problems.append("Integration shards must come from the suite selector.")
    for shard in INTEGRATION_SHARDS:
        if shard not in select_suites.INTEGRATION_SHARDS:
            problems.append(f"Integration shard missing: {shard}")
    security = job_block(text, "security")
    # All own images plus every pinned third-party image exceed the free disk
    # of a stock runner; the Security gate must not fail on space.
    start = security.find("tools/ci/free-runner-disk.sh start")
    finish = security.find("tools/ci/free-runner-disk.sh wait")
    gate = security.find("tools/ci/security.sh")
    if not 0 <= start < finish < gate:
        problems.append("Security job does not free runner disk before the gates.")
    leaves = job_block(text, "e2e")
    if "shard: ${{ fromJSON(needs.select.outputs.e2e) }}" not in leaves:
        problems.append("E2E leaves must come from the suite selector.")
    for shard in E2E_SHARDS:
        if shard not in select_suites.E2E_SHARDS:
            problems.append(f"E2E shard missing: {shard}")
    for job, key in (
        ("integration-shards", "integration"),
        ("e2e", "e2e"),
        ("emdash-cases", "emdash"),
        ("contract", "contract"),
        ("golden-parts", "golden"),
    ):
        block = job_block(text, job)
        if (
            "select" not in needs_of(block)
            or f"needs.select.outputs.{key}" not in block
        ):
            problems.append(f"{job} must depend on the suite selector output {key}.")
        if "needs.select.result == 'success'" not in block:
            problems.append(f"{job} must not run when the suite selector failed.")
    problems.extend(check_emdash(text))
    problems.extend(check_tiers(text, "ci.yml"))
    problems.extend(check_gate(text, "ci.yml"))
    problems.extend(check_retries(text, "ci.yml"))
    problems.extend(check_nightly(text))
    return problems


def check_summary(text: str, job: str, leaves: str, label: str) -> list[str]:
    """A summary passes only for success, or for a skip the selector ordered."""
    block = job_block(text, job)
    problems: list[str] = []
    for required in (
        f"needs: [select, {leaves}]",
        "if: ${{ !cancelled()",
        f"needs.{leaves}.result",
        'test "$SELECT" = success',
        'test "$RESULT" = success',
        'else test "$RESULT" = skipped',
    ):
        if required not in block:
            problems.append(f"{label} summary check must require all selected jobs.")
            break
    return problems


def check_emdash(text: str) -> list[str]:
    """EmDash regressions surfaced only in these proofs; keep them gating."""
    problems: list[str] = []
    cases = job_block(text, "emdash-cases")
    for group in EMDASH_GROUPS:
        if group not in select_suites.EMDASH_GROUPS:
            problems.append(f"EmDash proof group missing: {group}")
    if "group: ${{ fromJSON(needs.select.outputs.emdash) }}" not in cases:
        problems.append("EmDash proof groups must come from the suite selector.")
    if "sh tools/ci/emdash.sh" not in cases or "tools/ci/run-job.sh" not in cases:
        problems.append("EmDash proofs do not run through tools/ci/emdash.sh.")
    if "continue-on-error" in cases or re.search(
        r"(?i)retry", cases.replace("tools/ci/retry-infra.sh", "")
    ):
        problems.append("EmDash proofs must not retry or ignore failures.")
    return problems


def check_tiers(text: str, name: str) -> list[str]:
    problems: list[str] = []
    on = triggers(text)
    for event in ("pull_request:", "merge_group:"):
        if f"\n  {event}" not in on:
            problems.append(
                f"{name}: must run on {event.rstrip(':')} (merge queue tier)."
            )
    if "paths:" in on or "paths-ignore:" in on:
        problems.append(f"{name}: required CI must not use path filters.")
    if name in GATED_WORKFLOWS:
        select = job_block(text, "select")
        if "uses: ./.github/workflows/select-suites.yml" not in select:
            problems.append(f"{name}: the select job must use select-suites.yml.")
    return problems


def check_gate(text: str, name: str) -> list[str]:
    problems: list[str] = []
    block = job_block(text, "gate")
    title = GATED_WORKFLOWS[name]
    if f"    name: {title}\n" not in block:
        problems.append(f"{name}: aggregate gate '{title}' missing.")
        return problems
    if "    if: ${{ always()" not in block:
        problems.append(f"{name}: the gate must run after failures (always()).")
    if (
        "python3 tools/ci/gate.py" not in block
        or "NEEDS: ${{ toJSON(needs) }}" not in block
    ):
        problems.append(
            f"{name}: the gate must evaluate every need with tools/ci/gate.py."
        )
    missing = set(jobs_of(text)) - OUTSIDE_GATE - needs_of(block)
    if missing:
        problems.append(
            f"{name}: the gate does not require: {', '.join(sorted(missing))}"
        )
    return problems


def check_retries(text: str, name: str) -> list[str]:
    problems: list[str] = []
    if "continue-on-error" in text:
        problems.append(f"{name}: continue-on-error hides failures.")
    for line in text.splitlines():
        if re.search(r"(?i)retry", line) and not line.lstrip().startswith("#"):
            if not RETRYABLE.search(line):
                problems.append(
                    f"{name}: only infrastructure commands may be retried: {line.strip()}"
                )
    return problems


def check_nightly(text: str) -> list[str]:
    problems: list[str] = []
    if not re.search(r"\n  schedule:\n    - cron: ", triggers(text)):
        problems.append("ci.yml: nightly complete run (schedule) missing.")
    report = job_block(text, "flake-summary")
    if (
        "github.event_name == 'schedule'" not in report
        or "tools/ci/flake_summary.py" not in report
    ):
        problems.append("ci.yml: nightly flake summary missing.")
    return problems


def check_first_attempts(root: Path) -> list[str]:
    problems: list[str] = []
    for relative, step in FIRST_ATTEMPTS.items():
        text = (root / relative).read_text(encoding="utf-8")
        if (
            text.count("continue-on-error: true") != 1
            or f"id: {step}\n      continue-on-error: true" not in text
        ):
            problems.append(
                f"{relative}: only the '{step}' first attempt may continue on error."
            )
        if text.count(f"if: steps.{step}.outcome == 'failure'") < 2:
            problems.append(
                f"{relative}: a failed '{step}' first attempt must be retried once."
            )
    return problems


def check_repository(root: Path) -> list[str]:
    workflows = root / ".github/workflows"
    problems = check(workflows / "ci.yml")
    for name in GATED_WORKFLOWS:
        if name == "ci.yml":
            continue
        text = (workflows / name).read_text(encoding="utf-8")
        problems.extend(check_tiers(text, name))
        problems.extend(check_gate(text, name))
        problems.extend(check_retries(text, name))
    for name, job in UNGATED_REQUIRED.items():
        text = (workflows / name).read_text(encoding="utf-8")
        problems.extend(check_tiers(text, name))
        problems.extend(check_retries(text, name))
        if f"name: {job}\n" not in text:
            problems.append(f"{name}: required job '{job}' missing.")
    select = (workflows / "select-suites.yml").read_text(encoding="utf-8")
    if "tools/ci/select_suites.py --event" not in select:
        problems.append("select-suites.yml must run tools/ci/select_suites.py.")
    problems.extend(check_first_attempts(root))
    return problems


def main() -> None:
    argument = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    # Accept the repository root or (historically) the ci.yml path.
    root = argument.parents[2] if argument.is_file() else argument
    problems = check_repository(root.resolve())
    if problems:
        for problem in problems:
            print(f"ci-workflow-contract: ERROR: {problem}", file=sys.stderr)
        raise SystemExit(1)
    print(
        "ci-workflow-contract: OK: tiers, merge queue, gates, selector, infra-only "
        "retries, shards, cold rehearsal and failure artifacts"
    )


if __name__ == "__main__":
    main()
