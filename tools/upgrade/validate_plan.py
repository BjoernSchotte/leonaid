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
REQUIRED_COMPONENTS = {"twenty", "rustfs", "leonaid-core"}
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
        raise InvalidPlan(f"{path}: ungültiges JSON: {error}") from error
    if not isinstance(value, dict):
        raise InvalidPlan(f"{path}: Wurzel muss ein Objekt sein")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidPlan(message)


def system_images(lock: dict[str, Any]) -> dict[str, str]:
    systems = lock.get("systems")
    if not isinstance(systems, list):
        raise InvalidPlan("external-systems.lock: systems fehlt")
    result: dict[str, str] = {}
    for item in systems:
        require(isinstance(item, dict), "external-systems.lock: System ist kein Objekt")
        system_id = item.get("id")
        image = item.get("image")
        if isinstance(system_id, str) and isinstance(image, str):
            result[system_id] = image
    return result


def validate(matrix: dict[str, Any], lock: dict[str, Any]) -> None:
    require(matrix.get("schemaVersion") == 1, "schemaVersion muss 1 sein")
    window = matrix.get("changeWindow")
    if not isinstance(window, dict):
        raise InvalidPlan("changeWindow fehlt")
    for gate in (
        "backupRequired",
        "goldenCloneRequired",
        "maintenanceModeRequired",
        "releaseNotesReviewed",
    ):
        require(window.get(gate) is True, f"changeWindow.{gate} muss true sein")

    components = matrix.get("components")
    if not isinstance(components, list):
        raise InvalidPlan("components fehlt")
    by_id = {
        item.get("id"): item
        for item in components
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    require(set(by_id) == REQUIRED_COMPONENTS, "Komponentenmatrix ist unvollständig")
    locked = system_images(lock)

    for component_id, component in by_id.items():
        require(
            component.get("sourceVersion") != component.get("targetVersion"),
            f"{component_id}: Quell- und Zielversion sind gleich",
        )
        notes = component.get("releaseNotes")
        require(
            isinstance(notes, list)
            and len(notes) >= 1
            and all(
                isinstance(url, str) and url.startswith("https://") for url in notes
            ),
            f"{component_id}: Release-Notes-Quellen fehlen",
        )
        migration = component.get("migration")
        require(
            isinstance(migration, dict)
            and migration.get("reviewed") is True
            and isinstance(migration.get("command"), str)
            and bool(migration["command"].strip()),
            f"{component_id}: Migration ist nicht geprüft",
        )
        rollback = component.get("rollback")
        require(
            isinstance(rollback, dict)
            and rollback.get("strategy") == "backup_restore"
            and isinstance(rollback.get("boundary"), str)
            and bool(rollback["boundary"].strip())
            and isinstance(rollback.get("restoredComponents"), list)
            and bool(rollback["restoredComponents"]),
            f"{component_id}: Restore-Grenze fehlt",
        )

    image_pairs = {
        "twenty": ("twenty-upgrade-source", "twenty"),
        "rustfs": ("rustfs-upgrade-source", "rustfs"),
    }
    for component_id, (source_id, target_id) in image_pairs.items():
        component = by_id[component_id]
        source = component.get("sourceImage")
        target = component.get("targetImage")
        require(
            isinstance(source, str) and PINNED_IMAGE.fullmatch(source) is not None,
            f"{component_id}: Quellimage ist nicht mit Tag und Digest gepinnt",
        )
        require(
            isinstance(target, str) and PINNED_IMAGE.fullmatch(target) is not None,
            f"{component_id}: Zielimage ist nicht mit Tag und Digest gepinnt",
        )
        require(
            source == locked.get(source_id),
            f"{component_id}: Quellimage weicht vom System-Lock ab",
        )
        require(
            target == locked.get(target_id),
            f"{component_id}: Zielimage weicht vom System-Lock ab",
        )

    gates = matrix.get("gates")
    require(
        isinstance(gates, list) and set(gates) == REQUIRED_GATES,
        "Gate-Liste ist unvollständig oder enthält unbekannte Gates",
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
    print("upgrade-plan: OK: Release Notes, Migrationen, Backup und Rollback geprüft")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
