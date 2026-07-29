#!/usr/bin/env python3
"""Exercise release-manifest and promotion failures without test doubles."""

from __future__ import annotations

import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable

from tools.pilot_release.manifest import (
    InvalidManifest,
    create_manifest,
    validate_compose_images,
    validate_manifest,
)
from tools.pilot_release.promotion import InvalidPromotion, record_event

COMMIT = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "a" * 64


def _images() -> dict[str, str]:
    image = f"registry.example.org/leonaid/test:v1@sha256:{DIGEST}"
    return {
        service: image
        for service in (
            "api",
            "core-postgres",
            "proxy",
            "public",
            "pwa",
            "rustfs",
            "twenty-postgres",
            "twenty-redis",
            "twenty-server",
            "twenty-worker",
            "web",
            "worker",
        )
    }


def _must_reject(callback: Callable[[], object], label: str) -> None:
    try:
        callback()
    except (InvalidManifest, InvalidPromotion):
        return
    raise AssertionError(f"negative case accepted: {label}")


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    manifest = create_manifest(
        root=root,
        release_id="pilot-contract-v1",
        version="1.0.0",
        git_commit=COMMIT,
        deployment_mode="production",
        images=_images(),
    )
    validate_manifest(manifest, root=root, expected_commit=COMMIT)
    compose = {
        "services": {
            service: {"image": image} for service, image in manifest["images"].items()
        }
    }
    validate_compose_images(manifest, compose)

    missing_image = deepcopy(manifest)
    del missing_image["images"]["worker"]
    _must_reject(
        lambda: validate_manifest(missing_image, root=root),
        "missing image",
    )

    floating_image = deepcopy(manifest)
    floating_image["images"]["api"] = "registry.example.org/leonaid/api:latest"
    _must_reject(
        lambda: validate_manifest(floating_image, root=root),
        "floating image",
    )

    drifted_migration = deepcopy(manifest)
    drifted_migration["migrations"][-1]["sha256"] = "b" * 64
    _must_reject(
        lambda: validate_manifest(drifted_migration, root=root),
        "migration drift",
    )

    wrong_commit = deepcopy(manifest)
    wrong_commit["gitCommit"] = "f" * 40
    _must_reject(
        lambda: validate_manifest(
            wrong_commit,
            root=root,
            expected_commit=COMMIT,
        ),
        "checkout mismatch",
    )

    drifted_compose = deepcopy(compose)
    drifted_compose["services"]["api"]["image"] = (
        f"registry.example.org/leonaid/test:v2@sha256:{'b' * 64}"
    )
    _must_reject(
        lambda: validate_compose_images(manifest, drifted_compose),
        "compose image mismatch",
    )

    with tempfile.TemporaryDirectory() as temporary:
        ledger = Path(temporary) / "release-ledger.jsonl"
        _must_reject(
            lambda: record_event(
                manifest=manifest,
                ledger=ledger,
                event="production_started",
                result="passed",
                evidence_id="PILOT-043-PRODUCTION",
                occurred_at="2026-07-28T12:00:00Z",
            ),
            "production before staging",
        )
        record_event(
            manifest=manifest,
            ledger=ledger,
            event="staging_verified",
            result="passed",
            evidence_id="PILOT-043-STAGING",
            occurred_at="2026-07-28T12:00:00Z",
        )
        record_event(
            manifest=manifest,
            ledger=ledger,
            event="production_started",
            result="passed",
            evidence_id="PILOT-043-PRODUCTION",
            occurred_at="2026-07-28T12:01:00Z",
        )
        records = [
            json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
        ]
        assert [record["sequence"] for record in records] == [1, 2]
        assert {record["manifestSha256"] for record in records} == {
            records[0]["manifestSha256"]
        }
        serialized = ledger.read_text(encoding="utf-8")
        assert "@" not in serialized
        assert "secret" not in serialized.lower()

    print(
        "pilot-release-contract: OK: Manifestbindung, Drift, "
        "Staging-Promotion und secretsfreies Ledger bewiesen"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
