"""Exercise v1/v2 release compatibility against actual repository sources."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

from tools.pilot_release.cms_identity import (
    CMS_SOURCES,
    InvalidCmsIdentity,
    create_cms_identity,
    validate_cms_identity,
)
from tools.pilot_release.contract_test import COMMIT, _images, _must_reject
from tools.pilot_release.manifest import (
    create_manifest,
    validate_manifest,
    validate_compose_images,
    images_from_compose,
)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    images = {**_images(), "campaign-site": _images()["public"]}
    manifest = create_manifest(
        root=root,
        release_id="cms-contract-v2",
        version="1.0.0",
        git_commit=COMMIT,
        deployment_mode="production",
        images=images,
        schema_version=2,
    )
    validate_manifest(manifest, root=root, expected_schema_version=2)
    validate_manifest(manifest)
    revisions = {item["revision"] for item in manifest["migrations"]}
    assert {"0027_surveys", "0027_campaign_alias_namespaces"} <= revisions
    assert manifest["schemas"]["coreAlembicHead"] == "0035_merge_campaign_surveys"
    truncated = deepcopy(manifest)
    for item in truncated["migrations"]:
        item["revision"] = item["revision"].split("_", 1)[0]
    _must_reject(lambda: validate_manifest(truncated), "truncated migration identities")
    wrong_revision = deepcopy(manifest)
    wrong_revision["migrations"][0]["revision"] = "0001_wrong_identity"
    _must_reject(
        lambda: validate_manifest(wrong_revision, root=root),
        "migration identity differs from source",
    )
    compose = {
        "services": {service: {"image": image} for service, image in images.items()}
    }
    validate_compose_images(manifest, compose)
    assert images_from_compose(compose, schema_version=2) == images
    _must_reject(lambda: images_from_compose(compose), "v1 ignores CMS")
    _must_reject(
        lambda: validate_manifest(manifest, expected_schema_version=1),
        "implicit CMS release upgrade",
    )
    for field in ("cms",):
        missing = deepcopy(manifest)
        del missing[field]
        _must_reject(lambda: validate_manifest(missing), "missing CMS identity")
    for image in (None, "campaign-site:latest", "sha256:" + "a" * 64):
        invalid = deepcopy(manifest)
        if image is None:
            del invalid["images"]["campaign-site"]
        else:
            invalid["images"]["campaign-site"] = image
        _must_reject(
            lambda: validate_manifest(invalid),
            "missing or unpinned production CMS image",
        )
    mismatch = deepcopy(compose)
    mismatch["services"]["campaign-site"]["image"] = "different:v1@sha256:" + "b" * 64
    _must_reject(
        lambda: validate_compose_images(manifest, mismatch), "CMS compose drift"
    )
    for section in ("requiredGates", "rollback"):
        invalid = deepcopy(manifest)
        if section == "requiredGates":
            invalid[section].pop()
        else:
            del invalid[section]["cms"]
        _must_reject(
            lambda: validate_manifest(invalid), "missing CMS gate or rollback boundary"
        )
    for path in CMS_SOURCES:
        invalid = deepcopy(manifest)
        del invalid["cms"]["sources"][path]
        _must_reject(lambda: validate_manifest(invalid), "missing exact CMS source")
        invalid = deepcopy(manifest)
        invalid["cms"]["sources"][path] = "b" * 64
        _must_reject(
            lambda: validate_manifest(invalid, root=root), "CMS source hash drift"
        )
    for field, replacement in (
        ("editorialSchemaVersion", True),
        ("migrationMode", "runtime"),
    ):
        invalid = deepcopy(manifest)
        invalid["cms"][field] = replacement
        _must_reject(
            lambda: validate_manifest(invalid), "unsafe CMS schema/migration identity"
        )
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary)
        for relative in CMS_SOURCES:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / relative, destination)
        expected = create_cms_identity(target)
        for relative in CMS_SOURCES:
            source_path = target / relative
            original = source_path.read_bytes()
            source_path.write_bytes(original + b"\n")
            try:
                validate_cms_identity(expected, target)
            except InvalidCmsIdentity:
                pass
            else:
                raise AssertionError("actual source edit not detected")
            source_path.write_bytes(original)
        victim = target / "apps/campaign-site/emdash-auth-patch.mjs"
        victim.unlink()
        victim.symlink_to(root / "apps/campaign-site/emdash-auth-patch.mjs")
        try:
            create_cms_identity(target)
        except InvalidCmsIdentity:
            pass
        else:
            raise AssertionError("symlinked release source accepted")
        document = target / "manifest.json"
        document.write_text(json.dumps(manifest), encoding="utf-8")
        command = [
            sys.executable,
            "tools/pilot_release/manifest.py",
            "verify",
            "--root",
            str(root),
            "--manifest",
            str(document),
        ]
        denied = subprocess.run(command, cwd=root, capture_output=True, timeout=20)
        assert denied.returncode == 1 and not denied.stdout
        allowed = subprocess.run(
            [*command, "--expected-schema-version", "2"],
            cwd=root,
            capture_output=True,
            timeout=20,
        )
        assert allowed.returncode == 0 and not allowed.stderr, (
            "explicit v2 CLI verification must succeed"
        )
    print(
        "cms-release-contract: exact v2 CMS image/source/package/schema/gate binding; v1 isolation, actual source drift, symlink and default CLI denial passed; no deployment authorization"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
