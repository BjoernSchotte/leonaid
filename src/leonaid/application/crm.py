"""Semantic CRM port used by LeonAid application services."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from leonaid.application.errors import ApplicationError


class CrmPartyKind(StrEnum):
    COMPANY = "company"
    PERSON = "person"


class CrmSyncStatus(StrEnum):
    SYNCED = "synced"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


def _required_text(value: str, label: str, *, maximum: int = 300) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} darf nicht leer sein.")
    if len(normalized) > maximum:
        raise ValueError(f"{label} darf höchstens {maximum} Zeichen enthalten.")
    return normalized


def _optional_text(value: str | None, label: str, *, maximum: int = 300) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if len(normalized) > maximum:
        raise ValueError(f"{label} darf höchstens {maximum} Zeichen enthalten.")
    return normalized or None


@dataclass(frozen=True, slots=True)
class PostalAddress:
    street_line_1: str | None = None
    street_line_2: str | None = None
    postal_code: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "street_line_1",
            _optional_text(self.street_line_1, "Straße", maximum=300),
        )
        object.__setattr__(
            self,
            "street_line_2",
            _optional_text(self.street_line_2, "Adresszusatz", maximum=300),
        )
        object.__setattr__(
            self,
            "postal_code",
            _optional_text(self.postal_code, "Postleitzahl", maximum=40),
        )
        object.__setattr__(
            self,
            "city",
            _optional_text(self.city, "Ort", maximum=200),
        )
        object.__setattr__(
            self,
            "state",
            _optional_text(self.state, "Region", maximum=200),
        )
        object.__setattr__(
            self,
            "country",
            _optional_text(self.country, "Land", maximum=200),
        )


@dataclass(frozen=True, slots=True)
class CompanyData:
    name: str
    address: PostalAddress = field(default_factory=PostalAddress)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "Firmenname"))


@dataclass(frozen=True, slots=True)
class PersonData:
    given_name: str
    family_name: str
    email: str | None = None
    company_twenty_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "given_name",
            _required_text(self.given_name, "Vorname", maximum=200),
        )
        object.__setattr__(
            self,
            "family_name",
            _required_text(self.family_name, "Nachname", maximum=200),
        )
        normalized_email = _optional_text(self.email, "E-Mail-Adresse", maximum=320)
        if normalized_email is not None and (
            "@" not in normalized_email
            or normalized_email.startswith("@")
            or normalized_email.endswith("@")
        ):
            raise ValueError("E-Mail-Adresse ist ungültig.")
        object.__setattr__(self, "email", normalized_email)


@dataclass(frozen=True, slots=True)
class CompanyRecord:
    twenty_id: UUID
    data: CompanyData


@dataclass(frozen=True, slots=True)
class PersonRecord:
    twenty_id: UUID
    data: PersonData


@dataclass(frozen=True, slots=True)
class CompanyUpdate:
    name: str | None = None
    address: PostalAddress | None = None

    def __post_init__(self) -> None:
        normalized_name = (
            None if self.name is None else _required_text(self.name, "Firmenname")
        )
        object.__setattr__(self, "name", normalized_name)
        if normalized_name is None and self.address is None:
            raise ValueError("Company-Update muss mindestens ein Feld ändern.")


@dataclass(frozen=True, slots=True)
class PersonUpdate:
    given_name: str | None = None
    family_name: str | None = None
    email: str | None = None
    company_twenty_id: UUID | None = None

    def __post_init__(self) -> None:
        given_name = (
            None
            if self.given_name is None
            else _required_text(self.given_name, "Vorname", maximum=200)
        )
        family_name = (
            None
            if self.family_name is None
            else _required_text(self.family_name, "Nachname", maximum=200)
        )
        email = _optional_text(self.email, "E-Mail-Adresse", maximum=320)
        if email is not None and (
            "@" not in email or email.startswith("@") or email.endswith("@")
        ):
            raise ValueError("E-Mail-Adresse ist ungültig.")
        object.__setattr__(self, "given_name", given_name)
        object.__setattr__(self, "family_name", family_name)
        object.__setattr__(self, "email", email)
        if (
            given_name is None
            and family_name is None
            and email is None
            and self.company_twenty_id is None
        ):
            raise ValueError("Person-Update muss mindestens ein Feld ändern.")


@dataclass(frozen=True, slots=True)
class CrmSyncReceipt:
    leonaid_id: UUID
    twenty_id: UUID
    party_kind: CrmPartyKind
    status: CrmSyncStatus
    correlation_id: str


class CrmGatewayError(ApplicationError):
    """Secret-safe failure at the CRM boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        operation: str,
        correlation_id: str,
        retryable: bool,
        outcome_unknown: bool,
        leonaid_id: UUID | None = None,
        twenty_id: UUID | None = None,
        http_status: int | None = None,
        completed: tuple[CrmSyncReceipt, ...] = (),
    ) -> None:
        super().__init__(code, message)
        self.operation = operation
        self.correlation_id = correlation_id
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown
        self.leonaid_id = leonaid_id
        self.twenty_id = twenty_id
        self.http_status = http_status
        self.completed = completed
        self.sync_status = (
            CrmSyncStatus.OUTCOME_UNKNOWN if outcome_unknown else CrmSyncStatus.FAILED
        )


class CrmGateway(Protocol):
    async def search_companies(
        self,
        name_query: str,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, ...]: ...

    async def get_company(
        self,
        twenty_id: UUID,
        *,
        correlation_id: str,
    ) -> CompanyRecord | None: ...

    async def create_company(
        self,
        leonaid_id: UUID,
        company: CompanyData,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, CrmSyncReceipt]: ...

    async def create_companies(
        self,
        companies: tuple[tuple[UUID, CompanyData], ...],
        *,
        correlation_id: str,
    ) -> tuple[tuple[CompanyRecord, CrmSyncReceipt], ...]: ...

    async def update_company(
        self,
        leonaid_id: UUID,
        twenty_id: UUID,
        update: CompanyUpdate,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, CrmSyncReceipt]: ...

    async def search_people(
        self,
        *,
        given_name: str,
        family_name: str,
        correlation_id: str,
    ) -> tuple[PersonRecord, ...]: ...

    async def get_person(
        self,
        twenty_id: UUID,
        *,
        correlation_id: str,
    ) -> PersonRecord | None: ...

    async def create_person(
        self,
        leonaid_id: UUID,
        person: PersonData,
        *,
        correlation_id: str,
    ) -> tuple[PersonRecord, CrmSyncReceipt]: ...

    async def create_people(
        self,
        people: tuple[tuple[UUID, PersonData], ...],
        *,
        correlation_id: str,
    ) -> tuple[tuple[PersonRecord, CrmSyncReceipt], ...]: ...

    async def update_person(
        self,
        leonaid_id: UUID,
        twenty_id: UUID,
        update: PersonUpdate,
        *,
        correlation_id: str,
    ) -> tuple[PersonRecord, CrmSyncReceipt]: ...
