"""Typed material operations for direct callers and transport adapters."""

from dataclasses import dataclass

import hashlib
import re
import unicodedata
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import EmailStr, ConfigDict, Field, StringConstraints, field_validator

from leonaid.domain.identity import IdentityPrincipal
from leonaid.platform.http import TransportModel
from leonaid.platform.navigation import NavigationItem

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
        "user_id",
        "material_id",
        "action_id",
        "owner_user_id",
        "idempotency_key",
        "upload_id",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def parse_identifier(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value


class CleanupUpload(MaterialModel):
    material_id: UUID
    upload_id: UUID
    storage_version_id: str = Field(min_length=1, max_length=1024)
    reason: str = Field(min_length=8, max_length=500)
    apply: bool = False

    @field_validator("storage_version_id", "reason")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if (
            value != value.strip()
            or value == "null"
            or any(unicodedata.category(c).startswith("C") for c in value)
        ):
            raise ValueError(
                "Eine eindeutige Version und nachvollziehbare Begründung sind erforderlich."
            )
        return value


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


class MemberQuery(MaterialModel):
    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)


class SetMaterialMember(MaterialModel):
    idempotency_key: UUID
    expected_access_revision: int = Field(ge=1)
    user_id: UUID
    access: Literal["viewer", "editor"] | None


class SetMaterialMemberByEmail(MaterialModel):
    idempotency_key: UUID
    expected_access_revision: int = Field(ge=1)
    email: EmailStr
    access: Literal["viewer", "editor"]


class MaterialAccess(MaterialModel):
    owner_user_id: UUID
    access_revision: int = Field(ge=1)


class MaterialPermissions(MaterialModel):
    can_edit: bool
    can_manage: bool


class MaterialMember(MaterialModel):
    user_id: UUID
    display_name: str
    access: Literal["viewer", "editor"]
    active: bool


class MaterialMembers(MaterialAccess):
    items: list[MaterialMember]
    next_offset: int | None


class MaterialRepository(Protocol):
    async def cleanup_upload(
        self, actor: IdentityPrincipal, command: CleanupUpload
    ) -> bool: ...

    async def get_permissions(
        self, actor: IdentityPrincipal, material_id: UUID
    ) -> MaterialPermissions: ...

    async def set_material_member(
        self,
        actor: IdentityPrincipal,
        material_id: UUID,
        command: SetMaterialMember | SetMaterialMemberByEmail,
    ) -> MaterialAccess: ...
    async def list_members(
        self, actor: IdentityPrincipal, material_id: UUID, query: MemberQuery
    ) -> MaterialMembers: ...

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
    async def cleanup_upload(
        self, actor: IdentityPrincipal, command: CleanupUpload
    ) -> bool:
        """Administrative exact-version cleanup; false means already absent."""
        return await self._repository.cleanup_upload(
            actor, CleanupUpload.model_validate(command)
        )

    async def get_permissions(
        self, actor: IdentityPrincipal, material_id: UUID
    ) -> MaterialPermissions:
        return await self._repository.get_permissions(actor, material_id)

    async def set_material_member(
        self, actor: IdentityPrincipal, material_id: UUID, command: SetMaterialMember
    ) -> MaterialAccess:
        return await self._repository.set_material_member(
            actor, material_id, SetMaterialMember.model_validate(command)
        )

    async def set_material_member_by_email(
        self,
        actor: IdentityPrincipal,
        material_id: UUID,
        command: SetMaterialMemberByEmail,
    ) -> MaterialAccess:
        return await self._repository.set_material_member(
            actor, material_id, SetMaterialMemberByEmail.model_validate(command)
        )

    async def list_members(
        self, actor: IdentityPrincipal, material_id: UUID, query: MemberQuery
    ) -> MaterialMembers:
        return await self._repository.list_members(
            actor, material_id, MemberQuery.model_validate(query)
        )

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


def navigation(actor: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    if not actor.account.can_authenticate:
        return ()
    return (
        NavigationItem("materials", "Materialien", "/admin/materials", "web"),
        NavigationItem("materials", "Materialien", "/app/materials", "pwa"),
    )
