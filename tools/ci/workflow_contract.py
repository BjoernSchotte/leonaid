#!/usr/bin/env python3
"""Check the stable, branch-protectable GitHub Actions job contract.

Pull requests run the cheap gates plus the stack suites
tools/ci/select_suites.py selects (drafts nothing, stacks module-local
suites only); scheduled runs on main and dispatch run everything (the
3-hourly run without the E2E leaves). One aggregate gate per workflow is the
required check.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import gate as gate_script  # noqa: E402
from tools.ci import select_suites  # noqa: E402

REQUIRED_JOBS = {
    "artifact-probe",
    "build",
    "e2e",
    "emdash-cases",
    "flake-summary",
    "gate",
    "golden-journey",
    "golden-parts",
    "integration-shards",
    "lint-unit",
    "pilot-cold-rehearsal",
    "security",
    "select",
}
# Jobs without own test output: selector, gate, Golden comparison, nightly report.
NO_EVIDENCE = {"select", "gate", "golden-journey", "flake-summary"}
# Removed pure summary jobs: tools/ci/gate.py already requires every selected
# matrix leg, and each summary cost a runner slot per run.
REMOVED_SUMMARIES = ("integration", "e2e-summary", "emdash-proofs")
# Not part of the gate: dispatch-only probes and the post-gate report.
OUTSIDE_GATE = {
    "gate",
    "pilot-cold-rehearsal",
    "artifact-probe",
    "flake-summary",
    "rerun-stale-gates",
}
# After a real gate, re-run failed mirror gates (tools/ci/rerun_stale_gates.py).
RERUN_JOB = "rerun-stale-gates"

# Editor load race (PR #37) and Caddy body drain (PR #38) were only visible here.
EMDASH_GROUPS = ("krapfentaxi-orders", "krapfentaxi-migration", "static")

# Proofs that run nowhere else; dropping a shard silently stops the proof.
INTEGRATION_SHARDS = ("delivery",)
# Module browser proofs; each module's journeys run only in its own leaf.
E2E_SHARDS = (
    "tasks",
    "materials",
    "knowledge",
    "inbox",
    "leitsystem-ui",
    "operations",
    "invoice-flows",
)

# Workflows whose gate is a required check. Each must run on pull_request
# (never merge_group), must not use path filters and must end in its gate.
GATED_WORKFLOWS = {
    "ci.yml": "CI gate",
    "surveys.yml": "Survey gate",
    "api-contract.yml": "API contract gate",
    "pins.yml": "Dependency pins gate",
}
# Required without a gate: a single always-running job.
UNGATED_REQUIRED = {"docs.yml": "Bilingual site artifact"}
# Scheduled re-pin of moved image tags (tools/pins/image_digests.py).
PIN_DRIFT = "pin-drift.yml"
# Scheduled workflows that open a pull request with GITHUB_TOKEN.
PR_BOTS = ("pin-drift.yml", "refit-timings.yml")
PIN_DRIFT_PERMISSIONS = {
    ("actions", "write"),
    ("contents", "write"),
    ("pull-requests", "write"),
}
# Scheduled runs on main have no pull request that shows their result; the
# watchdog keeps an issue open while one is red or overdue. docs.yml has its
# own publication watchdog.
NIGHTLY_WATCHDOG = "nightly-watchdog.yml"
OWN_WATCHDOG = {"docs.yml", "docs-watchdog.yml", NIGHTLY_WATCHDOG}
# Image digests (not action SHAs) in a workflow; GITHUB_TOKEN cannot rewrite it.
DIGEST_PIN = re.compile(r"[a-z0-9./-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}")

# The only commands tools/ci/retry-infra.sh may wrap; tests are never retried.
RETRYABLE = re.compile(
    r"tools/ci/retry-infra\.sh (?:\./leonaid bootstrap|sh tools/ci/bootstrap-prefetch\.sh"
    r" (?:toolchains|seed|browser|\"\$1\"|\"\$BOOTSTRAP_PROFILE\")"
    r"|docker pull \"\$[A-Z_]+\")"
)
# Small AWS-hosted runners start with about 14 GB free disk; every job that
# builds or loads LeonAid images must free about 18 GB first. Jobs using the
# build cache need it unless listed as light (one or two small images);
# the cold rehearsal and nightly recovery proofs build without the cache.
FREE_DISK_LIGHT = {("api-contract.yml", "contract"), ("pins.yml", "sbom")}
FREE_DISK_EXTRA = {
    ("ci.yml", "pilot-cold-rehearsal"),
    ("surveys.yml", "backup-recovery"),
}
# Composite-action steps whose failure is retried once by the next steps.
FIRST_ATTEMPTS = {
    ".github/actions/build-cache/action.yml": "bake",
    ".github/actions/test-fixture/action.yml": "restore",
}

# Static gates the "Lint and types" job must run (tools/ci/lint-types.sh);
# ./leonaid check alone never runs in CI.
STATIC_GATES = (
    "conflict_markers_test.py",
    "conflict_markers.py",
    "axe_helper_test.py",
    "axe_helper.py",
    "legacy_ui_test.py",
    "legacy_ui.py",
    "base_path_literals_test.py",
    "base_path_literals.py",
    "core_oneoff_user_test.py",
    "core_oneoff_user.py",
    "select_suites_test.py",
    "gate_test.py",
)

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
    for summary in REMOVED_SUMMARIES:
        if f"\n  {summary}:\n" in text:
            problems.append(
                f"Summary job {summary} duplicates the CI gate and costs a runner."
            )
    problems.extend(check_summary(text, "golden-journey", "golden-parts", "Golden"))
    shards = job_block(text, "integration-shards")
    if "bin: ${{ fromJSON(needs.select.outputs.integration) }}" not in shards:
        problems.append("Integration shards must come from the suite selector.")
    if "tools/ci/integration.sh $SHARDS" not in shards:
        problems.append("Integration bins must run every shard of the bin.")
    for shard in INTEGRATION_SHARDS:
        if shard not in select_suites.INTEGRATION_SHARDS:
            problems.append(f"Integration shard missing: {shard}")
    leaves = job_block(text, "e2e")
    if "bin: ${{ fromJSON(needs.select.outputs.e2e) }}" not in leaves:
        problems.append("E2E leaves must come from the suite selector.")
    if "tools/ci/e2e.sh $SHARDS" not in leaves:
        problems.append("E2E bins must run every leaf of the bin.")
    for shard in E2E_SHARDS:
        if shard not in select_suites.E2E_SHARDS:
            problems.append(f"E2E shard missing: {shard}")
    for job, key in (
        ("integration-shards", "integration"),
        ("e2e", "e2e"),
        ("emdash-cases", "emdash"),
        ("golden-parts", "golden"),
    ):
        block = job_block(text, job)
        found = re.search(r"(?m)^    if: (.*)$", block)
        condition = found.group(1) if found else ""
        if "select" not in needs_of(block) or not re.search(
            rf"needs\.select\.outputs\.{re.escape(key)} (?:!= '\[\]'|== 'true')",
            condition,
        ):
            problems.append(f"{job} must depend on the suite selector output {key}.")
        if "needs.select.result == 'success'" not in condition:
            problems.append(f"{job} must not run when the suite selector failed.")
    for job, kind in (
        ("integration-shards", "integration"),
        ("e2e", "e2e"),
        ("emdash-cases", "emdash"),
    ):
        block = job_block(text, job)
        timeout = re.search(r"(?m)^    timeout-minutes: (\d+)$", block)
        if (
            not timeout
            or int(timeout.group(1)) != select_suites.JOB_TIMEOUT_MINUTES[kind]
        ):
            problems.append(
                f"{job}: timeout-minutes must equal select_suites.JOB_TIMEOUT_MINUTES"
                f"[{kind!r}] (the selector's load warning uses it)."
            )
        step = re.search(r'(?m)^      LEONAID_CI_STEP_SECONDS: "(\d+)"$', block)
        if (
            not step
            or not timeout
            or int(step.group(1)) > int(timeout.group(1)) * 60 - 120
        ):
            problems.append(
                f"{job}: LEONAID_CI_STEP_SECONDS must stop the suite at least 2 "
                "minutes before timeout-minutes, so evidence is still uploaded."
            )
        name = re.search(r"(?m)^    name: (.*)$", block)
        if not name or "matrix.bin.id" not in name.group(1) or "title" in name.group(1):
            problems.append(
                f"{job}: the leg name must be stable (bin id/count), shards go to the summary."
            )
    for job in ("security", "build"):
        block = job_block(text, job)
        found = re.search(r"(?m)^    if: (.*)$", block)
        condition = found.group(1) if found else ""
        if (
            "select" not in needs_of(block)
            or "needs.select.result == 'success'" not in condition
            or "needs.select.outputs.heavy != 'false'" not in condition
        ):
            problems.append(
                f"{job} may be skipped only for a stacked PR (selector output heavy)."
            )
        if f"--selectable {job}=heavy" not in job_block(text, "gate"):
            problems.append(f"The gate must require {job} unless heavy is false.")
    build = job_block(text, "build")
    if (
        "write: ${{ github.ref == 'refs/heads/main' && github.event_name != "
        "'pull_request' && 'true' || 'false' }}"
        not in build
        or text.count("write: ") != build.count("write: ")
    ):
        problems.append(
            "ci.yml: only the Build job of runs on main may write the shared cache."
        )
    problems.extend(check_emdash(text))
    problems.extend(check_tiers(text, "ci.yml"))
    problems.extend(check_drafts(text, "ci.yml"))
    problems.extend(check_gate(text, "ci.yml"))
    problems.extend(check_rerun(text, "ci.yml"))
    problems.extend(check_retries(text, "ci.yml"))
    problems.extend(check_free_disk(text, "ci.yml"))
    problems.extend(check_nightly(text))
    return problems


def check_free_disk(text: str, name: str) -> list[str]:
    """Image jobs start freeing disk before preparing images, wait before use."""
    problems: list[str] = []
    for job in jobs_of(text):
        block = job_block(text, job)
        cache = block.find("uses: ./.github/actions/build-cache")
        if (name, job) in FREE_DISK_LIGHT:
            continue
        if cache < 0 and (name, job) not in FREE_DISK_EXTRA:
            continue
        start = block.find("run: sh tools/ci/free-runner-disk.sh start")
        finish = block.find("run: sh tools/ci/free-runner-disk.sh wait")
        prepared = max(cache, block.find("uses: ./.github/actions/test-fixture"))
        suites = [
            index
            for index in (
                block.find("tools/ci/run-job.sh"),
                block.find("./leonaid test-"),
            )
            if index >= 0
        ]
        if not (
            0 <= start
            and (cache < 0 or start < cache)
            and prepared < finish
            and (not suites or finish < min(suites))
        ):
            problems.append(
                f"{name}: job {job} must free runner disk: free-runner-disk.sh "
                "start before image preparation, wait before its suite."
            )
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
    binned = [group for bin_ in select_suites.EMDASH_BINS for group in bin_]
    for group in EMDASH_GROUPS:
        if group not in select_suites.EMDASH_GROUPS:
            problems.append(f"EmDash proof group missing: {group}")
        if binned.count(group) != 1:
            problems.append(f"EmDash proof group {group} must be in exactly one bin.")
    if "bin: ${{ fromJSON(needs.select.outputs.emdash) }}" not in cases:
        problems.append("EmDash proof groups must come from the suite selector.")
    if (
        "sh tools/ci/emdash.sh $EMDASH_GROUPS" not in cases
        or "tools/ci/run-job.sh" not in cases
    ):
        problems.append("EmDash proofs do not run through tools/ci/emdash.sh.")
    if "continue-on-error" in cases or re.search(
        r"(?i)retry", cases.replace("tools/ci/retry-infra.sh", "")
    ):
        problems.append("EmDash proofs must not retry or ignore failures.")
    return problems


DRAFT = "github.event.pull_request.draft != true"
EDIT = "(github.event.action != 'edited' || github.event.changes.base)"
DRAFT_TYPES = frozenset(
    {
        "opened",
        "reopened",
        "synchronize",
        "ready_for_review",
        "converted_to_draft",
        "edited",
    }
)
# Environment the gate step hands to tools/ci/gate.py for drafts, title
# edits and stacked results.
GATE_CONTEXT = (
    "DRAFT: ${{ github.event.pull_request.draft == true }}",
    "EVENT_ACTION: ${{ github.event.action }}",
    "BASE_CHANGED: ${{ toJSON(github.event.changes.base) != 'null' }}",
    "STACK_BASE: ${{ github.base_ref }}",
    "HEAD_SHA: ${{ github.event.pull_request.head.sha }}",
    "GATE_NAME: ",
)
EDIT_GROUP = (
    "${{ github.event.action == 'edited' && !github.event.changes.base "
    "&& format('-edit-{0}', github.run_id) || '' }}"
)


def pull_request_types(on: str) -> set[str]:
    """Activity types of the pull_request trigger, inline or block list."""
    found = re.search(r"\n  pull_request:\n((?:    .*\n|      .*\n)*)", on + "\n")
    if not found:
        return set()
    body = found.group(1)
    types = re.search(r"(?ms)^    types:(.*?)(?=^    [a-z_-]+:|\Z)", body)
    if not types:
        return set()
    text = re.sub(r"(?m)#.*$", "", types.group(1))
    return set(re.findall(r"[a-z_]+", text))


def check_drafts(text: str, name: str) -> list[str]:
    """Drafts and title edits run no suite; their gate decides fail-closed.

    Every job without a `needs` (and every always()/!cancelled() job that
    does not wait for a successful selector) must skip drafts and edits that
    did not change the base. The gate runs anyway: tools/ci/gate.py fails a
    draft, mirrors the commit's real gate result for a title edit and fails
    a stacked result that no longer targets its base. A base change runs
    the normal selection. A title edit has its own concurrency group, so it
    never cancels the commit's real run.
    """
    problems: list[str] = []
    on = triggers(text)
    if not DRAFT_TYPES <= pull_request_types(on):
        problems.append(
            f"{name}: pull_request must list ready_for_review, converted_to_draft "
            "and edited."
        )
    gated = name in GATED_WORKFLOWS
    if gated and EDIT_GROUP not in text[: text.find("\njobs:\n")]:
        problems.append(
            f"{name}: a title edit must not share the PR's concurrency group."
        )
    for job in jobs_of(text):
        block = job_block(text, job)
        if gated and job == "gate":
            if "permissions:" not in block or not all(
                item in block for item in GATE_CONTEXT
            ):
                problems.append(
                    f"{name}: the gate must hand the draft/edit/stack context to gate.py."
                )
            continue
        condition = re.search(r"(?m)^    if: (.*)$", block)
        needs = needs_of(block)
        always = condition is not None and (
            "always()" in condition.group(1) or "!cancelled()" in condition.group(1)
        )
        runs_on_pr = condition is None or not re.search(
            r"github\.event_name == 'schedule'|github\.event\.schedule == "
            r"|inputs\.(?:cold_run|artifact_probe) == true|needs: build",
            condition.group(1),
        )
        if not ((not needs or always) and runs_on_pr):
            continue
        if (
            needs
            and always
            and condition is not None
            and "needs.select.result == 'success'" in condition.group(1)
        ):
            continue
        if not gated and "if: github.event.pull_request.draft == true" in block:
            # A single required job (docs.yml) fails a draft at once and
            # simply rebuilds on an edit.
            continue
        if (
            condition is None
            or DRAFT not in condition.group(1)
            or (gated and EDIT not in condition.group(1))
        ):
            problems.append(
                f"{name}: job {job} must not run for a draft or a title edit."
            )
    return problems


def check_tiers(text: str, name: str) -> list[str]:
    problems: list[str] = []
    on = triggers(text)
    if "\n  pull_request:" not in on:
        problems.append(f"{name}: must run on pull_request.")
    # GitHub's merge queue is not available for a personal-account repository.
    if "\n  merge_group:" in on:
        problems.append(f"{name}: merge_group is dead here (no merge queue).")
    if "paths:" in on or "paths-ignore:" in on:
        problems.append(f"{name}: required CI must not use path filters.")
    if name in GATED_WORKFLOWS:
        select = job_block(text, "select")
        if "uses: ./.github/workflows/select-suites.yml" not in select:
            problems.append(f"{name}: the select job must use select-suites.yml.")
    return problems


def check_rerun(text: str, name: str) -> list[str]:
    """Every gated workflow refreshes failed mirror gates after a real gate."""
    block = job_block(text, RERUN_JOB)
    condition = re.search(r"(?m)^    if: (.*)$", block)
    if (
        not block
        or needs_of(block) != {"gate"}
        or not condition
        or "always()" not in condition.group(1)
        or "github.event_name == 'pull_request'" not in condition.group(1)
        or DRAFT not in condition.group(1)
        or EDIT not in condition.group(1)
        or "      actions: write\n" not in block
        or "python3 tools/ci/rerun_stale_gates.py" not in block
    ):
        return [
            f"{name}: job {RERUN_JOB} must re-run failed mirror gates after every "
            "real pull-request gate (needs gate, always(), not for drafts or "
            "title edits, actions: write)."
        ]
    return []


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


NIGHTLY_CRON = '"7 3 * * *"'
MAIN_CRON = '"37 */3 * * *"'


def check_nightly(text: str) -> list[str]:
    """Main is proven by scheduled complete runs, not by a run per push."""
    problems: list[str] = []
    on = triggers(text)
    if not re.search(r"\n  schedule:\n    - cron: ", on) or NIGHTLY_CRON not in on:
        problems.append("ci.yml: nightly complete run (schedule) missing.")
    if MAIN_CRON not in on:
        problems.append("ci.yml: the 3-hourly complete run on main is missing.")
    if re.search(r"(?m)^      - main$", on):
        problems.append(
            "ci.yml: no complete run per push to main; the schedule proves main."
        )
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


def check_static_gates(root: Path) -> list[str]:
    text = (root / "tools/ci/lint-types.sh").read_text(encoding="utf-8")
    return [
        f"tools/ci/lint-types.sh must run tools/ci/{gate}."
        for gate in STATIC_GATES
        if not re.search(rf"python /workspace/tools/ci/{re.escape(gate)}(\s|$)", text)
    ]


def check_pin_drift(root: Path) -> list[str]:
    """The re-pin PR must get every required check, and must be pushable.

    Pushes and PRs made with GITHUB_TOKEN start no workflows, so pin-drift.yml
    dispatches each required workflow on its branch. GITHUB_TOKEN also cannot
    change workflow files, so no workflow may carry a digest of its own.
    """
    workflows = root / ".github/workflows"
    problems: list[str] = []
    for bot in PR_BOTS:
        problems.extend(check_pr_bot(workflows, bot))
    for path in sorted(workflows.glob("*.y*ml")):
        if DIGEST_PIN.search(path.read_text(encoding="utf-8")):
            problems.append(
                f"{path.name}: read images from infra/locks/images.env; a digest "
                "in a workflow blocks the automatic re-pin."
            )
    return problems


def check_pr_bot(workflows: Path, bot: str) -> list[str]:
    """One GITHUB_TOKEN pull-request bot: exact permissions, dispatches."""
    text = (workflows / bot).read_text(encoding="utf-8")
    problems: list[str] = []
    permissions = re.search(r"(?m)^permissions:\n((?:  .*\n|#.*\n)+)", text)
    granted = (
        set(re.findall(r"(?m)^  ([a-z-]+): ([a-z]+)$", permissions.group(1)))
        if permissions
        else set()
    )
    if granted != PIN_DRIFT_PERMISSIONS:
        problems.append(
            f"{bot}: permissions must be exactly "
            + ", ".join(
                f"{scope}: {level}" for scope, level in sorted(PIN_DRIFT_PERMISSIONS)
            )
        )
    if "GH_TOKEN: ${{ github.token }}" not in text or "secrets." in text:
        problems.append(f"{bot}: must use GITHUB_TOKEN and no other secret.")
    dispatch = re.search(r"for workflow in ([^;\n]+); do\n\s+gh workflow run ", text)
    dispatched = set(dispatch.group(1).split()) if dispatch else set()
    required = set(GATED_WORKFLOWS) | set(UNGATED_REQUIRED)
    if dispatched != required:
        problems.append(
            f"{bot}: must dispatch exactly the required workflows "
            f"{', '.join(sorted(required))}; dispatches {', '.join(sorted(dispatched)) or 'none'}"
        )
    for name in sorted(required):
        if "\n  workflow_dispatch:" not in triggers(
            (workflows / name).read_text(encoding="utf-8")
        ):
            problems.append(f"{name}: needs workflow_dispatch for the re-pin PR.")
    return problems


def workflow_name(text: str) -> str:
    match = re.search(r"(?m)^name: (.+)$", text)
    return match.group(1).strip() if match else ""


def check_nightly_watchdog(root: Path) -> list[str]:
    """Every scheduled workflow must alert when its scheduled run fails."""
    workflows = root / ".github/workflows"
    path = workflows / NIGHTLY_WATCHDOG
    if not path.exists():
        return [f"{NIGHTLY_WATCHDOG}: scheduled failures must open an issue."]
    text = path.read_text(encoding="utf-8")
    problems: list[str] = []
    permissions = re.search(r"(?m)^permissions:\n((?:  .*\n|#.*\n)+)", text)
    granted = (
        set(re.findall(r"(?m)^  ([a-z-]+): ([a-z]+)$", permissions.group(1)))
        if permissions
        else set()
    )
    if granted != {("actions", "read"), ("issues", "write")}:
        problems.append(
            f"{NIGHTLY_WATCHDOG}: permissions must be exactly actions: read, issues: write"
        )
    if "GH_TOKEN: ${{ github.token }}" not in text or "secrets." in text:
        problems.append(
            f"{NIGHTLY_WATCHDOG}: must use GITHUB_TOKEN and no other secret."
        )
    if not re.search(r"\n  schedule:\n    - cron: ", triggers(text)):
        problems.append(
            f"{NIGHTLY_WATCHDOG}: must also run on a schedule (overdue runs)."
        )
    listened = re.search(r"(?ms)^    workflows:\s*\[([^\]]*)\]$", text)
    names = (
        {item.strip() for item in listened.group(1).split(",")} if listened else set()
    )
    watched = re.search(r'(?m)^      WATCHED: "([^"]*)"$', text)
    files = (
        {entry.split(":", 1)[0] for entry in watched.group(1).split()}
        if watched
        else set()
    )
    # A workflow with several schedules runs different checks per cron; a
    # green frequent run must not hide a red nightly one. Each such workflow
    # needs a run name for its nightly cron and a title-tracked entry.
    entries = watched.group(1).split() if watched else []
    for candidate in sorted(workflows.glob("*.yml")):
        candidate_text = candidate.read_text(encoding="utf-8")
        if candidate.name in OWN_WATCHDOG:
            continue
        crons = re.findall(r'(?m)^    - cron: "([^"]+)"$', triggers(candidate_text))
        if len(crons) < 2:
            continue
        run_name = re.search(r"(?m)^run-name: (.*)$", candidate_text)
        if not run_name or "nightly" not in run_name.group(1):
            problems.append(
                f"{candidate.name}: several schedules need a run-name marking the nightly run."
            )
        if f"{candidate.name}:30:nightly" not in entries:
            problems.append(
                f"{NIGHTLY_WATCHDOG}: must track {candidate.name}'s nightly run "
                f"({candidate.name}:30:nightly)."
            )
    for candidate in sorted(workflows.glob("*.yml")):
        if candidate.name in OWN_WATCHDOG:
            continue
        candidate_text = candidate.read_text(encoding="utf-8")
        if not re.search(r"\n  schedule:\n    - cron: ", triggers(candidate_text)):
            continue
        if candidate.name not in files:
            problems.append(
                f"{NIGHTLY_WATCHDOG}: scheduled workflow {candidate.name} is not watched."
            )
        if workflow_name(candidate_text) not in names:
            problems.append(
                f"{NIGHTLY_WATCHDOG}: does not react to completed runs of {candidate.name}."
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
        problems.extend(check_drafts(text, name))
        problems.extend(check_gate(text, name))
        problems.extend(check_rerun(text, name))
        problems.extend(check_retries(text, name))
        problems.extend(check_free_disk(text, name))
    for name, job in UNGATED_REQUIRED.items():
        text = (workflows / name).read_text(encoding="utf-8")
        problems.extend(check_tiers(text, name))
        problems.extend(check_drafts(text, name))
        problems.extend(check_retries(text, name))
        if f"name: {job}\n" not in text:
            problems.append(f"{name}: required job '{job}' missing.")
    select = (workflows / "select-suites.yml").read_text(encoding="utf-8")
    # The title-edit mirror (gate.py real_run) recognizes real runs by this
    # job name; a rename would make every mirror fail (closed, but red).
    if f"\n    name: {gate_script.SELECT_JOB_NAME}\n" not in select:
        problems.append(
            f"select-suites.yml: the select job must be named "
            f"{gate_script.SELECT_JOB_NAME!r} (tools/ci/gate.py SELECT_JOB_NAME)."
        )
    if "tools/ci/select_suites.py --event" not in select:
        problems.append("select-suites.yml must run tools/ci/select_suites.py.")
    problems.extend(check_first_attempts(root))
    problems.extend(check_static_gates(root))
    problems.extend(check_pin_drift(root))
    problems.extend(check_nightly_watchdog(root))
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
        "ci-workflow-contract: OK: tiers, schedules, drafts, gates, selector, infra-only "
        "retries, shards, cold rehearsal and failure artifacts"
    )


if __name__ == "__main__":
    main()
