"""Atomic redirect mutations with current Core authority and durable receipts."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.campaign_aliases import (
    CampaignAliasCommand,
    CampaignAliasResult,
)
from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound

COMMAND_TYPE = "campaign_alias.mutate.v1"


class AsyncpgCampaignAliasRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    @staticmethod
    async def _authority(
        db: asyncpg.Connection[Any], actor: UUID, action: UUID
    ) -> None:
        status = await db.fetchval(
            "SELECT status FROM user_account WHERE id=$1 FOR SHARE", actor
        )
        if status != "active":
            raise PermissionDenied(
                "campaign_alias_management_required", "Alias-Verwaltung nicht erlaubt."
            )
        roles = await db.fetch(
            "SELECT role FROM user_global_role WHERE user_id=$1 FOR SHARE", actor
        )
        if not any(row["role"] == "system_admin" for row in roles):
            memberships = await db.fetch(
                "SELECT id FROM action_membership WHERE user_id=$1 AND action_id=$2 "
                "AND role='charity_admin' AND active_from<=clock_timestamp() "
                "AND (active_until IS NULL OR active_until>clock_timestamp()) FOR SHARE",
                actor,
                action,
            )
            if not memberships:
                raise PermissionDenied(
                    "campaign_alias_management_required",
                    "Alias-Verwaltung nicht erlaubt.",
                )
        if not await db.fetchval(
            "SELECT EXISTS(SELECT 1 FROM charity_action WHERE id=$1)", action
        ):
            raise ResourceNotFound(
                "campaign_alias_action_not_found", "Aktion nicht gefunden."
            )

    async def mutate(
        self, actor_id: UUID, command: CampaignAliasCommand, *, request_id: str
    ) -> CampaignAliasResult:
        key = f"campaign-alias:{command.command_id}"
        fingerprint = command.fingerprint(actor_id)
        try:
            async with self._pool.acquire() as db:
                async with db.transaction():
                    await db.execute("SET LOCAL lock_timeout='3s'")
                    await db.execute("SET LOCAL statement_timeout='5s'")
                    # Same ordering as legacy publication changes. Alias identity
                    # and both action rows cannot change between checks/writes.
                    await db.execute("SELECT pg_advisory_xact_lock(527052)")
                    for action in sorted({command.action_id, command.target_action_id}):
                        await self._authority(db, actor_id, action)
                    receipt = await db.fetchrow(
                        "SELECT command_type,request_hash,result FROM command_receipt WHERE idempotency_key=$1 FOR UPDATE",
                        key,
                    )
                    current = await db.fetchrow(
                        "SELECT * FROM public_action_alias WHERE id=$1 FOR UPDATE",
                        command.alias_id,
                    )
                    if receipt is not None:
                        if (
                            receipt["command_type"] != COMMAND_TYPE
                            or receipt["request_hash"] != fingerprint
                        ):
                            raise Conflict(
                                "idempotency_conflict",
                                "Diese Vorgangs-ID wurde für andere Daten verwendet.",
                            )
                        if current is not None:
                            await self._authority(db, actor_id, current["action_id"])
                        data = json.loads(receipt["result"])
                        return CampaignAliasResult(
                            **{
                                **data,
                                "alias_id": UUID(data["alias_id"]),
                                "action_id": UUID(data["action_id"]),
                            }
                        )
                    if command.operation == "create":
                        if current is not None:
                            raise Conflict(
                                "campaign_alias_conflict",
                                "Diese Alias-ID ist bereits vergeben.",
                            )
                    elif current is None or current["action_id"] != command.action_id:
                        raise ResourceNotFound(
                            "campaign_alias_not_found", "Alias nicht gefunden."
                        )
                    else:
                        if current["is_primary"]:
                            raise Conflict(
                                "campaign_alias_primary",
                                "Hauptadressen werden über die Publikation verwaltet.",
                            )
                        if current["revision"] != command.revision:
                            raise Conflict(
                                "campaign_alias_revision_conflict",
                                "Alias wurde geändert. Bitte neu laden.",
                            )
                    for action in sorted({command.action_id, command.target_action_id}):
                        status = await db.fetchval(
                            "SELECT status FROM charity_action WHERE id=$1 FOR UPDATE",
                            action,
                        )
                        if (
                            status in {"completed", "archived"}
                            and command.operation != "remove"
                        ):
                            raise Conflict(
                                "campaign_alias_action_closed",
                                "Für abgeschlossene Aktionen können keine Aliase geändert werden.",
                            )
                    if command.operation == "create":
                        row = await db.fetchrow(
                            "INSERT INTO public_action_alias(id,alias,action_id,is_primary,enabled) VALUES($1,$2,$3,false,$4) RETURNING *",
                            command.alias_id,
                            command.alias,
                            command.target_action_id,
                            command.enabled,
                        )
                    elif command.operation == "update":
                        row = await db.fetchrow(
                            "UPDATE public_action_alias SET alias=$2,action_id=$3,enabled=$4,revision=revision+1,switched_at=clock_timestamp() WHERE id=$1 RETURNING *",
                            command.alias_id,
                            command.alias,
                            command.target_action_id,
                            command.enabled,
                        )
                    else:
                        row = await db.fetchrow(
                            "DELETE FROM public_action_alias WHERE id=$1 RETURNING *",
                            command.alias_id,
                        )
                    assert row is not None
                    result = CampaignAliasResult(
                        command.alias_id,
                        row["action_id"],
                        row["alias"],
                        row["enabled"],
                        row["revision"],
                        command.operation == "remove",
                    )
                    payload = {
                        "operation": command.operation,
                        "previousTarget": str(current["action_id"])
                        if current
                        else None,
                        "newTarget": None if result.removed else str(result.action_id),
                        "previousAlias": current["alias"] if current else None,
                        "newAlias": None if result.removed else result.alias,
                        "enabled": result.enabled,
                        "revision": result.revision,
                    }
                    await db.execute(
                        "INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload) VALUES($1,$2,$3,'campaign_alias.changed','campaign_alias',$4,$5,$6::jsonb)",
                        uuid4(),
                        command.action_id,
                        actor_id,
                        command.alias_id,
                        request_id,
                        json.dumps(payload),
                    )
                    await db.execute(
                        "INSERT INTO command_receipt(idempotency_key,command_type,request_hash,result,completed_at) VALUES($1,$2,$3,$4::jsonb,clock_timestamp())",
                        key,
                        COMMAND_TYPE,
                        fingerprint,
                        json.dumps(asdict(result), default=str),
                    )
                    # Check membership expiry again at the transaction's final
                    # authority point, including for a cross-action move.
                    for action in sorted({command.action_id, command.target_action_id}):
                        await self._authority(db, actor_id, action)
                    return result
        except asyncpg.UniqueViolationError:
            raise Conflict(
                "campaign_alias_conflict",
                "Diese Alias-Adresse oder Vorgangs-ID ist bereits vergeben.",
            ) from None
        except (
            asyncpg.LockNotAvailableError,
            asyncpg.QueryCanceledError,
            asyncpg.DeadlockDetectedError,
        ):
            raise Conflict(
                "campaign_alias_busy",
                "Alias-Verwaltung ist beschäftigt. Bitte denselben Vorgang erneut versuchen.",
            ) from None
