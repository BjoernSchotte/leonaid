"""Recovery checkpoints must reject incomplete, stale or altered erasure lists."""

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest

from leonaid.application.surveys.recovery import (
    ErasureCheckpoint,
    ErasureRecord,
    seal,
    verify,
)

SECRET = "synthetic-recovery-key-not-used-outside-tests"


def sample():
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
    checkpoint = ErasureCheckpoint(
        installation_id=uuid4(),
        exported_at=cutoff,
        records=(
            ErasureRecord(
                survey_id=uuid4(),
                requested_by=uuid4(),
                operation_hash="a" * 64,
                expected_revision=3,
                event_id=uuid4(),
                requested_at=cutoff - timedelta(seconds=1),
            ),
        ),
    )
    return checkpoint, cutoff


def test_roundtrip_contains_only_content_free_record_fields():
    checkpoint, cutoff = sample()
    document = seal(checkpoint, SECRET)
    assert (
        verify(
            document,
            SECRET,
            installation_id=checkpoint.installation_id,
            required_through=cutoff,
        )
        == checkpoint
    )
    record = json.loads(document)["checkpoint"]["records"][0]
    assert set(record) == {
        "survey_id",
        "requested_by",
        "operation_hash",
        "expected_revision",
        "event_id",
        "requested_at",
    }


@pytest.mark.parametrize(
    "change",
    [
        "remove",
        "actor",
        "extra",
        "signature",
        "wrong-key",
        "wrong-installation",
        "stale",
        "naive",
        "future",
    ],
)
def test_rejects_unsafe_checkpoints(change):
    checkpoint, cutoff = sample()
    envelope = json.loads(seal(checkpoint, SECRET))
    key, installation, required = SECRET, checkpoint.installation_id, cutoff
    if change == "remove":
        envelope["checkpoint"]["records"] = []
    elif change == "actor":
        envelope["checkpoint"]["records"][0]["requested_by"] = str(uuid4())
    elif change == "extra":
        envelope["checkpoint"]["records"][0]["answers"] = {"private": "content"}
    elif change == "signature":
        envelope["hmac_sha256"] = "0" * 64
    elif change == "wrong-key":
        key = SECRET + "-different"
    elif change == "wrong-installation":
        installation = uuid4()
    elif change == "stale":
        required += timedelta(seconds=1)
    elif change == "naive":
        required = required.replace(tzinfo=None)
    elif change == "future":
        envelope = json.loads(
            seal(
                checkpoint.model_copy(
                    update={"exported_at": cutoff + timedelta(days=1)}
                ),
                SECRET,
            )
        )
    with pytest.raises(ValueError):
        verify(
            json.dumps(envelope).encode(),
            key,
            installation_id=installation,
            required_through=required,
        )


def test_duplicate_identities_rejected_even_with_valid_signature():
    checkpoint, cutoff = sample()
    duplicate = checkpoint.model_copy(update={"records": checkpoint.records * 2})
    with pytest.raises(ValueError):
        verify(
            seal(duplicate, SECRET),
            SECRET,
            installation_id=checkpoint.installation_id,
            required_through=cutoff,
        )


def test_export_and_import_share_the_exact_document_byte_boundary(monkeypatch):
    import leonaid.application.surveys.recovery as recovery

    checkpoint, cutoff = sample()
    document = seal(checkpoint, SECRET)
    # Exercise the same boundary with a small complete, authenticated document.
    monkeypatch.setattr(recovery, "MAX_DOCUMENT_BYTES", len(document))
    assert seal(checkpoint, SECRET) == document
    assert (
        verify(
            document,
            SECRET,
            installation_id=checkpoint.installation_id,
            required_through=cutoff,
        )
        == checkpoint
    )
    monkeypatch.setattr(recovery, "MAX_DOCUMENT_BYTES", len(document) - 1)
    with pytest.raises(ValueError, match="supported size"):
        seal(checkpoint, SECRET)
    with pytest.raises(ValueError, match="supported size"):
        verify(
            document,
            SECRET,
            installation_id=checkpoint.installation_id,
            required_through=cutoff,
        )
