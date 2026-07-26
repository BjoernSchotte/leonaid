"""CharityAction application service and persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Protocol, Sequence
from uuid import UUID, uuid4

from leonaid.application.policies import (
    concealed_resource,
    require_action_creator,
    require_action_manager,
)
from leonaid.application.errors import PermissionDenied
from leonaid.domain.actions import (
    ActionCapability,
    ActionGoal,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
)
from leonaid.domain.errors import DomainInvariantError
from leonaid.domain.identity import IdentityPrincipal


@dataclass(frozen=True, slots=True)
class BeneficiaryDraft:
    organization_name: str
    public_description: str


@dataclass(frozen=True, slots=True)
class CreateActionDraft:
    carrier_name: str
    name: str
    purpose: str
    starts_on: date
    ends_on: date
    archive_slug: str
    capabilities: tuple[ActionCapability, ...]
    beneficiaries: tuple[BeneficiaryDraft, ...]
    goal: ActionGoal


class CharityActionRepository(Protocol):
    async def get(self, action_id: UUID) -> CharityAction | None: ...

    async def create(
        self,
        action: CharityAction,
        *,
        responsible_admin_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction: ...

    async def update_goal(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction: ...

    async def replace_capabilities(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction: ...

    async def replace_beneficiaries(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction: ...

    async def transition(
        self,
        action: CharityAction,
        *,
        previous_status: CharityActionStatus,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction: ...


class CharityActionService:
    def __init__(self, repository: CharityActionRepository) -> None:
        self._repository = repository

    async def create(
        self,
        actor: IdentityPrincipal,
        draft: CreateActionDraft,
        *,
        request_id: str,
    ) -> CharityAction:
        require_action_creator(actor)
        action_id = uuid4()
        action = CharityAction(
            id=action_id,
            carrier_name=self._required_text(draft.carrier_name),
            name=self._required_text(draft.name),
            purpose=self._required_text(draft.purpose),
            status=CharityActionStatus.DRAFT,
            starts_on=draft.starts_on,
            ends_on=draft.ends_on,
            archive_slug=draft.archive_slug.strip(),
            capabilities=self._capabilities(draft.capabilities),
            beneficiaries=self._beneficiaries(action_id, draft.beneficiaries),
            goal=draft.goal,
        )
        return await self._repository.create(
            action,
            responsible_admin_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def get(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> CharityAction:
        return await self._managed_action(actor, action_id)

    async def set_goal(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        goal: ActionGoal,
        *,
        request_id: str,
    ) -> CharityAction:
        action = (await self._managed_action(actor, action_id)).with_goal(goal)
        return await self._repository.update_goal(
            action,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def set_capabilities(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        capabilities: Sequence[ActionCapability],
        *,
        request_id: str,
    ) -> CharityAction:
        action = (await self._managed_action(actor, action_id)).with_capabilities(
            self._capabilities(capabilities)
        )
        return await self._repository.replace_capabilities(
            action,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def set_beneficiaries(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        beneficiaries: Sequence[BeneficiaryDraft],
        *,
        request_id: str,
    ) -> CharityAction:
        action = (await self._managed_action(actor, action_id)).with_beneficiaries(
            self._beneficiaries(action_id, beneficiaries)
        )
        return await self._repository.replace_beneficiaries(
            action,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def transition(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        target: CharityActionStatus,
        *,
        request_id: str,
    ) -> CharityAction:
        current = await self._managed_action(actor, action_id)
        changed = current.transition_to(target)
        if changed is current:
            return current
        return await self._repository.transition(
            changed,
            previous_status=current.status,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def _managed_action(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> CharityAction:
        try:
            require_action_manager(actor, action_id)
        except PermissionDenied:
            raise concealed_resource() from None
        action = await self._repository.get(action_id)
        if action is None:
            raise concealed_resource()
        return action

    @staticmethod
    def _capabilities(
        values: Sequence[ActionCapability],
    ) -> frozenset[ActionCapability]:
        result = frozenset(values)
        if len(result) != len(values):
            raise DomainInvariantError(
                "action_capability_duplicate",
                "Eine Capability darf nur einmal aktiviert werden.",
            )
        return result

    @staticmethod
    def _beneficiaries(
        action_id: UUID,
        values: Sequence[BeneficiaryDraft],
    ) -> tuple[Beneficiary, ...]:
        return tuple(
            Beneficiary(
                id=uuid4(),
                action_id=action_id,
                organization_name=CharityActionService._required_text(
                    value.organization_name
                ),
                public_description=CharityActionService._required_text(
                    value.public_description
                ),
                sort_order=index,
            )
            for index, value in enumerate(values)
        )

    @staticmethod
    def _required_text(value: str) -> str:
        return " ".join(value.split())
