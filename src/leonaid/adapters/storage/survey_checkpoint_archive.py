"""POSIX checkpoint archive on an independently retained, durable filesystem.

Writers and readers serialize through flock. A durable pending document makes an
interrupted publication fail closed, including interruption after current.json
was replaced. Recovery requires another authenticated, non-regressing publication.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import os
from pathlib import Path
import tempfile
from uuid import UUID

from leonaid.application.surveys.recovery import (
    MAX_DOCUMENT_BYTES,
    ErasureCheckpoint,
    seal,
    verify,
)


def sync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: Path, document: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".erasure-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(document)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def bounded_read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        data = source.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise ValueError("Checkpoint exceeds the supported size")
    return data


class FileCheckpointArchive:
    def __init__(self, directory: Path):
        # Provision/mount this directory independently; silently creating a local
        # substitute for an absent recovery mount could produce false durability.
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("An existing recovery archive directory is required")
        self.directory = directory

    @contextmanager
    def locked(self) -> Iterator[None]:
        fd = os.open(
            self.directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    @staticmethod
    def extends(candidate: ErasureCheckpoint, previous: ErasureCheckpoint) -> None:
        if candidate.exported_at < previous.exported_at:
            raise ValueError("Archive publication would regress its cutoff")
        if candidate.exported_at == previous.exported_at and candidate != previous:
            raise ValueError("Archive cutoff has conflicting contents")
        records = {record.survey_id: record for record in candidate.records}
        if any(records.get(record.survey_id) != record for record in previous.records):
            raise ValueError("Archive publication omits or changes a prior erasure")

    def publish(self, checkpoint: ErasureCheckpoint, secret: str) -> None:
        document = seal(checkpoint, secret)
        # Verify even in-process models: model_copy can bypass Pydantic validators.
        checkpoint = verify(
            document,
            secret,
            installation_id=checkpoint.installation_id,
            required_through=checkpoint.exported_at,
        )
        with self.locked():
            current, pending = (
                self.directory / "current.json",
                self.directory / "pending.json",
            )
            if (
                not current.exists()
                and not current.is_symlink()
                and not pending.exists()
                and not pending.is_symlink()
                and any(self.directory.glob("*.json"))
            ):
                raise ValueError(
                    "Current checkpoint is missing from an existing archive"
                )
            for name in ["current.json", "pending.json"]:
                path = self.directory / name
                if path.exists() or path.is_symlink():
                    prior = verify(
                        bounded_read(path),
                        secret,
                        installation_id=checkpoint.installation_id,
                        required_through=datetime.min.replace(
                            tzinfo=checkpoint.exported_at.tzinfo
                        ),
                    )
                    self.extends(checkpoint, prior)
            atomic_write(self.directory / "pending.json", document)
            # Retain complete immutable content-addressed versions for inspection.
            retained = self.directory / (hashlib.sha256(document).hexdigest() + ".json")
            if retained.exists() or retained.is_symlink():
                if bounded_read(retained) != document:
                    raise ValueError("Archived checkpoint bytes differ")
            else:
                atomic_write(retained, document)
            atomic_write(self.directory / "current.json", document)
            (self.directory / "pending.json").unlink()
            sync_directory(self.directory)

    def fetch(
        self, secret: str, *, installation_id: UUID, required_through: datetime
    ) -> bytes:
        with self.locked():
            pending = self.directory / "pending.json"
            if pending.exists() or pending.is_symlink():
                raise ValueError("Archive publication is incomplete")
            document = bounded_read(self.directory / "current.json")
            verify(
                document,
                secret,
                installation_id=installation_id,
                required_through=required_through,
            )
            retained = self.directory / (hashlib.sha256(document).hexdigest() + ".json")
            if bounded_read(retained) != document:
                raise ValueError("Latest checkpoint has no matching retained version")
            return document
