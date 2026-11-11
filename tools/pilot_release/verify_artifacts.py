#!/usr/bin/env python3
"""Verify the sanitized evidence emitted by the real pilot release test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tools.pilot_release.manifest import (
    _load_object,
    validate_manifest,
)


class InvalidEvidence(RuntimeError):
    """Raised when release evidence cannot prove the intended contract."""


def _documents(snapshot: dict[str, Any]) -> list[tuple[str, str, int]]:
    core = snapshot.get("core")
    if not isinstance(core, dict):
        raise InvalidEvidence("snapshot has no core section")
    manifest = core.get("documentManifest")
    if not isinstance(manifest, list) or not manifest:
        raise InvalidEvidence("document manifest is missing")
    return sorted(
        (
            str(item["objectKey"]),
            str(item["sha256"]),
            int(item["size"]),
        )
        for item in manifest
        if isinstance(item, dict)
    )


def verify(root: Path, artifact_directory: Path) -> None:
    result = _load_object(artifact_directory / "result.json")
    required_results = {
        "preContract",
        "preE2e",
        "preGoldenJourney",
        "maintenanceWriteBoundary",
        "postContract",
        "postE2e",
        "postGoldenJourney",
        "coreMigrationFailureDetected",
        "failedUpgradeDetected",
        "backupRollback",
        "rollbackGoldenJourney",
        "rollbackJourneyEquivalent",
        "queueStoreMigration",
        "objectStoreUpgrade",
    }
    if result.get("result") != "passed" or any(
        result.get(key) != "passed" for key in required_results
    ):
        raise InvalidEvidence("release result is incomplete")

    release_v1 = _load_object(artifact_directory / "release-v1.json")
    release_v2 = _load_object(artifact_directory / "release-v2.json")
    validate_manifest(release_v1, root=root)
    validate_manifest(release_v2, root=root)
    if release_v1["gitCommit"] != release_v2["gitCommit"]:
        raise InvalidEvidence("release versions bind different checkouts")

    pre = _load_object(artifact_directory / "pre-upgrade.json")
    post = _load_object(artifact_directory / "post-upgrade.json")
    rollback = _load_object(artifact_directory / "rollback-restored.json")
    if _documents(pre) != _documents(post):
        raise InvalidEvidence("document SHAs drifted during upgrade")
    if _documents(pre) != _documents(rollback):
        raise InvalidEvidence("document SHAs drifted during rollback")
    for before_name, after_name in (
        ("objects-before-upgrade", "objects-after-upgrade"),
        ("objects-before-production", "objects-after-production"),
    ):
        before = _load_object(artifact_directory / f"{before_name}.json")
        after = _load_object(artifact_directory / f"{after_name}.json")
        if not before or before != after:
            raise InvalidEvidence("RustFS upgrade changed object versions")

    journey_before = _load_object(artifact_directory / "journey-before.normalized.json")
    journey_after = _load_object(artifact_directory / "journey-after.normalized.json")
    journey_rollback = _load_object(
        artifact_directory / "journey-rollback.normalized.json"
    )
    if journey_before.get("round") != "round-1":
        raise InvalidEvidence("golden journey before upgrade is not round 1")
    if journey_after.get("round") != "round-2":
        raise InvalidEvidence("golden journey after upgrade is not round 2")
    if journey_rollback != journey_after:
        raise InvalidEvidence(
            "golden journey after rollback is not identical in business terms"
        )

    failure_log = (artifact_directory / "core-migration-failure.log").read_text(
        encoding="utf-8"
    )
    if "pilot_missing_revision" not in failure_log:
        raise InvalidEvidence("real migration failure is not proven")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("artifact_directory", type=Path)
    arguments = parser.parse_args()
    try:
        verify(arguments.root.resolve(), arguments.artifact_directory.resolve())
    except (
        InvalidEvidence,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as error:
        print(f"pilot-release-evidence: ERROR: {error}", file=sys.stderr)
        return 1
    print(
        "pilot-release-evidence: OK: two releases, migration failure, "
        "rollback and document SHAs proven"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
