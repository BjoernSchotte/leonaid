"""Typed Inbox operations, independent of HTTP and CRM availability."""

from datetime import datetime
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
from leonaid.domain.identity import IdentityPrincipal
from leonaid.application.crm import PersonData


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
        "twenty_person_id",
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


class InboxRepository(Protocol):
    async def submit(self, command: SubmitCase) -> Submission: ...
    async def get_case(self, actor: IdentityPrincipal, case_id: UUID) -> Case: ...
    async def list_cases(self, actor: IdentityPrincipal, query: CaseQuery) -> Cases: ...
    async def update_case(
        self, actor: IdentityPrincipal, case_id: UUID, command: UpdateCase
    ) -> Case: ...


class InboxService:
    def __init__(self, repository: InboxRepository) -> None:
        self._repository = repository

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
    "Cases",
    "UpdateCase",
]
