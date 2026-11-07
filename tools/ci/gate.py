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
  runs no job; the gate mirrors the newest completed gate of a real run
  for the commit and fails fast without one (the real gate, created when
  its jobs finish, supersedes it), so an edit can neither hide a failure
  nor cancel a run;
* a stacked selection (``heavy`` false) never passes: it skipped the
  shared suites, and its green would stay the newest gate for 20-60
  minutes after a retarget to main.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
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


# Job name of select-suites.yml; workflow_contract.py keeps them equal.
SELECT_JOB_NAME = "Select suites"


def real_run(fetch: Fetch, repository: str, run_id: str) -> bool:
    """A run whose selector ran: not a draft or title-edit run."""
    data = fetch(f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100")
    for job in data.get("jobs", []) if isinstance(data, dict) else []:
        if (
            isinstance(job, dict)
            and SELECT_JOB_NAME in str(job.get("name", ""))
            and str(job.get("conclusion") or "") not in ("", "skipped")
        ):
            return True
    return False


def mirrored_result(
    fetch: Fetch, repository: str, sha: str, name: str, own_run: str
) -> str:
    """Conclusion of the newest completed gate of a real run for this commit.

    GitHub creates a gate's check run only when its needs have finished, so
    a real run still in progress has none yet; its gate will be newer than
    this mirror and supersede it. Gates of other title-edit or draft runs
    are skipped, so mirrors never copy each other. "missing" when no real
    run has a completed gate yet.
    """
    data = fetch(
        f"repos/{repository}/commits/{sha}/check-runs"
        f"?check_name={urllib.parse.quote(name)}&per_page=100"
    )
    candidates = sorted(
        (
            (int(run.get("id") or 0), match.group(1), run)
            for run in (data.get("check_runs", []) if isinstance(data, dict) else [])
            if isinstance(run, dict)
            and run.get("status") == "completed"
            and (match := RUN_ID.search(str(run.get("details_url", ""))))
            and match.group(1) != own_run
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    for _, run_id, run in candidates:
        if real_run(fetch, repository, run_id):
            return str(run.get("conclusion") or "missing")
    return "missing"


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
        message = f"title/body edit: this commit's real gate result is {result}"
        if result != "success":
            message += (
                "; when the real run finishes, its gate supersedes this one "
                "(or re-run the real run's gate job, or push)"
            )
        return result == "success", message
    return None, ""


def stacked_result(environ: Mapping[str, str], outputs: Mapping[str, object]) -> bool:
    """A stacked selection (heavy false): never a passing required gate.

    It skipped Build, Security and the shared suites. GitHub creates the
    gate of a later base-change run only when its jobs finish, so a green
    stacked gate would stay the newest result for 20-60 minutes after a
    retarget to main. The ruleset applies only to main, so a red gate does
    not block merging into the stack's parent branch.
    """
    return (
        environ.get("EVENT_NAME") == "pull_request"
        and str(outputs.get("heavy", "true")) == "false"
    )


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
    if not failed and stacked_result(os.environ, outputs):
        print(
            f"ci-gate: ERROR: {args.name}: stacked run (base is not main): the "
            "selected suites passed, but a stacked result never satisfies the "
            "gate; retarget to main for the real gate",
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
