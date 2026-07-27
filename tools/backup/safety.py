#!/usr/bin/env python3
"""Fail closed before backup or restore can touch operational data."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


REMOTE_PREFIXES = ("azure:", "b2:", "gs:", "rclone:", "rest:", "s3:", "sftp:")
SAFE_PROJECT = re.compile(r"^leonaid(?:-[a-z0-9][a-z0-9-]{0,47})?$")
SAFE_RESTORE_PROJECT = re.compile(r"^leonaid-restore-[a-z0-9][a-z0-9-]{0,39}$")


class SafetyError(RuntimeError):
    """A target is ambiguous or violates the backup boundary."""


def require_password_file(path: str) -> None:
    candidate = Path(path)
    if not candidate.is_file():
        raise SafetyError("Restic-Passwortdatei fehlt")
    mode = candidate.stat().st_mode & 0o777
    if mode & 0o077:
        raise SafetyError("Restic-Passwortdatei muss Modus 600 besitzen")
    if len(candidate.read_text(encoding="utf-8").strip()) < 24:
        raise SafetyError("Restic-Passwort muss mindestens 24 Zeichen lang sein")


def validate_repository(
    repository: str, *, allow_local_test: bool, project: str
) -> None:
    if repository.startswith(REMOTE_PREFIXES):
        if repository.startswith(("rest:", "sftp:")):
            parsed = urlparse(repository.split(":", 1)[1])
            if not parsed.hostname:
                raise SafetyError("Remote-Repository enthält keinen Host")
        return
    if allow_local_test and project.startswith(("leonaid-poc112-", "leonaid-poc113-")):
        candidate = Path(repository)
        if candidate.is_absolute() and candidate != Path("/"):
            return
    raise SafetyError(
        "Backup-Ziel muss außerhalb des VPS liegen "
        "(s3:, sftp:, rest:, rclone:, b2:, azure: oder gs:)"
    )


def validate_project(project: str) -> None:
    if not SAFE_PROJECT.fullmatch(project):
        raise SafetyError("Compose-Projektname ist nicht eindeutig oder nicht LeonAid")


def backup(arguments: argparse.Namespace) -> None:
    validate_project(arguments.project)
    validate_repository(
        arguments.repository,
        allow_local_test=arguments.allow_local_test,
        project=arguments.project,
    )
    require_password_file(arguments.password_file)


def restore(arguments: argparse.Namespace) -> None:
    validate_project(arguments.source_project)
    if not SAFE_RESTORE_PROJECT.fullmatch(arguments.target_project):
        raise SafetyError("Restore-Ziel muss explizit 'leonaid-restore-<name>' heißen")
    if arguments.source_project == arguments.target_project:
        raise SafetyError("Restore darf die Quellumgebung nicht überschreiben")
    expected = f"RESTORE:{arguments.target_project}"
    if arguments.confirm != expected:
        raise SafetyError(f"Bestätigung muss exakt '{expected}' lauten")
    validate_repository(
        arguments.repository,
        allow_local_test=arguments.allow_local_test,
        project=arguments.source_project,
    )
    require_password_file(arguments.password_file)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    subparsers = result.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--project", required=True)
    backup_parser.add_argument("--repository", required=True)
    backup_parser.add_argument("--password-file", required=True)
    backup_parser.add_argument("--allow-local-test", action="store_true")
    backup_parser.set_defaults(handler=backup)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--source-project", required=True)
    restore_parser.add_argument("--target-project", required=True)
    restore_parser.add_argument("--repository", required=True)
    restore_parser.add_argument("--password-file", required=True)
    restore_parser.add_argument("--confirm", required=True)
    restore_parser.add_argument("--allow-local-test", action="store_true")
    restore_parser.set_defaults(handler=restore)
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        arguments.handler(arguments)
    except (OSError, UnicodeError, SafetyError) as error:
        print(f"backup-safety: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"backup-safety: OK: {arguments.command}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
