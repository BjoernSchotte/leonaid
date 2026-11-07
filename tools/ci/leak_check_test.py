#!/usr/bin/env python3
"""tools/ci/leak-check.sh fails and cleans exactly the project a shard leaked."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "leak-check.sh"

# A stand-in for the Docker CLI: listings print the projects in $STATE,
# every other call is recorded in $CALLS.
FAKE_DOCKER = """#!/bin/sh
quiet=false
format=false
want=""
for argument; do
  case "$argument" in
    -q|-aq) quiet=true ;;
    "{{.Label"*) format=true ;;
    label=com.docker.compose.project=*) want=${argument#label=com.docker.compose.project=} ;;
  esac
done
case "$1 $2" in
  "ps "*|"network ls"|"volume ls")
    if [ -n "$want" ]; then lines=$(grep -x "$want" "$STATE" || true); else lines=$(cat "$STATE"); fi
    [ -n "$lines" ] || exit 0
    if [ "$format" = true ]; then printf '%s\\n' "$lines"
    elif [ "$quiet" = true ]; then printf '%s\\n' "$lines" | sed 's/^/id-/'
    else printf '%s\\n' "$lines" | sed 's/^/  /'; fi
    ;;
  *) echo "$*" >>"$CALLS" ;;
esac
"""
FAILURES: list[str] = []


def expect(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def run(
    directory: Path, *arguments: str, ci: bool = True
) -> subprocess.CompletedProcess[str]:
    env = dict(
        os.environ,
        PATH=f"{directory}:{os.environ['PATH']}",
        STATE=str(directory / "state"),
        CALLS=str(directory / "calls"),
    )
    env.pop("GITHUB_ACTIONS", None)
    if ci:
        env["GITHUB_ACTIONS"] = "true"
    return subprocess.run(
        ["/bin/sh", str(SCRIPT), *arguments],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        docker = directory / "docker"
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)
        state, calls, snapshot = (
            directory / "state",
            directory / "calls",
            directory / "snapshot",
        )
        state.write_text("other-job-stack\n")
        calls.write_text("")
        expect(run(directory, "snapshot", str(snapshot)).returncode == 0, "snapshot")
        # Nothing new: passes and removes nothing.
        clean = run(directory, "check", str(snapshot), "core")
        expect(clean.returncode == 0, f"clean shard must pass: {clean.stderr}")
        expect(calls.read_text() == "", "a clean shard must remove nothing")
        # A leaked project fails the shard that leaked and is removed alone.
        state.write_text("other-job-stack\nleonaid-poc023-test-1-2\n")
        leak = run(directory, "check", str(snapshot), "compose")
        expect(leak.returncode == 1, "a leaking shard must fail")
        expect(
            "compose left Compose project leonaid-poc023-test-1-2" in leak.stderr,
            f"the leak must name shard and project: {leak.stderr}",
        )
        removed = calls.read_text()
        for call in (
            "rm --force --volumes id-leonaid-poc023-test-1-2",
            "network rm id-leonaid-poc023-test-1-2",
            "volume rm --force id-leonaid-poc023-test-1-2",
        ):
            expect(call in removed.splitlines(), f"missing {call!r}: {removed}")
        expect("other-job-stack" not in removed, f"foreign project touched: {removed}")
        # Outside CI nothing is listed, compared or removed.
        calls.write_text("")
        local = run(directory, "check", str(snapshot), "compose", ci=False)
        expect(local.returncode == 0 and calls.read_text() == "", "local no-op")
        expect(run(directory, "bogus").returncode == 64, "unknown command")
    if FAILURES:
        for failure in FAILURES:
            print(f"ci-leak-check-test: ERROR: {failure}", file=sys.stderr)
        return 1
    print("ci-leak-check-test: OK: leaking shard fails and only its project is removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
