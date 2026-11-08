#!/usr/bin/env python3
"""Re-run the failed gates of title-edit and draft runs after a real gate.

A title edit (or a push to a draft) starts a run in which only the gate
runs: it mirrors the newest completed gate of a real run for the head
commit and fails fast while there is none (tools/ci/gate.py). GitHub keeps
such a failed gate blocking the pull request even after the real run's
gate passes later. So when a real run's gate has completed, this job
re-runs the failed gate of every such run of the same workflow and head
commit; the re-run mirrors the now completed real gate. That stays
fail-closed: a red real gate is mirrored as red, and a pull request that
is still a draft fails again.

A run qualifies when it is another completed, failed run of the same
workflow for the same head commit in which nothing but the gate ran (the
"Select suites" job was skipped) and its gate failed.

Environment: GH_TOKEN (actions: write), GITHUB_REPOSITORY, GITHUB_RUN_ID,
HEAD_SHA.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from tools.ci.gate import SELECT_JOB_NAME  # noqa: E402

Fetch = Callable[[str], object]


def request(path: str, method: str = "GET") -> object:
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ.get('GH_TOKEN', '')}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
    return json.loads(body) if body else {}


def gate_only_failure(jobs: Sequence[Mapping[str, object]]) -> bool:
    """Only the gate ran (selector skipped) and the gate failed."""
    select = [j for j in jobs if SELECT_JOB_NAME in str(j.get("name", ""))]
    gates = [j for j in jobs if str(j.get("name", "")).endswith("gate")]
    return (
        bool(select)
        and all(str(j.get("conclusion") or "") == "skipped" for j in select)
        and any(str(j.get("conclusion") or "") == "failure" for j in gates)
    )


def stale_runs(fetch: Fetch, repository: str, own_run: str, sha: str) -> list[int]:
    """Runs whose failed mirror gate should be re-run."""
    own = fetch(f"repos/{repository}/actions/runs/{own_run}")
    workflow = own.get("workflow_id") if isinstance(own, dict) else None
    if workflow is None:
        raise RuntimeError("cannot read this run's workflow")
    listing = fetch(
        f"repos/{repository}/actions/runs?event=pull_request"
        f"&head_sha={urllib.parse.quote(sha)}&per_page=100"
    )
    found = []
    for run in listing.get("workflow_runs", []) if isinstance(listing, dict) else []:
        if (
            not isinstance(run, dict)
            or str(run.get("id")) == own_run
            or run.get("workflow_id") != workflow
            or run.get("head_sha") != sha
            or run.get("status") != "completed"
            or run.get("conclusion") != "failure"
        ):
            continue
        jobs = fetch(f"repos/{repository}/actions/runs/{run['id']}/jobs?per_page=100")
        if isinstance(jobs, dict) and gate_only_failure(jobs.get("jobs", [])):
            found.append(int(run["id"]))
    return sorted(found)


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    own_run = os.environ.get("GITHUB_RUN_ID", "")
    sha = os.environ.get("HEAD_SHA", "")
    if not (repository and own_run and sha):
        print("rerun-stale-gates: ERROR: missing run context", file=sys.stderr)
        return 1
    runs = stale_runs(request, repository, own_run, sha)
    for run in runs:
        request(f"repos/{repository}/actions/runs/{run}/rerun-failed-jobs", "POST")
        print(f"rerun-stale-gates: re-running the failed gate of run {run}")
    if not runs:
        print("rerun-stale-gates: no failed title-edit or draft gate for this commit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
