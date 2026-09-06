"""Authorized action delivery schedule administration."""

from typing import Protocol
from uuid import UUID

from leonaid.application.errors import PermissionDenied
from leonaid.application.policies import require_action_manager
from leonaid.domain.delivery import DeliveryConfiguration
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.policies import may_manage_action


class DeliveryRepository(Protocol):
    async def get(self, action_id: UUID) -> DeliveryConfiguration: ...

    async def save(
        self, configuration: DeliveryConfiguration
    ) -> DeliveryConfiguration: ...


class DeliveryService:
    def __init__(self, repository: DeliveryRepository) -> None:
        self._repository = repository

    async def get(
        self, actor: IdentityPrincipal, action_id: UUID
    ) -> DeliveryConfiguration:
        if not actor.account.can_authenticate or (
            not may_manage_action(actor, action_id)
            and ActionRole.ACQUIRER not in actor.roles_for(action_id)
        ):
            raise PermissionDenied(
                "delivery_read_forbidden", "Für diese Aktion fehlen dir die Rechte."
            )
        return await self._repository.get(action_id)

    async def save(
        self, actor: IdentityPrincipal, configuration: DeliveryConfiguration
    ) -> DeliveryConfiguration:
        require_action_manager(actor, configuration.action_id)
        return await self._repository.save(configuration)
