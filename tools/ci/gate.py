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

Pull requests run only on opened, synchronize, reopened and
ready_for_review, so every gate belongs to a run that selected suites.
A draft fails (no CI ran). A stacked pull request (``BASE_REF`` not main)
fails: a retarget starts no run. A pull request that carries ``full-ci``
fails a run that was not the complete one (labels are read live): set the
label, then push a new commit (or set it while still a draft).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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


# The lead sets it on risky pull requests: the complete suite before the
# merge (tools/ci/select_suites.py FULL_CI_LABEL).
FULL_CI_LABEL = "full-ci"


def full_ci_pending(
    environ: Mapping[str, str], outputs: Mapping[str, object], fetch: Fetch
) -> bool:
    """A run without the complete suite while the PR carries full-ci.

    Only the workflows with a full-ci tier set FULL_CI_GATE. A re-run keeps
    its event's labels, so the labels are read live; an unreadable pull
    request counts as labelled (fail closed).
    """
    if (
        environ.get("FULL_CI_GATE") != "true"
        or environ.get("EVENT_NAME") != "pull_request"
    ):
        return False
    if str(outputs.get("tier", "")) == "full":
        return False
    try:
        pull = fetch(
            f"repos/{environ.get('GITHUB_REPOSITORY', '')}/pulls/"
            f"{environ.get('PR_NUMBER', '')}"
        )
    except Exception:  # noqa: BLE001 - any API failure fails closed
        return True
    if not isinstance(pull, dict) or not isinstance(pull.get("labels"), list):
        return True
    return any(
        isinstance(label, dict) and label.get("name") == FULL_CI_LABEL
        for label in pull["labels"]
    )


def stacked(environ: Mapping[str, str]) -> bool:
    """A pull request into another branch: its diff and checks miss main.

    A retarget to main is an ``edited`` event and starts no run, so its
    green gate must not count; the next push or reopen runs against main.
    """
    return (
        environ.get("EVENT_NAME") == "pull_request"
        and environ.get("BASE_REF", "main") != "main"
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
    if (
        os.environ.get("EVENT_NAME") == "pull_request"
        and os.environ.get("DRAFT") == "true"
    ):
        print(
            f"ci-gate: ERROR: {args.name}: draft pull request: no CI ran; "
            "mark it ready for review",
            file=sys.stderr,
        )
        return 1
    if stacked(os.environ):
        print(
            f"ci-gate: ERROR: {args.name}: stacked pull request (base "
            f"{os.environ.get('BASE_REF')!r}): a result against another branch "
            "never passes; retarget to main, then push or close and reopen",
            file=sys.stderr,
        )
        return 1
    if full_ci_pending(os.environ, outputs, github_fetch):
        print(
            f"ci-gate: ERROR: {args.name}: the pull request carries {FULL_CI_LABEL}, "
            f"but this run is the {outputs.get('tier') or 'unknown'} tier; only the "
            "complete run's gate counts (push a new commit)",
            file=sys.stderr,
        )
        return 1
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
    if failed:
        print(f"ci-gate: ERROR: {args.name}: {', '.join(failed)}", file=sys.stderr)
        return 1
    print(f"ci-gate: OK: {args.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
