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
    due_decisions,
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
    raise AssertionError(f"doctor mutation was accepted: {label}")


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
            "local backup target",
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
            "project/stage mix-up",
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
            "reused secret",
            lambda: validate_environment(
                duplicate_secrets,
                root=root,
                env_file=environment_path,
                compose_config=compose_config,
                expected_release_commit=expected_commit,
            ),
        )

        # Web Push is optional; a key needs a real contact (ADR-0017).
        for label, key, value in (
            (
                "VAPID subject of the template",
                "LEONAID_VAPID_SUBJECT",
                "mailto:operations@example.org",
            ),
            (
                "VAPID key placeholder",
                "LEONAID_VAPID_PRIVATE_KEY",
                "__RANDOM_P256_PRIVATE_KEY__",
            ),
            (
                "VAPID key is no P-256 scalar",
                "LEONAID_VAPID_PRIVATE_KEY",
                values["LEONAID_SECRET_KEY"],
            ),
        ):
            push_values = dict(values)
            push_values[key] = value
            write_environment(environment_path, push_values)
            rejected(
                label,
                # Called at once by rejected(), before the next round.
                lambda: validate_environment(
                    push_values,
                    root=root,
                    env_file=environment_path,
                    compose_config=compose_config,
                    expected_release_commit=expected_commit,
                ),
            )
        # The key in the env file must reach the API and the worker.
        for service, key in (
            ("api", "LEONAID_VAPID_PRIVATE_KEY"),
            ("worker", "LEONAID_VAPID_PRIVATE_KEY"),
            ("worker", "LEONAID_VAPID_SUBJECT"),
        ):
            not_passed = copy.deepcopy(compose_config)
            del not_passed["services"][service]["environment"][key]
            rejected(
                f"{key} not passed to {service}",
                lambda: validate_environment(
                    values,
                    root=root,
                    env_file=environment_path,
                    compose_config=not_passed,
                    expected_release_commit=expected_commit,
                ),
            )
        without_push = dict(values)
        without_push["LEONAID_VAPID_PRIVATE_KEY"] = ""
        without_push["LEONAID_VAPID_SUBJECT"] = ""
        write_environment(environment_path, without_push)
        validate_environment(
            without_push,
            root=root,
            env_file=environment_path,
            compose_config=compose_config,
            expected_release_commit=expected_commit,
        )
        write_environment(environment_path, values)

        wrong_commit = "f" * 40
        rejected(
            "wrong release commit",
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
            "stale backup",
            lambda: validate_backup(
                stale_path,
                project=project,
                maximum_age_hours=26,
            ),
        )

        rejected(
            "invalid DNS override",
            lambda: parse_resolve(["portal.leonaid.org=:70000"]),
        )

        # Without the key the API no longer waits for Twenty (E-031), so a
        # forgotten key must fail here instead of looking ready.
        for label, missing in (
            ("missing integration key", True),
            ("empty integration key", False),
        ):
            without_key = dict(values)
            if missing:
                del without_key["TWENTY_INTEGRATION_API_KEY"]
            else:
                without_key["TWENTY_INTEGRATION_API_KEY"] = ""
            write_environment(environment_path, without_key)
            rejected(
                label,
                lambda: validate_environment(
                    without_key,
                    root=root,
                    env_file=environment_path,
                    compose_config=compose_config,
                    expected_release_commit=expected_commit,
                    first_install=True,
                ),
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

        # Backup topology (specs/multi-domain R11): with the CMS enabled the
        # backup must hold the CMS data; only pilot-cms-provision accepts the
        # last backup from before the CMS, and pilot-backup takes a new one.
        fresh_payload = json.loads(backup_path.read_text(encoding="utf-8"))
        cms_payload = copy.deepcopy(fresh_payload)
        cms_payload["schemaVersion"] = 2
        for name in ("emdash.dump", "cms-bootstrap-state.tar"):
            cms_payload["files"][name] = {"sha256": "c" * 64, "size": 1}
        cms_path = temporary_root / "cms-backup.json"
        cms_path.write_text(json.dumps(cms_payload), encoding="utf-8")
        validate_backup(
            cms_path, project=project, maximum_age_hours=26, cms_enabled=True
        )
        rejected(
            "legacy backup while the CMS is enabled",
            lambda: validate_backup(
                backup_path, project=project, maximum_age_hours=26, cms_enabled=True
            ),
        )
        validate_backup(
            backup_path,
            project=project,
            maximum_age_hours=26,
            cms_enabled=True,
            allow_backup_without_cms=True,
        )
        validate_backup(
            backup_path,
            project=project,
            maximum_age_hours=26,
            cms_enabled=True,
            tolerate_missing_or_stale=True,
        )
        rejected(
            "CMS backup while the CMS is disabled",
            lambda: validate_backup(cms_path, project=project, maximum_age_hours=26),
        )
        for label, version, extra in (
            ("schema 2 without CMS data", 2, ()),
            ("schema 1 with CMS data", 1, ("emdash.dump",)),
        ):
            mismatch = copy.deepcopy(fresh_payload)
            mismatch["schemaVersion"] = version
            for name in extra:
                mismatch["files"][name] = {"sha256": "d" * 64, "size": 1}
            mismatch_path = temporary_root / f"mismatch-{version}.json"
            mismatch_path.write_text(json.dumps(mismatch), encoding="utf-8")

            def validate_mismatch(path: Path = mismatch_path) -> None:
                validate_backup(
                    path,
                    project=project,
                    maximum_age_hours=26,
                    cms_enabled=True,
                    allow_backup_without_cms=True,
                )

            rejected(label, validate_mismatch)

    # The real register still has open decisions: production waits for them
    # at the first start and at every later gate, staging never does.
    for gate in ("pilot-deploy", "upgrade"):
        open_ids, _ = due_decisions(
            root, gate=gate, staging=False, deployment_only=False
        )
        if "PILOT-TAX-001" not in open_ids:
            raise AssertionError(f"production {gate} ignores the tax decision")
        if due_decisions(root, gate=gate, staging=True, deployment_only=False) != (
            [],
            [],
        ):
            raise AssertionError(f"staging {gate} waits for the decision register")

    print(
        "pilot-deployment-doctor-test: OK: unsafe real file and parameter "
        "mutations rejected fail-closed, including first-install, heartbeat "
        "and backup-gate boundaries"
    )


if __name__ == "__main__":
    main()
