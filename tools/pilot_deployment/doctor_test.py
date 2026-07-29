#!/usr/bin/env python3
"""Negative contract tests for the deployment doctor without test doubles."""

from __future__ import annotations

import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable

from tools.pilot_deployment.doctor import (
    DoctorError,
    parse_resolve,
    read_dotenv,
    validate_backup,
    validate_environment,
)


def rejected(label: str, operation: Callable[[], object]) -> None:
    try:
        operation()
    except DoctorError:
        return
    raise AssertionError(f"Doctor-Mutation wurde akzeptiert: {label}")


def write_environment(path: Path, values: dict[str, str]) -> None:
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    path.chmod(0o600)


def main() -> None:
    root = Path(sys.argv[1]).resolve()
    source_environment = Path(sys.argv[2]).resolve()
    compose_path = Path(sys.argv[3]).resolve()
    backup_path = Path(sys.argv[4]).resolve()
    expected_commit = sys.argv[5]
    values = read_dotenv(source_environment)
    compose_config: dict[str, Any] = json.loads(
        compose_path.read_text(encoding="utf-8")
    )

    with tempfile.TemporaryDirectory() as directory:
        temporary_root = Path(directory)
        environment_path = temporary_root / "production.env"
        write_environment(environment_path, values)
        project = validate_environment(
            values,
            root=root,
            env_file=environment_path,
            compose_config=compose_config,
            expected_release_commit=expected_commit,
        )
        validate_backup(backup_path, project=project, maximum_age_hours=26)

        local_backup = dict(values)
        local_backup["RESTIC_REPOSITORY"] = "/srv/leonaid-backup"
        write_environment(environment_path, local_backup)
        rejected(
            "lokales Backup-Ziel",
            lambda: validate_environment(
                local_backup,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=expected_commit,
            ),
        )

        wrong_stage = dict(values)
        wrong_stage["LEONAID_DEPLOYMENT_STAGE"] = "staging"
        write_environment(environment_path, wrong_stage)
        rejected(
            "Projekt/Stage-Verwechslung",
            lambda: validate_environment(
                wrong_stage,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=expected_commit,
            ),
        )

        duplicate_secrets = dict(values)
        duplicate_secrets["MAIL_SMTP_PASSWORD"] = duplicate_secrets[
            "LEONAID_SECRET_KEY"
        ]
        write_environment(environment_path, duplicate_secrets)
        rejected(
            "wiederverwendetes Secret",
            lambda: validate_environment(
                duplicate_secrets,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=expected_commit,
            ),
        )

        wrong_commit = "f" * 40
        rejected(
            "falscher Release-Commit",
            lambda: validate_environment(
                values,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=wrong_commit,
            ),
        )

        stale_payload = json.loads(backup_path.read_text(encoding="utf-8"))
        stale_payload = copy.deepcopy(stale_payload)
        stale_payload["createdAt"] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=27)
        ).isoformat()
        stale_path = temporary_root / "stale-backup.json"
        stale_path.write_text(json.dumps(stale_payload), encoding="utf-8")
        rejected(
            "veraltetes Backup",
            lambda: validate_backup(
                stale_path,
                project=project,
                maximum_age_hours=26,
            ),
        )

        rejected(
            "ungültiges DNS-Override",
            lambda: parse_resolve(["portal.leonaid.org=:70000"]),
        )

    print(
        "pilot-deployment-doctor-test: OK: sechs unsichere reale "
        "Datei-/Parameter-Mutationen fail-closed abgewiesen"
    )


if __name__ == "__main__":
    main()
