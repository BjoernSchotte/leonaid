#!/usr/bin/env python3
"""Aggregate one workflow's jobs into a single required check.

The repository ruleset requires only this gate. It reads
``toJSON(needs)`` and the selector outputs it contains and fails unless:

* the ``select`` job succeeded;
* every selected job succeeded;
* every job that was not selected was skipped (never failed or cancelled);
* every other job succeeded (``--may-skip`` jobs may also be skipped).

So a skipped job never hides an upstream failure: a skipped Contract job
passes only when the selector said Contract was not needed.

Pull request context (environment of the gate step):

* a draft fails the gate: no CI ran, and a red gate cannot be mistaken for
  a result after ``ready_for_review`` (a draft cannot be merged anyway);
* an ``edited`` event that did not change the base (title or body edits)
  runs no job; the gate mirrors the commit's latest real gate result and
  waits for it while that run is still going, so an edit can neither hide
  a failure nor cancel a run;
* a stacked selection (``heavy`` false) fails once the pull request's
  current base, read from the API, is main: the stacked result never
  ran the shared suites and must not be merged into main.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence

UNSELECTED = {"", "false", "[]"}


def evaluate(
    needs: Mapping[str, Mapping[str, object]],
    selectable: Mapping[str, str],
    may_skip: Sequence[str] = (),
    select_job: str = "select",
) -> list[tuple[str, str, str, bool]]:
    """Return (job, result, expectation, ok) rows."""
    rows: list[tuple[str, str, str, bool]] = []
    selection = needs.get(select_job)
    if selection is None:
        return [(select_job, "missing", "success", False)]
    outputs = selection.get("outputs") or {}
    if not isinstance(outputs, Mapping):
        outputs = {}
    for job in sorted(needs):
        result = str(needs[job].get("result", "missing"))
        if job == select_job:
            rows.append((job, result, "success", result == "success"))
            continue
        key = selectable.get(job)
        if key is not None:
            # A missing output counts as selected: fail closed.
            selected = str(outputs.get(key, "true")) not in UNSELECTED
            expected = "success" if selected else "skipped"
            rows.append((job, result, expected, result == expected))
        elif job in may_skip:
            rows.append(
                (job, result, "success or skipped", result in ("success", "skipped"))
            )
        else:
            rows.append((job, result, "success", result == "success"))
    for job in sorted(set(selectable) - set(needs)):
        rows.append((job, "missing", "listed in needs", False))
    return rows


Fetch = Callable[[str], object]
RUN_ID = re.compile(r"/actions/runs/(\d+)/")


def github_fetch(path: str) -> object:
    """GET an API path with GITHUB_TOKEN (read scopes only)."""
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ.get('GH_TOKEN', '')}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def mirrored_result(
    fetch: Fetch,
    repository: str,
    sha: str,
    name: str,
    own_run: str,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 100,
) -> str:
    """Conclusion of the latest other run's gate check for this commit.

    Waits while that check is still running. "missing" when there is none.
    """
    for _ in range(attempts):
        data = fetch(
            f"repos/{repository}/commits/{sha}/check-runs"
            f"?check_name={urllib.request.quote(name)}&per_page=100"
        )
        runs = [
            run
            for run in (data.get("check_runs", []) if isinstance(data, dict) else [])
            if isinstance(run, dict)
            and (match := RUN_ID.search(str(run.get("details_url", ""))))
            and match.group(1) != own_run
        ]
        if not runs:
            return "missing"
        latest = max(runs, key=lambda run: str(run.get("started_at") or ""))
        if latest.get("status") == "completed":
            return str(latest.get("conclusion") or "missing")
        sleep(30)
    return "still running"


def pull_request_context(
    environ: Mapping[str, str], outputs: Mapping[str, object], fetch: Fetch
) -> tuple[bool | None, str]:
    """(decision, message): None = evaluate the needs normally."""
    if environ.get("EVENT_NAME") != "pull_request":
        return None, ""
    if environ.get("DRAFT") == "true":
        return False, "draft pull request: no CI ran; mark it ready for review"
    if (
        environ.get("EVENT_ACTION") == "edited"
        and environ.get("BASE_CHANGED") != "true"
    ):
        result = mirrored_result(
            fetch,
            environ.get("GITHUB_REPOSITORY", ""),
            environ.get("HEAD_SHA", ""),
            environ.get("GATE_NAME", ""),
            environ.get("GITHUB_RUN_ID", ""),
        )
        return (
            result == "success",
            f"title/body edit: this commit's gate result is {result}",
        )
    return None, ""


def stacked_into_main(
    environ: Mapping[str, str], outputs: Mapping[str, object], fetch: Fetch
) -> bool:
    """A stacked selection whose pull request now targets main."""
    if environ.get("EVENT_NAME") != "pull_request":
        return False
    if str(outputs.get("heavy", "true")) != "false":
        return False
    data = fetch(
        f"repos/{environ.get('GITHUB_REPOSITORY', '')}/pulls/{environ.get('PR_NUMBER', '')}"
    )
    base = data.get("base", {}).get("ref") if isinstance(data, dict) else None
    # Unknown base: fail closed.
    return base != environ.get("STACK_BASE", "")


def parse_selectable(values: Sequence[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        job, separator, key = value.partition("=")
        if not separator or not job or not key:
            raise SystemExit(
                f"ci-gate: ERROR: expected job=selector-key, got {value!r}"
            )
        mapping[job] = key
    return mapping


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="gate name for messages")
    parser.add_argument("--selectable", action="append", default=[], metavar="JOB=KEY")
    parser.add_argument("--may-skip", action="append", default=[], metavar="JOB")
    args = parser.parse_args(argv)
    raw = os.environ.get("NEEDS", "")
    try:
        needs = json.loads(raw)
    except json.JSONDecodeError:
        print(f"ci-gate: ERROR: NEEDS is not JSON: {raw[:200]!r}", file=sys.stderr)
        return 1
    outputs = (needs.get("select") or {}).get("outputs") or {}
    decision, message = pull_request_context(os.environ, outputs, github_fetch)
    if decision is not None:
        print(f"ci-gate: {args.name}: {message}")
        if not decision:
            print(f"ci-gate: ERROR: {args.name}: {message}", file=sys.stderr)
            return 1
        print(f"ci-gate: OK: {args.name}")
        return 0
    rows = evaluate(needs, parse_selectable(args.selectable), args.may_skip)
    lines = [
        f"### {args.name}",
        "",
        "| Job | Result | Expected | |",
        "|---|---|---|---|",
    ]
    for job, result, expected, ok in rows:
        lines.append(f"| {job} | {result} | {expected} | {'✅' if ok else '❌'} |")
    report = "\n".join(lines) + "\n"
    print(report)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(report)
    failed = [job for job, _, _, ok in rows if not ok]
    if not failed and stacked_into_main(os.environ, outputs, github_fetch):
        print(
            f"ci-gate: ERROR: {args.name}: stacked result, but the pull request "
            "no longer targets its stack base: push or re-run to verify it "
            "against main",
            file=sys.stderr,
        )
        return 1
    if failed:
        print(f"ci-gate: ERROR: {args.name}: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"ci-gate: OK: {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
