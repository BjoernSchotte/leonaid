"""CharityAction application service and persistence port."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, Sequence
from uuid import UUID, uuid4

from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.application.policies import (
    concealed_resource,
    require_action_creator,
    require_action_manager,
)
from leonaid.domain.action_templates import (
    ActionConfiguration,
    ActionTemplate,
    ActionTemplateKey,
    OfferingStatus,
    TemplateOffering,
)
from leonaid.domain.actions import (
    ActionManagementState,
    ActionCapability,
    ActionGoal,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
    PublicationWindow,
    PublicActionAlias,
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


@dataclass(frozen=True, slots=True)
class UpdateActionDetailsDraft:
    carrier_name: str
    name: str
    purpose: str
    starts_on: date
    ends_on: date


class PublicActionRouteKind(StrEnum):
    ALIAS = "alias"
    ARCHIVE = "archive"


class PublicActionAvailability(StrEnum):
    PUBLISHED = "published"
    INACTIVE = "inactive"
    ARCHIVE = "archive"


@dataclass(frozen=True, slots=True)
class PublicActionRoute:
    route_kind: PublicActionRouteKind
    route_value: str
    route_path: str
    canonical_path: str
    availability: PublicActionAvailability
    submissions_allowed: bool
    action: CharityAction | None
    offerings: tuple[TemplateOffering, ...] = ()

    def __post_init__(self) -> None:
        if self.availability is PublicActionAvailability.INACTIVE:
            if self.action is not None or self.offerings or self.submissions_allowed:
                raise ValueError("Eine inaktive Route darf keine Aktion freigeben.")
            return
        if self.action is None:
            raise ValueError("Eine öffentliche Aktionsroute benötigt eine Aktion.")
        if self.submissions_allowed != (
            self.route_kind is PublicActionRouteKind.ALIAS
            and self.availability is PublicActionAvailability.PUBLISHED
        ):
            raise ValueError("Der Schreibstatus der öffentlichen Route ist ungültig.")


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

    async def get_management(
        self,
        action_id: UUID,
    ) -> ActionManagementState | None: ...

    async def get_alias_target(
        self,
        public_alias: PublicActionAlias,
    ) -> UUID | None: ...

    async def get_by_public_alias(
        self,
        public_alias: PublicActionAlias,
    ) -> tuple[CharityAction, ActionConfiguration | None] | None: ...

    async def get_by_archive_slug(
        self,
        archive_slug: str,
    ) -> tuple[CharityAction, ActionConfiguration | None] | None: ...

    async def update_details(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction: ...

    async def replace_publication(
        self,
        action: CharityAction,
        *,
        public_alias: PublicActionAlias | None,
        allowed_previous_target_id: UUID | None,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> ActionManagementState: ...

    async def replace_responsible_administrators(
        self,
        action: CharityAction,
        *,
        responsible_user_ids: frozenset[UUID],
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> ActionManagementState: ...

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

    async def resolve_public_alias(
        self,
        public_alias: str,
        *,
        evaluated_at: datetime | None = None,
    ) -> PublicActionRoute:
        alias = PublicActionAlias(public_alias.strip())
        snapshot = await self._repository.get_by_public_alias(alias)
        now = evaluated_at or datetime.now(timezone.utc)
        route_path = f"/{alias.value}"
        if snapshot is None or not snapshot[0].is_published_at(now):
            return PublicActionRoute(
                route_kind=PublicActionRouteKind.ALIAS,
                route_value=alias.value,
                route_path=route_path,
                canonical_path=route_path,
                availability=PublicActionAvailability.INACTIVE,
                submissions_allowed=False,
                action=None,
            )
        action, configuration = snapshot
        return PublicActionRoute(
            route_kind=PublicActionRouteKind.ALIAS,
            route_value=alias.value,
            route_path=route_path,
            canonical_path=f"/archive/{action.archive_slug}",
            availability=PublicActionAvailability.PUBLISHED,
            submissions_allowed=True,
            action=action,
            offerings=self._public_offerings(configuration),
        )

    async def resolve_public_archive(
        self,
        archive_slug: str,
    ) -> PublicActionRoute:
        normalized_slug = archive_slug.strip()
        if not normalized_slug:
            raise ResourceNotFound(
                "public_action_not_found",
                "Diese öffentliche Aktionsseite wurde nicht gefunden.",
            )
        snapshot = await self._repository.get_by_archive_slug(normalized_slug)
        if snapshot is None:
            raise ResourceNotFound(
                "public_action_not_found",
                "Diese öffentliche Aktionsseite wurde nicht gefunden.",
            )
        action, configuration = snapshot
        path = f"/archive/{action.archive_slug}"
        return PublicActionRoute(
            route_kind=PublicActionRouteKind.ARCHIVE,
            route_value=action.archive_slug,
            route_path=path,
            canonical_path=path,
            availability=PublicActionAvailability.ARCHIVE,
            submissions_allowed=False,
            action=action,
            offerings=self._public_offerings(configuration),
        )

    @staticmethod
    def _public_offerings(
        configuration: ActionConfiguration | None,
    ) -> tuple[TemplateOffering, ...]:
        if configuration is None:
            return ()
        return tuple(
            item.definition
            for item in configuration.offerings
            if item.definition.status is OfferingStatus.ACTIVE
        )

    async def get_management(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
    ) -> ActionManagementState:
        try:
            require_action_manager(actor, action_id)
        except PermissionDenied:
            raise concealed_resource() from None
        state = await self._repository.get_management(action_id)
        if state is None:
            raise concealed_resource()
        return state

    async def set_details(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        draft: UpdateActionDetailsDraft,
        *,
        expected_revision: int,
        request_id: str,
    ) -> CharityAction:
        current = await self._managed_action(actor, action_id)
        changed = current.with_details(
            carrier_name=self._required_text(draft.carrier_name),
            name=self._required_text(draft.name),
            purpose=self._required_text(draft.purpose),
            starts_on=draft.starts_on,
            ends_on=draft.ends_on,
        )
        if self._same_details(current, changed):
            return current
        self._require_revision(current, expected_revision)
        return await self._repository.update_details(
            changed,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def set_publication(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        publication_starts_at: datetime | None,
        publication_ends_at: datetime | None,
        public_alias: str | None,
        expected_revision: int,
        request_id: str,
    ) -> ActionManagementState:
        current = await self.get_management(actor, action_id)
        window = self._publication_window(
            publication_starts_at,
            publication_ends_at,
        )
        normalized_alias = (
            PublicActionAlias(public_alias.strip())
            if public_alias is not None
            else None
        )
        if normalized_alias is not None and window is None:
            raise DomainInvariantError(
                "action_public_alias_window_required",
                "Ein öffentlicher Alias benötigt ein vollständiges Publikationsfenster.",
            )
        changed = current.action.with_publication_window(window)
        if (
            changed.publication_window == current.action.publication_window
            and normalized_alias == current.public_alias
        ):
            return current
        self._require_revision(current.action, expected_revision)
        allowed_previous_target_id: UUID | None = None
        if normalized_alias is not None:
            target = await self._repository.get_alias_target(normalized_alias)
            if target is not None and target != action_id:
                try:
                    require_action_manager(actor, target)
                except PermissionDenied:
                    raise Conflict(
                        "action_public_alias_unavailable",
                        "Dieser öffentliche Alias ist nicht verfügbar.",
                    ) from None
                allowed_previous_target_id = target
        return await self._repository.replace_publication(
            changed,
            public_alias=normalized_alias,
            allowed_previous_target_id=allowed_previous_target_id,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def set_responsible_administrators(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        responsible_user_ids: Sequence[UUID],
        *,
        expected_revision: int,
        request_id: str,
    ) -> ActionManagementState:
        current = await self.get_management(actor, action_id)
        selected = frozenset(responsible_user_ids)
        if not selected:
            raise DomainInvariantError(
                "action_responsible_administrator_required",
                "Eine Charity-Aktion benötigt mindestens einen verantwortlichen Admin.",
            )
        if len(selected) != len(responsible_user_ids):
            raise DomainInvariantError(
                "action_responsible_administrator_duplicate",
                "Ein verantwortlicher Admin darf nur einmal ausgewählt werden.",
            )
        existing = frozenset(
            item.user_id
            for item in current.administrator_options
            if item.is_responsible
        )
        if selected == existing:
            return current
        self._require_revision(current.action, expected_revision)
        return await self._repository.replace_responsible_administrators(
            current.action,
            responsible_user_ids=selected,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )

    async def set_goal(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        goal: ActionGoal,
        *,
        expected_revision: int,
        request_id: str,
    ) -> CharityAction:
        current = await self._managed_action(actor, action_id)
        action = current.with_goal(goal)
        if action.goal == current.goal:
            return current
        self._require_revision(current, expected_revision)
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
        expected_revision: int,
        request_id: str,
    ) -> CharityAction:
        current = await self._managed_action(actor, action_id)
        selected = self._capabilities(capabilities)
        if selected == current.capabilities:
            return current
        self._require_revision(current, expected_revision)
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
        expected_revision: int,
        request_id: str,
    ) -> CharityAction:
        current = await self._managed_action(actor, action_id)
        if self._same_beneficiaries(current, beneficiaries):
            return current
        self._require_revision(current, expected_revision)
        action = current.with_beneficiaries(
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
        expected_revision: int,
        request_id: str,
    ) -> CharityAction:
        current = await self._managed_action(actor, action_id)
        changed = current.transition_to(target)
        if changed is current:
            return current
        self._require_revision(current, expected_revision)
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
    def _publication_window(
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> PublicationWindow | None:
        if starts_at is None and ends_at is None:
            return None
        if starts_at is None or ends_at is None:
            raise DomainInvariantError(
                "action_publication_window_incomplete",
                "Publikationsbeginn und Publikationsende müssen gemeinsam gepflegt werden.",
            )
        return PublicationWindow(starts_at=starts_at, ends_at=ends_at)

    @staticmethod
    def _require_revision(action: CharityAction, expected_revision: int) -> None:
        if expected_revision != action.revision:
            raise Conflict(
                "action_revision_conflict",
                "Die Charity-Aktion wurde zwischenzeitlich geändert. "
                "Lade den aktuellen Stand und prüfe deine Eingaben erneut.",
            )

    @staticmethod
    def _same_details(first: CharityAction, second: CharityAction) -> bool:
        return (
            first.carrier_name,
            first.name,
            first.purpose,
            first.starts_on,
            first.ends_on,
        ) == (
            second.carrier_name,
            second.name,
            second.purpose,
            second.starts_on,
            second.ends_on,
        )

    @staticmethod
    def _same_beneficiaries(
        action: CharityAction,
        drafts: Sequence[BeneficiaryDraft],
    ) -> bool:
        return tuple(
            (item.organization_name, item.public_description)
            for item in action.beneficiaries
        ) == tuple(
            (
                CharityActionService._required_text(item.organization_name),
                CharityActionService._required_text(item.public_description),
            )
            for item in drafts
        )

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
