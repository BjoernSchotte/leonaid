"""Deterministic sponsor matching and self-assignment at the CRM boundary."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from leonaid.application.crm import (
    CompanyData,
    CompanyRecord,
    CrmGateway,
    CrmPartyKind,
    PersonData,
    PersonRecord,
    PostalAddress,
)
from leonaid.application.errors import Conflict
from leonaid.application.policies import concealed_resource
from leonaid.domain.identity import IdentityPrincipal


class SponsorMatchStatus(StrEnum):
    NO_MATCH = "no_match"
    SINGLE_MATCH = "single_match"
    AMBIGUOUS_MATCH = "ambiguous_match"


class SponsorResolutionOutcome(StrEnum):
    CREATED = "created"
    REUSED = "reused"


def normalize_match_name(value: str) -> str:
    """Return the PoC match key shared by imports and interactive matching."""

    normalized = unicodedata.normalize("NFC", value.casefold())
    normalized = normalized.replace("k.g.", "kg").replace("e.k.", "ek")
    normalized = (
        normalized.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    normalized = unicodedata.normalize("NFKD", normalized)
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def candidate_company_query(value: str) -> str:
    """Choose a useful Twenty pre-filter without changing the exact match key."""

    ignored = {"ag", "ek", "gbr", "gmbh", "kg", "mbh", "ohg", "ug"}
    tokens = [
        token
        for token in normalize_match_name(value).split()
        if token not in ignored and len(token) >= 2
    ]
    if not tokens:
        tokens = normalize_match_name(value).split()
    if not tokens:
        raise ValueError("Firmenname enthält keinen suchbaren Bestandteil.")
    return max(tokens, key=len)


def company_matches(
    records: tuple[CompanyRecord, ...],
    normalized_key: str,
) -> tuple[CompanyRecord, ...]:
    return tuple(
        record
        for record in records
        if normalize_match_name(record.data.name) == normalized_key
    )


def person_matches(
    records: tuple[PersonRecord, ...],
    normalized_key: str,
) -> tuple[PersonRecord, ...]:
    return tuple(
        record
        for record in records
        if normalize_match_name(f"{record.data.given_name} {record.data.family_name}")
        == normalized_key
    )


def match_status(candidate_count: int) -> SponsorMatchStatus:
    if candidate_count < 0:
        raise ValueError("Trefferanzahl darf nicht negativ sein.")
    if candidate_count == 0:
        return SponsorMatchStatus.NO_MATCH
    if candidate_count == 1:
        return SponsorMatchStatus.SINGLE_MATCH
    return SponsorMatchStatus.AMBIGUOUS_MATCH


def _optional_text(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if len(normalized) > maximum:
        raise ValueError(f"Eingabe darf höchstens {maximum} Zeichen enthalten.")
    return normalized or None


@dataclass(frozen=True, slots=True)
class SponsorDraft:
    company_name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    email: str | None = None
    street_line_1: str | None = None
    postal_code: str | None = None
    city: str | None = None

    def __post_init__(self) -> None:
        for field_name, maximum in (
            ("company_name", 300),
            ("given_name", 200),
            ("family_name", 200),
            ("email", 320),
            ("street_line_1", 300),
            ("postal_code", 40),
            ("city", 200),
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), maximum=maximum),
            )
        if self.company_name is None and (
            self.given_name is None or self.family_name is None
        ):
            raise ValueError(
                "Ohne Firma sind Vorname und Nachname für das Matching erforderlich."
            )
        if self.email is not None and (
            "@" not in self.email
            or self.email.startswith("@")
            or self.email.endswith("@")
        ):
            raise ValueError("E-Mail-Adresse ist ungültig.")
        if not self.normalized_key:
            raise ValueError("Der Matchschlüssel darf nicht leer sein.")

    @property
    def party_kind(self) -> CrmPartyKind:
        return (
            CrmPartyKind.COMPANY
            if self.company_name is not None
            else CrmPartyKind.PERSON
        )

    @property
    def normalized_key(self) -> str:
        if self.company_name is not None:
            return normalize_match_name(self.company_name)
        return normalize_match_name(f"{self.given_name} {self.family_name}")


@dataclass(frozen=True, slots=True)
class AssignedAcquirer:
    user_id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class SponsorMatchCandidate:
    party_kind: CrmPartyKind
    twenty_id: UUID
    display_name: str
    postal_code: str | None
    city: str | None
    email: str | None
    assigned_acquirers: tuple[AssignedAcquirer, ...]


@dataclass(frozen=True, slots=True)
class SponsorMatchResult:
    status: SponsorMatchStatus
    party_kind: CrmPartyKind
    normalized_key: str
    input: SponsorDraft
    candidates: tuple[SponsorMatchCandidate, ...]


@dataclass(frozen=True, slots=True)
class SponsorResolution:
    outcome: SponsorResolutionOutcome
    party_kind: CrmPartyKind
    twenty_id: UUID
    display_name: str
    normalized_key: str
    assignment_id: UUID
    assignment_created: bool
    prior_assignees: tuple[AssignedAcquirer, ...]


@dataclass(frozen=True, slots=True)
class RecordedAssignment:
    assignment_id: UUID
    created: bool


class SponsorMatchingRepository(Protocol):
    async def can_self_assign(
        self,
        actor_user_id: UUID,
        action_id: UUID,
        *,
        evaluated_at: datetime,
    ) -> bool: ...

    async def assigned_acquirers(
        self,
        action_id: UUID,
        party_kind: CrmPartyKind,
        party_ids: tuple[UUID, ...],
        *,
        evaluated_at: datetime,
    ) -> dict[UUID, tuple[AssignedAcquirer, ...]]: ...

    async def record_resolution(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        party_kind: CrmPartyKind,
        twenty_id: UUID,
        outcome: SponsorResolutionOutcome,
        normalized_key: str,
        prior_assignee_ids: tuple[UUID, ...],
        request_id: str,
        occurred_at: datetime,
    ) -> RecordedAssignment | None: ...


class SponsorMatchingService:
    def __init__(
        self,
        repository: SponsorMatchingRepository,
        crm: CrmGateway,
    ) -> None:
        self._repository = repository
        self._crm = crm

    async def preview(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        draft: SponsorDraft,
        *,
        request_id: str,
    ) -> SponsorMatchResult:
        evaluated_at = datetime.now(timezone.utc)
        await self._authorize(actor, action_id, evaluated_at=evaluated_at)
        records: tuple[CompanyRecord | PersonRecord, ...]
        if draft.party_kind is CrmPartyKind.COMPANY:
            records = await self._matching_companies(
                draft,
                correlation_id=f"{request_id}:company-preview",
            )
        else:
            records = await self._matching_people(
                draft,
                correlation_id=f"{request_id}:person-preview",
            )
        party_ids = tuple(record.twenty_id for record in records)
        assigned = await self._repository.assigned_acquirers(
            action_id,
            draft.party_kind,
            party_ids,
            evaluated_at=evaluated_at,
        )
        candidates = tuple(
            sorted(
                (
                    (
                        self._company_candidate(record, assigned)
                        if isinstance(record, CompanyRecord)
                        else self._person_candidate(record, assigned)
                    )
                    for record in records
                ),
                key=lambda item: (item.display_name.casefold(), str(item.twenty_id)),
            )
        )
        status = match_status(len(candidates))
        return SponsorMatchResult(
            status=status,
            party_kind=draft.party_kind,
            normalized_key=draft.normalized_key,
            input=draft,
            candidates=candidates,
        )

    async def resolve(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        draft: SponsorDraft,
        *,
        expected_status: SponsorMatchStatus,
        selected_twenty_id: UUID | None,
        confirm_existing_assignments: bool,
        request_id: str,
    ) -> SponsorResolution:
        preview = await self.preview(
            actor,
            action_id,
            draft,
            request_id=request_id,
        )
        if preview.status is not expected_status:
            raise Conflict(
                "sponsor_match_changed",
                "Der CRM-Bestand hat sich geändert. Bitte prüfe die Treffer erneut.",
            )

        outcome: SponsorResolutionOutcome
        candidate: SponsorMatchCandidate
        if preview.status is SponsorMatchStatus.NO_MATCH:
            if selected_twenty_id is not None:
                raise Conflict(
                    "sponsor_match_selection_invalid",
                    "Für eine Neuanlage darf kein bestehender Treffer gewählt sein.",
                )
            candidate = await self._create_candidate(
                draft,
                correlation_id=f"{request_id}:create",
            )
            outcome = SponsorResolutionOutcome.CREATED
        else:
            candidate = self._selected_candidate(preview, selected_twenty_id)
            other_assignees = tuple(
                assignee
                for assignee in candidate.assigned_acquirers
                if assignee.user_id != actor.account.id
            )
            if other_assignees and not confirm_existing_assignments:
                names = ", ".join(item.display_name for item in other_assignees)
                raise Conflict(
                    "sponsor_match_confirmation_required",
                    f"Der Sponsor ist bereits {names} zugeordnet. "
                    "Bestätige die zusätzliche Zuordnung ausdrücklich.",
                )
            outcome = SponsorResolutionOutcome.REUSED

        occurred_at = datetime.now(timezone.utc)
        recorded = await self._repository.record_resolution(
            action_id=action_id,
            actor_user_id=actor.account.id,
            party_kind=candidate.party_kind,
            twenty_id=candidate.twenty_id,
            outcome=outcome,
            normalized_key=preview.normalized_key,
            prior_assignee_ids=tuple(
                item.user_id for item in candidate.assigned_acquirers
            ),
            request_id=request_id,
            occurred_at=occurred_at,
        )
        if recorded is None:
            raise concealed_resource()
        return SponsorResolution(
            outcome=outcome,
            party_kind=candidate.party_kind,
            twenty_id=candidate.twenty_id,
            display_name=candidate.display_name,
            normalized_key=preview.normalized_key,
            assignment_id=recorded.assignment_id,
            assignment_created=recorded.created,
            prior_assignees=candidate.assigned_acquirers,
        )

    async def _authorize(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        evaluated_at: datetime,
    ) -> None:
        if not await self._repository.can_self_assign(
            actor.account.id,
            action_id,
            evaluated_at=evaluated_at,
        ):
            raise concealed_resource()

    async def _matching_companies(
        self,
        draft: SponsorDraft,
        *,
        correlation_id: str,
    ) -> tuple[CompanyRecord, ...]:
        assert draft.company_name is not None
        direct = await self._crm.search_companies(
            candidate_company_query(draft.company_name),
            correlation_id=correlation_id,
        )
        exact = company_matches(direct, draft.normalized_key)
        if exact:
            return exact
        all_records = await self._crm.list_companies(
            correlation_id=f"{correlation_id}:unicode-fallback",
        )
        return company_matches(all_records, draft.normalized_key)

    async def _matching_people(
        self,
        draft: SponsorDraft,
        *,
        correlation_id: str,
    ) -> tuple[PersonRecord, ...]:
        assert draft.given_name is not None
        assert draft.family_name is not None
        direct = await self._crm.search_people(
            given_name=draft.given_name,
            family_name=draft.family_name,
            correlation_id=correlation_id,
        )
        exact = person_matches(direct, draft.normalized_key)
        if exact:
            return exact
        all_records = await self._crm.list_people(
            correlation_id=f"{correlation_id}:unicode-fallback",
        )
        return person_matches(all_records, draft.normalized_key)

    @staticmethod
    def _selected_candidate(
        preview: SponsorMatchResult,
        selected_twenty_id: UUID | None,
    ) -> SponsorMatchCandidate:
        if selected_twenty_id is None and len(preview.candidates) == 1:
            return preview.candidates[0]
        for candidate in preview.candidates:
            if candidate.twenty_id == selected_twenty_id:
                return candidate
        raise Conflict(
            "sponsor_match_selection_required",
            "Wähle einen der angezeigten CRM-Treffer aus.",
        )

    async def _create_candidate(
        self,
        draft: SponsorDraft,
        *,
        correlation_id: str,
    ) -> SponsorMatchCandidate:
        leonaid_id = uuid4()
        if draft.party_kind is CrmPartyKind.COMPANY:
            assert draft.company_name is not None
            company_record, _receipt = await self._crm.create_company(
                leonaid_id,
                CompanyData(
                    name=draft.company_name,
                    address=PostalAddress(
                        street_line_1=draft.street_line_1,
                        postal_code=draft.postal_code,
                        city=draft.city,
                    ),
                ),
                correlation_id=correlation_id,
            )
            return self._company_candidate(company_record, {})
        assert draft.given_name is not None
        assert draft.family_name is not None
        person_record, _receipt = await self._crm.create_person(
            leonaid_id,
            PersonData(
                given_name=draft.given_name,
                family_name=draft.family_name,
                email=draft.email,
            ),
            correlation_id=correlation_id,
        )
        return self._person_candidate(person_record, {})

    @staticmethod
    def _company_candidate(
        record: CompanyRecord,
        assigned: dict[UUID, tuple[AssignedAcquirer, ...]],
    ) -> SponsorMatchCandidate:
        return SponsorMatchCandidate(
            party_kind=CrmPartyKind.COMPANY,
            twenty_id=record.twenty_id,
            display_name=record.data.name,
            postal_code=record.data.address.postal_code,
            city=record.data.address.city,
            email=None,
            assigned_acquirers=assigned.get(record.twenty_id, ()),
        )

    @staticmethod
    def _person_candidate(
        record: PersonRecord,
        assigned: dict[UUID, tuple[AssignedAcquirer, ...]],
    ) -> SponsorMatchCandidate:
        return SponsorMatchCandidate(
            party_kind=CrmPartyKind.PERSON,
            twenty_id=record.twenty_id,
            display_name=f"{record.data.given_name} {record.data.family_name}",
            postal_code=None,
            city=None,
            email=record.data.email,
            assigned_acquirers=assigned.get(record.twenty_id, ()),
        )
