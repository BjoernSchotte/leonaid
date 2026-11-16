#!/usr/bin/env python3
"""Prove the post-merge base lookup and the watchdog's run choice."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.ci import post_merge  # noqa: E402

FAILURES: list[str] = []


def expect(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def run(
    number: int,
    event: str,
    conclusion: str,
    sha: str,
    branch: str = "main",
    title: str = "LeonAid CI post-merge",
) -> dict[str, Any]:
    return {
        "id": number,
        "event": event,
        "status": "completed",
        "conclusion": conclusion,
        "head_sha": sha,
        "head_branch": branch,
        "display_title": title,
        "created_at": f"2026-11-08T10:{number:02d}:00Z",
        "html_url": f"https://github.com/o/r/actions/runs/{number}",
    }


def test_base() -> None:
    own = "f" * 40
    for runs, want, what in (
        ([run(1, "push", "success", "a")], "a", "a green push run"),
        ([run(1, "schedule", "success", "a")], "a", "a green nightly run"),
        ([run(1, "workflow_dispatch", "success", "a")], "a", "a green dispatch"),
        ([run(1, "pull_request", "success", "a")], None, "a PR run never counts"),
        ([run(1, "push", "success", own)], None, "the run's own commit never counts"),
        ([run(1, "push", "failure", "a")], None, "a red run is no base"),
        ([run(1, "push", "cancelled", "a")], None, "a cancelled run is no base"),
        ([run(1, "push", "success", "a", branch="x")], None, "another branch"),
        (
            [run(1, "push", "success", "a"), run(2, "push", "failure", "b")],
            "a",
            "the newest green run, not the newest run",
        ),
        (
            [run(3, "push", "success", "c"), run(1, "push", "success", "a")],
            "c",
            "the newest green run (any API order)",
        ),
        (
            [run(4, "pull_request", "success", "d"), run(2, "push", "success", "b")],
            "b",
            "a newer PR run is skipped",
        ),
        ([], None, "no run: complete suite"),
    ):
        got = post_merge.pick_base(runs, own)
        expect(got == want, f"base: {what}: {got!r} != {want!r}")
    expect(
        post_merge.workflow_file("o/r/.github/workflows/ci.yml@refs/heads/main")
        == "ci.yml",
        "workflow file from github.workflow_ref",
    )

    def unreachable(*_: object) -> list[dict[str, Any]]:
        raise OSError("HTTP 403")

    original = post_merge.fetch_runs
    post_merge.fetch_runs = unreachable  # type: ignore[assignment]
    printed = io.StringIO()
    try:
        with (
            contextlib.redirect_stdout(printed),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = post_merge.main(["base"], {"WORKFLOW_REF": "x/ci.yml@m"})
    finally:
        post_merge.fetch_runs = original
    expect(
        status == 0 and printed.getvalue() == "",
        "an unreadable API prints no base (complete suite) and never fails",
    )


def latest(runs: list[dict[str, Any]], *args: str) -> str:
    printed = io.StringIO()
    stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps({"workflow_runs": runs}))
    try:
        with contextlib.redirect_stdout(printed):
            post_merge.main(["latest", *args])
    finally:
        sys.stdin = stdin
    return printed.getvalue().split("\t")[1] if printed.getvalue() else ""


def test_watchdog() -> None:
    red, green = run(1, "push", "failure", "a"), run(2, "push", "success", "b")
    cancelled = run(3, "push", "cancelled", "c")
    for runs, want, what in (
        ([red, cancelled], "failure", "cancelled after red keeps the issue open"),
        ([red, green, cancelled], "success", "green after red closes it"),
        ([red], "failure", "a red post-merge run opens the issue"),
        ([cancelled], "", "only cancelled runs: nothing to judge"),
        (
            [red, run(4, "schedule", "success", "d")],
            "failure",
            "push entries see pushes",
        ),
    ):
        got = latest(runs, "--event", "push")
        expect(got == want, f"watchdog push: {what}: {got!r} != {want!r}")
    nightly = run(
        5, "schedule", "failure", "e", title="LeonAid CI nightly (every E2E leaf)"
    )
    other = run(6, "schedule", "success", "f", title="LeonAid CI main every 3 hours")
    expect(
        latest([nightly, other], "--event", "schedule", "--word", "nightly")
        == "failure",
        "a schedule entry with a word matches only its runs",
    )
    expect(
        latest([run(7, "schedule", "cancelled", "g")], "--event", "schedule")
        == "cancelled",
        "a cancelled scheduled run still counts (scheduled runs are never cancelled)",
    )


TREE = "1" * 40
HEAD = "2" * 40


def pr_run(
    number: int, head: str = HEAD, repository: str = "o/r", **extra: Any
) -> dict[str, Any]:
    return (
        run(number, "pull_request", "success", head, branch="feature")
        | {"head_repository": {"full_name": repository}}
        | extra
    )


def lookup(
    parents: str,
    runs: list[dict[str, Any]],
    proofs: dict[int, object],
    fail: bool = False,
) -> tuple[int, str]:
    """`post_merge.py proof` with git, the runs API and gh replaced."""

    def git(*arguments: str) -> str:
        if fail:
            raise OSError("no git")
        return parents if arguments[0] == "rev-list" else TREE

    def fetch(*_: object) -> list[dict[str, Any]]:
        return runs

    def download(run_id: int, repository: str) -> object:
        return proofs.get(run_id) if repository == "o/r" else None

    originals = (post_merge.git, post_merge.fetch_runs, post_merge.download_proof)
    post_merge.git = git
    post_merge.fetch_runs = fetch  # type: ignore[assignment]
    post_merge.download_proof = download
    printed = io.StringIO()
    try:
        with (
            contextlib.redirect_stdout(printed),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = post_merge.main(
                ["proof"], {"GITHUB_REPOSITORY": "o/r", "WORKFLOW_REF": "o/r/ci.yml@m"}
            )
    finally:
        post_merge.git, post_merge.fetch_runs, post_merge.download_proof = originals
    return status, printed.getvalue().strip()


def test_proof() -> None:
    record = post_merge.proof_record(TREE, "golden, checks,integration:policy,checks")
    expect(
        record
        == {
            "version": 1,
            "tree": TREE,
            "suites": ["checks", "golden", "integration:policy"],
        },
        f"record: {record}",
    )
    for tree, suites in ((TREE, ""), ("main", "checks"), (TREE, "checks,Bad Name")):
        try:
            post_merge.proof_record(tree, suites)
        except ValueError:
            continue
        FAILURES.append(f"record must refuse {tree!r} {suites!r}")
    merge = f"{'3' * 40} {'4' * 40} {HEAD}"
    cases: tuple[tuple[str, list[dict[str, Any]], dict[int, object], str, str], ...] = (
        (
            merge,
            [pr_run(1)],
            {1: record},
            "checks,golden,integration:policy",
            "same tree",
        ),
        (merge, [pr_run(1)], {1: record | {"tree": "5" * 40}}, "", "another tree"),
        (merge, [pr_run(1)], {1: record | {"version": 2}}, "", "unknown version"),
        (merge, [pr_run(1)], {1: record | {"suites": ["x y"]}}, "", "bad suite"),
        (merge, [pr_run(1)], {1: None}, "", "no artifact"),
        (merge, [pr_run(1, repository="fork/r")], {1: record}, "", "a fork's run"),
        (merge, [pr_run(1, head="6" * 40)], {1: record}, "", "another head"),
        (merge, [pr_run(1, conclusion="failure")], {1: record}, "", "a red run"),
        (
            merge,
            [pr_run(1), pr_run(2)],
            {1: record, 2: record | {"tree": "5" * 40}},
            "checks,golden,integration:policy",
            "an older run of the same head may hold the proof",
        ),
        (f"{'3' * 40} {'4' * 40}", [pr_run(1)], {1: record}, "", "a squash merge"),
        (merge, [], {}, "", "no pull-request run"),
    )
    for parents, runs, proofs, want, what in cases:
        status, printed = lookup(parents, runs, proofs)
        expect(
            status == 0 and printed == want, f"proof: {what}: {printed!r} != {want!r}"
        )
    status, printed = lookup(merge, [pr_run(1)], {1: record}, fail=True)
    expect(
        status == 0 and printed == "", "a failing lookup proves nothing and never fails"
    )
    many = [pr_run(n) for n in range(1, 10)]
    expect(
        post_merge.proof_runs(many, "o/r", HEAD) == [9, 8, 7],
        "only the newest runs are tried",
    )


def main() -> int:
    test_base()
    test_watchdog()
    test_proof()
    if FAILURES:
        for failure in FAILURES:
            print(f"post-merge-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print(
        "post-merge-test: OK: green base, own commit, PR runs, watchdog run choice, "
        "proof of the same tree"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
