#!/usr/bin/env python3
"""Re-run the failed gate-only runs of a commit after its real run completed.

A title edit, or a push while the pull request is a draft, starts runs in
which only the gate runs (tools/ci/gate.py: a title edit mirrors the newest
completed real gate and fails fast while there is none; a draft fails).
GitHub keeps the failed check runs of such a *failed* run blocking the pull
request even after the real run's gates passed (seen on #130); a cancelled
run does not block (#134). So refresh-gates.yml calls this script whenever a
pull-request run of a required workflow completes. When that run is a real
one (its selector ran, or its docs build was not refused as a draft) and its
commit is still the pull request's head, every completed *failed* gate-only
run of the same workflow and commit gets "re-run failed jobs": the re-run
mirrors the completed real gate (red stays red), and a draft gate reads the
pull request's current draft state (still a draft: fails again).

Environment: GH_TOKEN (actions: write), GITHUB_REPOSITORY, RUN_ID (the
completed run from the workflow_run event).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

Fetch = Callable[[str], object]
Post = Callable[[str], None]
# Job key of the reusable selector: a skipped caller job is reported under
# its key "select", a run one as "select / Select suites"
# (workflow_contract.py pins the key in every gated workflow).
SELECT_JOB_KEY = "select"
DRAFT_STEP = "Refuse a draft"
PAGE = 100


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


def as_dict(value: object, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"unexpected API answer for {what}")
    return value


def selector_jobs(jobs: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [
        job
        for job in jobs
        if str(job.get("name", "")) == SELECT_JOB_KEY
        or str(job.get("name", "")).startswith(SELECT_JOB_KEY + " / ")
    ]


def draft_refused(jobs: Sequence[Mapping[str, object]]) -> bool:
    for job in jobs:
        steps = job.get("steps")
        for step in steps if isinstance(steps, list) else []:
            if (
                isinstance(step, Mapping)
                and step.get("name") == DRAFT_STEP
                and step.get("conclusion") == "failure"
            ):
                return True
    return False


def gate_only(jobs: Sequence[Mapping[str, object]]) -> bool:
    """Only a gate ran and failed (title edit or draft), or a draft was refused."""
    selectors = selector_jobs(jobs)
    if selectors and all(job.get("conclusion") == "skipped" for job in selectors):
        return any(
            str(job.get("name", "")).endswith("gate")
            and job.get("conclusion") == "failure"
            for job in jobs
        )
    return draft_refused(jobs)


def real(jobs: Sequence[Mapping[str, object]]) -> bool:
    """The selector ran, or (docs.yml) a build ran without a draft refusal."""
    selectors = selector_jobs(jobs)
    if selectors:
        return any(job.get("conclusion") not in (None, "skipped") for job in selectors)
    return (
        bool(jobs)
        and not draft_refused(jobs)
        and any(job.get("conclusion") in ("success", "failure") for job in jobs)
    )


def paged(fetch: Fetch, path: str, key: str) -> list[dict[str, Any]]:
    """Every item of a paged listing; fails when the listing is short."""
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        data = as_dict(fetch(f"{path}&per_page={PAGE}&page={page}"), path)
        batch = data.get(key)
        if not isinstance(batch, list):
            raise RuntimeError(f"unexpected API answer for {path}")
        items += [item for item in batch if isinstance(item, dict)]
        total = int(data.get("total_count", len(items)))
        if len(batch) < PAGE or len(items) >= total:
            if len(items) < total:
                raise RuntimeError(f"{path}: {len(items)} of {total} items read")
            return items
        page += 1


def jobs_of(fetch: Fetch, repository: str, run: int) -> list[dict[str, Any]]:
    return paged(
        fetch, f"repos/{repository}/actions/runs/{run}/jobs?filter=latest", "jobs"
    )


def stale_runs(fetch: Fetch, repository: str, run_id: int) -> tuple[list[int], str]:
    """(runs to re-run, notice) for the completed run ``run_id``."""
    run = as_dict(fetch(f"repos/{repository}/actions/runs/{run_id}"), "the run")
    if run.get("event") != "pull_request":
        return [], "not a pull-request run"
    if not real(jobs_of(fetch, repository, run_id)):
        return [], "a gate-only run (title edit or draft) refreshes nothing"
    sha = str(run.get("head_sha", ""))
    for pull in run.get("pull_requests") or []:
        number = pull.get("number") if isinstance(pull, dict) else None
        current = as_dict(
            fetch(f"repos/{repository}/pulls/{number}"), "the pull request"
        )
        if current.get("head", {}).get("sha") != sha:
            return [], "the pull request moved on to a newer commit"
    runs = paged(
        fetch,
        f"repos/{repository}/actions/workflows/{run.get('workflow_id')}/runs"
        f"?event=pull_request&head_sha={urllib.parse.quote(sha)}",
        "workflow_runs",
    )
    stale = []
    for candidate in runs:
        if (
            candidate.get("id") != run_id
            and candidate.get("head_sha") == sha
            and candidate.get("status") == "completed"
            and candidate.get("conclusion") == "failure"
            and gate_only(jobs_of(fetch, repository, int(candidate["id"])))
        ):
            stale.append(int(candidate["id"]))
    return sorted(stale), ""


def refresh(fetch: Fetch, post: Post, repository: str, run_id: int) -> int:
    runs, notice = stale_runs(fetch, repository, run_id)
    if notice:
        print(f"rerun-stale-gates: nothing to do: {notice}")
        return 0
    failed = 0
    for run in runs:
        try:
            post(f"repos/{repository}/actions/runs/{run}/rerun-failed-jobs")
        except urllib.error.HTTPError as error:
            failed += 1
            print(
                f"rerun-stale-gates: ERROR: run {run} could not be re-run "
                f"(HTTP {error.code}); re-run its failed jobs by hand",
                file=sys.stderr,
            )
            continue
        print(f"rerun-stale-gates: re-running the failed gate of run {run}")
    if not runs:
        print("rerun-stale-gates: no failed gate-only run for this commit")
    return 1 if failed else 0


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("RUN_ID", "")
    if not repository or not run_id.isdigit():
        print("rerun-stale-gates: ERROR: missing run context", file=sys.stderr)
        return 1
    def post(path: str) -> None:
        request(path, "POST")

    return refresh(request, post, repository, int(run_id))


if __name__ == "__main__":
    raise SystemExit(main())
