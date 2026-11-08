#!/usr/bin/env python3
"""Run choices of the post-merge tier (decision E-018/E-019).

``base``: the commit the post-merge selection diffs from, the head of the
newest *green* run of the calling workflow on main (push, schedule or
dispatch; never a pull-request run, never this run's own commit). A red or
superseded run's paths therefore stay in the next diff. Prints the SHA, or
nothing (the selector then runs the complete suite) when there is none or
the API cannot be read; never fails.

``latest``: the run nightly-watchdog.yml judges for one entry, read as the
runs API JSON from stdin: for ``--event push`` the newest completed run that
was not cancelled (superseded or cancelled by hand: its commits are in the
next run's diff), for ``--event schedule`` the newest completed run whose
title contains ``--word``. Prints ``id<TAB>conclusion<TAB>created_at<TAB>url``
or nothing.

Standard library only (runs on the plain runner Python).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

BASE_EVENTS = frozenset({"push", "schedule", "workflow_dispatch"})


def newest_first(runs: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(
        (run for run in runs if isinstance(run, Mapping)),
        key=lambda run: (str(run.get("created_at", "")), int(run.get("id") or 0)),
        reverse=True,
    )


def pick_base(runs: Sequence[Mapping[str, Any]], sha: str) -> str | None:
    for run in newest_first(runs):
        if (
            run.get("conclusion") == "success"
            and run.get("status", "completed") == "completed"
            and run.get("event") in BASE_EVENTS
            and run.get("head_branch") == "main"
            and run.get("head_sha")
            and run.get("head_sha") != sha
        ):
            return str(run["head_sha"])
    return None


def pick_latest(
    runs: Sequence[Mapping[str, Any]], event: str, word: str = ""
) -> Mapping[str, Any] | None:
    for run in newest_first(runs):
        if run.get("status", "completed") != "completed" or run.get("event") != event:
            continue
        if event == "push" and run.get("conclusion") == "cancelled":
            continue
        if word and word not in str(run.get("display_title", "")):
            continue
        return run
    return None


def workflow_file(workflow_ref: str) -> str:
    """ci.yml from owner/repo/.github/workflows/ci.yml@refs/heads/main."""
    return workflow_ref.split("@", 1)[0].rsplit("/", 1)[-1]


def fetch_runs(repository: str, workflow: str, token: str) -> list[Mapping[str, Any]]:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}"
        "/runs?branch=main&status=success&per_page=50",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    return runs if isinstance(runs, list) else []


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] = os.environ
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("base", help="green base of this push (env WORKFLOW_REF, SHA)")
    latest = commands.add_parser(
        "latest", help="watchdog run choice (runs JSON on stdin)"
    )
    latest.add_argument("--event", required=True, choices=("push", "schedule"))
    latest.add_argument("--word", default="")
    args = parser.parse_args(argv)
    if args.command == "base":
        try:
            runs = fetch_runs(
                environ.get("GITHUB_REPOSITORY", ""),
                workflow_file(environ.get("WORKFLOW_REF", "")),
                environ.get("GH_TOKEN", ""),
            )
        except (OSError, ValueError) as error:
            print(f"post-merge: WARNING: run lookup failed: {error}", file=sys.stderr)
            return 0
        base = pick_base(runs, environ.get("SHA", ""))
        if base:
            print(base)
        return 0
    data = json.load(sys.stdin)
    listed = data.get("workflow_runs") if isinstance(data, dict) else None
    run = pick_latest(listed if isinstance(listed, list) else [], args.event, args.word)
    if run is not None:
        print(
            "\t".join(
                str(run.get(key, ""))
                for key in ("id", "conclusion", "created_at", "html_url")
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
