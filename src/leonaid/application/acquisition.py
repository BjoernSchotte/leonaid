"""Row-safe acquisition reads across Core PostgreSQL and Twenty."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.crm import (
    CompanyRecord,
    CrmGateway,
    CrmPartyKind,
    PersonRecord,
)
from leonaid.application.policies import concealed_resource
from leonaid.domain.identity import IdentityPrincipal
from leonaid.domain.policies import AuthorizedPartyScope, PolicySurface


@dataclass(frozen=True, slots=True)
class PartyAssignmentRoster:
    company_assignees: dict[UUID, tuple[UUID, ...]]
    person_assignees: dict[UUID, tuple[UUID, ...]]

    def for_company(self, company_id: UUID) -> tuple[UUID, ...]:
        return self.company_assignees.get(company_id, ())

    def for_person(self, person_id: UUID) -> tuple[UUID, ...]:
        return self.person_assignees.get(person_id, ())


@dataclass(frozen=True, slots=True)
class AcquisitionParty:
    party_kind: CrmPartyKind
    twenty_id: UUID
    display_name: str
    postal_code: str | None
    city: str | None
    email: str | None
    assigned_acquirer_ids: tuple[UUID, ...]

    def searchable_text(self) -> str:
        return " ".join(
            value.casefold()
            for value in (
                self.display_name,
                self.postal_code,
                self.city,
                self.email,
            )
            if value
        )


@dataclass(frozen=True, slots=True)
class AcquisitionPartyPage:
    items: tuple[AcquisitionParty, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class AcquisitionActivity:
    id: UUID
    action_id: UUID
    party_kind: CrmPartyKind
    party_id: UUID
    actor_user_id: UUID | None
    outcome: str
    channel: str
    note: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AcquisitionActivityPage:
    items: tuple[AcquisitionActivity, ...]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class AcquisitionDocument:
    id: UUID
    action_id: UUID
    party_kind: CrmPartyKind
    party_id: UUID
    document_type: str
    media_type: str
    sha256: str
    version: int
    created_at: datetime


class AcquisitionPolicyRepository(Protocol):
    async def authorized_scope(
        self,
        actor_user_id: UUID,
        action_id: UUID,
        *,
        evaluated_at: datetime,
    ) -> AuthorizedPartyScope | None: ...

    async def assignment_roster(
        self,
        scope: AuthorizedPartyScope,
        *,
        evaluated_at: datetime,
    ) -> PartyAssignmentRoster: ...

    async def activities(
        self,
        scope: AuthorizedPartyScope,
        *,
        offset: int,
        limit: int,
    ) -> AcquisitionActivityPage: ...

    async def document(
        self,
        scope: AuthorizedPartyScope,
        document_id: UUID,
    ) -> AcquisitionDocument | None: ...


class AcquisitionPolicyService:
    def __init__(
        self,
        repository: AcquisitionPolicyRepository,
        crm: CrmGateway,
    ) -> None:
        self._repository = repository
        self._crm = crm

    async def list_parties(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        query: str | None,
        offset: int,
        limit: int,
        surface: PolicySurface = PolicySurface.LIST,
    ) -> AcquisitionPartyPage:
        self._page(offset, limit)
        scope, evaluated_at = await self._scope(actor, action_id, surface)
        parties = await self._parties(scope, evaluated_at=evaluated_at)
        filtered = self._filter(parties, query)
        return AcquisitionPartyPage(
            items=filtered[offset : offset + limit],
            total=len(filtered),
            offset=offset,
            limit=limit,
        )

    async def count_parties(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        query: str | None,
    ) -> int:
        page = await self.list_parties(
            actor,
            action_id,
            query=query,
            offset=0,
            limit=1,
            surface=PolicySurface.COUNT,
        )
        return page.total

    async def export_parties(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        query: str | None,
    ) -> tuple[AcquisitionParty, ...]:
        scope, evaluated_at = await self._scope(
            actor,
            action_id,
            PolicySurface.EXPORT,
        )
        return self._filter(
            await self._parties(scope, evaluated_at=evaluated_at),
            query,
        )

    async def party(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        party_kind: CrmPartyKind,
        party_id: UUID,
    ) -> AcquisitionParty:
        scope, evaluated_at = await self._scope(
            actor,
            action_id,
            PolicySurface.DETAIL,
        )
        if party_kind is CrmPartyKind.COMPANY:
            if not scope.allows_company(party_id):
                raise concealed_resource()
            record = await self._crm.get_company(
                party_id,
                correlation_id=f"policy:detail:{action_id}:{party_id}",
            )
            if record is None:
                raise concealed_resource()
            roster = await self._repository.assignment_roster(
                scope,
                evaluated_at=evaluated_at,
            )
            return self._company(record, roster)
        if not scope.allows_person(party_id):
            raise concealed_resource()
        person = await self._crm.get_person(
            party_id,
            correlation_id=f"policy:detail:{action_id}:{party_id}",
        )
        if person is None:
            raise concealed_resource()
        roster = await self._repository.assignment_roster(
            scope,
            evaluated_at=evaluated_at,
        )
        return self._person(person, roster)

    async def activities(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> AcquisitionActivityPage:
        self._page(offset, limit)
        scope, _evaluated_at = await self._scope(
            actor,
            action_id,
            PolicySurface.ACTIVITY,
        )
        return await self._repository.activities(
            scope,
            offset=offset,
            limit=limit,
        )

    async def document(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        document_id: UUID,
    ) -> AcquisitionDocument:
        scope, _evaluated_at = await self._scope(
            actor,
            action_id,
            PolicySurface.DOCUMENT,
        )
        document = await self._repository.document(scope, document_id)
        if document is None:
            raise concealed_resource()
        return document

    async def _scope(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        _surface: PolicySurface,
    ) -> tuple[AuthorizedPartyScope, datetime]:
        evaluated_at = datetime.now(timezone.utc)
        scope = await self._repository.authorized_scope(
            actor.account.id,
            action_id,
            evaluated_at=evaluated_at,
        )
        if scope is None:
            raise concealed_resource()
        return scope, evaluated_at

    async def _parties(
        self,
        scope: AuthorizedPartyScope,
        *,
        evaluated_at: datetime,
    ) -> tuple[AcquisitionParty, ...]:
        roster, companies, people = await asyncio.gather(
            self._repository.assignment_roster(
                scope,
                evaluated_at=evaluated_at,
            ),
            self._companies(scope),
            self._people(scope),
        )
        parties = [
            *(self._company(record, roster) for record in companies if record),
            *(self._person(record, roster) for record in people if record),
        ]
        return tuple(
            sorted(
                parties,
                key=lambda item: (
                    item.display_name.casefold(),
                    item.party_kind.value,
                    str(item.twenty_id),
                ),
            )
        )

    async def _companies(
        self,
        scope: AuthorizedPartyScope,
    ) -> tuple[CompanyRecord | None, ...]:
        return tuple(
            await asyncio.gather(
                *(
                    self._crm.get_company(
                        company_id,
                        correlation_id=(
                            f"policy:list:{scope.action_id}:company:{company_id}"
                        ),
                    )
                    for company_id in sorted(scope.company_ids, key=str)
                )
            )
        )

    async def _people(
        self,
        scope: AuthorizedPartyScope,
    ) -> tuple[PersonRecord | None, ...]:
        return tuple(
            await asyncio.gather(
                *(
                    self._crm.get_person(
                        person_id,
                        correlation_id=(
                            f"policy:list:{scope.action_id}:person:{person_id}"
                        ),
                    )
                    for person_id in sorted(scope.person_ids, key=str)
                )
            )
        )

    @staticmethod
    def _company(
        record: CompanyRecord,
        roster: PartyAssignmentRoster,
    ) -> AcquisitionParty:
        return AcquisitionParty(
            party_kind=CrmPartyKind.COMPANY,
            twenty_id=record.twenty_id,
            display_name=record.data.name,
            postal_code=record.data.address.postal_code,
            city=record.data.address.city,
            email=None,
            assigned_acquirer_ids=roster.for_company(record.twenty_id),
        )

    @staticmethod
    def _person(
        record: PersonRecord,
        roster: PartyAssignmentRoster,
    ) -> AcquisitionParty:
        return AcquisitionParty(
            party_kind=CrmPartyKind.PERSON,
            twenty_id=record.twenty_id,
            display_name=f"{record.data.given_name} {record.data.family_name}",
            postal_code=None,
            city=None,
            email=record.data.email,
            assigned_acquirer_ids=roster.for_person(record.twenty_id),
        )

    @staticmethod
    def _filter(
        parties: tuple[AcquisitionParty, ...],
        query: str | None,
    ) -> tuple[AcquisitionParty, ...]:
        normalized = (query or "").strip().casefold()
        if not normalized:
            return parties
        return tuple(
            party for party in parties if normalized in party.searchable_text()
        )

    @staticmethod
    def _page(offset: int, limit: int) -> None:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("Pagination liegt außerhalb des erlaubten Bereichs.")
