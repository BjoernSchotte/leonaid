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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence

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
