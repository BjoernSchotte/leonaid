"""Delivery tours: authorized reads and order writes (specs/krapfentaxi-touren).

Behind the feature flag ``delivery.tours``: switched off, every call answers
404 before any rights check. Managers of an action read every tour of a day
and write base orders; drivers read their own tour ("Meine Tour") and write
only their own order beside it (spec §10). An empty driver write resets the
driver order to the base order ("Zurück zur Planung", Ruling 7). Managers
pin a stop by hand when its address was not found (spec §6.4).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from leonaid.application.delivery_board import is_driver, require_manager, translate
from leonaid.application.errors import PermissionDenied
from leonaid.application.feature_flags import FeatureFlagService
from leonaid.domain.delivery_board import DeliveryBoardError
from leonaid.domain.delivery_geo import GeoPoint
from leonaid.domain.delivery_tours import (
    DayTours,
    DriverTour,
    MapTiles,
    MyTour,
    TourStopView,
)
from leonaid.domain.feature_flags import FeatureFlagKey, FeatureFlagSurface
from leonaid.domain.identity import IdentityPrincipal


class DeliveryTourRepository(Protocol):
    async def day_tours(
        self, *, action_id: UUID, day: date | None, viewed_at: datetime
    ) -> DayTours: ...

    async def my_tour(
        self,
        *,
        action_id: UUID,
        driver_user_id: UUID,
        day: date | None,
        viewed_at: datetime,
    ) -> MyTour: ...

    async def save_order(
        self,
        *,
        action_id: UUID,
        driver_user_id: UUID,
        day: date,
        ordered_ids: Sequence[UUID],
        expected_revision: str,
        driver: bool,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> DriverTour: ...

    async def discard_driver_order(
        self,
        *,
        action_id: UUID,
        driver_user_id: UUID,
        day: date,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        driver: bool = False,
    ) -> DriverTour: ...

    async def set_pin(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        point: GeoPoint,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> TourStopView: ...


def _require_driver(actor: IdentityPrincipal, action_id: UUID) -> None:
    if not is_driver(actor, action_id):
        raise PermissionDenied(
            "delivery_board_forbidden", "Kein Zugriff auf die Auslieferung."
        )


class DeliveryTourService:
    def __init__(
        self,
        repository: DeliveryTourRepository,
        flags: FeatureFlagService,
        tiles: MapTiles,
    ) -> None:
        self._repository = repository
        self._flags = flags
        self._tiles = tiles

    @property
    def tiles(self) -> MapTiles:
        """The map tiles both tour reads hand to the apps (D14 b)."""
        return self._tiles

    async def _manager(self, actor: IdentityPrincipal, action_id: UUID) -> None:
        await self._flags.require_enabled(
            actor, FeatureFlagKey.DELIVERY_TOURS, surface=FeatureFlagSurface.WEB
        )
        require_manager(actor, action_id)

    async def _driver(self, actor: IdentityPrincipal, action_id: UUID) -> None:
        await self._flags.require_enabled(
            actor, FeatureFlagKey.DELIVERY_TOURS, surface=FeatureFlagSurface.PWA
        )
        _require_driver(actor, action_id)

    async def day_tours(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        day: date | None,
        viewed_at: datetime,
    ) -> DayTours:
        await self._manager(actor, action_id)
        return await self._repository.day_tours(
            action_id=action_id, day=day, viewed_at=viewed_at
        )

    async def my_tour(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        day: date | None,
        viewed_at: datetime,
    ) -> MyTour:
        await self._driver(actor, action_id)
        return await self._repository.my_tour(
            action_id=action_id,
            driver_user_id=actor.account.id,
            day=day,
            viewed_at=viewed_at,
        )

    async def save_base_order(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        driver_user_id: UUID,
        *,
        day: date,
        ordered_ids: Sequence[UUID],
        expected_revision: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DriverTour:
        await self._manager(actor, action_id)
        try:
            return await self._repository.save_order(
                action_id=action_id,
                driver_user_id=driver_user_id,
                day=day,
                ordered_ids=tuple(ordered_ids),
                expected_revision=expected_revision,
                driver=False,
                actor_user_id=actor.account.id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error

    async def discard_driver_order(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        driver_user_id: UUID,
        *,
        day: date,
        request_id: str,
        occurred_at: datetime,
    ) -> DriverTour:
        await self._manager(actor, action_id)
        try:
            return await self._repository.discard_driver_order(
                action_id=action_id,
                driver_user_id=driver_user_id,
                day=day,
                actor_user_id=actor.account.id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error

    async def save_driver_order(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        day: date,
        ordered_ids: Sequence[UUID],
        expected_revision: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DriverTour:
        await self._driver(actor, action_id)
        try:
            if not ordered_ids:
                # Reset is idempotent by its target state, so it needs no
                # revision: whatever changed, the base order applies.
                return await self._repository.discard_driver_order(
                    action_id=action_id,
                    driver_user_id=actor.account.id,
                    day=day,
                    actor_user_id=actor.account.id,
                    request_id=request_id,
                    occurred_at=occurred_at,
                    driver=True,
                )
            return await self._repository.save_order(
                action_id=action_id,
                driver_user_id=actor.account.id,
                day=day,
                ordered_ids=tuple(ordered_ids),
                expected_revision=expected_revision,
                driver=True,
                actor_user_id=actor.account.id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error

    async def set_pin(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        commitment_id: UUID,
        *,
        lat: float,
        lon: float,
        request_id: str,
        occurred_at: datetime,
    ) -> TourStopView:
        await self._manager(actor, action_id)
        point = GeoPoint.parse(lat, lon)
        try:
            return await self._repository.set_pin(
                action_id=action_id,
                commitment_id=commitment_id,
                point=point,
                actor_user_id=actor.account.id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error
