#!/usr/bin/env python3
"""Exercise release-manifest and promotion failures without test doubles."""

from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Callable

from tools.pilot_release.manifest import (
    InvalidManifest,
    create_manifest,
    images_from_compose,
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
            "survey-validator",
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
    if sys.argv[1:] == ["--cms-compose-stdin"]:
        configuration = json.load(sys.stdin)
        assert "campaign-site" in configuration["services"]
        _must_reject(
            lambda: images_from_compose(configuration),
            "actual rendered CMS configuration accepted by legacy contract",
        )
        print(
            "pilot-release-contract: actual CMS Compose denied; no configuration output"
        )
    else:
        assert not sys.argv[1:]
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

    cms_compose = deepcopy(compose)
    cms_compose["services"]["campaign-site"] = {"image": _images()["public"]}
    _must_reject(
        lambda: images_from_compose(cms_compose),
        "legacy manifest creation silently ignores configured CMS",
    )
    _must_reject(
        lambda: validate_compose_images(manifest, cms_compose),
        "legacy manifest verification silently ignores configured CMS",
    )
    for schema_version in (True, 1.0, "1", 2):
        invalid_version = deepcopy(manifest)
        invalid_version["schemaVersion"] = schema_version
        _must_reject(
            lambda: validate_manifest(invalid_version),
            "noninteger or unsupported release version",
        )
    for field in ("cms", "emdash"):
        hidden_cms = deepcopy(manifest)
        hidden_cms[field] = {"version": "0.36.0"}
        _must_reject(
            lambda: validate_manifest(hidden_cms),
            "ignored CMS release metadata",
        )
    hidden_schema = deepcopy(manifest)
    hidden_schema["schemas"]["emdash"] = "0.36.0"
    _must_reject(lambda: validate_manifest(hidden_schema), "ignored CMS schema")
    cms_images = deepcopy(manifest)
    cms_images["images"]["campaign-site"] = _images()["public"]
    _must_reject(lambda: validate_manifest(cms_images), "CMS image in v1 inventory")

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
