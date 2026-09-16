"""Untrusted upload metadata and actual byte limits; no storage or API doubles."""

import hashlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from leonaid.modules.materials.api import (
    AddVersion,
    CleanupUpload,
    CreateMaterial,
    MaterialQuery,
    MAX_UPLOAD_BYTES,
    upload_digest,
)


def metadata(**changes: object) -> dict[str, object]:
    return {
        "idempotencyKey": str(uuid4()),
        "title": "Preparation",
        "filename": "Ablauf ü.pdf",
        **changes,
    }


def test_metadata_keeps_unicode_basename_and_normalizes_title() -> None:
    command = CreateMaterial.model_validate(metadata(title="  Vorbereitung  "))
    assert command.filename == "Ablauf ü.pdf"
    assert command.title == "Vorbereitung"
    assert command.media_type == "application/octet-stream"
    assert command.action_id is None


@pytest.mark.parametrize(
    "filename",
    [
        "",
        " ",
        "../private",
        "path/file",
        "path\\file",
        ".",
        "..",
        "a\r\nContent-Type: text/html",
        "a\x00.pdf",
        "a\u202efile",
        " leading",
        "trailing ",
        "x" * 241,
    ],
)
def test_reject_path_header_control_and_oversized_names(filename: str) -> None:
    with pytest.raises(ValidationError):
        CreateMaterial.model_validate(metadata(filename=filename))


@pytest.mark.parametrize(
    "media_type",
    [
        "text/html; charset=utf-8",
        "text/plain\r\nX: value",
        "image",
        "/png",
        "text/",
        "Text/Plain",
        "a" * 256,
    ],
)
def test_media_type_cannot_inject_parameters_or_headers(media_type: str) -> None:
    with pytest.raises(ValidationError):
        CreateMaterial.model_validate(metadata(mediaType=media_type))


def test_revalidation_rejects_mutated_command() -> None:
    command = CreateMaterial.model_validate(metadata())
    command.filename = "../secret"
    with pytest.raises(ValidationError):
        CreateMaterial.model_validate(command)


def test_binary_integrity_and_actual_size_boundary() -> None:
    content = bytes(range(256))
    assert upload_digest(content) == hashlib.sha256(content).hexdigest()
    assert len(upload_digest(b"x" * MAX_UPLOAD_BYTES)) == 64
    for invalid in (b"", b"x" * (MAX_UPLOAD_BYTES + 1), "text", bytearray(b"x")):
        with pytest.raises(ValueError):
            upload_digest(invalid)  # type: ignore[arg-type]


def test_versions_require_real_positive_revision_and_exclude_storage_fields() -> None:
    for revision in (0, -1, True, "1"):
        with pytest.raises(ValidationError):
            AddVersion.model_validate(
                {
                    "idempotencyKey": str(uuid4()),
                    "filename": "file",
                    "expectedRevision": revision,
                }
            )
    for field in (
        "storageBucket",
        "objectKey",
        "storageVersionId",
        "sha256",
        "sizeBytes",
    ):
        with pytest.raises(ValidationError):
            CreateMaterial.model_validate(metadata(**{field: "untrusted"}))


@pytest.mark.parametrize(
    "changes",
    [
        {"limit": 101},
        {"offset": 5001},
        {"offset": -1},
        {"limit": True},
        {"search": "x" * 201},
        {"actionId": "not-uuid"},
    ],
)
def test_search_bounds(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MaterialQuery.model_validate(changes)


@pytest.mark.parametrize(
    "change",
    [
        {"storageVersionId": "null"},
        {"storageVersionId": ""},
        {"storageVersionId": "bad\nversion"},
        {"materialId": "../surveys"},
        {"uploadId": "not-a-uuid"},
        {"apply": "true"},
        {"reason": "short"},
        {"reason": "        "},
        {"bucket": "other"},
    ],
)
def test_cleanup_requires_exact_bounded_operator_input(
    change: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CleanupUpload.model_validate(
            {
                "materialId": str(uuid4()),
                "uploadId": str(uuid4()),
                "storageVersionId": "exact-version",
                "reason": "Abandoned upload verification",
                **change,
            }
        )


def test_cleanup_defaults_to_dry_run_and_revalidates() -> None:
    command = CleanupUpload(
        material_id=uuid4(),
        upload_id=uuid4(),
        storage_version_id="exact-version",
        reason="Abandoned upload verification",
    )
    assert command.apply is False
    command.storage_version_id = "null"
    with pytest.raises(ValidationError):
        CleanupUpload.model_validate(command)
