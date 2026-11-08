#!/usr/bin/env python3
"""Prove the aggregate gate and the infra-retry allowlist."""

from __future__ import annotations

import json
import urllib.error
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.ci import gate  # noqa: E402
from tools.ci import select_suites  # noqa: E402

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


def test_pull_request() -> None:
    base_env = {"EVENT_NAME": "pull_request", "GITHUB_REPOSITORY": "o/r"}

    def never(path: str) -> object:
        raise AssertionError(f"unexpected API call {path}")

    # A draft fails the gate: no CI ran.
    good = json.dumps(needs(e2e="success", contract="skipped", emdash_cases="skipped"))
    for draft, code in (("true", 1), ("false", 0)):
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
            env={**os.environ, **base_env, "DRAFT": draft, "NEEDS": good},
            capture_output=True,
            text=True,
            check=False,
        )
        expect(
            result.returncode == code,
            f"draft={draft}: gate exit {result.returncode}: {result.stderr}",
        )
    expect(
        gate.FULL_CI_LABEL == select_suites.FULL_CI_LABEL,
        "gate.py and select_suites.py agree on the full-ci label",
    )
    # N1: re-running an old fast run after full-ci was added keeps its old
    # labels; the gate reads them live, so only the complete run counts.
    full_env = {
        **base_env,
        "FULL_CI_GATE": "true",
        "PR_NUMBER": "7",
        "EVENT_ACTION": "synchronize",
    }

    def labels(*names: str) -> gate.Fetch:
        def fetch(path: str) -> object:
            assert path.endswith("/pulls/7"), path
            return {"labels": [{"name": name} for name in names]}

        return fetch

    def broken(path: str) -> object:
        raise urllib.error.URLError("down")

    for env, outputs, fetch, pending, what in (
        (full_env, {"tier": "fast"}, labels("full-ci"), True, "fast run, label set"),
        (full_env, {}, labels("x", "full-ci"), True, "no tier output, label set"),
        (full_env, {"tier": "fast"}, labels("x"), False, "fast run, no label"),
        (full_env, {"tier": "full"}, labels("full-ci"), False, "the complete run"),
        (full_env, {"tier": "fast"}, broken, True, "unreadable PR fails closed"),
        (full_env, {"tier": "fast"}, lambda path: {}, True, "no labels field"),
        (
            {**full_env, "FULL_CI_GATE": ""},
            {"tier": "fast"},
            never,
            False,
            "workflows without a full tier (API contract, pins)",
        ),
        (
            {**full_env, "EVENT_NAME": "push"},
            {"tier": "post-merge"},
            never,
            False,
            "post-merge runs",
        ),
    ):
        expect(
            gate.full_ci_pending(env, outputs, fetch) is pending,
            f"full_ci_pending: {what}",
        )


def main() -> int:
    test_gate()
    test_pull_request()
    test_retry_allowlist()
    if FAILURES:
        for failure in FAILURES:
            print(f"ci-gate-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print("ci-gate-test: OK: gate fails closed, drafts, full-ci, retry allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
