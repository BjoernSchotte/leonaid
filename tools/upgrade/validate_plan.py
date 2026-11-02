#!/usr/bin/env python3
"""Validate the auditable POC-113 upgrade decision before touching data."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PINNED_IMAGE = re.compile(r"^[^@\s]+:[^@:\s]+@sha256:[0-9a-f]{64}$")
REQUIRED_COMPONENTS = {
    "twenty",
    "rustfs",
    "twenty-queue-store",
    "postgres",
    "leonaid-core",
}
REQUIRED_GATES = {
    "pins",
    "release-notes",
    "fresh-encrypted-backup",
    "pre-upgrade-contract",
    "pre-upgrade-e2e",
    "maintenance-write-rejection",
    "target-health",
    "post-upgrade-contract",
    "post-upgrade-e2e",
    "rollback-recovery",
}


class InvalidPlan(RuntimeError):
    pass


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidPlan(f"{path}: invalid JSON: {error}") from error
    if not isinstance(value, dict):
        raise InvalidPlan(f"{path}: root must be an object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidPlan(message)


def system_images(lock: dict[str, Any]) -> dict[str, str]:
    systems = lock.get("systems")
    if not isinstance(systems, list):
        raise InvalidPlan("external-systems.lock: systems missing")
    result: dict[str, str] = {}
    for item in systems:
        require(
            isinstance(item, dict), "external-systems.lock: system is not an object"
        )
        system_id = item.get("id")
        image = item.get("image")
        if isinstance(system_id, str) and isinstance(image, str):
            result[system_id] = image
    return result


def validate(matrix: dict[str, Any], lock: dict[str, Any]) -> None:
    require(matrix.get("schemaVersion") == 1, "schemaVersion must be 1")
    window = matrix.get("changeWindow")
    if not isinstance(window, dict):
        raise InvalidPlan("changeWindow missing")
    for gate in (
        "backupRequired",
        "goldenCloneRequired",
        "maintenanceModeRequired",
        "releaseNotesReviewed",
    ):
        require(window.get(gate) is True, f"changeWindow.{gate} must be true")

    components = matrix.get("components")
    if not isinstance(components, list):
        raise InvalidPlan("components missing")
    by_id = {
        item.get("id"): item
        for item in components
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    require(set(by_id) == REQUIRED_COMPONENTS, "component matrix is incomplete")
    locked = system_images(lock)

    for component_id, component in by_id.items():
        require(
            component.get("sourceVersion") != component.get("targetVersion"),
            f"{component_id}: source and target version are equal",
        )
        notes = component.get("releaseNotes")
        require(
            isinstance(notes, list)
            and len(notes) >= 1
            and all(
                isinstance(url, str) and url.startswith("https://") for url in notes
            ),
            f"{component_id}: release notes sources missing",
        )
        migration = component.get("migration")
        require(
            isinstance(migration, dict)
            and migration.get("reviewed") is True
            and isinstance(migration.get("command"), str)
            and bool(migration["command"].strip()),
            f"{component_id}: migration is not reviewed",
        )
        rollback = component.get("rollback")
        require(
            isinstance(rollback, dict)
            and rollback.get("strategy") == "backup_restore"
            and isinstance(rollback.get("boundary"), str)
            and bool(rollback["boundary"].strip())
            and isinstance(rollback.get("restoredComponents"), list)
            and bool(rollback["restoredComponents"]),
            f"{component_id}: restore boundary missing",
        )

    image_pairs = {
        "twenty": ("twenty-upgrade-source", "twenty"),
        "rustfs": ("rustfs-upgrade-source", "rustfs"),
        "twenty-queue-store": ("redis-upgrade-source", "valkey"),
        "postgres": ("postgres-upgrade-source", "postgres"),
    }
    for component_id, (source_id, target_id) in image_pairs.items():
        component = by_id[component_id]
        source = component.get("sourceImage")
        target = component.get("targetImage")
        require(
            isinstance(source, str) and PINNED_IMAGE.fullmatch(source) is not None,
            f"{component_id}: source image is not pinned by tag and digest",
        )
        require(
            isinstance(target, str) and PINNED_IMAGE.fullmatch(target) is not None,
            f"{component_id}: target image is not pinned by tag and digest",
        )
        require(
            source == locked.get(source_id),
            f"{component_id}: source image differs from the system lock",
        )
        require(
            target == locked.get(target_id),
            f"{component_id}: target image differs from the system lock",
        )

    gates = matrix.get("gates")
    require(
        isinstance(gates, list) and set(gates) == REQUIRED_GATES,
        "gate list is incomplete or contains unknown gates",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", type=Path)
    parser.add_argument("external_lock", type=Path)
    arguments = parser.parse_args()
    try:
        validate(load_object(arguments.matrix), load_object(arguments.external_lock))
    except InvalidPlan as error:
        print(f"upgrade-plan: ERROR: {error}", file=sys.stderr)
        return 1
    print("upgrade-plan: OK: release notes, migrations, backup and rollback checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
