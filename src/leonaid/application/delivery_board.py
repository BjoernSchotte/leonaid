"""Delivery day board: authorized reads and commands.

Managers of an action see and edit every drop. Drivers see and tick only the
drops assigned to them, at any time, without amounts, e-mail, message or
history (Björn, 2026-11-04). Only managers assign drivers and close or reopen
windows. Every command is idempotent by its target state.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from leonaid.application.errors import Conflict, PermissionDenied
from leonaid.domain.delivery_board import (
    DeliveryBoard,
    DeliveryBoardError,
    DeliveryDrop,
)
from leonaid.domain.identity import ActionRole, IdentityPrincipal
from leonaid.domain.policies import may_manage_action


class DeliveryFollowUp(Protocol):
    """The tasks module's "Nachliefern" task for one missed order.

    Runs inside the board's transaction (``connection``). The task mirrors the
    drop: ``needed`` opens or creates it for ``assignee_user_id``, otherwise
    it is marked done. A ``closing_note`` is appended to the description of a
    task that this call marks done (an order cancellation says why). It must
    not contain personal data: the task outlives the order's erasure. Wired
    only while the tasks module is enabled.
    """

    async def sync(
        self,
        connection: Any,
        *,
        action_id: UUID,
        commitment_id: UUID,
        title: str,
        description: str,
        needed: bool,
        assignee_user_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        closing_note: str | None = None,
    ) -> None: ...


class DeliveryBoardRepository(Protocol):
    async def board(
        self,
        *,
        action_id: UUID,
        day: date | None,
        driver_user_id: UUID | None,
        viewed_at: datetime,
    ) -> DeliveryBoard: ...

    async def set_state(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        delivered: bool,
        expected_revision: int,
        actor_user_id: UUID,
        manager: bool,
        request_id: str,
        occurred_at: datetime,
    ) -> DeliveryDrop: ...

    async def assign_driver(
        self,
        *,
        action_id: UUID,
        commitment_ids: tuple[UUID, ...],
        driver_user_id: UUID | None,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int: ...

    async def close_window(
        self,
        *,
        action_id: UUID,
        window_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int: ...

    async def reopen_window(
        self,
        *,
        action_id: UUID,
        window_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> int: ...


def _is_driver(actor: IdentityPrincipal, action_id: UUID) -> bool:
    return ActionRole.DRIVER in actor.roles_for(action_id)


def _require_manager(actor: IdentityPrincipal, action_id: UUID) -> None:
    if not (actor.account.can_authenticate and may_manage_action(actor, action_id)):
        raise PermissionDenied(
            "delivery_management_required",
            "Nur wer die Aktion verwaltet, darf das.",
        )


def translate(error: DeliveryBoardError) -> Exception:
    if error.status == 403:
        return PermissionDenied(error.code, error.message)
    return Conflict(error.code, error.message)


class DeliveryBoardService:
    def __init__(
        self, repository: DeliveryBoardRepository, *, follow_up_tasks: bool = False
    ) -> None:
        self._repository = repository
        # Whether closing a window creates "Nachliefern" tasks.
        self.follow_up_tasks = follow_up_tasks

    async def board(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        day: date | None,
        viewed_at: datetime,
    ) -> DeliveryBoard:
        if not actor.account.can_authenticate:
            raise PermissionDenied(
                "delivery_board_forbidden", "Kein Zugriff auf die Auslieferung."
            )
        if may_manage_action(actor, action_id):
            driver = None
        elif _is_driver(actor, action_id):
            driver = actor.account.id
        else:
            raise PermissionDenied(
                "delivery_board_forbidden", "Kein Zugriff auf die Auslieferung."
            )
        return await self._repository.board(
            action_id=action_id,
            day=day,
            driver_user_id=driver,
            viewed_at=viewed_at,
        )

    async def set_state(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        commitment_id: UUID,
        *,
        delivered: bool,
        expected_revision: int,
        request_id: str,
        occurred_at: datetime,
    ) -> DeliveryDrop:
        manager = actor.account.can_authenticate and may_manage_action(actor, action_id)
        if not manager and not (
            actor.account.can_authenticate and _is_driver(actor, action_id)
        ):
            raise PermissionDenied(
                "delivery_board_forbidden", "Kein Zugriff auf die Auslieferung."
            )
        try:
            return await self._repository.set_state(
                action_id=action_id,
                commitment_id=commitment_id,
                delivered=delivered,
                expected_revision=expected_revision,
                actor_user_id=actor.account.id,
                manager=manager,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error

    async def assign_driver(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        *,
        commitment_ids: tuple[UUID, ...],
        driver_user_id: UUID | None,
        request_id: str,
        occurred_at: datetime,
    ) -> int:
        _require_manager(actor, action_id)
        try:
            return await self._repository.assign_driver(
                action_id=action_id,
                commitment_ids=commitment_ids,
                driver_user_id=driver_user_id,
                actor_user_id=actor.account.id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error

    async def close_window(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        window_id: UUID,
        *,
        request_id: str,
        occurred_at: datetime,
    ) -> int:
        _require_manager(actor, action_id)
        try:
            return await self._repository.close_window(
                action_id=action_id,
                window_id=window_id,
                actor_user_id=actor.account.id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error

    async def reopen_window(
        self,
        actor: IdentityPrincipal,
        action_id: UUID,
        window_id: UUID,
        *,
        request_id: str,
        occurred_at: datetime,
    ) -> int:
        _require_manager(actor, action_id)
        try:
            return await self._repository.reopen_window(
                action_id=action_id,
                window_id=window_id,
                actor_user_id=actor.account.id,
                request_id=request_id,
                occurred_at=occurred_at,
            )
        except DeliveryBoardError as error:
            raise translate(error) from error
