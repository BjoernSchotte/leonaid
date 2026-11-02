#!/usr/bin/env python3
"""Create and validate immutable LeonAid pilot release manifests."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    # Preserve direct `python tools/pilot_release/manifest.py` callers whose
    # PYTHONPATH contains only src; import from this checkout, not the cwd.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pilot_release.cms_identity import (
    CMS_GATES,
    CMS_ROLLBACK,
    create_cms_identity,
    validate_cms_identity,
)

PINNED_IMAGE = re.compile(r"^[^@\s]+:[^@:\s]+@sha256:[0-9a-f]{64}$")
LOCAL_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
MIGRATION_REVISION = re.compile(r"^[0-9]{4}_[a-z0-9_]+$")
REQUIRED_IMAGES = {
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
        raise InvalidManifest(f"{label} must be an object")
    return value


def _load_object(path: Path) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), str(path))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidManifest(f"{path}: invalid JSON: {error}") from error


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def manifest_sha256(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _image_inventory(schema_version: object) -> set[str]:
    _require(
        type(schema_version) is int and schema_version in (1, 2),
        "release version must be 1 or 2",
    )
    return REQUIRED_IMAGES | ({"campaign-site"} if schema_version == 2 else set())


def images_from_compose(
    value: dict[str, Any], *, schema_version: int = 1
) -> dict[str, str]:
    services = _object(value.get("services"), "Compose services")
    # Version 1 has no CMS image, migration, patch or rollback identity. Never
    # silently omit a configured CMS service while approving the legacy stack.
    _require(
        schema_version == 2 or "campaign-site" not in services,
        "release contract v1 does not allow campaign-site; CMS release contract is missing",
    )
    images: dict[str, str] = {}
    for service in _image_inventory(schema_version):
        configuration = _object(services.get(service), f"Compose service {service}")
        image = configuration.get("image")
        if not isinstance(image, str) or not image:
            raise InvalidManifest(f"{service}: Compose image is missing")
        images[service] = image
    return images


def validate_compose_images(
    manifest: dict[str, Any],
    compose_configuration: dict[str, Any],
) -> None:
    compose_images = images_from_compose(
        compose_configuration, schema_version=manifest.get("schemaVersion", 1)
    )
    manifest_images = _object(manifest.get("images"), "images")
    _require(
        manifest_images == compose_images,
        "manifest images differ from the effective Compose configuration",
    )


def _migration_inventory(root: Path) -> list[dict[str, str]]:
    paths = sorted((root / "migrations" / "versions").glob("*.py"))
    _require(bool(paths), "Alembic migrations are missing")
    return [
        {
            "revision": _migration_revision(path),
            "path": path.relative_to(root).as_posix(),
            "sha256": _sha256(path),
        }
        for path in paths
    ]


def _migration_revision(path: Path) -> str:
    # Read the declared identity without importing/executing migration code.
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        if any(
            isinstance(target, ast.Name) and target.id == "revision"
            for target in targets
        ):
            assert isinstance(node, (ast.Assign, ast.AnnAssign))
            value = ast.literal_eval(node.value) if node.value is not None else None
            _require(isinstance(value, str), f"{path.name}: revision is missing")
            return str(value)
    raise InvalidManifest(f"{path.name}: revision is missing")


def _artifact_inventory(root: Path) -> dict[str, dict[str, str]]:
    paths = {
        "compatibilityMatrix": root / "infra/upgrade/compatibility-matrix.json",
        "invoiceTemplate": (
            root / "src/leonaid/adapters/typst/templates/invoice-v2.typ"
        ),
        "openapi": root / "packages/api-client/openapi.json",
    }
    for label, path in paths.items():
        _require(path.is_file(), f"release artifact is missing: {label}")
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
    schema_version: int = 1,
) -> dict[str, Any]:
    migrations = _migration_inventory(root)
    value: dict[str, Any] = {
        "schemaVersion": schema_version,
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
    if schema_version == 2:
        try:
            value["cms"] = create_cms_identity(root)
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise InvalidManifest("CMS release identity is invalid") from error
        value["requiredGates"].extend(CMS_GATES)
        value["rollback"]["cms"] = CMS_ROLLBACK
    validate_manifest(value, root=root)
    return value


def validate_manifest(
    value: dict[str, Any],
    *,
    root: Path | None = None,
    expected_commit: str | None = None,
    expected_schema_version: int | None = None,
) -> None:
    schema_version = value.get("schemaVersion")
    required_images = _image_inventory(schema_version)
    if expected_schema_version is not None:
        _require(
            schema_version == expected_schema_version,
            "release version does not match the explicit caller contract",
        )
    _require(
        (schema_version == 2 or "cms" not in value) and "emdash" not in value,
        "release contract v1 does not allow CMS metadata",
    )
    if schema_version == 2:
        try:
            validate_cms_identity(value.get("cms"), root)
        except (ValueError, KeyError, TypeError, OSError) as error:
            raise InvalidManifest("CMS release identity is invalid") from error
    release_id = value.get("releaseId")
    _require(
        isinstance(release_id, str) and RELEASE_ID.fullmatch(release_id) is not None,
        "releaseId is invalid",
    )
    version = value.get("version")
    _require(
        isinstance(version, str) and bool(version.strip()),
        "version is missing",
    )
    git_commit = value.get("gitCommit")
    _require(
        isinstance(git_commit, str) and GIT_COMMIT.fullmatch(git_commit) is not None,
        "gitCommit must be a full SHA",
    )
    if expected_commit is not None:
        _require(git_commit == expected_commit, "gitCommit differs from the checkout")

    mode = value.get("deploymentMode")
    _require(mode in {"production", "test"}, "deploymentMode is invalid")
    images = _object(value.get("images"), "images")
    _require(set(images) == required_images, "image inventory is incomplete")
    for service, image in images.items():
        _require(isinstance(image, str), f"{service}: image is not a string")
        if mode == "production":
            _require(
                PINNED_IMAGE.fullmatch(image) is not None,
                f"{service}: production image requires tag and digest",
            )
        else:
            _require(
                PINNED_IMAGE.fullmatch(image) is not None
                or LOCAL_IMAGE_ID.fullmatch(image) is not None,
                f"{service}: test image is not immutably pinned",
            )

    schemas = _object(value.get("schemas"), "schemas")
    _require(
        set(schemas) == {"coreAlembicHead", "goldenData"},
        "release contract v1 allows only the existing core schema inventory",
    )
    head = schemas.get("coreAlembicHead")
    _require(
        isinstance(head, str) and MIGRATION_REVISION.fullmatch(head) is not None,
        "core schema target is invalid",
    )
    _require(schemas.get("goldenData") == 1, "golden dataset version is missing")
    _require(
        value.get("templates") == {"invoice": "invoice-v2"},
        "invoice template is not pinned",
    )

    migrations = value.get("migrations")
    if not isinstance(migrations, list) or not migrations:
        raise InvalidManifest("migration inventory is missing")
    revisions: list[str] = []
    for item in migrations:
        migration = _object(item, "Migration")
        revision = migration.get("revision")
        path = migration.get("path")
        digest = migration.get("sha256")
        if (
            not isinstance(revision, str)
            or MIGRATION_REVISION.fullmatch(revision) is None
        ):
            raise InvalidManifest("migration revision is invalid")
        if (
            not isinstance(path, str)
            or not path.startswith("migrations/versions/")
            or not path.endswith(".py")
        ):
            raise InvalidManifest(f"{revision}: migration path is invalid")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise InvalidManifest(f"{revision}: migration SHA is invalid")
        revisions.append(revision)
        if root is not None:
            actual_path = root / path
            _require(
                actual_path.is_file(),
                f"{revision}: migration is missing from the checkout",
            )
            _require(
                _migration_revision(actual_path) == revision,
                f"{revision}: migration identity differs from the checkout",
            )
            _require(
                _sha256(actual_path) == digest,
                f"{revision}: migration differs from the manifest",
            )
    _require(revisions == sorted(set(revisions)), "migrations are not unique")
    _require(revisions[-1] == head, "core schema target is not the manifest head")

    artifacts = _object(value.get("artifacts"), "artifacts")
    _require(
        set(artifacts) == {"compatibilityMatrix", "invoiceTemplate", "openapi"},
        "release artifact inventory is incomplete",
    )
    for label, item in artifacts.items():
        artifact = _object(item, label)
        path = artifact.get("path")
        digest = artifact.get("sha256")
        if not isinstance(path, str) or not path:
            raise InvalidManifest(f"{label}: path is missing")
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise InvalidManifest(f"{label}: SHA is missing")
        if root is not None:
            actual_path = root / path
            _require(
                actual_path.is_file(), f"{label}: artifact is missing from the checkout"
            )
            _require(
                _sha256(actual_path) == digest,
                f"{label}: artifact differs from the manifest",
            )

    _require(
        value.get("requiredGates")
        == list(REQUIRED_GATES + (CMS_GATES if schema_version == 2 else ())),
        "release gates are incomplete or out of order",
    )
    _require(
        value.get("rollback")
        == {
            "core": "backup_restore",
            "rustfs": "binary_before_write_else_backup_restore",
            "twenty": "backup_restore_after_migration",
            **({"cms": CMS_ROLLBACK} if schema_version == 2 else {}),
        },
        "rollback boundaries are incomplete",
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--release-id", required=True)
    create.add_argument("--version", required=True)
    create.add_argument("--schema-version", type=int, choices=(1, 2), default=1)
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
    verify.add_argument(
        "--expected-schema-version", type=int, choices=(1, 2), default=1
    )
    verify.add_argument("--compose-config", type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    try:
        root = arguments.root.resolve()
        if arguments.command == "create":
            if arguments.compose_config is not None:
                images = images_from_compose(
                    _load_object(arguments.compose_config),
                    schema_version=arguments.schema_version,
                )
            else:
                if arguments.images is None:
                    raise InvalidManifest("image source is missing")
                images = _load_object(arguments.images)
            manifest = create_manifest(
                root=root,
                release_id=arguments.release_id,
                version=arguments.version,
                git_commit=arguments.git_commit,
                deployment_mode=arguments.deployment_mode,
                images={str(service): str(image) for service, image in images.items()},
                schema_version=arguments.schema_version,
            )
            arguments.output.write_bytes(canonical_bytes(manifest))
            print(f"pilot-release-manifest: OK: {manifest_sha256(manifest)}")
            return 0
        manifest = _load_object(arguments.manifest)
        validate_manifest(
            manifest,
            root=root,
            expected_commit=arguments.expected_commit,
            expected_schema_version=arguments.expected_schema_version,
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
