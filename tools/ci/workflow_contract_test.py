#!/usr/bin/env python3
"""Prove that the workflow contract rejects every broken invariant."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.ci import workflow_contract as contract  # noqa: E402

CI_MUTATIONS = (
    (
        '      LEONAID_CI_STEP_SECONDS: "5100"\n',
        '      LEONAID_CI_STEP_SECONDS: "5400"\n',
        "e2e: LEONAID_CI_STEP_SECONDS must stop the suite",
    ),
    (
        '    - cron: "37 */3 * * *"\n',
        "",
        "the 3-hourly complete run on main is missing",
    ),
    (
        "      - ci-artifact-probe\n",
        "      - ci-artifact-probe\n      - main\n",
        "no complete run per push to main",
    ),
    (
        "    types: [opened, reopened, synchronize, ready_for_review, converted_to_draft]\n",
        "",
        "ci.yml: pull_request must list ready_for_review and converted_to_draft",
    ),
    (
        "  lint-unit:\n",
        "  lint-unit:\n    if: true\n  lint-unit-copy:\n",
        "ci.yml: job lint-unit must not run for a draft",
    ),
    (
        "needs.select.outputs.heavy != 'false' && (needs.fixture.result",
        "(needs.fixture.result",
        "security may be skipped only for a stacked PR",
    ),
    (
        "            --selectable build=heavy",
        "            --may-skip build",
        "The gate must require build unless heavy is false",
    ),
    (
        "    name: E2E ${{ matrix.bin.id }}/${{ matrix.bin.count }}\n",
        "    name: E2E / ${{ matrix.bin.title }}\n",
        "e2e: the leg name must be stable",
    ),
    (
        "    name: E2E ${{ matrix.bin.id }}/${{ matrix.bin.count }}\n    runs-on: ubuntu-24.04\n    timeout-minutes: 90\n",
        "    name: E2E ${{ matrix.bin.id }}/${{ matrix.bin.count }}\n    runs-on: ubuntu-24.04\n    timeout-minutes: 30\n",
        "e2e: timeout-minutes must equal",
    ),
    (
        "run: sh tools/ci/free-runner-disk.sh wait",
        "run: true",
        "job integration-shards must free runner disk",
    ),
    (
        "run: sh tools/ci/free-runner-disk.sh start",
        "run: true",
        "job integration-shards must free runner disk",
    ),
    (
        "      - name: Finish freeing runner disk\n"
        "        run: sh tools/ci/free-runner-disk.sh wait\n"
        "      - name: Report runner disk after preparation\n",
        "      - name: Report runner disk after preparation\n",
        "job security must free runner disk",
    ),
    (
        "actions/upload-artifact@",
        "actions/removed-artifact@",
        "evidence artifacts",
    ),
    (
        "        bin: ${{ fromJSON(needs.select.outputs.e2e) }}\n",
        "        bin: [{id: '1', shards: tasks}]\n",
        "E2E leaves must come from the suite selector",
    ),
    (
        "        bin: ${{ fromJSON(needs.select.outputs.integration) }}\n",
        "        bin: [{id: '1', shards: delivery}]\n",
        "Integration shards must come from the suite selector",
    ),
    (
        "tools/ci/integration.sh $SHARDS",
        "tools/ci/integration.sh core",
        "Integration bins must run every shard of the bin",
    ),
    (
        "tools/ci/e2e.sh $SHARDS",
        "tools/ci/e2e.sh tasks",
        "E2E bins must run every leaf of the bin",
    ),
    (
        "  security:\n",
        "  e2e-summary:\n    needs: [select, e2e]\n    runs-on: ubuntu-24.04\n\n  security:\n",
        "Summary job e2e-summary duplicates the CI gate",
    ),
    (
        "needs: [select, golden-parts]\n    if: ${{ !cancelled()",
        "needs: [select, golden-parts]\n    if: ${{ always()",
        "Golden summary check",
    ),
    (
        'then test "$RESULT" = success; else test "$RESULT" = skipped; fi\n',
        'then test "$RESULT" != failure; else true; fi\n',
        "summary check",
    ),
    (
        'test "$SELECT" = success\n',
        "true\n",
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
        "        bin: ${{ fromJSON(needs.select.outputs.emdash) }}\n",
        "        bin: [{id: '1', shards: static}]\n",
        "EmDash proof groups must come from the suite selector",
    ),
    (
        "sh tools/ci/emdash.sh $EMDASH_GROUPS",
        "sh tools/ci/emdash.sh static",
        "EmDash proofs do not run through tools/ci/emdash.sh",
    ),
    (
        "    name: EmDash proof ${{ matrix.bin.id }}/${{ matrix.bin.count }}\n",
        "    name: EmDash proof ${{ matrix.bin.id }}/${{ matrix.bin.count }}\n    continue-on-error: true\n",
        "retry or ignore",
    ),
    (
        "  pull_request:\n",
        "  pull_request:\n    paths: [apps/campaign-site/**]\n",
        "path filters",
    ),
    (
        "  pull_request:\n",
        "  merge_group:\n  pull_request:\n",
        "merge_group is dead here",
    ),
    (
        "needs.select.outputs.emdash != '[]'",
        "true",
        "emdash-cases must depend on the suite selector output emdash",
    ),
    (
        "&& needs.select.result == 'success' && needs.select.outputs.golden",
        "&& needs.select.outputs.golden",
        "golden-parts must not run when the suite selector failed",
    ),
    (
        "      - golden-journey\n    # Skipped",
        "    # Skipped",
        "gate does not require: golden-journey",
    ),
    (
        "    if: ${{ always() && github.event.pull_request.draft != true && github.ref",
        "    if: ${{ success() && github.event.pull_request.draft != true && github.ref",
        "the gate must run after failures",
    ),
    (
        "    name: CI gate\n",
        "    name: Everything\n",
        "aggregate gate 'CI gate' missing",
    ),
    (
        "bash tools/ci/run-job.sh unit ./leonaid test-unit",
        "sh tools/ci/retry-infra.sh bash tools/ci/run-job.sh unit ./leonaid test-unit",
        "only infrastructure commands may be retried",
    ),
    (
        "        run: bash tools/ci/run-job.sh build bash tools/ci/build.sh\n",
        "        run: bash tools/ci/run-job.sh build bash tools/ci/build.sh\n"
        "        continue-on-error: true\n",
        "continue-on-error hides failures",
    ),
    (
        '    - cron: "7 3 * * *"\n',
        "",
        "nightly complete run",
    ),
    (
        "tools/ci/flake_summary.py",
        "tools/ci/removed.py",
        "nightly flake summary",
    ),
    (
        "    uses: ./.github/workflows/select-suites.yml\n",
        "    uses: ./.github/workflows/test-fixture.yml\n",
        "select job must use select-suites.yml",
    ),
)

OTHER_MUTATIONS = (
    (
        "nightly-watchdog.yml",
        " ci.yml:30:nightly",
        "",
        "must track ci.yml's nightly run",
    ),
    (
        "docs.yml",
        "    if: github.event.pull_request.draft != true\n    name: Bilingual site artifact\n",
        "    name: Bilingual site artifact\n",
        "docs.yml: job build must not run for a draft",
    ),
    (
        "pins.yml",
        "    if: ${{ always() && github.event.pull_request.draft != true }}\n",
        "    if: ${{ always() }}\n",
        "pins.yml: job gate must not run for a draft",
    ),
    (
        "surveys.yml",
        "run: sh tools/ci/free-runner-disk.sh wait",
        "run: true",
        "job surveys must free runner disk",
    ),
    (
        "surveys.yml",
        "      - name: Finish freeing runner disk\n"
        "        run: sh tools/ci/free-runner-disk.sh wait\n"
        "      - name: Run isolated backup and recovery proof\n",
        "      - name: Run isolated backup and recovery proof\n",
        "job backup-recovery must free runner disk",
    ),
    ("surveys.yml", "  pull_request:\n", "  push:\n", "must run on pull_request"),
    (
        "surveys.yml",
        "inventory, surveys, backup-recovery]",
        "inventory, backup-recovery]",
        "gate does not require: surveys",
    ),
    (
        "api-contract.yml",
        "  pull_request:\n",
        "  pull_request:\n    paths: [src/**]\n",
        "path filters",
    ),
    ("api-contract.yml", "python3 tools/ci/gate.py", "true", "tools/ci/gate.py"),
    (
        "pins.yml",
        "    needs: [select, policy, reproducibility, sbom]",
        "    needs: [select, policy]",
        "gate does not require",
    ),
    (
        "pins.yml",
        'sh tools/ci/retry-infra.sh docker pull "$PYTHON_IMAGE"',
        "sh tools/ci/retry-infra.sh /bin/sh tools/pins/reproduce.sh",
        "only infrastructure commands may be retried",
    ),
    (
        "docs.yml",
        "  pull_request:\n",
        "  merge_group:\n  pull_request:\n",
        "merge_group is dead here",
    ),
    (
        "pin-drift.yml",
        "for workflow in ci.yml surveys.yml api-contract.yml pins.yml docs.yml; do",
        "for workflow in ci.yml pins.yml; do",
        "must dispatch exactly the required workflows",
    ),
    (
        "pin-drift.yml",
        "  actions: write\n",
        "  actions: write\n  packages: write\n",
        "permissions must be exactly",
    ),
    (
        "pin-drift.yml",
        "GH_TOKEN: ${{ github.token }}",
        "GH_TOKEN: ${{ secrets.REPIN_TOKEN }}",
        "must use GITHUB_TOKEN",
    ),
    (
        "surveys.yml",
        "  workflow_dispatch:\n",
        "",
        "surveys.yml: needs workflow_dispatch for the re-pin PR",
    ),
    (
        "api-contract.yml",
        '          "$UV_IMAGE"\n',
        "          ghcr.io/astral-sh/uv:0.13.6-python3.13-trixie-slim@sha256:"
        + "e" * 64
        + "\n",
        "a digest in a workflow blocks the automatic re-pin",
    ),
    (
        "nightly-watchdog.yml",
        'WATCHED: "ci.yml:8 ci.yml:30:nightly surveys.yml:8',
        'WATCHED: "ci.yml:8 ci.yml:30:nightly',
        "scheduled workflow surveys.yml is not watched",
    ),
    (
        "nightly-watchdog.yml",
        "[LeonAid CI, Survey acceptance,",
        "[LeonAid CI,",
        "does not react to completed runs of surveys.yml",
    ),
    (
        "nightly-watchdog.yml",
        "  issues: write\n",
        "  issues: write\n  contents: write\n",
        "permissions must be exactly actions: read, issues: write",
    ),
    (
        "nightly-watchdog.yml",
        "GH_TOKEN: ${{ github.token }}",
        "GH_TOKEN: ${{ secrets.ALERT_TOKEN }}",
        "nightly-watchdog.yml: must use GITHUB_TOKEN",
    ),
)

ACTION_MUTATIONS = (
    (
        "tools/ci/lint-types.sh",
        "  python /workspace/tools/ci/axe_helper.py /workspace\n",
        "  true\n",
        "lint-types.sh must run tools/ci/axe_helper.py",
    ),
    (
        "tools/ci/lint-types.sh",
        "  python /workspace/tools/ci/legacy_ui.py /workspace\n",
        "  true\n",
        "lint-types.sh must run tools/ci/legacy_ui.py",
    ),
    (
        ".github/actions/build-cache/action.yml",
        "    - name: Retry layer import and image build\n      if: steps.bake.outcome == 'failure'\n",
        "    - name: Retry layer import and image build\n      if: false\n",
        "must be retried once",
    ),
    (
        ".github/actions/test-fixture/action.yml",
        "    - name: Validate fixture",
        "    - name: Validate fixture\n      continue-on-error: true\n      shell: bash\n      run: true\n    - name: Validate fixture again",
        "may continue on error",
    ),
)


def rejected(problems: list[str], expected: str) -> bool:
    return any(expected in problem for problem in problems)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parents[1]).resolve()
    result = subprocess.run(
        [sys.executable, str(HERE / "workflow_contract.py"), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"The current workflows violate the contract:\n{result.stderr}"
        )
    workflows = root / ".github/workflows"
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as temporary:
        copy = Path(temporary)
        shutil.copytree(root / ".github", copy / ".github")
        (copy / "tools/ci").mkdir(parents=True)
        shutil.copy(root / "tools/ci/lint-types.sh", copy / "tools/ci/lint-types.sh")
        ci = copy / ".github/workflows/ci.yml"
        text = (workflows / "ci.yml").read_text(encoding="utf-8")
        for old, new, expected in CI_MUTATIONS:
            if old not in text:
                failures.append(f"mutation anchor vanished: {old.strip()[:60]!r}")
                continue
            ci.write_text(text.replace(old, new, 1), encoding="utf-8")
            if not rejected(contract.check_repository(copy), expected):
                failures.append(f"ci.yml violation {expected!r} was not rejected")
        ci.write_text(text, encoding="utf-8")
        for name, old, new, expected in OTHER_MUTATIONS:
            target = copy / ".github/workflows" / name
            original = (workflows / name).read_text(encoding="utf-8")
            if old not in original:
                failures.append(
                    f"{name}: mutation anchor vanished: {old.strip()[:60]!r}"
                )
                continue
            target.write_text(original.replace(old, new, 1), encoding="utf-8")
            if not rejected(contract.check_repository(copy), expected):
                failures.append(f"{name} violation {expected!r} was not rejected")
            target.write_text(original, encoding="utf-8")
        for relative, old, new, expected in ACTION_MUTATIONS:
            target = copy / relative
            original = (root / relative).read_text(encoding="utf-8")
            if old not in original:
                failures.append(
                    f"{relative}: mutation anchor vanished: {old.strip()[:60]!r}"
                )
                continue
            target.write_text(original.replace(old, new, 1), encoding="utf-8")
            if not rejected(contract.check_repository(copy), expected):
                failures.append(f"{relative} violation {expected!r} was not rejected")
            target.write_text(original, encoding="utf-8")
    if failures:
        for failure in failures:
            print(f"ci-workflow-contract-test: ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)
    print(
        "ci-workflow-contract-test: OK: tiers, schedules, drafts, gates, selector, retries, "
        "shards, cold rehearsal and missing upload are checked"
    )


if __name__ == "__main__":
    main()
