"""Transactional application service for manually maintained action progress."""

from __future__ import annotations

from decimal import Decimal
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from leonaid.application.errors import ApplicationError
from leonaid.domain.action_progress import (
    ActionProgressResult,
    RecordActionProgressCommand,
)
from leonaid.domain.outbox import PendingOutboxEvent


class ActionProgressRepository(Protocol):
    async def set_actual_value(self, action_id: UUID, value: Decimal) -> Decimal: ...


class AuditRepository(Protocol):
    async def append_action_progress(
        self,
        *,
        event_id: UUID,
        action_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        actual_value: Decimal,
    ) -> None: ...


class TransactionalOutboxRepository(Protocol):
    async def append(self, event: PendingOutboxEvent) -> None: ...


class CommandReceiptRepository(Protocol):
    async def reserve(
        self,
        *,
        idempotency_key: str,
        command_type: str,
        request_hash: str,
    ) -> dict[str, str] | None: ...

    async def complete(
        self,
        *,
        idempotency_key: str,
        result: dict[str, str],
    ) -> None: ...


class ActionProgressUnitOfWork(Protocol):
    @property
    def actions(self) -> ActionProgressRepository: ...

    @property
    def audit(self) -> AuditRepository: ...

    @property
    def outbox(self) -> TransactionalOutboxRepository: ...

    @property
    def command_receipts(self) -> CommandReceiptRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class ActionProgressUnitOfWorkFactory(Protocol):
    def __call__(self) -> ActionProgressUnitOfWork: ...


class RecordActionProgress:
    """Persist action state, audit and durable work as one atomic command."""

    def __init__(self, unit_of_work: ActionProgressUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    async def execute(
        self,
        command: RecordActionProgressCommand,
    ) -> ActionProgressResult:
        event = command.outbox_event()
        async with self._unit_of_work() as unit_of_work:
            existing = await unit_of_work.command_receipts.reserve(
                idempotency_key=command.idempotency_key,
                command_type="record_action_progress",
                request_hash=command.request_hash,
            )
            if existing is not None:
                return self._replayed(existing)

            value = await unit_of_work.actions.set_actual_value(
                command.action_id,
                command.actual_value,
            )
            await unit_of_work.audit.append_action_progress(
                event_id=command.audit_event_id,
                action_id=command.action_id,
                actor_user_id=command.actor_user_id,
                request_id=command.request_id,
                actual_value=value,
            )
            await unit_of_work.outbox.append(event)
            result = {
                "actionId": str(command.action_id),
                "actualValue": str(value),
                "outboxEventId": str(event.id),
            }
            await unit_of_work.command_receipts.complete(
                idempotency_key=command.idempotency_key,
                result=result,
            )
            await unit_of_work.commit()
            return ActionProgressResult(
                action_id=command.action_id,
                actual_value=value,
                outbox_event_id=event.id,
                replayed=False,
            )

    @staticmethod
    def _replayed(result: dict[str, str]) -> ActionProgressResult:
        try:
            return ActionProgressResult(
                action_id=UUID(result["actionId"]),
                actual_value=Decimal(result["actualValue"]),
                outbox_event_id=UUID(result["outboxEventId"]),
                replayed=True,
            )
        except (KeyError, ValueError) as error:
            raise ApplicationError(
                "idempotency_record_corrupt",
                "Der gespeicherte Befehlsnachweis ist ungültig.",
            ) from error
