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
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.ci import gate  # noqa: E402
from tools.ci import hold_gate  # noqa: E402
from tools.ci import rerun_stale_gates  # noqa: E402
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
    # Label changes: adding full-ci is a real (complete) run; any other label
    # change, and every removal, mirrors the commit's real gate.
    expect(
        gate.pull_request_context(
            {**base_env, "EVENT_ACTION": "labeled", "LABEL": "full-ci"}, {}, never
        )
        == (None, ""),
        "adding full-ci evaluates the complete run normally",
    )
    for action, label in (
        ("labeled", "documentation"),
        ("labeled", ""),
        ("unlabeled", "full-ci"),
        ("unlabeled", "x"),
    ):
        label_env = {**edit, "EVENT_ACTION": action, "LABEL": label}
        for conclusion, expected in (("success", True), ("failure", False)):
            decision, message = gate.pull_request_context(
                label_env, {}, api([check_run(5, "completed", conclusion, "t")], {5})
            )
            expect(
                decision is expected and "label change" in message,
                f"{action} {label!r} mirrors the real {conclusion}: {decision} {message}",
            )
        decision, _ = gate.pull_request_context(label_env, {}, api([], set()))
        expect(decision is False, f"{action} {label!r} without a real gate fails fast")
    expect(
        gate.FULL_CI_LABEL == select_suites.FULL_CI_LABEL,
        "gate.py and select_suites.py agree on the full-ci label",
    )
    # E-019 H1: full-ci added after a green fast gate. The hold check
    # (tools/ci/hold_gate.py) is newer than the green gate and blocks; a
    # mirror copies it as red; only the complete run's newer gate replaces it.
    expect(gate.HOLD_TITLE == hold_gate.HOLD_TITLE, "hold titles agree")
    # N1: re-running an old fast run after full-ci was added must not create
    # a green gate that lifts the hold; only the complete run counts.
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
    sent: list[tuple[str, dict[str, object]]] = []
    hold_gate.main(
        {
            "GITHUB_REPOSITORY": "o/r",
            "HEAD_SHA": "a" * 40,
            "GATE_NAME": "CI gate",
            "RUN_URL": "https://github.com/o/r/actions/runs/6",
        },
        lambda path, body: sent.append((path, dict(body))),
    )
    body = sent[0][1] if sent else {}
    expect(
        len(sent) == 1
        and sent[0][0] == "repos/o/r/check-runs"
        and body.get("name") == "CI gate"
        and body.get("head_sha") == "a" * 40
        and body.get("status") == "completed"
        and body.get("conclusion") == "failure",
        f"hold posts one failed gate check on the head commit: {sent}",
    )
    for bad in ("", "abc", "A" * 40):
        try:
            hold_gate.payload("CI gate", bad, "u")
        except ValueError:
            continue
        FAILURES.append(f"hold accepted the SHA {bad!r}")
    green_fast = check_run(5, "completed", "success", "t")
    hold = {
        "id": 60,
        "details_url": "https://github.com/o/r/runs/60",
        "status": "completed",
        "conclusion": "failure",
        "output": {"title": hold_gate.HOLD_TITLE},
    }
    full_gate = check_run(7, "completed", "success", "t")
    full_red = check_run(7, "completed", "failure", "t")
    for runs, expected, what in (
        ([green_fast], True, "before the label: the fast gate counts"),
        ([green_fast, hold], False, "the hold blocks after the label"),
        ([green_fast, hold, full_gate], True, "the full run's green gate replaces it"),
        ([green_fast, hold, full_red], False, "a red full run stays red"),
    ):
        decision, _ = gate.pull_request_context(edit, {}, api(runs, {5, 6, 7}))
        expect(decision is expected, f"mirror with hold: {what}: {decision}")
    expect(
        gate.mirrored_result(api([green_fast, hold], {5}), "o/r", "abc", "CI gate", "9")
        == "failure",
        "a hold counts even though its link is no run",
    )
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


FIXTURES = HERE / "fixtures/rerun_stale_gates"


def fixture(name: str) -> dict[str, Any]:
    """Trimmed real GitHub API payloads (see each file's "source")."""
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def test_rerun_selection() -> None:
    real = fixture("real-run-134.json")
    edit = fixture("edit-run-130.json")
    draft = fixture("draft-run-134.json")
    docs_real = fixture("docs-real-run-134.json")
    # The real API shapes: a skipped selector is the caller key "select".
    expect(rerun_stale_gates.gate_only(edit["jobs"]), "#130 edit run is gate-only")
    expect(rerun_stale_gates.gate_only(draft["jobs"]), "#134 draft run is gate-only")
    expect(not rerun_stale_gates.gate_only(real["jobs"]), "a real run is not")
    expect(rerun_stale_gates.real(real["jobs"]), "a real run is real")
    expect(not rerun_stale_gates.real(edit["jobs"]), "an edit run is not real")
    expect(rerun_stale_gates.real(docs_real["jobs"]), "a docs build is real")
    # A docs draft refusal: the real docs job shape with its refusal failed.
    refused = json.loads(json.dumps(docs_real["jobs"]))
    refused[0]["conclusion"] = "failure"
    for step in refused[0]["steps"]:
        if step["name"] == rerun_stale_gates.DRAFT_STEP:
            step["conclusion"] = "failure"
    expect(rerun_stale_gates.gate_only(refused), "a refused docs draft is gate-only")
    expect(not rerun_stale_gates.real(refused), "a refused docs draft is not real")

    sha = real["run"]["head_sha"]
    workflow = real["run"]["workflow_id"]
    own = real["run"]["id"]

    def candidate(
        base: dict[str, Any], number: int, **fields: object
    ) -> dict[str, Any]:
        run = {**base["run"], "id": number, "head_sha": sha, "workflow_id": workflow}
        run.update(fields)
        return run

    runs = [
        candidate(edit, 2),  # completed, failed edit run: re-run
        candidate(draft, 3, conclusion="failure"),  # failed draft run: re-run
        candidate(draft, 4),  # cancelled draft run: does not block, skip
        candidate(real, 5, conclusion="failure"),  # real red run: stays red
        candidate(edit, 6, head_sha="old"),  # another commit
        candidate(edit, 7, status="in_progress", conclusion=None),
        {**real["run"]},  # this run
    ]
    jobs = {
        2: edit["jobs"],
        3: draft["jobs"],
        4: draft["jobs"],
        5: real["jobs"],
        6: edit["jobs"],
        7: edit["jobs"],
        own: real["jobs"],
    }
    posted: list[str] = []

    def make_fetch(head: str, listing: list[dict[str, Any]]) -> Callable[[str], object]:
        def fetch(path: str) -> object:
            if path == f"repos/o/r/actions/runs/{own}":
                return {**real["run"], "pull_requests": [{"number": 134}]}
            if path == "repos/o/r/pulls/134":
                return {"head": {"sha": head}}
            if "/runs?event=pull_request" in path:
                return {"total_count": len(listing), "workflow_runs": listing}
            number = int(path.split("/actions/runs/")[1].split("/")[0])
            return {"total_count": len(jobs[number]), "jobs": jobs[number]}

        return fetch

    code = rerun_stale_gates.refresh(make_fetch(sha, runs), posted.append, "o/r", own)
    expect(
        code == 0
        and posted
        == [
            "repos/o/r/actions/runs/2/rerun-failed-jobs",
            "repos/o/r/actions/runs/3/rerun-failed-jobs",
        ],
        f"only failed gate-only runs of this commit are re-run: {posted}",
    )
    # A gate-only run completing never refreshes (no loops); a moved pull
    # request refreshes nothing; a short listing fails visibly.
    edit_run, notice = rerun_stale_gates.stale_runs(
        lambda path: {**edit["run"], "pull_requests": []}
        if path.endswith(f"/runs/{edit['run']['id']}")
        else {"total_count": len(edit["jobs"]), "jobs": edit["jobs"]},
        "o/r",
        edit["run"]["id"],
    )
    expect(edit_run == [] and "gate-only" in notice, f"edit run: {notice}")
    moved, notice = rerun_stale_gates.stale_runs(make_fetch("newer", runs), "o/r", own)
    expect(moved == [] and "newer commit" in notice, f"moved PR: {notice}")

    def short(path: str) -> object:
        if "/runs?event=pull_request" in path:
            return {"total_count": 500, "workflow_runs": runs}
        return make_fetch(sha, runs)(path)

    try:
        rerun_stale_gates.stale_runs(short, "o/r", own)
        expect(False, "a truncated listing must fail")
    except RuntimeError:
        pass
    # A read-only token (fork pull request) cannot re-run: say so, exit 1.

    def forbidden(path: str) -> None:
        raise urllib.error.HTTPError(path, 403, "Forbidden", None, None)  # type: ignore[arg-type]

    code = rerun_stale_gates.refresh(make_fetch(sha, runs), forbidden, "o/r", own)
    expect(code == 1, "a refused re-run fails the refresh job visibly")


def main() -> int:
    test_gate()
    test_rerun_selection()
    test_pull_request_context()
    test_retry_allowlist()
    if FAILURES:
        for failure in FAILURES:
            print(f"ci-gate-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print("ci-gate-test: OK: gate fails closed, retry allowlist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
