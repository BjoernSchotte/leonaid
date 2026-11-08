#!/usr/bin/env python3
"""Hold a required gate red while a full-ci run is pending (decision E-019).

Adding the ``full-ci`` label starts the complete run, but GitHub creates its
gate check only when the gate's jobs finish, about 40 minutes later. Until
then the newest gate check of the head commit would still be the green fast
one, and the pull request could be merged before the heavy suites ran.

So the first job of that run calls this script: it creates a completed,
failed check run with the gate's name on the head commit. Required checks
follow the newest check run of a name, so the pull request is blocked at
once. Only a newer gate supersedes it: the full run's own gate, or the gate
of a later push (which, with the label, is a full run too). A title edit or
label change mirrors it as red (``gate.py`` ``mirrored_result``).

Environment: GH_TOKEN (checks: write), GITHUB_REPOSITORY, HEAD_SHA,
GATE_NAME, RUN_URL.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections.abc import Callable, Mapping

# gate.py recognizes a hold by this title (its details link is not a run).
HOLD_TITLE = "full-ci requested: waiting for the complete run"
SHA = re.compile(r"[0-9a-f]{40}")

Post = Callable[[str, Mapping[str, object]], object]


def payload(gate: str, sha: str, run_url: str) -> dict[str, object]:
    if not SHA.fullmatch(sha):
        raise ValueError(f"not a commit SHA: {sha!r}")
    if not gate:
        raise ValueError("gate name missing")
    return {
        "name": gate,
        "head_sha": sha,
        "status": "completed",
        "conclusion": "failure",
        "details_url": run_url,
        "output": {
            "title": HOLD_TITLE,
            "summary": (
                f"The full-ci label was added. {gate} stays red until the gate "
                f"of the complete run ({run_url}) or of a later push replaces "
                "this check."
            ),
        },
    }


def post(path: str, body: Mapping[str, object]) -> object:
    request = urllib.request.Request(
        f"https://api.github.com/{path}",
        method="POST",
        data=json.dumps(body).encode(),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ.get('GH_TOKEN', '')}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main(environ: Mapping[str, str] = os.environ, send: Post = post) -> int:
    gate = environ.get("GATE_NAME", "")
    body = payload(gate, environ.get("HEAD_SHA", ""), environ.get("RUN_URL", ""))
    send(f"repos/{environ.get('GITHUB_REPOSITORY', '')}/check-runs", body)
    print(f"hold-gate: {gate} is red until the complete run's gate replaces it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
