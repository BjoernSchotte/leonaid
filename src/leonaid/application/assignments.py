"""Assignment management, proactive allocation and explicit handover."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from leonaid.application.crm import CrmGateway
from leonaid.application.errors import Conflict
from leonaid.application.policies import concealed_resource, require_action_manager
from leonaid.domain.acquisition import (
    AcquisitionAssignment,
    AssignmentHistoryEntry,
    AssignmentPartyKind,
    AssignmentStatus,
)
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.policies import may_manage_action


@dataclass(frozen=True, slots=True)
class AssignmentCreateResult:
    assignment: AcquisitionAssignment
    created: bool


@dataclass(frozen=True, slots=True)
class AssignmentHandoverResult:
    source: AcquisitionAssignment
    target: AcquisitionAssignment
    target_created: bool


@dataclass(frozen=True, slots=True)
class AssignmentDetails:
    assignment: AcquisitionAssignment
    history: tuple[AssignmentHistoryEntry, ...]


class AssignmentManagementRepository(Protocol):
    async def get_assignment(
        self,
        action_id: UUID,
        assignment_id: UUID,
    ) -> AcquisitionAssignment | None: ...

    async def assignment_history(
        self,
        assignment_id: UUID,
    ) -> tuple[AssignmentHistoryEntry, ...]: ...

    async def create_proactive_assignment(
        self,
        *,
        action_id: UUID,
        party_kind: AssignmentPartyKind,
        party_id: UUID,
        acquirer_user_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> AssignmentCreateResult | None: ...

    async def save_assignment(
        self,
        previous: AcquisitionAssignment,
        changed: AcquisitionAssignment,
        *,
        actor_user_id: UUID,
        actor_may_manage: bool,
        request_id: str,
        occurred_at: datetime,
    ) -> AcquisitionAssignment | None: ...

    async def hand_over_assignment(
        self,
        previous: AcquisitionAssignment,
        changed: AcquisitionAssignment,
        *,
        target_acquirer_user_id: UUID,
        actor_user_id: UUID,
        actor_may_manage: bool,
        request_id: str,
        occurred_at: datetime,
    ) -> AssignmentHandoverResult | None: ...


class AssignmentManagementService:
    def __init__(
        self,
        repository: AssignmentManagementRepository,
        crm: CrmGateway,
    ) -> None:
        self._repository = repository
        self._crm = crm

    async def create_proactive(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        party_kind: AssignmentPartyKind,
        party_id: UUID,
        acquirer_user_id: UUID,
        request_id: str,
    ) -> AssignmentCreateResult:
        require_action_manager(actor, action_id)
        await self._require_party(
            party_kind,
            party_id,
            correlation_id=f"{request_id}:assignment-party",
        )
        result = await self._repository.create_proactive_assignment(
            action_id=action_id,
            party_kind=party_kind,
            party_id=party_id,
            acquirer_user_id=acquirer_user_id,
            actor_user_id=actor.account.id,
            request_id=request_id,
            occurred_at=datetime.now(timezone.utc),
        )
        if result is None:
            raise Conflict(
                "assignment_acquirer_unavailable",
                "Die ausgewählte Person ist für diese Aktion nicht als "
                "aktive Akquisiteurin oder aktiver Akquisiteur verfügbar.",
            )
        return result

    async def details(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        assignment_id: UUID,
    ) -> AssignmentDetails:
        assignment = await self._required_assignment(action_id, assignment_id)
        self._require_view(actor, assignment)
        return AssignmentDetails(
            assignment=assignment,
            history=await self._repository.assignment_history(assignment.id),
        )

    async def update(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        assignment_id: UUID,
        *,
        expected_revision: int,
        status: AssignmentStatus,
        priority: int,
        next_action: str | None,
        due_at: datetime | None,
        request_id: str,
    ) -> AcquisitionAssignment:
        previous = await self._required_assignment(action_id, assignment_id)
        actor_may_manage = may_manage_action(actor, action_id)
        self._require_mutation(actor, previous, actor_may_manage=actor_may_manage)
        self._require_revision(previous, expected_revision)
        occurred_at = datetime.now(timezone.utc)
        changed = previous.update_work(
            status=status,
            priority=priority,
            next_action=next_action,
            due_at=due_at,
            occurred_at=occurred_at,
        )
        if changed is previous:
            return previous
        saved = await self._repository.save_assignment(
            previous,
            changed,
            actor_user_id=actor.account.id,
            actor_may_manage=actor_may_manage,
            request_id=request_id,
            occurred_at=occurred_at,
        )
        if saved is None:
            raise concealed_resource()
        return saved

    async def hand_over(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        assignment_id: UUID,
        *,
        expected_revision: int,
        target_acquirer_user_id: UUID,
        request_id: str,
    ) -> AssignmentHandoverResult:
        previous = await self._required_assignment(action_id, assignment_id)
        actor_may_manage = may_manage_action(actor, action_id)
        self._require_mutation(actor, previous, actor_may_manage=actor_may_manage)
        self._require_revision(previous, expected_revision)
        if target_acquirer_user_id == previous.acquirer_user_id:
            raise Conflict(
                "assignment_handover_same_acquirer",
                "Eine Zuordnung kann nicht an dieselbe Person übergeben werden.",
            )
        occurred_at = datetime.now(timezone.utc)
        changed = previous.hand_over(occurred_at=occurred_at)
        result = await self._repository.hand_over_assignment(
            previous,
            changed,
            target_acquirer_user_id=target_acquirer_user_id,
            actor_user_id=actor.account.id,
            actor_may_manage=actor_may_manage,
            request_id=request_id,
            occurred_at=occurred_at,
        )
        if result is None:
            raise Conflict(
                "assignment_handover_target_unavailable",
                "Die Zielperson ist für diese Aktion nicht als aktive "
                "Akquisiteurin oder aktiver Akquisiteur verfügbar.",
            )
        return result

    async def _required_assignment(
        self,
        action_id: UUID,
        assignment_id: UUID,
    ) -> AcquisitionAssignment:
        assignment = await self._repository.get_assignment(action_id, assignment_id)
        if assignment is None:
            raise concealed_resource()
        return assignment

    async def _require_party(
        self,
        party_kind: AssignmentPartyKind,
        party_id: UUID,
        *,
        correlation_id: str,
    ) -> None:
        if party_kind is AssignmentPartyKind.COMPANY:
            company = await self._crm.get_company(
                party_id,
                correlation_id=correlation_id,
            )
            if company is None:
                raise concealed_resource()
            return
        person = await self._crm.get_person(
            party_id,
            correlation_id=correlation_id,
        )
        if person is None:
            raise concealed_resource()

    @staticmethod
    def _require_view(
        actor: IdentityPrincipal,
        assignment: AcquisitionAssignment,
    ) -> None:
        if may_manage_action(actor, assignment.action_id):
            return
        if (
            assignment.state.status is not AssignmentStatus.HANDED_OVER
            and assignment.acquirer_user_id == actor.account.id
            and ActionRole.ACQUIRER in actor.roles_for(assignment.action_id)
        ):
            return
        raise concealed_resource()

    @staticmethod
    def _require_mutation(
        actor: IdentityPrincipal,
        assignment: AcquisitionAssignment,
        *,
        actor_may_manage: bool,
    ) -> None:
        if actor_may_manage:
            return
        if (
            assignment.state.status is not AssignmentStatus.HANDED_OVER
            and assignment.acquirer_user_id == actor.account.id
            and ActionRole.ACQUIRER in actor.roles_for(assignment.action_id)
        ):
            return
        raise concealed_resource()

    @staticmethod
    def _require_revision(
        assignment: AcquisitionAssignment,
        expected_revision: int,
    ) -> None:
        if assignment.revision != expected_revision:
            raise Conflict(
                "assignment_revision_conflict",
                "Die Zuordnung wurde zwischenzeitlich geändert. Bitte lade sie neu.",
            )
