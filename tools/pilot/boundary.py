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
ALLOWED_PUBLIC_UPLOADS = (".artifacts/sbom/*.cdx.json",)
ALLOWED_PUBLIC_UPLOAD_PREFIXES = (".artifacts/ci/",)
UPLOAD_ACTION = "actions/upload-artifact@"


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


def upload_paths(workflow: Path, text: str) -> list[str]:
    lines = text.splitlines()
    paths: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip().removeprefix("- ").strip()
        if not stripped.startswith("uses:"):
            continue
        action = stripped.removeprefix("uses:").strip()
        if "upload" in action.casefold() and not action.startswith(UPLOAD_ACTION):
            raise BoundaryError(
                f"{workflow}: unbekannte Upload-Action ist nicht freigegeben: {action}"
            )
        if not action.startswith(UPLOAD_ACTION):
            continue
        action_indent = len(line) - len(line.lstrip())
        path: str | None = None
        for candidate in lines[index + 1 :]:
            candidate_stripped = candidate.strip()
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if (
                candidate_stripped.startswith("- ")
                and candidate_indent <= action_indent
            ):
                break
            if candidate_stripped.startswith("path:"):
                if path is not None:
                    raise BoundaryError(
                        f"{workflow}: Upload-Schritt enthält mehrere path-Werte"
                    )
                path = candidate_stripped.removeprefix("path:").strip()
        if path is None:
            raise BoundaryError(f"{workflow}: Upload-Schritt enthält keinen path-Wert")
        path = path.strip("\"'")
        if (
            not path
            or path in {"|", ">"}
            or "\n" in path
            or path.startswith("/")
            or ".." in Path(path).parts
        ):
            raise BoundaryError(
                f"{workflow}: Uploadpfad ist dynamisch oder nicht sicher: {path!r}"
            )
        paths.append(path)
    return paths


def check_workflows(root: Path) -> None:
    workflow_root = root / ".github" / "workflows"
    workflows = sorted(
        (
            *workflow_root.glob("*.yml"),
            *workflow_root.glob("*.yaml"),
        )
    )
    if not workflows:
        raise BoundaryError("GitHub-Workflows fehlen")
    upload_count = 0
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for path in upload_paths(workflow, text):
            upload_count += 1
            if path in ALLOWED_PUBLIC_UPLOADS:
                continue
            if any(
                path.startswith(prefix) for prefix in ALLOWED_PUBLIC_UPLOAD_PREFIXES
            ):
                continue
            raise BoundaryError(
                f"{workflow}: nicht freigegebener öffentlicher Uploadpfad: {path}"
            )
    if upload_count == 0:
        raise BoundaryError("GitHub-Workflows enthalten keinen geprüften Upload")


def check(root: Path) -> None:
    check_ignored_paths(root)
    check_git_index_and_history(root)
    check_workflows(root)


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
