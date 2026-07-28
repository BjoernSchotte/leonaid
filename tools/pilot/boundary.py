#!/usr/bin/env python3
"""Enforce that private pilot paths never enter Git or public CI uploads."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

PRIVATE_PREFIXES = (
    ".local/pilot/",
    ".local/test-logins.md",
)


class BoundaryError(RuntimeError):
    """Raised when a private pilot path crosses a public boundary."""


def git_lines(root: Path, *arguments: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def private_paths(paths: list[str]) -> list[str]:
    return sorted(
        {
            path
            for path in paths
            if any(
                path == prefix.rstrip("/") or path.startswith(prefix)
                for prefix in PRIVATE_PREFIXES
            )
        }
    )


def check_ignored_paths(root: Path) -> None:
    probes = [
        ".local/pilot/intake/private.xlsx",
        ".local/pilot/evidence/private.pdf",
        ".local/pilot/backups/production.dump",
        ".local/pilot/manifests/evidence.json",
        ".local/test-logins.md",
    ]
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin"],
        input="\n".join(probes) + "\n",
        check=False,
        capture_output=True,
        text=True,
    )
    ignored = set(result.stdout.splitlines())
    missing = [probe for probe in probes if probe not in ignored]
    if result.returncode not in {0, 1} or missing:
        raise BoundaryError(f"private Pfade sind nicht ignoriert: {', '.join(missing)}")


def check_git_index_and_history(root: Path) -> None:
    indexed = private_paths(git_lines(root, "ls-files", "--cached"))
    if indexed:
        raise BoundaryError(f"private Pilotdateien im Git-Index: {', '.join(indexed)}")
    historical = private_paths(
        git_lines(root, "log", "--all", "--format=", "--name-only")
    )
    if historical:
        raise BoundaryError(
            f"private Pilotdateien in Git-Historie: {', '.join(historical)}"
        )


def check_workflow(root: Path) -> None:
    workflow = root / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")
    forbidden = (
        ".local/pilot",
        ".local/test-logins",
        ".artifacts/poc122",
        ".artifacts/failures",
    )
    leaks = [value for value in forbidden if value in text]
    if leaks:
        raise BoundaryError(
            "CI-Workflow referenziert private/unsanitisierte Uploadpfade: "
            + ", ".join(leaks)
        )
    if "path: .artifacts/ci/" not in text:
        raise BoundaryError("CI-Uploads sind nicht auf sanitisierte Pfade begrenzt")


def check(root: Path) -> None:
    check_ignored_paths(root)
    check_git_index_and_history(root)
    check_workflow(root)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    try:
        check(arguments.root.resolve())
    except (BoundaryError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"pilot-data-boundary: BLOCKED: {error}\n")
    print(
        "pilot-data-boundary: OK: private Pfade sind ignoriert, "
        "Git-frei und von öffentlichen CI-Uploads getrennt"
    )


if __name__ == "__main__":
    main()
