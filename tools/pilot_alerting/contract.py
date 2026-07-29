#!/usr/bin/env python3
"""File contracts for the isolated real Alertmanager delivery test."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.request import urlopen

REQUIRED_FILES = (
    "core.dump",
    "rustfs-data.tar",
    "twenty-storage.tar",
    "twenty.dump",
)


def write_manifest(path: Path, *, project: str, stale: bool) -> None:
    timestamp = datetime.now(timezone.utc)
    if stale:
        timestamp -= timedelta(hours=48)
    document = {
        "schemaVersion": 1,
        "sourceProject": project,
        "createdAt": timestamp.isoformat(),
        "files": {
            name: {"sha256": chr(97 + index) * 64, "size": index + 1}
            for index, name in enumerate(REQUIRED_FILES)
        },
    }
    path.write_text(
        json.dumps(document, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _documents(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    result: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(document, dict):
            result.append(document)
    return result


def has_event(
    path: Path,
    *,
    alert_name: str,
    status: str,
    dependency: str | None,
) -> bool:
    for document in _documents(path):
        payload = document.get("payload")
        if not isinstance(payload, dict) or payload.get("status") != status:
            continue
        alerts = payload.get("alerts")
        if not isinstance(alerts, list):
            continue
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            labels = alert.get("labels")
            if not isinstance(labels, dict) or labels.get("alertname") != alert_name:
                continue
            if dependency is not None and labels.get("dependency") != dependency:
                continue
            return True
    return False


def assert_no_sensitive(path: Path, values: tuple[str, ...]) -> None:
    content = path.read_text(encoding="utf-8") if path.is_file() else ""
    found = [value for value in values if value and value in content]
    if found:
        raise RuntimeError("alert_payload_contains_synthetic_pii")


def monitoring_status(url: str, *, check: str, expected: str) -> None:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - isolated test network
        document = json.load(response)
    if not isinstance(document, dict):
        raise RuntimeError("monitoring_status_not_an_object")
    item = document.get(check)
    if not isinstance(item, dict) or item.get("status") != expected:
        raise RuntimeError(f"monitoring_status_mismatch:{check}:{item!r}")


def alertmanager_has(url: str, *, alert_name: str) -> None:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - isolated test network
        document = json.load(response)
    if not isinstance(document, list):
        raise RuntimeError("alertmanager_response_not_a_list")
    for item in document:
        if not isinstance(item, dict):
            continue
        labels = item.get("labels")
        if isinstance(labels, dict) and labels.get("alertname") == alert_name:
            return
    raise RuntimeError(f"alertmanager_alert_missing:{alert_name}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    commands = result.add_subparsers(dest="command", required=True)
    write = commands.add_parser("write-manifest")
    write.add_argument("path", type=Path)
    write.add_argument("--project", required=True)
    write.add_argument("--stale", action="store_true")
    event = commands.add_parser("has-event")
    event.add_argument("path", type=Path)
    event.add_argument("--alert", required=True)
    event.add_argument("--status", choices=("firing", "resolved"), required=True)
    event.add_argument("--dependency")
    wait = commands.add_parser("wait-event")
    wait.add_argument("path", type=Path)
    wait.add_argument("--alert", required=True)
    wait.add_argument("--status", choices=("firing", "resolved"), required=True)
    wait.add_argument("--dependency")
    wait.add_argument("--timeout-seconds", type=float, default=75)
    sensitive = commands.add_parser("assert-no-sensitive")
    sensitive.add_argument("path", type=Path)
    sensitive.add_argument("values", nargs="+")
    monitoring = commands.add_parser("assert-monitoring-status")
    monitoring.add_argument("--url", required=True)
    monitoring.add_argument("--check", choices=("backup", "disk", "tls"), required=True)
    monitoring.add_argument("--status", choices=("ready", "critical"), required=True)
    alertmanager = commands.add_parser("assert-alertmanager")
    alertmanager.add_argument("--url", required=True)
    alertmanager.add_argument("--alert", required=True)
    return result


def main() -> int:
    arguments = parser().parse_args()
    if arguments.command == "write-manifest":
        write_manifest(
            arguments.path,
            project=arguments.project,
            stale=arguments.stale,
        )
        return 0
    if arguments.command == "has-event":
        return (
            0
            if has_event(
                arguments.path,
                alert_name=arguments.alert,
                status=arguments.status,
                dependency=arguments.dependency,
            )
            else 1
        )
    if arguments.command == "wait-event":
        deadline = time.monotonic() + arguments.timeout_seconds
        while time.monotonic() < deadline:
            if has_event(
                arguments.path,
                alert_name=arguments.alert,
                status=arguments.status,
                dependency=arguments.dependency,
            ):
                return 0
            time.sleep(1)
        print(
            "pilot-alerting-contract: BLOCKED: alert_delivery_timeout",
            file=sys.stderr,
        )
        return 1
    if arguments.command == "assert-no-sensitive":
        try:
            assert_no_sensitive(arguments.path, tuple(arguments.values))
        except RuntimeError as error:
            print(f"pilot-alerting-contract: BLOCKED: {error}", file=sys.stderr)
            return 1
        return 0
    if arguments.command == "assert-monitoring-status":
        try:
            monitoring_status(
                arguments.url,
                check=arguments.check,
                expected=arguments.status,
            )
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            print(f"pilot-alerting-contract: BLOCKED: {error}", file=sys.stderr)
            return 1
        return 0
    if arguments.command == "assert-alertmanager":
        try:
            alertmanager_has(arguments.url, alert_name=arguments.alert)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            print(f"pilot-alerting-contract: BLOCKED: {error}", file=sys.stderr)
            return 1
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
