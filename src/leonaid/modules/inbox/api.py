"""Typed Inbox operations, independent of HTTP and CRM availability."""

from datetime import datetime
from dataclasses import asdict
import hashlib
import json
from typing import Annotated, Literal, Protocol
from uuid import UUID

from pydantic import (
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from leonaid.platform.http import TransportModel
from leonaid.platform.navigation import NavigationItem
from leonaid.domain.identity import IdentityPrincipal
from leonaid.application.crm import (
    CrmGateway,
    CrmGatewayError,
    PersonData,
    PersonRecord,
)
from leonaid.application.errors import Conflict, DependencyUnavailable, ResourceNotFound
from leonaid.modules.tasks.api import Task
from leonaid.modules.materials.api import MaterialVersion


class InboxModel(TransportModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, revalidate_instances="always"
    )

    @field_validator(
        "idempotency_key",
        "action_id",
        "reference",
        "id",
        "assignee_user_id",
        "user_id",
        "case_id",
        "task_id",
        "material_id",
        "author_user_id",
        "twenty_person_id",
        "person_id",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def parse_identifier(cls, value: object) -> object:
        return UUID(value) if isinstance(value, str) else value


class SubmitCase(InboxModel):
    idempotency_key: UUID
    action_id: UUID | None = None
    subject: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)
    ]
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
    ]
    given_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    family_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    email: EmailStr | None = None
    phone: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=7, max_length=40)
        ]
        | None
    ) = None

    @field_validator("subject", "message", "given_name", "family_name")
    @classmethod
    def reject_controls(cls, value: str) -> str:
        if any(
            ord(char) < 32 and char not in "\n\r\t" or ord(char) == 127
            for char in value
        ):
            raise ValueError("Steuerzeichen sind nicht erlaubt.")
        return value

    @field_validator("email")
    @classmethod
    def email_length(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 320:
            raise ValueError("E-Mail-Adresse ist zu lang.")
        return value

    @model_validator(mode="after")
    def require_contact(self) -> "SubmitCase":
        if self.email is None and self.phone is None:
            raise ValueError("E-Mail-Adresse oder Telefonnummer erforderlich.")
        # Use the same contact contract as the existing CRM adapter. In particular,
        # do not accept a national phone number that cannot later be synchronized.
        PersonData(
            given_name=self.given_name,
            family_name=self.family_name,
            email=self.email,
            phone=self.phone,
        )
        return self


class Submission(InboxModel):
    # This reference confirms receipt; it is never an authorization token.
    reference: UUID


class Case(InboxModel):
    id: UUID
    public_reference: UUID
    action_id: UUID | None
    subject: str
    message: str
    given_name: str
    family_name: str
    email: str | None
    phone: str | None
    received_at: datetime
    status: Literal["new", "in_progress", "closed"]
    assignee_user_id: UUID | None
    revision: int
    closure_note: str | None
    closed_at: datetime | None
    updated_at: datetime
    contact_status: Literal["pending", "linked", "needs_review", "failed"]
    contact_revision: int
    contact_error_code: str | None
    twenty_person_id: UUID | None


class CaseQuery(InboxModel):
    search: str = Field(default="", max_length=200)
    action_id: UUID | None = None
    status: Literal["new", "in_progress", "closed"] | None = None
    for_me: bool = False
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)


class Cases(InboxModel):
    items: list[Case]
    next_offset: int | None


class AssigneeQuery(InboxModel):
    search: str = Field(default="", max_length=200)
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)


class Assignee(InboxModel):
    user_id: UUID
    display_name: str


class Assignees(InboxModel):
    items: list[Assignee]
    next_offset: int | None


class ContactQuery(InboxModel):
    given_name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
        ]
        | None
    ) = None
    family_name: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
        ]
        | None
    ) = None


class ContactCandidate(InboxModel):
    person_id: UUID
    given_name: str
    family_name: str
    email: str | None
    phone: str | None
    fingerprint: str


class ContactCandidates(InboxModel):
    items: list[ContactCandidate]
    truncated: bool


class ConfirmContact(InboxModel):
    idempotency_key: UUID
    expected_contact_revision: int = Field(ge=1)
    person_id: UUID
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
    ]

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        return SubmitCase.reject_controls(value)


def contact_candidate(person: PersonRecord) -> ContactCandidate:
    fingerprint = hashlib.sha256(
        json.dumps(
            {"id": str(person.twenty_id), "data": asdict(person.data)},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    return ContactCandidate(
        person_id=person.twenty_id,
        given_name=person.data.given_name,
        family_name=person.data.family_name,
        email=person.data.email,
        phone=person.data.phone,
        fingerprint=fingerprint,
    )


class SetTaskReference(InboxModel):
    idempotency_key: UUID
    expected_revision: int = Field(ge=1)
    task_id: UUID
    present: bool


class TaskReference(InboxModel):
    task_id: UUID
    # A stored reference never grants access to the referenced task.
    task: Task | None


class TaskReferences(InboxModel):
    items: list[TaskReference]


class SetMaterialReference(InboxModel):
    idempotency_key: UUID
    expected_revision: int = Field(ge=1)
    material_id: UUID
    material_version: int = Field(ge=1, le=9223372036854775807)
    present: bool


class MaterialReference(InboxModel):
    material_id: UUID
    material_version: int
    file: MaterialVersion | None


class MaterialReferences(InboxModel):
    items: list[MaterialReference]


class AddComment(InboxModel):
    idempotency_key: UUID
    body: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        return SubmitCase.reject_controls(value)


class Comment(InboxModel):
    id: UUID
    case_id: UUID
    author_user_id: UUID
    body: str
    created_at: datetime


class CommentQuery(InboxModel):
    offset: int = Field(default=0, ge=0, le=5000)
    limit: int = Field(default=50, ge=1, le=100)


class Comments(InboxModel):
    items: list[Comment]
    next_offset: int | None


class UpdateCase(InboxModel):
    idempotency_key: UUID
    expected_revision: int = Field(ge=1)
    status: Literal["new", "in_progress", "closed"]
    assignee_user_id: UUID | None
    closure_note: (
        Annotated[
            str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def closure_matches_status(self) -> "UpdateCase":
        if (self.status == "closed") != (self.closure_note is not None):
            raise ValueError("Abschlussnotiz nur bei geschlossenem Fall erforderlich.")
        if self.closure_note is not None:
            SubmitCase.reject_controls(self.closure_note)
        return self


class CasePermissions(InboxModel):
    can_manage: bool


class InboxRepository(Protocol):
    async def get_permissions(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> CasePermissions: ...

    async def get_managed_case(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> Case: ...
    async def confirm_contact(
        self, actor: IdentityPrincipal, case_id: UUID, command: ConfirmContact
    ) -> Case: ...

    async def set_material_reference(
        self, actor: IdentityPrincipal, case_id: UUID, command: SetMaterialReference
    ) -> Case: ...
    async def list_material_references(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> MaterialReferences: ...

    async def set_task_reference(
        self, actor: IdentityPrincipal, case_id: UUID, command: SetTaskReference
    ) -> Case: ...
    async def list_task_references(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> TaskReferences: ...

    async def add_comment(
        self, actor: IdentityPrincipal, case_id: UUID, command: AddComment
    ) -> Comment: ...
    async def list_comments(
        self, actor: IdentityPrincipal, case_id: UUID, query: CommentQuery
    ) -> Comments: ...

    async def list_assignees(
        self, actor: IdentityPrincipal, case_id: UUID, query: AssigneeQuery
    ) -> Assignees: ...

    async def submit(self, command: SubmitCase) -> Submission: ...
    async def get_case(self, actor: IdentityPrincipal, case_id: UUID) -> Case: ...
    async def list_cases(self, actor: IdentityPrincipal, query: CaseQuery) -> Cases: ...
    async def update_case(
        self, actor: IdentityPrincipal, case_id: UUID, command: UpdateCase
    ) -> Case: ...


class InboxService:
    def __init__(
        self, repository: InboxRepository, crm: CrmGateway | None = None
    ) -> None:
        self._repository = repository
        self._crm = crm

    async def get_permissions(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> CasePermissions:
        return await self._repository.get_permissions(actor, case_id)

    def _contact_gateway(self) -> CrmGateway:
        if self._crm is None:
            raise DependencyUnavailable(
                "inbox_crm_not_configured",
                "Kontaktklärung ist derzeit nicht verfügbar.",
            )
        return self._crm

    async def list_contact_candidates(
        self, actor: IdentityPrincipal, case_id: UUID, query: ContactQuery
    ) -> ContactCandidates:
        query = ContactQuery.model_validate(query)
        current = await self._repository.get_managed_case(actor, case_id)
        try:
            people = await self._contact_gateway().search_people(
                given_name=query.given_name or current.given_name,
                family_name=query.family_name or current.family_name,
                correlation_id=f"inbox.contact-preview:{case_id}",
            )
        except CrmGatewayError as error:
            raise DependencyUnavailable(
                "inbox_crm_unavailable", "Kontaktklärung ist derzeit nicht verfügbar."
            ) from error
        # Permissions may have changed while Twenty was answering.
        await self._repository.get_managed_case(actor, case_id)
        return ContactCandidates(
            items=[contact_candidate(person) for person in people[:50]],
            truncated=len(people) > 50,
        )

    async def confirm_contact(
        self, actor: IdentityPrincipal, case_id: UUID, command: ConfirmContact
    ) -> Case:
        command = ConfirmContact.model_validate(command)
        await self._repository.get_managed_case(actor, case_id)
        try:
            person = await self._contact_gateway().get_person(
                command.person_id, correlation_id=f"inbox.contact-confirm:{case_id}"
            )
        except CrmGatewayError as error:
            raise DependencyUnavailable(
                "inbox_crm_unavailable", "Kontaktklärung ist derzeit nicht verfügbar."
            ) from error
        if person is None:
            raise ResourceNotFound("not_found", "Kontakt nicht gefunden.")
        if contact_candidate(person).fingerprint != command.fingerprint:
            raise Conflict(
                "contact_changed",
                "Der Kontakt wurde inzwischen geändert. Bitte erneut prüfen.",
            )
        return await self._repository.confirm_contact(actor, case_id, command)

    async def set_material_reference(
        self, actor: IdentityPrincipal, case_id: UUID, command: SetMaterialReference
    ) -> Case:
        return await self._repository.set_material_reference(
            actor, case_id, SetMaterialReference.model_validate(command)
        )

    async def list_material_references(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> MaterialReferences:
        return await self._repository.list_material_references(actor, case_id)

    async def set_task_reference(
        self, actor: IdentityPrincipal, case_id: UUID, command: SetTaskReference
    ) -> Case:
        return await self._repository.set_task_reference(
            actor, case_id, SetTaskReference.model_validate(command)
        )

    async def list_task_references(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> TaskReferences:
        return await self._repository.list_task_references(actor, case_id)

    async def add_comment(
        self, actor: IdentityPrincipal, case_id: UUID, command: AddComment
    ) -> Comment:
        return await self._repository.add_comment(
            actor, case_id, AddComment.model_validate(command)
        )

    async def list_comments(
        self, actor: IdentityPrincipal, case_id: UUID, query: CommentQuery
    ) -> Comments:
        return await self._repository.list_comments(
            actor, case_id, CommentQuery.model_validate(query)
        )

    async def list_assignees(
        self, actor: IdentityPrincipal, case_id: UUID, query: AssigneeQuery
    ) -> Assignees:
        return await self._repository.list_assignees(
            actor, case_id, AssigneeQuery.model_validate(query)
        )

    async def submit(self, command: SubmitCase) -> Submission:
        return await self._repository.submit(SubmitCase.model_validate(command))

    async def get_case(self, actor: IdentityPrincipal, case_id: UUID) -> Case:
        return await self._repository.get_case(actor, case_id)

    async def list_cases(self, actor: IdentityPrincipal, query: CaseQuery) -> Cases:
        return await self._repository.list_cases(actor, CaseQuery.model_validate(query))

    async def update_case(
        self, actor: IdentityPrincipal, case_id: UUID, command: UpdateCase
    ) -> Case:
        return await self._repository.update_case(
            actor, case_id, UpdateCase.model_validate(command)
        )


__all__ = [
    "InboxService",
    "SubmitCase",
    "Submission",
    "Case",
    "CaseQuery",
    "CasePermissions",
    "Cases",
    "UpdateCase",
    "AssigneeQuery",
    "Assignee",
    "Assignees",
    "ContactQuery",
    "ContactCandidate",
    "ContactCandidates",
    "ConfirmContact",
    "SetMaterialReference",
    "MaterialReference",
    "MaterialReferences",
    "SetTaskReference",
    "TaskReference",
    "TaskReferences",
    "AddComment",
    "Comment",
    "CommentQuery",
    "Comments",
]


def navigation(actor: IdentityPrincipal) -> tuple[NavigationItem, ...]:
    if not actor.account.can_authenticate:
        return ()
    return (
        NavigationItem("inbox", "Eingänge", "/admin/inbox", "web"),
        NavigationItem("inbox", "Eingänge", "/app/inbox", "pwa"),
    )
