#!/usr/bin/env python3
"""cms_bootstrap_state (tools/backup/cms-bootstrap-state.sh) fails closed.

Runs the real shell function with a stub `docker` on PATH: only an absent
volume or an absent state.json means "unfinished"; a Docker error or an
unreadable state fails, so a live CMS never falls back to a backup without
its data.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name("cms-bootstrap-state.sh")


def probe(volume_ls: str, run: str) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as directory:
        stub = Path(directory) / "docker"
        stub.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            f"  volume) {volume_ls} ;;\n"
            f"  run) {run} ;;\n"
            "  *) exit 2 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        result = subprocess.run(
            [
                "sh",
                "-c",
                f'. "{SCRIPT}"; cms_bootstrap_state proof_cms-bootstrap-state',
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "PATH": f"{directory}:{os.environ['PATH']}"},
            check=False,
        )
        return result.returncode, result.stdout.strip()


def main() -> None:
    listed = "echo proof_cms-bootstrap-state"
    cases = [
        ("no volume", "true", "exit 9", (0, "unfinished")),
        ("no state.json", listed, "echo ABSENT", (0, "unfinished")),
        ("armed", listed, """echo '{"status":"armed"}'""", (0, "unfinished")),
        ("consumed", listed, """echo '{"status":"consumed"}'""", (0, "unfinished")),
        ("complete", listed, """echo '{"status":"complete"}'""", (0, "complete")),
        ("volume listing fails", "exit 1", "echo ABSENT", (1, "")),
        ("probe container fails", listed, "exit 125", (1, "")),
        ("malformed state", listed, "echo garbage", (1, "")),
    ]
    for label, volume_ls, run, expected in cases:
        actual = probe(volume_ls, run)
        assert actual == expected, f"{label}: {actual} != {expected}"
    print(
        "cms-bootstrap-state-test: OK: only an absent volume or state.json is "
        "unfinished; Docker errors and unreadable states fail closed"
    )


if __name__ == "__main__":
    main()
