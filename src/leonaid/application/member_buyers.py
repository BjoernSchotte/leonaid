"""Admin-verified own CRM identity; acquisition assignments remain authoritative."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import UUID

from leonaid.application.crm import CrmGateway, CrmGatewayError, PersonRecord
from leonaid.application.errors import Conflict
from leonaid.application.policies import require_system_admin
from leonaid.domain.commitments import BuyerSnapshot, CommitmentPartyKind
from leonaid.domain.identity import ActionRole, IdentityPrincipal

SelfBuyerUnavailableReason = Literal[
    "not_linked", "not_assigned", "crm_unavailable", "person_missing"
]


@dataclass(frozen=True, slots=True)
class MemberBuyerLink:
    user_id: UUID
    twenty_person_id: UUID | None = None
    revision: int = 0
    verified_by_user_id: UUID | None = None
    verified_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemberBuyerDetails:
    link: MemberBuyerLink
    buyer: BuyerSnapshot | None


class MemberBuyerRepository(Protocol):
    async def get(self, user_id: UUID) -> MemberBuyerLink: ...

    async def is_assigned(
        self, user_id: UUID, person_id: UUID, action_id: UUID
    ) -> bool: ...

    async def save(
        self,
        user_id: UUID,
        person_id: UUID | None,
        *,
        expected_revision: int,
        actor_user_id: UUID,
        occurred_at: datetime,
        request_id: str,
    ) -> MemberBuyerLink: ...


def person_buyer(person: PersonRecord) -> BuyerSnapshot:
    return BuyerSnapshot(
        party_kind=CommitmentPartyKind.PERSON,
        twenty_id=person.twenty_id,
        display_name=f"{person.data.given_name} {person.data.family_name}",
        email=person.data.email.casefold() if person.data.email else None,
    )


class MemberBuyerService:
    def __init__(self, repository: MemberBuyerRepository, crm: CrmGateway) -> None:
        self._repository = repository
        self._crm = crm

    async def get(
        self, actor: IdentityPrincipal, user_id: UUID, *, request_id: str
    ) -> MemberBuyerDetails:
        require_system_admin(actor)
        link = await self._repository.get(user_id)
        person = (
            await self._crm.get_person(link.twenty_person_id, correlation_id=request_id)
            if link.twenty_person_id
            else None
        )
        return MemberBuyerDetails(link, person_buyer(person) if person else None)

    async def save(
        self,
        actor: IdentityPrincipal,
        user_id: UUID,
        person_id: UUID | None,
        *,
        expected_revision: int,
        request_id: str,
    ) -> MemberBuyerDetails:
        require_system_admin(actor)
        # Confirm an actual existing CRM person. Never create or merge by email.
        person = (
            await self._crm.get_person(person_id, correlation_id=request_id)
            if person_id
            else None
        )
        if person_id is not None and person is None:
            raise Conflict(
                "member_buyer_person_missing",
                "Die gewählte CRM-Person existiert nicht mehr. Bitte lade die Personen neu.",
            )
        link = await self._repository.save(
            user_id,
            person_id,
            expected_revision=expected_revision,
            actor_user_id=actor.account.id,
            occurred_at=datetime.now(timezone.utc),
            request_id=request_id,
        )
        return MemberBuyerDetails(link, person_buyer(person) if person else None)

    async def self_buyer(
        self, actor: IdentityPrincipal, action_id: UUID, *, request_id: str
    ) -> tuple[BuyerSnapshot | None, SelfBuyerUnavailableReason | None]:
        link = await self._repository.get(actor.account.id)
        if link.twenty_person_id is None:
            return None, "not_linked"
        if ActionRole.ACQUIRER not in actor.roles_for(action_id) or not (
            await self._repository.is_assigned(
                actor.account.id, link.twenty_person_id, action_id
            )
        ):
            return None, "not_assigned"
        try:
            person = await self._crm.get_person(
                link.twenty_person_id, correlation_id=request_id
            )
        except CrmGatewayError:
            return None, "crm_unavailable"
        if person is None:
            return None, "person_missing"
        return person_buyer(person), None
