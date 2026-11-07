#!/usr/bin/env python3
"""Summarize failed and rerun jobs over the most recent workflow runs.

Runs nightly from ci.yml. For each workflow it reads the last N completed
runs (all events and branches) and every attempt of each run. A job that
failed in an earlier attempt and was then rerun is the flake signal; a job
that failed in the final attempt is a plain failure. The table goes to the
workflow summary. Only the standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# Decoded GitHub REST JSON.
Fetch = Callable[[str], Any]
# "cancelled" is left out: cancel-in-progress cancels superseded runs.
FAILED = {"failure", "timed_out", "startup_failure"}
IGNORED = {"skipped", "cancelled"}


def github_fetch(token: str) -> Fetch:
    def fetch(path: str) -> Any:
        request = urllib.request.Request(
            f"https://api.github.com/{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    return fetch


@dataclass
class JobStats:
    runs: int = 0
    final_failures: int = 0
    rerun_failures: int = 0
    links: list[str] = field(default_factory=list)


def jobs_of_attempt(
    fetch: Fetch, repository: str, run_id: int, attempt: int
) -> list[Mapping[str, object]]:
    jobs: list[Mapping[str, object]] = []
    page = 1
    while True:
        data = fetch(
            f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}"
        )
        batch = list(data.get("jobs", []))
        jobs.extend(batch)
        if len(batch) < 100:
            return jobs
        page += 1


RunAttempts = Sequence[Sequence[Mapping[str, object]]]


def collect(
    fetch: Fetch, repository: str, workflow: str, runs: int
) -> list[RunAttempts]:
    """Jobs of every attempt (oldest first) of the last ``runs`` runs."""
    data = fetch(
        f"repos/{repository}/actions/workflows/{workflow}/runs?status=completed&per_page={runs}"
    )
    collected: list[RunAttempts] = []
    for run in list(data.get("workflow_runs", []))[:runs]:
        run_id = int(run["id"])
        attempts = int(run.get("run_attempt", 1))
        collected.append(
            [
                jobs_of_attempt(fetch, repository, run_id, n)
                for n in range(1, attempts + 1)
            ]
        )
    return collected


DRAFT_STEP = "Refuse a draft"


def nothing_ran(attempt: Sequence[Mapping[str, object]]) -> bool:
    """A draft or title-edit run: only the gates ran, or a draft was refused.

    Drafts fail their gates on purpose (no CI ran) and a title edit only
    mirrors the commit's real gate; neither is a test result.
    """
    others = [job for job in attempt if not str(job.get("name", "")).endswith("gate")]
    if others and all(str(job.get("conclusion") or "") == "skipped" for job in others):
        return True
    return any(
        str(step.get("name", "")) == DRAFT_STEP
        and str(step.get("conclusion") or "") == "failure"
        for job in attempt
        for step in (job.get("steps") or [])  # type: ignore[union-attr]
        if isinstance(step, Mapping)
    )


def tally(runs: Sequence[RunAttempts]) -> tuple[dict[str, JobStats], int, int]:
    """Count per job: runs, failures in the final attempt, failures that were rerun."""
    stats: dict[str, JobStats] = defaultdict(JobStats)
    rerun_runs = 0
    runs = [
        attempts for attempts in runs if not (attempts and nothing_ran(attempts[-1]))
    ]
    for attempts in runs:
        if len(attempts) > 1:
            rerun_runs += 1
        seen: set[str] = set()
        # Newest attempt first, so the first link is the latest failure.
        for index in range(len(attempts) - 1, -1, -1):
            final = index == len(attempts) - 1
            for job in attempts[index]:
                name = str(job.get("name", "?"))
                conclusion = str(job.get("conclusion") or "")
                if conclusion in IGNORED:
                    continue
                entry = stats[name]
                if name not in seen:
                    seen.add(name)
                    entry.runs += 1
                if conclusion not in FAILED:
                    continue
                if final:
                    entry.final_failures += 1
                else:
                    # Failed, then the run was attempted again: a flake or
                    # an infrastructure failure, never silently green.
                    entry.rerun_failures += 1
                entry.links.append(str(job.get("html_url", "")))
    return dict(stats), len(runs), rerun_runs


def render(
    workflow: str, stats: Mapping[str, JobStats], total: int, reruns: int
) -> str:
    lines = [
        f"### {workflow}: last {total} completed runs, {reruns} with reruns",
        "",
    ]
    noisy = {
        name: entry
        for name, entry in stats.items()
        if entry.final_failures or entry.rerun_failures
    }
    if not noisy:
        return "\n".join(lines + ["No failed or rerun jobs.", ""])
    lines += [
        "| Job | Runs | Failed (final) | Failed, then rerun | Latest |",
        "|---|---:|---:|---:|---|",
    ]
    ordered = sorted(
        noisy.items(),
        key=lambda item: (-item[1].rerun_failures, -item[1].final_failures, item[0]),
    )
    for name, entry in ordered:
        link = f"[log]({entry.links[0]})" if entry.links and entry.links[0] else ""
        lines.append(
            f"| {name} | {entry.runs} | {entry.final_failures} | {entry.rerun_failures} | {link} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", action="append", required=True)
    parser.add_argument("--runs", type=int, default=50)
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("flake-summary: ERROR: GITHUB_TOKEN is required", file=sys.stderr)
        return 1
    fetch = github_fetch(token)
    report = ["## Flake summary", ""]
    for workflow in args.workflow:
        stats, total, reruns = tally(
            collect(fetch, args.repository, workflow, args.runs)
        )
        report.append(render(workflow, stats, total, reruns))
    text = "\n".join(report)
    print(text)
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
