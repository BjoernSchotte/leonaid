"""CharityAction application service and persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Protocol, Sequence
from uuid import UUID, uuid4

from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.application.policies import (
    concealed_resource,
    require_action_creator,
    require_action_manager,
)
from leonaid.domain.action_templates import (
    ActionConfiguration,
    ActionTemplate,
    ActionTemplateKey,
)
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


@dataclass(frozen=True, slots=True)
class CreateActionFromTemplateDraft:
    template_key: ActionTemplateKey
    template_version: int | None
    carrier_name: str
    name: str
    purpose: str
    starts_on: date
    ends_on: date
    archive_slug: str
    beneficiaries: tuple[BeneficiaryDraft, ...]
    goal: ActionGoal


@dataclass(frozen=True, slots=True)
class CopyActionDraft:
    name: str
    starts_on: date
    ends_on: date
    archive_slug: str


class CharityActionRepository(Protocol):
    async def get(self, action_id: UUID) -> CharityAction | None: ...

    async def create(
        self,
        action: CharityAction,
        *,
        responsible_admin_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        configuration: ActionConfiguration | None = None,
    ) -> CharityAction: ...

    async def list_latest_templates(self) -> tuple[ActionTemplate, ...]: ...

    async def get_template(
        self,
        template_key: ActionTemplateKey,
        template_version: int | None = None,
    ) -> ActionTemplate | None: ...

    async def get_configuration(
        self,
        action_id: UUID,
    ) -> ActionConfiguration | None: ...

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
        blank_template = await self._required_template(ActionTemplateKey.BLANK, 1)
        return await self._repository.create(
            action,
            responsible_admin_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
            configuration=blank_template.configure(
                action.id,
                capabilities=action.capabilities,
            ),
        )

    async def list_templates(
        self,
        actor: IdentityPrincipal,
    ) -> tuple[ActionTemplate, ...]:
        require_action_creator(actor)
        return await self._repository.list_latest_templates()

    async def create_from_template(
        self,
        actor: IdentityPrincipal,
        draft: CreateActionFromTemplateDraft,
        *,
        request_id: str,
    ) -> tuple[CharityAction, ActionConfiguration]:
        require_action_creator(actor)
        template = await self._required_template(
            draft.template_key,
            draft.template_version,
        )
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
            capabilities=template.capabilities,
            beneficiaries=self._beneficiaries(action_id, draft.beneficiaries),
            goal=draft.goal,
        )
        configuration = template.configure(action.id)
        created = await self._repository.create(
            action,
            responsible_admin_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
            configuration=configuration,
        )
        return created, configuration

    async def get_configuration(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> tuple[CharityAction, ActionConfiguration]:
        action = await self._managed_action(actor, action_id)
        configuration = await self._repository.get_configuration(action_id)
        if configuration is None:
            raise concealed_resource()
        return action, configuration

    async def copy(
        self,
        actor: IdentityPrincipal,
        source_action_id: UUID,
        draft: CopyActionDraft,
        *,
        request_id: str,
    ) -> tuple[CharityAction, ActionConfiguration]:
        source = await self._managed_action(actor, source_action_id)
        source_configuration = await self._repository.get_configuration(
            source_action_id
        )
        if source_configuration is None:
            raise Conflict(
                "action_copy_configuration_missing",
                "Diese ältere Aktion besitzt noch keinen kopierbaren Template-Snapshot.",
            )
        action_id = uuid4()
        action = CharityAction(
            id=action_id,
            carrier_name=source.carrier_name,
            name=self._required_text(draft.name),
            purpose=source.purpose,
            status=CharityActionStatus.DRAFT,
            starts_on=draft.starts_on,
            ends_on=draft.ends_on,
            archive_slug=draft.archive_slug.strip(),
            capabilities=source.capabilities,
            beneficiaries=self._beneficiaries(
                action_id,
                tuple(
                    BeneficiaryDraft(
                        organization_name=item.organization_name,
                        public_description=item.public_description,
                    )
                    for item in source.beneficiaries
                ),
            ),
            goal=ActionGoal(
                goal_value=source.goal.goal_value,
                actual_value=Decimal("0"),
                unit=source.goal.unit,
                currency=source.goal.currency,
            ),
        )
        configuration = source_configuration.copy_for(
            action.id,
            source_action_id=source_action_id,
            capabilities=source.capabilities,
        )
        created = await self._repository.create(
            action,
            responsible_admin_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
            configuration=configuration,
        )
        return created, configuration

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
        current = await self._managed_action(actor, action_id)
        selected = self._capabilities(capabilities)
        configuration = await self._repository.get_configuration(action_id)
        if configuration is not None:
            configuration.require_compatible_capabilities(selected)
        action = current.with_capabilities(selected)
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

    async def _required_template(
        self,
        template_key: ActionTemplateKey,
        template_version: int | None,
    ) -> ActionTemplate:
        template = await self._repository.get_template(
            template_key,
            template_version,
        )
        if template is None:
            raise concealed_resource()
        return template

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
