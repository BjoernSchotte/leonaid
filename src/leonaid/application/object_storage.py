"""Provider-neutral private object-storage port."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from uuid import UUID

from leonaid.domain.errors import DomainInvariantError

SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ObjectStorageError(RuntimeError):
    """Base error without provider-specific details."""


class ObjectStorageUnavailable(ObjectStorageError):
    pass


class ObjectStorageConflict(ObjectStorageError):
    pass


class ObjectStorageIntegrityError(ObjectStorageError):
    pass


class ObjectStorageNotFound(ObjectStorageError):
    pass


@dataclass(frozen=True, slots=True)
class ObjectLocation:
    bucket: str
    key: str
    version_id: str | None = None

    def __post_init__(self) -> None:
        if not self.bucket.strip() or not self.key.strip():
            raise DomainInvariantError(
                "object_location_invalid",
                "Bucket und Object Key dürfen nicht leer sein.",
            )


@dataclass(frozen=True, slots=True)
class ObjectWrite:
    location: ObjectLocation
    content: bytes
    media_type: str
    sha256: str
    metadata: dict[str, str]

    def __post_init__(self) -> None:
        if self.location.version_id is not None:
            raise DomainInvariantError(
                "object_write_version_forbidden",
                "Eine neue Objektversion darf keine Version-ID vorgeben.",
            )
        if not self.content:
            raise DomainInvariantError(
                "object_write_empty",
                "Ein Speicherobjekt darf nicht leer sein.",
            )
        if not self.media_type.strip() or not SHA256.fullmatch(self.sha256):
            raise DomainInvariantError(
                "object_write_metadata_invalid",
                "Medientyp oder SHA-256 des Speicherobjekts ist ungültig.",
            )
        if any(
            not key.strip() or not value.strip() or key.casefold() == "sha256"
            for key, value in self.metadata.items()
        ):
            raise DomainInvariantError(
                "object_write_metadata_invalid",
                "Objekt-Metadaten sind leer, ungültig oder reserviert.",
            )


@dataclass(frozen=True, slots=True)
class StoredObject:
    location: ObjectLocation
    media_type: str
    size_bytes: int
    sha256: str
    metadata: dict[str, str]

    def __post_init__(self) -> None:
        if not self.location.version_id or self.location.version_id == "null":
            raise ObjectStorageIntegrityError(
                "Das gespeicherte Objekt besitzt keine unveränderliche Version-ID."
            )
        if self.size_bytes < 1 or not SHA256.fullmatch(self.sha256):
            raise ObjectStorageIntegrityError(
                "Das gespeicherte Objekt besitzt ungültige Integritätsdaten."
            )


@dataclass(frozen=True, slots=True)
class RetrievedObject:
    stored: StoredObject
    content: bytes

    def __post_init__(self) -> None:
        if len(self.content) != self.stored.size_bytes:
            raise ObjectStorageIntegrityError(
                "Die gelesene Objektgröße stimmt nicht mit den Metadaten überein."
            )


@dataclass(frozen=True, slots=True)
class ObjectDeletionAuthorization:
    actor_user_id: UUID
    reason: str

    def __post_init__(self) -> None:
        if len(self.reason.strip()) < 8:
            raise DomainInvariantError(
                "object_delete_reason_required",
                "Eine kontrollierte Löschung benötigt eine nachvollziehbare Begründung.",
            )


class ObjectStorage(Protocol):
    @property
    def bucket(self) -> str: ...

    async def ensure_private_versioned_bucket(self) -> None: ...

    async def put_immutable(self, write: ObjectWrite) -> StoredObject: ...

    async def head(self, location: ObjectLocation) -> StoredObject | None: ...

    async def get(self, location: ObjectLocation) -> RetrievedObject: ...

    async def protected_download_url(
        self,
        location: ObjectLocation,
        *,
        expires_in: timedelta,
    ) -> str: ...

    async def delete(
        self,
        location: ObjectLocation,
        *,
        authorization: ObjectDeletionAuthorization,
    ) -> None: ...
