"""Authorized delivery schedule administration."""

from typing import Protocol
from uuid import UUID

from leonaid.application.policies import require_action_manager
from leonaid.domain.delivery import DeliveryConfiguration
from leonaid.domain.identity import IdentityPrincipal


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
        require_action_manager(actor, action_id)
        return await self._repository.get(action_id)

    async def save(
        self, actor: IdentityPrincipal, configuration: DeliveryConfiguration
    ) -> DeliveryConfiguration:
        require_action_manager(actor, configuration.action_id)
        return await self._repository.save(configuration)
