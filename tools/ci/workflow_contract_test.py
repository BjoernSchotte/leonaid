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
        "      - surveys\n      - backup-recovery\n",
        "      - backup-recovery\n",
        "the gate does not require: surveys",
    ),
    (
        "    name: Survey gate\n    needs: gate\n",
        "    name: Survey gate\n    needs: select\n",
        "the required 'Survey gate' must mirror the CI gate",
    ),
    (
        "github.ref == 'refs/heads/main' && github.event_name != 'pull_request' && 'true' || 'false'",
        "github.event_name != 'pull_request' && 'true' || 'false'",
        "only the Build job of runs on main may write the shared cache",
    ),
    (
        "  select:\n    if: github.event.pull_request.draft != true\n",
        "  select:\n    if: true\n",
        "ci.yml: job select must not run for a draft",
    ),
    (
        "    types: [opened, reopened, synchronize, ready_for_review]\n",
        "    types: [opened, reopened, synchronize, ready_for_review, edited]\n",
        "ci.yml: pull_request must list exactly opened",
    ),
    (
        "          DRAFT: ${{ github.event.pull_request.draft == true }}\n          # A stacked result never passes (tools/ci/gate.py stacked).\n          BASE_REF: ${{ github.base_ref }}\n          PR_NUMBER: ${{ github.event.pull_request.number }}\n          GATE_NAME: CI gate\n",
        "          PR_NUMBER: ${{ github.event.pull_request.number }}\n          GATE_NAME: CI gate\n",
        "ci.yml: the gate must hand the draft context",
    ),
    (
        "    with:\n      post-merge: true\n",
        "",
        "ci.yml: the selector must diff a push since the last green run",
    ),
    (
        '          FULL_CI_GATE: "true"\n',
        "",
        "ci.yml: the gate must hand the draft context",
    ),
    (
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n",
        "  cancel-in-progress: ${{ github.event_name == 'pull_request' || github.event_name == 'push' }}\n",
        "ci.yml: only pull-request runs may be cancelled",
    ),
    (
        '      LEONAID_CI_STEP_SECONDS: "5100"\n',
        '      LEONAID_CI_STEP_SECONDS: "5400"\n',
        "e2e: LEONAID_CI_STEP_SECONDS must stop the suite",
    ),
    (
        '    - cron: "7 3 * * *"\n',
        '    - cron: "7 3 * * *"\n    - cron: "37 */3 * * *"\n',
        "the nightly run is the only schedule",
    ),
    (
        "  lint:\n",
        "  lint:\n    if: true\n  lint-copy:\n",
        "ci.yml: job lint must not run for a draft",
    ),
    (
        "  unit:\n",
        "  unit-removed:\n",
        "Job missing: unit",
    ),
    (
        "  vulnerability:\n",
        "  vulnerability-removed:\n",
        "Job missing: vulnerability",
    ),
    (
        "    needs: [select, lint, integration-shards]\n",
        "    needs: [select, integration-shards]\n",
        "API contract gate",
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
        "      - name: Run policies, secret scan and the security stack test\n",
        "      - name: Run policies, secret scan and the security stack test\n",
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
        "./leonaid test-integration $SHARDS",
        "./leonaid test-integration core",
        "Integration bins must run every shard of the bin",
    ),
    (
        "./leonaid test-e2e $SHARDS",
        "./leonaid test-e2e tasks",
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
        "        bin: ${{ fromJSON(needs.select.outputs.emdash) }}\n",
        "        bin: [{id: '1', shards: static}]\n",
        "EmDash proof groups must come from the suite selector",
    ),
    (
        "./leonaid test-emdash $EMDASH_GROUPS",
        "./leonaid test-emdash static",
        "EmDash proofs do not run through ./leonaid test-emdash",
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
        "      - golden-journey\n      - surveys\n",
        "      - surveys\n",
        "gate does not require: golden-journey",
    ),
    (
        "    if: ${{ always()",
        "    if: ${{ success()",
        "the gate must run after failures",
    ),
    (
        "    name: CI gate\n",
        "    name: Everything\n",
        "aggregate gate 'CI gate' missing",
    ),
    (
        "bash tools/ci/run-job.sh unit sh tools/ci/unit.sh",
        "sh tools/ci/retry-infra.sh bash tools/ci/run-job.sh unit sh tools/ci/unit.sh",
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
        "    uses: ./.github/workflows/select-suites.yml\n",
        "    uses: ./.github/workflows/test-fixture.yml\n",
        "select job must use select-suites.yml",
    ),
)

OTHER_MUTATIONS = (
    (
        "pins.yml",
        "          BASE_REF: ${{ github.base_ref }}\n",
        "",
        "pins.yml: the gate must hand the draft context to gate.py",
    ),
    (
        "select-suites.yml",
        "  actions: read\n",
        "",
        "select-suites.yml: top-level permissions need actions: read",
    ),
    (
        "test-fixture.yml",
        "  actions: read\n",
        "",
        "test-fixture.yml: top-level permissions need actions: read",
    ),
    (
        "nightly-watchdog.yml",
        " ci.yml:30:nightly",
        "",
        "scheduled workflow ci.yml is not watched",
    ),
    (
        "nightly-watchdog.yml",
        "ci.yml:push ",
        "",
        "must report a red post-merge run of ci.yml",
    ),
    (
        "nightly-watchdog.yml",
        " || github.event.workflow_run.event == 'push'",
        "",
        "must react to completed post-merge runs",
    ),
    (
        "docs.yml",
        "        if: github.event.pull_request.draft == true\n",
        "        if: false\n",
        "docs.yml: job build must not run for a draft",
    ),
    (
        "pins.yml",
        "          DRAFT: ${{ github.event.pull_request.draft == true }}\n",
        "",
        "pins.yml: the gate must hand the draft context to gate.py",
    ),
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
        "for workflow in ci.yml pins.yml docs.yml; do",
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
        "tools/ci/lint-types.sh",
        "  python /workspace/tools/ci/base_path_literals.py /workspace\n",
        "  true\n",
        "lint-types.sh must run tools/ci/base_path_literals.py",
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
        "shards and missing upload are checked"
    )


if __name__ == "__main__":
    main()
