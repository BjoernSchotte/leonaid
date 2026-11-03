#!/usr/bin/env python3
"""Prove the aggregate gate, the flake tally and the infra-retry allowlist."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.ci import flake_summary  # noqa: E402
from tools.ci import gate  # noqa: E402

FAILURES: list[str] = []


def expect(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def needs(select: str = "success", **jobs: str) -> dict[str, dict[str, object]]:
    data: dict[str, dict[str, object]] = {
        "select": {
            "result": select,
            "outputs": {"e2e": '["tasks"]', "contract": "false", "emdash": "[]"},
        }
    }
    for job, result in jobs.items():
        data[job.replace("_", "-")] = {"result": result, "outputs": {}}
    return data


SELECTABLE = {"e2e": "e2e", "contract": "contract", "emdash-cases": "emdash"}


def passes(data: dict[str, dict[str, object]], may_skip: tuple[str, ...] = ()) -> bool:
    return all(ok for *_, ok in gate.evaluate(data, SELECTABLE, may_skip))


def test_gate() -> None:
    good = needs(
        e2e="success", contract="skipped", emdash_cases="skipped", unit="success"
    )
    expect(passes(good), "selected success plus unselected skip must pass")
    expect(
        not passes(
            needs("failure", e2e="success", contract="skipped", emdash_cases="skipped")
        ),
        "a failed selector must fail the gate",
    )
    expect(
        not passes(needs(e2e="skipped", contract="skipped", emdash_cases="skipped")),
        "a skipped selected job (upstream failure) must fail the gate",
    )
    expect(
        not passes(needs(e2e="success", contract="failure", emdash_cases="skipped")),
        "a failed unselected job must fail the gate",
    )
    expect(
        not passes(needs(e2e="success", contract="skipped", emdash_cases="cancelled")),
        "a cancelled job must fail the gate",
    )
    expect(
        not passes(
            needs(
                e2e="success",
                contract="skipped",
                emdash_cases="skipped",
                unit="skipped",
            )
        ),
        "an always-required job must not be skipped",
    )
    expect(
        passes(
            needs(
                e2e="success",
                contract="skipped",
                emdash_cases="skipped",
                fixture="skipped",
            ),
            may_skip=("fixture",),
        ),
        "--may-skip allows a skip",
    )
    expect(
        not passes(
            needs(
                e2e="success",
                contract="skipped",
                emdash_cases="skipped",
                fixture="failure",
            ),
            may_skip=("fixture",),
        ),
        "--may-skip never allows a failure",
    )
    missing = needs(e2e="success", contract="skipped", emdash_cases="skipped")
    missing["select"]["outputs"] = {}
    expect(not passes(missing), "missing selector outputs must fail closed")
    incomplete = needs(e2e="success", contract="skipped")
    expect(not passes(incomplete), "a selectable job missing from needs must fail")
    expect(
        not passes({"unit": {"result": "success"}}), "a gate without select must fail"
    )
    env = dict(os.environ, NEEDS=json.dumps(good))
    env.pop("GITHUB_STEP_SUMMARY", None)
    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "gate.py"),
            "--name",
            "Test gate",
            "--selectable",
            "e2e=e2e",
            "--selectable",
            "contract=contract",
            "--selectable",
            "emdash-cases=emdash",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    expect(result.returncode == 0, f"gate CLI rejected a good run: {result.stderr}")
    env["NEEDS"] = json.dumps(
        needs(e2e="failure", contract="skipped", emdash_cases="skipped")
    )
    result = subprocess.run(
        [
            sys.executable,
            str(HERE / "gate.py"),
            "--name",
            "Test gate",
            "--selectable",
            "e2e=e2e",
            "--selectable",
            "contract=contract",
            "--selectable",
            "emdash-cases=emdash",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    expect(
        result.returncode == 1 and "e2e" in result.stderr, "gate CLI accepted a failure"
    )


def job(name: str, conclusion: str) -> dict[str, object]:
    return {
        "name": name,
        "conclusion": conclusion,
        "html_url": f"https://x/{name}/{conclusion}",
    }


def test_flake_tally() -> None:
    runs = [
        # Rerun: Security failed in attempt 1, passed in attempt 2.
        [
            [job("Security", "failure"), job("Unit", "success")],
            [job("Security", "success"), job("Unit", "success")],
        ],
        # Plain failure, superseded cancellation and a skipped job.
        [
            [
                job("Security", "success"),
                job("Unit", "failure"),
                job("Build", "cancelled"),
                job("Golden", "skipped"),
            ]
        ],
    ]
    stats, total, reruns = flake_summary.tally(runs)
    expect(total == 2 and reruns == 1, f"run counts: {total}, {reruns}")
    expect(
        stats["Security"].runs == 2
        and stats["Security"].rerun_failures == 1
        and stats["Security"].final_failures == 0,
        f"Security: {stats['Security']}",
    )
    expect(
        stats["Unit"].final_failures == 1 and stats["Unit"].runs == 2,
        f"Unit: {stats['Unit']}",
    )
    expect(
        "Build" not in stats and "Golden" not in stats,
        "cancelled/skipped jobs are not counted",
    )
    text = flake_summary.render("ci.yml", stats, total, reruns)
    expect(text.index("Security") < text.index("Unit"), "reruns are listed first")
    quiet = flake_summary.render("ci.yml", {}, 3, 0)
    expect("No failed or rerun jobs." in quiet, "quiet summary")


def test_retry_allowlist() -> None:
    script = HERE / "retry-infra.sh"
    for command in (
        ["./leonaid", "test-unit"],
        ["bash", "tools/ci/integration.sh", "core"],
        ["sh", "tools/ci/emdash.sh", "static"],
        ["docker", "pull", "x;", "./leonaid", "test-unit"],
        ["docker", "run", "image"],
    ):
        result = subprocess.run(
            ["sh", str(script), *command], capture_output=True, text=True, check=False
        )
        expect(
            result.returncode == 64,
            f"retry-infra.sh accepted {command}: {result.stderr}",
        )
    # A PATH without docker makes the allowlisted pull fail every time.
    with tempfile.TemporaryDirectory() as directory:
        sleep = shutil.which("sleep")
        assert sleep is not None
        os.symlink(sleep, Path(directory) / "sleep")
        env = dict(
            os.environ,
            LEONAID_INFRA_ATTEMPTS="2",
            LEONAID_INFRA_DELAY="0",
            PATH=directory,
        )
        result = subprocess.run(
            ["/bin/sh", str(script), "docker", "pull", "example.invalid/none:1"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    expect(
        result.returncode != 0 and "failed 2 times" in result.stderr,
        f"retry-infra.sh must retry and then fail: {result.stderr}",
    )


def main() -> int:
    test_gate()
    test_flake_tally()
    test_retry_allowlist()
    if FAILURES:
        for failure in FAILURES:
            print(f"ci-gate-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print("ci-gate-test: OK: gate fails closed, flake tally, retry allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
