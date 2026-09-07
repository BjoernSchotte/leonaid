"""Real filesystem/process failures must not turn an old archive into latest state."""

from datetime import datetime, timedelta, timezone
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from leonaid.adapters.storage.survey_checkpoint_archive import FileCheckpointArchive
from leonaid.application.surveys.recovery import ErasureCheckpoint, ErasureRecord, seal

SECRET = "synthetic-checkpoint-archive-key-not-for-real-use"


def checkpoints():
    now = datetime.now(timezone.utc)
    previous = ErasureCheckpoint(
        installation_id=uuid4(), exported_at=now - timedelta(seconds=2), records=()
    )
    latest = previous.model_copy(
        update={
            "exported_at": now,
            "records": (
                ErasureRecord(
                    survey_id=uuid4(),
                    requested_by=uuid4(),
                    operation_hash="a" * 64,
                    expected_revision=2,
                    event_id=uuid4(),
                    requested_at=now - timedelta(seconds=1),
                ),
            ),
        }
    )
    return previous, latest


def fetch(archive, checkpoint):
    return archive.fetch(
        SECRET,
        installation_id=checkpoint.installation_id,
        required_through=checkpoint.exported_at,
    )


def test_latest_publication_is_retained_and_never_regresses(tmp_path):
    previous, latest = checkpoints()
    archive = FileCheckpointArchive(tmp_path)
    archive.publish(previous, SECRET)
    archive.publish(latest, SECRET)
    archive.publish(latest, SECRET)
    assert fetch(archive, latest) == seal(latest, SECRET)
    assert (
        len(list(tmp_path.glob("*.json"))) == 3
    )  # two immutable documents and current
    with pytest.raises(ValueError, match="regress"):
        archive.publish(previous, SECRET)
    omitted = latest.model_copy(
        update={"exported_at": datetime.now(timezone.utc), "records": ()}
    )
    with pytest.raises(ValueError, match="omits"):
        archive.publish(omitted, SECRET)
    assert fetch(archive, latest) == seal(latest, SECRET)
    for path in tmp_path.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("stage", ["before-pending", "after-pending", "after-current"])
def test_killed_publisher_fails_closed_and_can_resume(tmp_path, stage):
    previous, latest = checkpoints()
    archive = FileCheckpointArchive(tmp_path)
    archive.publish(previous, SECRET)
    candidate = tmp_path / "candidate"
    candidate.write_bytes(seal(latest, SECRET))
    script = """
import json, os, sys
from pathlib import Path
import leonaid.adapters.storage.survey_checkpoint_archive as module
from leonaid.application.surveys.recovery import ErasureCheckpoint
root, stage, secret = Path(sys.argv[1]), sys.argv[2], os.environ["ARCHIVE_TEST_SECRET"]
candidate = ErasureCheckpoint.model_validate(json.loads((root / "candidate").read_bytes())["checkpoint"])
original = module.atomic_write
def crash(path, document):
    if stage == "before-pending" and path.name == "pending.json": os._exit(73)
    original(path, document)
    if (stage == "after-pending" and path.name == "pending.json") or (stage == "after-current" and path.name == "current.json"): os._exit(73)
module.atomic_write = crash
module.FileCheckpointArchive(root).publish(candidate, secret)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), stage],
        env={**os.environ, "ARCHIVE_TEST_SECRET": SECRET},
        timeout=15,
    )
    assert result.returncode == 73
    with pytest.raises(ValueError):
        fetch(archive, latest)
    if stage != "before-pending":
        # A supplied stale cutoff must not bypass an unfinished publication.
        with pytest.raises(ValueError, match="incomplete"):
            fetch(archive, previous)
        with pytest.raises(ValueError):
            archive.publish(previous, SECRET)
    archive.publish(latest, SECRET)
    assert fetch(archive, latest) == seal(latest, SECRET)
    assert not (tmp_path / "pending.json").exists()


@pytest.mark.parametrize(
    "damage",
    [
        "missing-current",
        "tampered-current",
        "missing-retained",
        "wrong-key",
        "wrong-installation",
        "stale",
        "symlink",
    ],
)
def test_archive_corruption_and_stale_inputs_fail_closed(tmp_path, damage):
    _, latest = checkpoints()
    archive = FileCheckpointArchive(tmp_path)
    archive.publish(latest, SECRET)
    key, identity, cutoff = SECRET, latest.installation_id, latest.exported_at
    current = tmp_path / "current.json"
    if damage == "missing-current":
        current.unlink()
    elif damage == "tampered-current":
        current.write_text("{}")
    elif damage == "missing-retained":
        next(path for path in tmp_path.glob("*.json") if path != current).unlink()
    elif damage == "wrong-key":
        key += "wrong"
    elif damage == "wrong-installation":
        identity = uuid4()
    elif damage == "stale":
        cutoff += timedelta(seconds=1)
    elif damage == "symlink":
        retained = next(path for path in tmp_path.glob("*.json") if path != current)
        current.unlink()
        current.symlink_to(retained)
    with pytest.raises((ValueError, OSError)):
        archive.fetch(key, installation_id=identity, required_through=cutoff)


def test_fetch_cli_needs_no_database_and_preserves_output_on_failure(tmp_path):
    _, latest = checkpoints()
    directory = tmp_path / "archive"
    directory.mkdir()
    FileCheckpointArchive(directory).publish(latest, SECRET)
    output = tmp_path / "fetched.json"
    command = [
        sys.executable,
        "tools/surveys/recovery.py",
        "fetch",
        "--archive",
        str(directory),
        "--output",
        str(output),
        "--installation-id",
        str(latest.installation_id),
        "--required-through",
        latest.exported_at.isoformat(),
    ]
    env = {**os.environ, "LEONAID_SESSION_ENCRYPTION_KEY": SECRET}
    env.pop("CORE_DATABASE_URL", None)
    result = subprocess.run(command, env=env, capture_output=True, timeout=15)
    assert result.returncode == 0
    assert output.read_bytes() == seal(latest, SECRET)
    assert output.stat().st_mode & 0o777 == 0o600
    (directory / "pending.json").write_bytes(seal(latest, SECRET))
    result = subprocess.run(command, env=env, capture_output=True, timeout=15)
    assert result.returncode == 1 and b"BLOCKED" in result.stderr
    assert output.read_bytes() == seal(latest, SECRET)
    assert SECRET.encode() not in result.stdout + result.stderr


def test_missing_archive_is_not_created_as_a_local_fallback(tmp_path):
    with pytest.raises(ValueError):
        FileCheckpointArchive(tmp_path / "not-mounted")


def test_unchanged_ledger_does_not_grow_archive_or_claim_a_new_cutoff(tmp_path):
    _, latest = checkpoints()
    archive = FileCheckpointArchive(tmp_path)
    archive.publish(latest, SECRET)
    later = latest.model_copy(update={"exported_at": datetime.now(timezone.utc)})
    for _ in range(10):
        archive.publish(later, SECRET, only_if_changed=True)
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert fetch(archive, latest) == seal(latest, SECRET)
    with pytest.raises(ValueError):
        fetch(archive, later)
    archive.publish(later, SECRET)
    assert fetch(archive, later) == seal(later, SECRET)


def test_unchanged_ledger_still_repairs_pending_and_checks_retained_bytes(tmp_path):
    _, latest = checkpoints()
    archive = FileCheckpointArchive(tmp_path)
    archive.publish(latest, SECRET)
    (tmp_path / "pending.json").write_bytes(seal(latest, SECRET))
    later = latest.model_copy(update={"exported_at": datetime.now(timezone.utc)})
    archive.publish(later, SECRET, only_if_changed=True)
    assert fetch(archive, later) == seal(later, SECRET)
    import hashlib

    retained = tmp_path / (hashlib.sha256(seal(later, SECRET)).hexdigest() + ".json")
    retained.unlink()
    with pytest.raises(OSError):
        archive.publish(later, SECRET, only_if_changed=True)


def test_missing_current_cannot_reinitialize_an_existing_archive_with_old_state(
    tmp_path,
):
    previous, latest = checkpoints()
    archive = FileCheckpointArchive(tmp_path)
    archive.publish(previous, SECRET)
    archive.publish(latest, SECRET)
    (tmp_path / "current.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        archive.publish(previous, SECRET)
    assert not (tmp_path / "current.json").exists()
