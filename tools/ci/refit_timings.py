#!/usr/bin/env python3
"""Refit the shard seconds of tools/ci/select_suites.py from recent runs.

The bin packing (select_suites.pack) balances legs with INTEGRATION_SECONDS,
E2E_SECONDS and EMDASH_SECONDS. Shards grow; stale numbers make one leg the
slowest. This reads the job logs of the last successful nightly runs of
ci.yml on main (the only runs with every shard), takes per shard the median
after dropping outliers (outside half to double the median), and rewrites a
value only when it moved by more than BAND (15 %). The scheduled workflow
refit-timings.yml opens a pull request with the result; a human merges it.

Per-shard seconds:
* Integration: "ci-integration: bin: <shard> passed (<n>s)" (run-shards.sh).
* E2E: the sum of "shared-stack: <leaf script> <n>s, exit 0" over the
  shard's leaf scripts (tools/ci/e2e.sh) plus E2E_SETUP_SHARE for its share
  of the stack preparation.
* EmDash: the sum of "ci-emdash: OK: <case> (<n>s)" over the group's cases.

Usage: refit_timings.py [--runs N] [--write] ROOT
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

BAND = 0.15
E2E_SETUP_SHARE = 30
NIGHTLY_TITLE = "nightly"
INTEGRATION_LINE = re.compile(r"ci-integration: bin: ([a-z0-9-]+) passed \((\d+)s\)")
LEAF_LINE = re.compile(
    r"(?:shared-stack|ci-e2e: own leaf): (tools/[A-Za-z0-9_/.-]+\.sh) ([0-9.]+)s, exit 0"
)
EMDASH_LINE = re.compile(r"ci-emdash: OK: ([a-z0-9-]+) \((\d+)s\)")
TABLES = ("INTEGRATION_SECONDS", "E2E_SECONDS", "EMDASH_SECONDS")


def e2e_leaves(e2e_script: str) -> dict[str, list[str]]:
    """Shard -> leaf scripts, parsed from the leaves() case in tools/ci/e2e.sh."""
    body = e2e_script.split("leaves() {", 1)[1].split("\n}\n", 1)[0]
    result: dict[str, list[str]] = {}
    for labels, block in re.findall(r"(?ms)^  ([a-z0-9|-]+)\)\n(.*?)^    ;;", body):
        mapped = "tr '-' '_'" in block
        scripts = re.findall(r"tools/[A-Za-z0-9_/.$-]+\.sh", block)
        for label in labels.split("|"):
            if mapped:
                # "tools/$(printf '%s' "$1" | tr '-' '_')/test.sh"
                result[label] = [f"tools/{label.replace('-', '_')}/test.sh"]
            else:
                result[label] = [s.replace("$1", label) for s in scripts]
    return result


def emdash_cases(emdash_script: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for group, block in re.findall(
        r"(?ms)^  ([a-z0-9-]+)\)\n(.*?)^    ;;", emdash_script
    ):
        found = re.search(r'cases="?([^"\n]+)"?', block)
        if found:
            result[group] = found.group(1).replace("$group", group).split()
    return result


def shard_seconds(
    log: str, leaves: Mapping[str, list[str]], cases: Mapping[str, list[str]]
) -> dict[str, float]:
    """Per-shard seconds observed in one job log."""
    seconds: dict[str, float] = {}
    for shard, value in INTEGRATION_LINE.findall(log):
        seconds[shard] = float(value)
    leaf_seconds: dict[str, float] = {}
    for script, value in LEAF_LINE.findall(log):
        leaf_seconds[script] = float(value)
    for shard, scripts in leaves.items():
        if scripts and all(s in leaf_seconds for s in scripts):
            seconds[shard] = sum(leaf_seconds[s] for s in scripts) + E2E_SETUP_SHARE
    case_seconds = {case: float(value) for case, value in EMDASH_LINE.findall(log)}
    for group, names in cases.items():
        if names and all(n in case_seconds for n in names):
            seconds[group] = sum(case_seconds[n] for n in names)
    return seconds


def robust_median(values: Iterable[float]) -> float | None:
    values = sorted(values)
    if not values:
        return None
    median = statistics.median(values)
    kept = [v for v in values if median / 2 <= v <= median * 2]
    return statistics.median(kept) if kept else median


def refit(
    current: Mapping[str, Mapping[str, int]],
    observations: Mapping[str, list[float]],
) -> dict[str, dict[str, int]]:
    """New values for entries that moved by more than BAND."""
    changes: dict[str, dict[str, int]] = {}
    for table, entries in current.items():
        for shard, old in entries.items():
            new = robust_median(observations.get(shard, []))
            if new is None or old <= 0:
                continue
            if abs(new - old) / old > BAND:
                changes.setdefault(table, {})[shard] = int(round(new))
    return changes


def rewrite(source: str, changes: Mapping[str, Mapping[str, int]]) -> str:
    for table, entries in changes.items():
        start = source.index(f"{table} = {{")
        end = source.index("\n}", start)
        block = source[start:end]
        for shard, value in entries.items():
            block, count = re.subn(
                rf'(\n    "{re.escape(shard)}": )\d+,', rf"\g<1>{value},", block
            )
            if count != 1:
                raise ValueError(f"{table}[{shard!r}] not found exactly once")
        source = source[:start] + block + source[end:]
    return source


def gh_json(*args: str) -> object:
    return json.loads(subprocess.check_output(["gh", "api", *args], text=True))


def gh_text(*args: str) -> str:
    return subprocess.run(
        ["gh", "api", *args], capture_output=True, text=True, check=False
    ).stdout


def collect(
    repository: str,
    runs: int,
    leaves: Mapping[str, list[str]],
    cases: Mapping[str, list[str]],
    fetch_json: Callable[..., object] = gh_json,
    fetch_text: Callable[..., str] = gh_text,
) -> dict[str, list[float]]:
    listing = fetch_json(
        f"repos/{repository}/actions/workflows/ci.yml/runs"
        "?branch=main&event=schedule&status=success&per_page=50"
    )
    nightly = [
        run
        for run in (
            listing.get("workflow_runs", []) if isinstance(listing, dict) else []
        )
        if NIGHTLY_TITLE in str(run.get("display_title", ""))
    ][:runs]
    observations: dict[str, list[float]] = defaultdict(list)
    for run in nightly:
        jobs = fetch_json(
            f"repos/{repository}/actions/runs/{run['id']}/jobs?per_page=100"
        )
        for job in jobs.get("jobs", []) if isinstance(jobs, dict) else []:
            if not str(job.get("name", "")).startswith(
                ("Integration", "E2E", "EmDash")
            ):
                continue
            log = fetch_text(f"repos/{repository}/actions/jobs/{job['id']}/logs")
            for shard, value in shard_seconds(log, leaves, cases).items():
                observations[shard].append(value)
    return dict(observations)


def current_tables(root: Path) -> dict[str, dict[str, int]]:
    sys.path.insert(0, str(root))
    from tools.ci import select_suites

    return {table: dict(getattr(select_suites, table)) for table in TABLES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--repository", default="BjoernSchotte/leonaid")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    current = current_tables(root)
    # Only real leaves: the smoke leg reuses leaf scripts with a filter.
    leaves = {
        shard: scripts
        for shard, scripts in e2e_leaves(
            (root / "tools/ci/e2e.sh").read_text(encoding="utf-8")
        ).items()
        if shard in current["E2E_SECONDS"] and shard != "smoke"
    }
    cases = emdash_cases((root / "tools/ci/emdash.sh").read_text(encoding="utf-8"))
    observations = collect(args.repository, args.runs, leaves, cases)
    changes = refit(current, observations)
    lines = ["| Table | Shard | Old s | New s | Runs |", "|---|---|---|---|---|"]
    for table, entries in changes.items():
        for shard, value in sorted(entries.items()):
            lines.append(
                f"| {table} | {shard} | {current[table][shard]} | {value} | "
                f"{len(observations.get(shard, []))} |"
            )
    report = "\n".join(lines) if changes else "No shard moved by more than 15 %."
    print(report)
    if args.summary:
        args.summary.write_text(report + "\n", encoding="utf-8")
    if args.write and changes:
        path = root / "tools/ci/select_suites.py"
        path.write_text(
            rewrite(path.read_text(encoding="utf-8"), changes), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
