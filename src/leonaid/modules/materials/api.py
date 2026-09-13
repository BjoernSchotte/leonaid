"""Typed material operations for direct callers and transport adapters."""

from dataclasses import dataclass

import hashlib
import re
import unicodedata
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import ConfigDict, Field, StringConstraints, field_validator

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.http import TransportModel

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
]
MEDIA_TYPE = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")


class MaterialModel(TransportModel):
    model_config = ConfigDict(
        strict=True, revalidate_instances="always", validate_default=True
    )

    @field_validator(
        "id",
        "material_id",
        "action_id",
        "owner_user_id",
        "idempotency_key",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def parse_identifier(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value


class UploadMetadata(MaterialModel):
    idempotency_key: UUID
    filename: str = Field(min_length=1, max_length=240)
    media_type: str = Field(
        default="application/octet-stream", min_length=1, max_length=255
    )

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if (
            value != value.strip()
            or value in {".", ".."}
            or any(
                character in "/\\" or unicodedata.category(character).startswith("C")
                for character in value
            )
        ):
            raise ValueError(
                "Dateiname muss ein einfacher Name ohne Pfad oder Steuerzeichen sein."
            )
        return value

    @field_validator("media_type")
    @classmethod
    def valid_media_type(cls, value: str) -> str:
        if not MEDIA_TYPE.fullmatch(value):
            raise ValueError("Medientyp muss type/subtype ohne Parameter sein.")
        return value


class CreateMaterial(UploadMetadata):
    title: Title
    action_id: UUID | None = None


class AddVersion(UploadMetadata):
    expected_revision: int = Field(ge=1)


class MaterialQuery(MaterialModel):
    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)
    action_id: UUID | None = None


class Material(MaterialModel):
    id: UUID
    action_id: UUID | None
    owner_user_id: UUID
    title: str
    revision: int = Field(ge=1)
    current_version: int = Field(ge=1)


class MaterialVersion(MaterialModel):
    material_id: UUID
    version: int = Field(ge=1)
    filename: str
    media_type: str
    size_bytes: int = Field(ge=1, le=MAX_UPLOAD_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class MaterialDownload:
    version: MaterialVersion
    content: bytes


class Materials(MaterialModel):
    items: list[Material]
    next_offset: int | None


def upload_digest(content: bytes) -> str:
    """Validate actual bytes before storage; caller metadata never sets the digest."""
    if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_UPLOAD_BYTES:
        raise ValueError("Eine Datei muss zwischen einem Byte und 25 MiB groß sein.")
    return hashlib.sha256(content).hexdigest()


class MaterialRepository(Protocol):
    async def download(
        self, actor: IdentityPrincipal, material_id: UUID, version: int
    ) -> MaterialDownload: ...

    async def create_material(
        self, actor: IdentityPrincipal, command: CreateMaterial, content: bytes
    ) -> Material: ...

    async def add_version(
        self,
        actor: IdentityPrincipal,
        material_id: UUID,
        command: AddVersion,
        content: bytes,
    ) -> Material: ...

    async def get_material(
        self, actor: IdentityPrincipal, material_id: UUID
    ) -> Material: ...

    async def get_version(
        self, actor: IdentityPrincipal, material_id: UUID, version: int
    ) -> MaterialVersion: ...

    async def list_materials(
        self, actor: IdentityPrincipal, query: MaterialQuery
    ) -> Materials: ...


class MaterialService:
    async def download(
        self, actor: IdentityPrincipal, material_id: UUID, version: int
    ) -> MaterialDownload:
        if type(version) is not int or version < 1:
            raise ValueError("Dateiversion muss eine positive ganze Zahl sein.")
        return await self._repository.download(actor, material_id, version)

    def __init__(self, repository: MaterialRepository) -> None:
        self._repository = repository

    async def create_material(
        self, actor: IdentityPrincipal, command: CreateMaterial, content: bytes
    ) -> Material:
        command = CreateMaterial.model_validate(command)
        upload_digest(content)
        return await self._repository.create_material(actor, command, content)

    async def add_version(
        self,
        actor: IdentityPrincipal,
        material_id: UUID,
        command: AddVersion,
        content: bytes,
    ) -> Material:
        command = AddVersion.model_validate(command)
        upload_digest(content)
        return await self._repository.add_version(actor, material_id, command, content)

    async def get_material(
        self, actor: IdentityPrincipal, material_id: UUID
    ) -> Material:
        return await self._repository.get_material(actor, material_id)

    async def get_version(
        self, actor: IdentityPrincipal, material_id: UUID, version: int
    ) -> MaterialVersion:
        if type(version) is not int or version < 1:
            raise ValueError("Dateiversion muss eine positive ganze Zahl sein.")
        return await self._repository.get_version(actor, material_id, version)

    async def list_materials(
        self, actor: IdentityPrincipal, query: MaterialQuery
    ) -> Materials:
        return await self._repository.list_materials(
            actor, MaterialQuery.model_validate(query)
        )
