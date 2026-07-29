#!/usr/bin/env python3
"""Create and validate immutable LeonAid pilot release manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

PINNED_IMAGE = re.compile(r"^[^@\s]+:[^@:\s]+@sha256:[0-9a-f]{64}$")
LOCAL_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
REQUIRED_IMAGES = {
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
}
REQUIRED_GATES = (
    "manifest-verified",
    "staging-promoted",
    "maintenance-write-rejection",
    "recovery-point-verified",
    "migrations-passed",
    "readiness-passed",
    "golden-journey-passed",
)


class InvalidManifest(RuntimeError):
    """Raised when a release cannot be reproduced safely."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidManifest(message)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidManifest(f"{label} muss ein Objekt sein")
    return value


def _load_object(path: Path) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidManifest(f"{path}: ungültiges JSON: {error}") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def manifest_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def images_from_compose(value: dict[str, Any]) -> dict[str, str]:
    services = _object(value.get("services"), "Compose services")
    images: dict[str, str] = {}
    for service in REQUIRED_IMAGES:
        configuration = _object(services.get(service), f"Compose service {service}")
        image = configuration.get("image")
        if not isinstance(image, str) or not image:
            raise InvalidManifest(f"{service}: Compose-Image fehlt")
        images[service] = image
    return images


def validate_compose_images(
    manifest: dict[str, Any],
    compose_configuration: dict[str, Any],
) -> None:
    compose_images = images_from_compose(compose_configuration)
    manifest_images = _object(manifest.get("images"), "images")
    _require(
        manifest_images == compose_images,
        "Manifest-Images weichen von der effektiven Compose-Konfiguration ab",
    )


def _migration_inventory(root: Path) -> list[dict[str, str]]:
    paths = sorted((root / "migrations" / "versions").glob("*.py"))
    _require(bool(paths), "Alembic-Migrationen fehlen")
    return [
        {
            "revision": path.name.split("_", maxsplit=1)[0],
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
        }
        for path in paths
    ]


def _artifact_inventory(root: Path) -> dict[str, dict[str, str]]:
    paths = {
        "compatibilityMatrix": root / "infra/upgrade/compatibility-matrix.json",
        "invoiceTemplate": (
            root / "src/leonaid/adapters/typst/templates/invoice-v2.typ"
        ),
        "openapi": root / "packages/api-client/openapi.json",
    }
    for label, path in paths.items():
        _require(path.is_file(), f"Release-Artefakt fehlt: {label}")
    return {
        label: {
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
        }
        for label, path in paths.items()
    }


def create_manifest(
    *,
    root: Path,
    release_id: str,
    version: str,
    git_commit: str,
    deployment_mode: str,
    images: dict[str, str],
) -> dict[str, Any]:
    migrations = _migration_inventory(root)
    value: dict[str, Any] = {
        "schemaVersion": 1,
        "releaseId": release_id,
        "version": version,
        "gitCommit": git_commit,
        "deploymentMode": deployment_mode,
        "images": dict(sorted(images.items())),
        "schemas": {
            "coreAlembicHead": migrations[-1]["revision"],
            "goldenData": 1,
        },
        "templates": {"invoice": "invoice-v2"},
        "migrations": migrations,
        "artifacts": _artifact_inventory(root),
        "requiredGates": list(REQUIRED_GATES),
        "rollback": {
            "core": "backup_restore",
            "rustfs": "binary_before_write_else_backup_restore",
            "twenty": "backup_restore_after_migration",
        },
    }
    validate_manifest(value, root=root)
    return value


def validate_manifest(
    value: dict[str, Any],
    *,
    root: Path | None = None,
    expected_commit: str | None = None,
) -> None:
    _require(value.get("schemaVersion") == 1, "schemaVersion muss 1 sein")
    release_id = value.get("releaseId")
    _require(
        isinstance(release_id, str) and RELEASE_ID.fullmatch(release_id) is not None,
        "releaseId ist ungültig",
    )
    version = value.get("version")
    _require(
        isinstance(version, str) and bool(version.strip()),
        "version fehlt",
    )
    git_commit = value.get("gitCommit")
    _require(
        isinstance(git_commit, str) and GIT_COMMIT.fullmatch(git_commit) is not None,
        "gitCommit muss ein vollständiger SHA sein",
    )
    if expected_commit is not None:
        _require(git_commit == expected_commit, "gitCommit weicht vom Checkout ab")

    mode = value.get("deploymentMode")
    _require(mode in {"production", "test"}, "deploymentMode ist ungültig")
    images = _object(value.get("images"), "images")
    _require(set(images) == REQUIRED_IMAGES, "Image-Inventar ist unvollständig")
    for service, image in images.items():
        _require(isinstance(image, str), f"{service}: Image ist kein String")
        if mode == "production":
            _require(
                PINNED_IMAGE.fullmatch(image) is not None,
                f"{service}: Produktionsimage benötigt Tag und Digest",
            )
        else:
            _require(
                PINNED_IMAGE.fullmatch(image) is not None
                or LOCAL_IMAGE_ID.fullmatch(image) is not None,
                f"{service}: Testimage ist nicht unveränderlich gebunden",
            )

    schemas = _object(value.get("schemas"), "schemas")
    head = schemas.get("coreAlembicHead")
    _require(
        isinstance(head, str) and re.fullmatch(r"[0-9]{4}", head) is not None,
        "Core-Schemaziel ist ungültig",
    )
    _require(schemas.get("goldenData") == 1, "Golden-Datensatzversion fehlt")
    _require(
        value.get("templates") == {"invoice": "invoice-v2"},
        "Rechnungstemplate ist nicht gebunden",
    )

    migrations = value.get("migrations")
    if not isinstance(migrations, list) or not migrations:
        raise InvalidManifest("Migrationsinventar fehlt")
    revisions: list[str] = []
    for item in migrations:
        migration = _object(item, "Migration")
        revision = migration.get("revision")
        path = migration.get("path")
        digest = migration.get("sha256")
        if not isinstance(revision, str) or re.fullmatch(r"[0-9]{4}", revision) is None:
            raise InvalidManifest("Migrationsrevision ist ungültig")
        if (
            not isinstance(path, str)
            or not path.startswith("migrations/versions/")
            or not path.endswith(".py")
        ):
            raise InvalidManifest(f"{revision}: Migrationspfad ist ungültig")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise InvalidManifest(f"{revision}: Migrations-SHA ist ungültig")
        revisions.append(revision)
        if root is not None:
            actual_path = root / path
            _require(actual_path.is_file(), f"{revision}: Migration fehlt im Checkout")
            _require(
                _sha256(actual_path) == digest,
                f"{revision}: Migration weicht vom Manifest ab",
            )
    _require(revisions == sorted(set(revisions)), "Migrationen sind nicht eindeutig")
    _require(revisions[-1] == head, "Core-Schemaziel ist nicht der Manifest-Head")

    artifacts = _object(value.get("artifacts"), "artifacts")
    _require(
        set(artifacts) == {"compatibilityMatrix", "invoiceTemplate", "openapi"},
        "Release-Artefaktinventar ist unvollständig",
    )
    for label, item in artifacts.items():
        artifact = _object(item, label)
        path = artifact.get("path")
        digest = artifact.get("sha256")
        if not isinstance(path, str) or not path:
            raise InvalidManifest(f"{label}: Pfad fehlt")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise InvalidManifest(f"{label}: SHA fehlt")
        if root is not None:
            actual_path = root / path
            _require(actual_path.is_file(), f"{label}: Artefakt fehlt im Checkout")
            _require(
                _sha256(actual_path) == digest,
                f"{label}: Artefakt weicht vom Manifest ab",
            )

    _require(
        value.get("requiredGates") == list(REQUIRED_GATES),
        "Release-Gates sind unvollständig oder ungeordnet",
    )
    _require(
        value.get("rollback")
        == {
            "core": "backup_restore",
            "rustfs": "binary_before_write_else_backup_restore",
            "twenty": "backup_restore_after_migration",
        },
        "Rollbackgrenzen sind unvollständig",
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--release-id", required=True)
    create.add_argument("--version", required=True)
    create.add_argument("--git-commit", required=True)
    create.add_argument(
        "--deployment-mode",
        choices=("production", "test"),
        required=True,
    )
    create_sources = create.add_mutually_exclusive_group(required=True)
    create_sources.add_argument("--images", type=Path)
    create_sources.add_argument("--compose-config", type=Path)
    create.add_argument("--output", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--expected-commit")
    verify.add_argument("--compose-config", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    try:
        root = arguments.root.resolve()
        if arguments.command == "create":
            if arguments.compose_config is not None:
                images = images_from_compose(_load_object(arguments.compose_config))
            else:
                if arguments.images is None:
                    raise InvalidManifest("Imagequelle fehlt")
                images = _load_object(arguments.images)
            manifest = create_manifest(
                root=root,
                release_id=arguments.release_id,
                version=arguments.version,
                git_commit=arguments.git_commit,
                deployment_mode=arguments.deployment_mode,
                images={str(service): str(image) for service, image in images.items()},
            )
            arguments.output.write_bytes(canonical_bytes(manifest))
            print(f"pilot-release-manifest: OK: {manifest_sha256(manifest)}")
            return 0
        manifest = _load_object(arguments.manifest)
        validate_manifest(
            manifest,
            root=root,
            expected_commit=arguments.expected_commit,
        )
        if arguments.compose_config is not None:
            validate_compose_images(
                manifest,
                _load_object(arguments.compose_config),
            )
        print(f"pilot-release-manifest: OK: {manifest_sha256(manifest)}")
        return 0
    except (InvalidManifest, OSError) as error:
        print(f"pilot-release-manifest: ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
