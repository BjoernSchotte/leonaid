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
    PENDING_INTEGRATION_KEY,
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

        # A first install may carry the pending marker; no other gate may.
        pending_key = dict(values)
        pending_key["TWENTY_INTEGRATION_API_KEY"] = PENDING_INTEGRATION_KEY
        write_environment(environment_path, pending_key)
        rejected(
            "pending integration key outside a first install",
            lambda: validate_environment(
                pending_key,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=expected_commit,
            ),
        )
        validate_environment(
            pending_key,
            root=root,
            env_file=environment_path,
            compose_config=compose_config,
            expected_release_commit=expected_commit,
            first_install=True,
        )
        other_placeholder = dict(pending_key)
        other_placeholder["LEONAID_SECRET_KEY"] = PENDING_INTEGRATION_KEY
        write_environment(environment_path, other_placeholder)
        rejected(
            "pending marker on another secret",
            lambda: validate_environment(
                other_placeholder,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=expected_commit,
                first_install=True,
            ),
        )

        heartbeat = temporary_root / "alert-heartbeat-url"
        for label, url, mode in (
            ("heartbeat equals the operator webhook", None, 0o600),
            ("plain-HTTP heartbeat", "http://hc-ping.leonaid.org/check\n", 0o600),
            ("reserved heartbeat host", "https://hc.example.org/check\n", 0o600),
            (
                "world-readable heartbeat file",
                "https://hc-ping.leonaid.org/check\n",
                0o644,
            ),
        ):
            if url is None:
                url = Path(values["LEONAID_ALERT_WEBHOOK_URL_FILE"]).read_text(
                    encoding="utf-8"
                )
            heartbeat.write_text(url, encoding="utf-8")
            heartbeat.chmod(mode)
            changed = dict(values)
            changed["LEONAID_ALERT_HEARTBEAT_URL_FILE"] = str(heartbeat)
            write_environment(environment_path, changed)
            rejected(
                label,
                lambda: validate_environment(
                    changed,
                    root=root,
                    env_file=environment_path,
                    compose_config=compose_config,
                    expected_release_commit=expected_commit,
                ),
            )
        missing_heartbeat = dict(values)
        del missing_heartbeat["LEONAID_ALERT_HEARTBEAT_URL_FILE"]
        write_environment(environment_path, missing_heartbeat)
        rejected(
            "missing heartbeat configuration",
            lambda: validate_environment(
                missing_heartbeat,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=expected_commit,
            ),
        )

        # pilot-backup repairs a missing or stale backup, but never accepts a
        # manifest of another installation.
        missing_manifest = temporary_root / "missing-backup.json"
        validate_backup(
            missing_manifest,
            project=project,
            maximum_age_hours=26,
            tolerate_missing_or_stale=True,
        )
        rejected(
            "missing backup outside pilot-backup",
            lambda: validate_backup(
                missing_manifest, project=project, maximum_age_hours=26
            ),
        )
        validate_backup(
            stale_path,
            project=project,
            maximum_age_hours=26,
            tolerate_missing_or_stale=True,
        )
        foreign_payload = dict(stale_payload)
        foreign_payload["sourceProject"] = "leonaid-production-other-club"
        foreign_path = temporary_root / "foreign-backup.json"
        foreign_path.write_text(json.dumps(foreign_payload), encoding="utf-8")
        rejected(
            "backup manifest of another installation",
            lambda: validate_backup(
                foreign_path,
                project=project,
                maximum_age_hours=26,
                tolerate_missing_or_stale=True,
            ),
        )

    print(
        "pilot-deployment-doctor-test: OK: unsafe real file and parameter "
        "mutations rejected fail-closed, including first-install, heartbeat "
        "and backup-gate boundaries"
    )


if __name__ == "__main__":
    main()
