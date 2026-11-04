"""Authorized delivery schedule administration."""

from typing import Protocol
from uuid import UUID

from leonaid.application.errors import Conflict
from leonaid.application.policies import require_action_manager
from leonaid.domain.delivery import DeliveryConfiguration
from leonaid.domain.identity import IdentityPrincipal


def window_full_conflict() -> Conflict:
    """The refusal of a window that a manager marked as "ausgebucht"."""
    return Conflict(
        "delivery_window_full",
        "Dieses Lieferfenster ist ausgebucht. Bitte ein anderes wählen.",
    )


def require_publicly_bookable(
    configuration: DeliveryConfiguration, window_id: UUID | None
) -> None:
    """Early public refusal; the order transaction checks again under lock."""
    if window_id is None:
        return
    if any(
        window.id == window_id and window.fully_booked
        for window in configuration.windows
    ):
        raise window_full_conflict()


class DeliveryRepository(Protocol):
    async def get(self, action_id: UUID) -> DeliveryConfiguration: ...

    async def save(
        self,
        configuration: DeliveryConfiguration,
        *,
        actor_user_id: UUID | None = None,
        request_id: str = "internal",
    ) -> DeliveryConfiguration: ...

    async def set_fully_booked(
        self,
        *,
        action_id: UUID,
        window_id: UUID,
        fully_booked: bool,
        actor_user_id: UUID,
        request_id: str,
    ) -> DeliveryConfiguration: ...


class DeliveryService:
    def __init__(self, repository: DeliveryRepository) -> None:
        self._repository = repository

    async def for_published_order_form(self, action_id: UUID) -> DeliveryConfiguration:
        """Only called after the existing public publication/alias gate."""
        return await self._repository.get(action_id)

    async def get(
        self, actor: IdentityPrincipal, action_id: UUID
    ) -> DeliveryConfiguration:
        require_action_manager(actor, action_id)
        return await self._repository.get(action_id)

    async def save(
        self,
        actor: IdentityPrincipal,
        configuration: DeliveryConfiguration,
        *,
        request_id: str = "internal",
    ) -> DeliveryConfiguration:
        require_action_manager(actor, configuration.action_id)
        return await self._repository.save(
            configuration,
            actor_user_id=actor.account.id,
            request_id=request_id,
        )

    async def set_fully_booked(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        window_id: UUID,
        *,
        fully_booked: bool,
        request_id: str,
    ) -> DeliveryConfiguration:
        require_action_manager(actor, action_id)
        return await self._repository.set_fully_booked(
            action_id=action_id,
            window_id=window_id,
            fully_booked=fully_booked,
            actor_user_id=actor.account.id,
            request_id=request_id,
        )
