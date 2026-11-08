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
from tools.ci import rerun_stale_gates  # noqa: E402

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
    # A draft run (only the gate ran and failed) is not a test result.
    draft_run = [
        [
            job("select / Select suites", "skipped"),
            job("Unit", "skipped"),
            job("CI gate", "failure"),
        ]
    ]
    draft_stats, draft_total, _ = flake_summary.tally([draft_run])
    expect(draft_total == 0 and not draft_stats, f"drafts are ignored: {draft_stats}")
    docs_draft = [
        [
            {
                "name": "Bilingual site artifact",
                "conclusion": "failure",
                "steps": [{"name": "Refuse a draft", "conclusion": "failure"}],
            }
        ]
    ]
    expect(flake_summary.tally([docs_draft])[1] == 0, "a refused docs draft is ignored")
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


def check_run(
    run: int, status: str, conclusion: str | None, started: str | None
) -> dict[str, object]:
    return {
        "id": run * 10,
        "details_url": f"https://github.com/o/r/actions/runs/{run}/job/1",
        "status": status,
        "conclusion": conclusion,
        "started_at": started,
    }


def api(check_runs: list[dict[str, object]], real: set[int]) -> gate.Fetch:
    """Check runs of the commit; the jobs of a run show if its selector ran."""

    def fetch(path: str) -> object:
        if "/check-runs" in path:
            return {"check_runs": check_runs}
        run = int(path.split("/actions/runs/")[1].split("/")[0])
        conclusion = "success" if run in real else "skipped"
        return {"jobs": [{"name": "select / Select suites", "conclusion": conclusion}]}

    return fetch


def test_pull_request_context() -> None:
    base_env = {"EVENT_NAME": "pull_request", "GITHUB_REPOSITORY": "o/r"}

    def never(path: str) -> object:
        raise AssertionError(f"unexpected API call {path}")

    # Drafts fail the gate while the pull request is still a draft (read from
    # the API, not the event: a re-run after ready_for_review mirrors).
    draft_env = {
        **base_env,
        "DRAFT": "true",
        "PR_NUMBER": "7",
        "HEAD_SHA": "abc",
        "GATE_NAME": "CI gate",
        "GITHUB_RUN_ID": "9",
    }

    def still_draft(path: str) -> object:
        assert path.endswith("/pulls/7"), path
        return {"draft": True}

    decision, message = gate.pull_request_context(draft_env, {}, still_draft)
    expect(decision is False and "draft" in message, f"draft: {decision} {message}")
    for real_conclusion, expected in (("success", True), ("failure", False)):
        mirror = api([check_run(5, "completed", real_conclusion, "t")], {5})

        def now_ready(path: str, mirror: gate.Fetch = mirror) -> object:
            return {"draft": False} if path.endswith("/pulls/7") else mirror(path)

        decision, _ = gate.pull_request_context(draft_env, {}, now_ready)
        expect(
            decision is expected,
            f"a re-run draft gate mirrors the real {real_conclusion}: {decision}",
        )
    decision, _ = gate.pull_request_context(draft_env, {}, lambda path: {})
    expect(decision is False, "an unreadable pull request stays a draft")
    expect(
        gate.pull_request_context(
            {**base_env, "EVENT_ACTION": "synchronize"}, {}, never
        )
        == (None, ""),
        "synchronize evaluates normally",
    )
    expect(
        gate.pull_request_context({"EVENT_NAME": "schedule"}, {}, never) == (None, ""),
        "schedule evaluates normally",
    )
    expect(
        gate.pull_request_context(
            {**base_env, "EVENT_ACTION": "edited", "BASE_CHANGED": "true"}, {}, never
        )
        == (None, ""),
        "a base change runs the normal selection",
    )
    edit = {
        **base_env,
        "EVENT_ACTION": "edited",
        "BASE_CHANGED": "false",
        "HEAD_SHA": "abc",
        "GATE_NAME": "CI gate",
        "GITHUB_RUN_ID": "9",
    }
    for runs, real, expected in (
        ([check_run(5, "completed", "success", "t")], {5}, True),
        ([check_run(5, "completed", "failure", "t")], {5}, False),
        # The newest completed real gate decides.
        (
            [
                check_run(5, "completed", "success", "t"),
                check_run(6, "completed", "failure", "t"),
            ],
            {5, 6},
            False,
        ),
        # Another title-edit run's gate is never mirrored.
        (
            [
                check_run(5, "completed", "failure", "t"),
                check_run(7, "completed", "success", "t"),
            ],
            {5},
            False,
        ),
        # Our own check run never counts; nothing real yet fails fast.
        ([check_run(9, "completed", "success", "t")], {9}, False),
        ([], set(), False),
        # A real gate still in progress is not a result yet: fail fast.
        ([check_run(6, "in_progress", None, None)], {6}, False),
    ):
        decision, message = gate.pull_request_context(edit, {}, api(runs, real))
        expect(decision is expected, f"mirror {runs} real={real}: {decision}")
        if not expected:
            expect("supersedes" in message, f"fail-fast message: {message}")
    # A stacked selection never passes; a selection into main does.
    expect(
        gate.stacked_result(base_env, {"heavy": "false"}),
        "a stacked result never passes the gate",
    )
    expect(not gate.stacked_result(base_env, {"heavy": "true"}), "heavy passes")
    expect(not gate.stacked_result(base_env, {}), "a missing output is not stacked")
    expect(
        not gate.stacked_result({"EVENT_NAME": "schedule"}, {"heavy": "false"}),
        "only pull requests can be stacked",
    )


def test_rerun_selection() -> None:
    def job(name: str, conclusion: str) -> dict[str, object]:
        return {"name": name, "conclusion": conclusion}

    def run(number: int, **fields: object) -> dict[str, object]:
        return {
            "id": number,
            "workflow_id": 1,
            "head_sha": "abc",
            "status": "completed",
            "conclusion": "failure",
            **fields,
        }

    edit_jobs = [job("select / Select suites", "skipped"), job("CI gate", "failure")]
    real_red = [job("select / Select suites", "success"), job("CI gate", "failure")]
    draft_ok = [job("select / Select suites", "skipped"), job("CI gate", "success")]
    runs = [
        run(2),  # failed mirror gate: re-run
        run(3),  # real run, red: never re-run (stays red)
        run(4, workflow_id=2),  # another workflow
        run(5, head_sha="old"),  # another commit
        run(6, status="in_progress", conclusion=None),
        run(7, conclusion="success"),
        run(8),  # gate-only run whose gate passed: nothing to fix
        run(9),  # this run
    ]
    jobs = {2: edit_jobs, 3: real_red, 8: draft_ok}

    def fetch(path: str) -> object:
        if path.endswith("/actions/runs/9"):
            return {"workflow_id": 1}
        if "/actions/runs?" in path:
            return {"workflow_runs": runs}
        number = int(path.split("/actions/runs/")[1].split("/")[0])
        return {"jobs": jobs.get(number, [])}

    selected = rerun_stale_gates.stale_runs(fetch, "o/r", "9", "abc")
    expect(selected == [2], f"only failed mirror gates are re-run: {selected}")
    expect(
        not rerun_stale_gates.gate_only_failure(
            [job("Survey gate", "failure"), job("Unit", "skipped")]
        ),
        "without the select job a run is never treated as a mirror",
    )


def main() -> int:
    test_gate()
    test_rerun_selection()
    test_pull_request_context()
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
