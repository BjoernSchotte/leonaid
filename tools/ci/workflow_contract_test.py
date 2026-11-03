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
        "run: sh tools/ci/free-runner-disk.sh wait",
        "run: true",
        "free runner disk",
    ),
    (
        "run: sh tools/ci/free-runner-disk.sh start",
        "run: true",
        "free runner disk",
    ),
    (
        "actions/upload-artifact@",
        "actions/removed-artifact@",
        "evidence artifacts",
    ),
    (
        "        shard: ${{ fromJSON(needs.select.outputs.e2e) }}\n",
        "        shard: [tasks]\n",
        "E2E leaves must come from the suite selector",
    ),
    (
        "        shard: ${{ fromJSON(needs.select.outputs.integration) }}\n",
        "        shard: [delivery]\n",
        "Integration shards must come from the suite selector",
    ),
    (
        "needs: [select, integration-shards]\n    if: ${{ !cancelled()",
        "needs: [select, integration-shards]\n    if: ${{ always()",
        "integration summary check",
    ),
    (
        "needs: [select, integration-shards]",
        "needs: [select, unit]",
        "integration summary check",
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
        "        group: ${{ fromJSON(needs.select.outputs.emdash) }}\n",
        "        group: [static]\n",
        "EmDash proof groups must come from the suite selector",
    ),
    (
        "    name: EmDash proof / ${{ matrix.group }}\n",
        "    name: EmDash proof / ${{ matrix.group }}\n    continue-on-error: true\n",
        "retry or ignore",
    ),
    (
        "  pull_request:\n",
        "  pull_request:\n    paths: [apps/campaign-site/**]\n",
        "path filters",
    ),
    (
        "  merge_group:\n",
        "",
        "must run on merge_group",
    ),
    (
        "needs: [select, emdash-cases]\n    if: ${{ !cancelled()",
        "needs: [select, emdash-cases]\n    if: ${{ always()",
        "EmDash summary check",
    ),
    (
        "needs.emdash-cases.result",
        "needs.emdash-cases.outputs.result",
        "EmDash summary check",
    ),
    (
        "needs.select.outputs.contract == 'true'",
        "true",
        "contract must depend on the suite selector",
    ),
    (
        "&& needs.select.result == 'success' && needs.select.outputs.golden",
        "&& needs.select.outputs.golden",
        "golden-parts must not run when the suite selector failed",
    ),
    (
        "      - golden-journey\n    if: ${{ always()",
        "    if: ${{ always()",
        "gate does not require: golden-journey",
    ),
    (
        "    if: ${{ always() && github.ref != 'refs/heads/ci-artifact-probe'",
        "    if: ${{ success() && github.ref != 'refs/heads/ci-artifact-probe'",
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
    ("surveys.yml", "  merge_group:\n", "", "must run on merge_group"),
    (
        "surveys.yml",
        "acceptance, backup-recovery]",
        "backup-recovery]",
        "gate does not require: acceptance",
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
    ("docs.yml", "  merge_group:\n", "", "must run on merge_group"),
)

ACTION_MUTATIONS = (
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
        "ci-workflow-contract-test: OK: tiers, merge queue, gates, selector, retries, "
        "shards, cold rehearsal and missing upload are checked"
    )


if __name__ == "__main__":
    main()
