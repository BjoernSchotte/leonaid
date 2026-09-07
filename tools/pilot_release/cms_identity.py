"""Exact, non-secret source identity for the CMS release contract."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

CMS_SOURCES = tuple(
    sorted(
        (
            "bun.lock",
            "apps/campaign-site/package.json",
            "apps/campaign-site/astro.config.mjs",
            "apps/campaign-site/emdash-auth-patch.mjs",
            "apps/campaign-site/emdash-editor-patch.mjs",
            "apps/campaign-site/emdash-content-log-patch.mjs",
            "apps/campaign-site/emdash-postgres-patch.mjs",
            "apps/campaign-site/emdash-media-editor-patch.mjs",
            "apps/campaign-site/emdash-repeater-editor-patch.mjs",
            "apps/campaign-site/src/campaign-schema.mjs",
            "apps/campaign-site/src/install-campaign-schema.mjs",
            "apps/campaign-site/src/auth/campaign-bindings.mjs",
            "apps/campaign-site/src/auth/campaign-media.mjs",
            "apps/campaign-site/src/auth/identity-map.mjs",
            "tools/emdash_spike/krapfentaxi-import.mjs",
            "tools/backup/cms-recovery.mjs",
            "tools/pilot_release/cms_identity.py",
            "tools/pilot_release/cms_image_identity.py",
            "infra/compose/Dockerfile.campaign-site",
        )
    )
)
CMS_GATES = ("cms-image-verified", "cms-migrations-passed", "cms-recovery-verified")
CMS_ROLLBACK = "restore_matching_cms_sql_media_key_image_preserve_later_core_orders"


class InvalidCmsIdentity(ValueError):
    """CMS metadata is missing, unsafe or different from the checkout."""


def _require(condition: bool) -> None:
    if not condition:
        raise InvalidCmsIdentity(
            "CMS release identity invalid or differs from checkout"
        )


def _read(root: Path, relative: str) -> bytes:
    path = root / relative
    _require(path.is_file())
    _require(
        not any(
            parent.is_symlink()
            for parent in (path, *path.parents)
            if parent != root.parent
        )
    )
    _require(path.resolve().is_relative_to(root.resolve()))
    return path.read_bytes()


def create_cms_identity(root: Path) -> dict[str, Any]:
    actual_patches = {
        path.relative_to(root).as_posix()
        for path in (root / "apps/campaign-site").glob("emdash-*-patch.mjs")
    }
    _require(
        actual_patches == {path for path in CMS_SOURCES if path.endswith("-patch.mjs")}
    )
    files = {path: _read(root, path) for path in CMS_SOURCES}
    package = json.loads(files["apps/campaign-site/package.json"])
    version = package["dependencies"]["emdash"]
    entries = re.findall(rb'^\s*"emdash": (\[.+\]),?$', files["bun.lock"], re.MULTILINE)
    _require(len(entries) == 1)
    entry = json.loads(entries[0])
    _require(entry[0] == f"emdash@{version}")
    schema = re.findall(
        rb"export const campaignSchemaVersion = ([0-9]+);",
        files["apps/campaign-site/src/campaign-schema.mjs"],
    )
    _require(len(schema) == 1)
    value = {
        "package": {"name": "emdash", "version": version, "integrity": entry[-1]},
        "editorialSchemaVersion": int(schema[0]),
        "migrationMode": "operator-only",
        "sources": {
            path: hashlib.sha256(data).hexdigest() for path, data in files.items()
        },
    }
    validate_cms_identity(value)
    return value


def validate_cms_identity(value: object, root: Path | None = None) -> None:
    _require(isinstance(value, dict))
    assert isinstance(value, dict)
    _require(
        set(value) == {"package", "editorialSchemaVersion", "migrationMode", "sources"}
    )
    package = value.get("package")
    _require(isinstance(package, dict))
    assert isinstance(package, dict)
    _require(set(package) == {"name", "version", "integrity"})
    _require(package["name"] == "emdash")
    _require(
        isinstance(package["version"], str)
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", package["version"]) is not None
    )
    _require(
        isinstance(package["integrity"], str)
        and re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", package["integrity"])
        is not None
    )
    _require(
        type(value["editorialSchemaVersion"]) is int
        and value["editorialSchemaVersion"] > 0
    )
    _require(value["migrationMode"] == "operator-only")
    sources = value["sources"]
    _require(isinstance(sources, dict))
    assert isinstance(sources, dict)
    _require(set(sources) == set(CMS_SOURCES))
    for digest in sources.values():
        _require(
            isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
        )
    if root is not None:
        _require(value == create_cms_identity(root))
