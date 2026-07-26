"""PostgreSQL persistence for the neutral CharityAction aggregate."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.actions import CharityActionRepository
from leonaid.application.errors import Conflict
from leonaid.domain.actions import (
    ActionCapability,
    ActionGoal,
    Beneficiary,
    CharityAction,
    CharityActionStatus,
)


class AsyncpgCharityActionRepository(CharityActionRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def get(self, action_id: UUID) -> CharityAction | None:
        async with self._pool.acquire() as connection:
            return await self._get(connection, action_id)

    async def create(
        self,
        action: CharityAction,
        *,
        responsible_admin_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        try:
            async with self._pool.acquire() as connection:
                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO charity_action (
                            id, carrier_name, name, purpose, status,
                            starts_on, ends_on, archive_slug,
                            goal_value, actual_value, goal_unit, currency,
                            created_at, updated_at
                        )
                        VALUES (
                            $1, $2, $3, $4, $5,
                            $6, $7, $8,
                            $9, $10, $11, $12,
                            $13, $13
                        )
                        """,
                        action.id,
                        action.carrier_name,
                        action.name,
                        action.purpose,
                        action.status.value,
                        action.starts_on,
                        action.ends_on,
                        action.archive_slug,
                        action.goal.goal_value,
                        action.goal.actual_value,
                        action.goal.unit,
                        action.goal.currency,
                        occurred_at,
                    )
                    await self._insert_capabilities(connection, action)
                    await self._insert_beneficiaries(connection, action, occurred_at)
                    await connection.execute(
                        """
                        INSERT INTO action_membership (
                            id, action_id, user_id, role, active_from
                        )
                        VALUES ($1, $2, $3, 'charity_admin', $4)
                        """,
                        uuid4(),
                        action.id,
                        responsible_admin_user_id,
                        occurred_at,
                    )
                    await self._audit(
                        connection,
                        action=action,
                        actor_user_id=responsible_admin_user_id,
                        event_type="charity_action.created",
                        request_id=request_id,
                        payload={
                            "status": action.status.value,
                            "capabilities": self._capability_values(action),
                            "beneficiaryCount": len(action.beneficiaries),
                            "goal": self._goal_payload(action.goal),
                        },
                        occurred_at=occurred_at,
                    )
        except asyncpg.UniqueViolationError as error:
            raise Conflict(
                "action_archive_slug_conflict",
                "Dieser Archiv-Slug wird bereits von einer Charity-Aktion verwendet.",
            ) from error
        return action

    async def update_goal(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._lock_expected_status(connection, action)
                status = await connection.execute(
                    """
                    UPDATE charity_action
                    SET goal_value = $2,
                        actual_value = $3,
                        goal_unit = $4,
                        currency = $5,
                        updated_at = $6
                    WHERE id = $1
                    """,
                    action.id,
                    action.goal.goal_value,
                    action.goal.actual_value,
                    action.goal.unit,
                    action.goal.currency,
                    occurred_at,
                )
                self._require_update(status)
                await self._audit(
                    connection,
                    action=action,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.goal_changed",
                    request_id=request_id,
                    payload=self._goal_payload(action.goal),
                    occurred_at=occurred_at,
                )
        return action

    async def replace_capabilities(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._lock_expected_status(connection, action)
                await connection.execute(
                    "DELETE FROM charity_action_capability WHERE action_id = $1",
                    action.id,
                )
                await self._insert_capabilities(connection, action)
                await connection.execute(
                    "UPDATE charity_action SET updated_at = $2 WHERE id = $1",
                    action.id,
                    occurred_at,
                )
                await self._audit(
                    connection,
                    action=action,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.capabilities_changed",
                    request_id=request_id,
                    payload={"capabilities": self._capability_values(action)},
                    occurred_at=occurred_at,
                )
        return action

    async def replace_beneficiaries(
        self,
        action: CharityAction,
        *,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await self._lock_expected_status(connection, action)
                await connection.execute(
                    "DELETE FROM beneficiary WHERE action_id = $1",
                    action.id,
                )
                await self._insert_beneficiaries(connection, action, occurred_at)
                await connection.execute(
                    "UPDATE charity_action SET updated_at = $2 WHERE id = $1",
                    action.id,
                    occurred_at,
                )
                await self._audit(
                    connection,
                    action=action,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.beneficiaries_changed",
                    request_id=request_id,
                    payload={"beneficiaryCount": len(action.beneficiaries)},
                    occurred_at=occurred_at,
                )
        return action

    async def transition(
        self,
        action: CharityAction,
        *,
        previous_status: CharityActionStatus,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> CharityAction:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                status = await connection.execute(
                    """
                    UPDATE charity_action
                    SET status = $3, updated_at = $4
                    WHERE id = $1 AND status = $2
                    """,
                    action.id,
                    previous_status.value,
                    action.status.value,
                    occurred_at,
                )
                if status != "UPDATE 1":
                    raise Conflict(
                        "action_concurrent_change",
                        "Die Charity-Aktion wurde zwischenzeitlich geändert.",
                    )
                await self._audit(
                    connection,
                    action=action,
                    actor_user_id=actor_user_id,
                    event_type="charity_action.status_changed",
                    request_id=request_id,
                    payload={
                        "previousStatus": previous_status.value,
                        "newStatus": action.status.value,
                    },
                    occurred_at=occurred_at,
                )
        return action

    @staticmethod
    async def _get(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
    ) -> CharityAction | None:
        row = await connection.fetchrow(
            """
            SELECT
                id, carrier_name, name, purpose, status,
                starts_on, ends_on, archive_slug,
                goal_value, actual_value, goal_unit, currency
            FROM charity_action
            WHERE id = $1
            """,
            action_id,
        )
        if row is None:
            return None
        capability_rows = await connection.fetch(
            """
            SELECT capability
            FROM charity_action_capability
            WHERE action_id = $1
            ORDER BY capability
            """,
            action_id,
        )
        beneficiary_rows = await connection.fetch(
            """
            SELECT
                id, action_id, organization_name,
                public_description, sort_order
            FROM beneficiary
            WHERE action_id = $1
            ORDER BY sort_order, id
            """,
            action_id,
        )
        return CharityAction(
            id=row["id"],
            carrier_name=str(row["carrier_name"]),
            name=str(row["name"]),
            purpose=str(row["purpose"]),
            status=CharityActionStatus(str(row["status"])),
            starts_on=row["starts_on"],
            ends_on=row["ends_on"],
            archive_slug=str(row["archive_slug"]),
            capabilities=frozenset(
                ActionCapability(str(item["capability"])) for item in capability_rows
            ),
            beneficiaries=tuple(
                Beneficiary(
                    id=item["id"],
                    action_id=item["action_id"],
                    organization_name=str(item["organization_name"]),
                    public_description=str(item["public_description"]),
                    sort_order=int(item["sort_order"]),
                )
                for item in beneficiary_rows
            ),
            goal=ActionGoal(
                goal_value=(
                    Decimal(row["goal_value"])
                    if row["goal_value"] is not None
                    else None
                ),
                actual_value=Decimal(row["actual_value"]),
                unit=str(row["goal_unit"]) if row["goal_unit"] is not None else None,
                currency=str(row["currency"]) if row["currency"] is not None else None,
            ),
        )

    @staticmethod
    async def _insert_capabilities(
        connection: asyncpg.Connection[Any],
        action: CharityAction,
    ) -> None:
        if not action.capabilities:
            return
        await connection.executemany(
            """
            INSERT INTO charity_action_capability (action_id, capability)
            VALUES ($1, $2)
            """,
            [
                (action.id, capability.value)
                for capability in sorted(
                    action.capabilities, key=lambda item: item.value
                )
            ],
        )

    @staticmethod
    async def _insert_beneficiaries(
        connection: asyncpg.Connection[Any],
        action: CharityAction,
        occurred_at: datetime,
    ) -> None:
        await connection.executemany(
            """
            INSERT INTO beneficiary (
                id, action_id, organization_name, public_description,
                sort_order, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $6)
            """,
            [
                (
                    item.id,
                    item.action_id,
                    item.organization_name,
                    item.public_description,
                    item.sort_order,
                    occurred_at,
                )
                for item in action.beneficiaries
            ],
        )

    @staticmethod
    async def _audit(
        connection: asyncpg.Connection[Any],
        *,
        action: CharityAction,
        actor_user_id: UUID,
        event_type: str,
        request_id: str,
        payload: dict[str, object],
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type,
                entity_type, entity_id, request_id, payload, occurred_at
            )
            VALUES (
                $1, $2, $3, $4,
                'charity_action', $2, $5, $6::jsonb, $7
            )
            """,
            uuid4(),
            action.id,
            actor_user_id,
            event_type,
            request_id,
            json.dumps(payload, separators=(",", ":")),
            occurred_at,
        )

    @staticmethod
    def _capability_values(action: CharityAction) -> list[str]:
        return sorted(item.value for item in action.capabilities)

    @staticmethod
    def _goal_payload(goal: ActionGoal) -> dict[str, object]:
        return {
            "goalValue": str(goal.goal_value) if goal.goal_value is not None else None,
            "actualValue": str(goal.actual_value),
            "unit": goal.unit,
            "currency": goal.currency,
        }

    @staticmethod
    def _require_update(status: str) -> None:
        if status != "UPDATE 1":
            raise Conflict(
                "action_concurrent_change",
                "Die Charity-Aktion wurde zwischenzeitlich geändert.",
            )

    @staticmethod
    async def _lock_expected_status(
        connection: asyncpg.Connection[Any],
        action: CharityAction,
    ) -> None:
        current_status = await connection.fetchval(
            """
            SELECT status
            FROM charity_action
            WHERE id = $1
            FOR UPDATE
            """,
            action.id,
        )
        if current_status != action.status.value:
            raise Conflict(
                "action_concurrent_change",
                "Die Charity-Aktion wurde zwischenzeitlich geändert.",
            )
