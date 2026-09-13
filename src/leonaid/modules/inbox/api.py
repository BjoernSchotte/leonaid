"""Typed Inbox operations, independent of HTTP and CRM availability."""

from typing import Annotated, Protocol
from uuid import UUID
import re

from pydantic import (
    ConfigDict,
    EmailStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from leonaid.platform.http import TransportModel


class InboxModel(TransportModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, revalidate_instances="always"
    )

    @field_validator(
        "idempotency_key", "action_id", "reference", mode="before", check_fields=False
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

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str | None) -> str | None:
        if value is not None and (
            re.fullmatch(r"\+?[0-9 ()/.-]+", value) is None
            or not 7 <= sum(char.isdigit() for char in value) <= 15
        ):
            raise ValueError("Telefonnummer mit 7 bis 15 Ziffern erforderlich.")
        return value

    @model_validator(mode="after")
    def require_contact(self) -> "SubmitCase":
        if self.email is None and self.phone is None:
            raise ValueError("E-Mail-Adresse oder Telefonnummer erforderlich.")
        return self


class Submission(InboxModel):
    # This reference confirms receipt; it is never an authorization token.
    reference: UUID


class InboxRepository(Protocol):
    async def submit(self, command: SubmitCase) -> Submission: ...


class InboxService:
    def __init__(self, repository: InboxRepository) -> None:
        self._repository = repository

    async def submit(self, command: SubmitCase) -> Submission:
        return await self._repository.submit(SubmitCase.model_validate(command))


__all__ = ["InboxService", "SubmitCase", "Submission"]
