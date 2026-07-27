"""PostgreSQL persistence and audit trail for feature flags."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.feature_flags import FeatureFlagRepository
from leonaid.domain.feature_flags import FeatureFlagKey, FeatureFlagState


class AsyncpgFeatureFlagRepository(FeatureFlagRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def list(self) -> tuple[FeatureFlagState, ...]:
        rows = await self._pool.fetch(
            """
            SELECT
                id, key, enabled, revision, updated_by_user_id, updated_at
            FROM feature_flag
            ORDER BY key
            """
        )
        return tuple(self._state(row) for row in rows)

    async def update(
        self,
        *,
        key: FeatureFlagKey,
        enabled: bool,
        expected_revision: int,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> FeatureFlagState:
        async with self._pool.acquire() as connection:
            async with connection.transaction(isolation="serializable"):
                row = await connection.fetchrow(
                    """
                    SELECT
                        id, key, enabled, revision,
                        updated_by_user_id, updated_at
                    FROM feature_flag
                    WHERE key = $1
                    FOR UPDATE
                    """,
                    key.value,
                )
                if row is None:
                    raise ResourceNotFound(
                        "feature_flag_not_found",
                        "Dieses Feature-Flag ist nicht registriert.",
                    )
                current = self._state(row)
                if current.revision != expected_revision:
                    raise Conflict(
                        "feature_flag_revision_conflict",
                        "Das Feature-Flag wurde zwischenzeitlich geändert. "
                        "Lade den aktuellen Stand neu.",
                    )
                if current.enabled == enabled:
                    return current
                updated = await connection.fetchrow(
                    """
                    UPDATE feature_flag
                    SET enabled = $2,
                        revision = revision + 1,
                        updated_by_user_id = $3,
                        updated_at = $4
                    WHERE id = $1
                    RETURNING
                        id, key, enabled, revision,
                        updated_by_user_id, updated_at
                    """,
                    current.id,
                    enabled,
                    actor_user_id,
                    occurred_at,
                )
                if updated is None:
                    raise RuntimeError(
                        "Das Feature-Flag konnte nicht gespeichert werden."
                    )
                state = self._state(updated)
                await connection.execute(
                    """
                    INSERT INTO audit_event (
                        id, action_id, actor_user_id, event_type,
                        entity_type, entity_id, request_id, payload, occurred_at
                    )
                    VALUES ($1, NULL, $2, $3, $4, $5, $6, $7::jsonb, $8)
                    """,
                    uuid4(),
                    actor_user_id,
                    "feature_flag_changed",
                    "feature_flag",
                    state.id,
                    request_id,
                    json.dumps(
                        {
                            "key": state.key.value,
                            "previousEnabled": current.enabled,
                            "enabled": state.enabled,
                            "previousRevision": current.revision,
                            "revision": state.revision,
                        },
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
                return state

    @staticmethod
    def _state(row: asyncpg.Record) -> FeatureFlagState:
        return FeatureFlagState(
            id=row["id"],
            key=FeatureFlagKey(str(row["key"])),
            enabled=bool(row["enabled"]),
            revision=int(row["revision"]),
            updated_by_user_id=row["updated_by_user_id"],
            updated_at=row["updated_at"],
        )
