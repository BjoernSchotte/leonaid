"""Inbox persistence using the existing transactional outbox and receipts."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.action_progress import AsyncpgCommandReceiptRepository
from leonaid.application.errors import (
    ApplicationError,
    AuthenticationRequired,
    Conflict,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.domain.identity import IdentityPrincipal
from leonaid.modules.inbox.api import (
    Assignee,
    AssigneeQuery,
    Assignees,
    Case,
    CaseQuery,
    Cases,
    Submission,
    SubmitCase,
    UpdateCase,
)


_CASE_COLUMNS = ",".join(f"c.{name}" for name in Case.model_fields)
_MANAGE = """
    (EXISTS (SELECT 1 FROM user_global_role g WHERE g.user_id=$1 AND g.role='system_admin')
    OR EXISTS (SELECT 1 FROM action_membership m WHERE m.user_id=$1 AND m.action_id=c.action_id
        AND m.role='charity_admin' AND m.active_from<=now() AND (m.active_until IS NULL OR m.active_until>now())))
"""
_READ = f"""
    ({_MANAGE} OR (c.assignee_user_id=$1 AND (c.action_id IS NULL OR EXISTS (
        SELECT 1 FROM action_membership m WHERE m.user_id=$1 AND m.action_id=c.action_id
        AND m.active_from<=now() AND (m.active_until IS NULL OR m.active_until>now())))))
"""


# Shared by candidate discovery and assignment validation. $2 is the case action.
_ELIGIBLE_ASSIGNEE = """
    u.status='active' AND ($2::uuid IS NULL OR EXISTS (
        SELECT 1 FROM user_global_role g WHERE g.user_id=u.id AND g.role='system_admin')
    OR EXISTS (SELECT 1 FROM action_membership m WHERE m.user_id=u.id AND m.action_id=$2
        AND m.active_from<=now() AND (m.active_until IS NULL OR m.active_until>now())))
"""


class AsyncpgInboxRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self.pool = pool

    async def submit(self, command: SubmitCase) -> Submission:
        key = f"inbox.submit:{command.idempotency_key}"
        digest = hashlib.sha256(command.model_dump_json().encode()).hexdigest()
        async with self.pool.acquire() as conn, conn.transaction():
            receipts = AsyncpgCommandReceiptRepository(conn)
            try:
                replay = await receipts.reserve(
                    idempotency_key=key,
                    command_type="inbox.submitted",
                    request_hash=digest,
                )
            except ApplicationError as error:
                if error.code == "idempotency_conflict":
                    raise Conflict(error.code, error.message) from error
                raise
            if replay is not None:
                # A confirmed receipt remains valid after a publication closes.
                # No case contents, contact details or internal IDs are returned.
                return Submission.model_validate_json(replay["document"])
            if command.action_id is not None:
                action = await conn.fetchrow(
                    """
                    SELECT id FROM charity_action WHERE id=$1 AND status='active'
                        AND publication_starts_at <= now() AND publication_ends_at >= now()
                    FOR SHARE
                    """,
                    command.action_id,
                )
                if action is None:
                    raise ResourceNotFound(
                        "not_found", "Öffentliche Aktion nicht gefunden."
                    )
            case_id, job_id = uuid4(), uuid4()
            result = Submission(reference=uuid4())
            await conn.execute(
                """
                INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload)
                VALUES ($1,'inbox_case',$2,'inbox.contact_link.v1',$3,jsonb_build_object('caseId',$2::uuid::text))
                """,
                job_id,
                case_id,
                f"inbox-contact:{case_id}",
            )
            await conn.execute(
                """
                INSERT INTO inbox_case(id,public_reference,action_id,subject,message,given_name,family_name,email,phone,contact_create_id,contact_job_id)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """,
                case_id,
                result.reference,
                command.action_id,
                command.subject,
                command.message,
                command.given_name,
                command.family_name,
                command.email,
                command.phone,
                uuid4(),
                job_id,
            )
            await conn.execute(
                """
                INSERT INTO audit_event(id,action_id,event_type,entity_type,entity_id,request_id,payload)
                VALUES ($1,$2,'inbox.submitted','inbox_case',$3,$4,'{}'::jsonb)
                """,
                uuid4(),
                command.action_id,
                case_id,
                key,
            )
            await receipts.complete(
                idempotency_key=key, result={"document": result.model_dump_json()}
            )
            return result

    async def _active(self, conn: asyncpg.Connection[Any], user_id: UUID) -> None:
        if (
            await conn.fetchval(
                "SELECT status FROM user_account WHERE id=$1 FOR SHARE", user_id
            )
            != "active"
        ):
            raise AuthenticationRequired(
                "authentication_required", "Aktives Konto erforderlich."
            )

    async def _case(
        self, conn: asyncpg.Connection[Any], user_id: UUID, case_id: UUID
    ) -> Case:
        row = await conn.fetchrow(
            f"SELECT {_CASE_COLUMNS} FROM inbox_case c WHERE c.id=$2 AND {_READ} FOR UPDATE OF c",
            user_id,
            case_id,
        )
        if row is None:
            raise ResourceNotFound("not_found", "Fall nicht gefunden.")
        return Case.model_validate(dict(row))

    async def get_case(self, actor: IdentityPrincipal, case_id: UUID) -> Case:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            return await self._case(conn, actor.account.id, case_id)

    async def list_cases(self, actor: IdentityPrincipal, query: CaseQuery) -> Cases:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            rows = await conn.fetch(
                f"""SELECT {_CASE_COLUMNS} FROM inbox_case c WHERE {_READ}
                    AND ($2::uuid IS NULL OR c.action_id=$2)
                    AND ($3::text IS NULL OR c.status=$3)
                    AND (NOT $4 OR c.assignee_user_id=$1)
                    AND strpos(lower(c.subject),lower($5))>0
                    ORDER BY c.received_at DESC,c.id LIMIT $6 OFFSET $7""",
                actor.account.id,
                query.action_id,
                query.status,
                query.for_me,
                query.search,
                query.limit + 1,
                query.offset,
            )
            return Cases(
                items=[Case.model_validate(dict(row)) for row in rows[: query.limit]],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def list_assignees(
        self, actor: IdentityPrincipal, case_id: UUID, query: AssigneeQuery
    ) -> Assignees:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            current = await self._case(conn, actor.account.id, case_id)
            if not await conn.fetchval(
                f"SELECT {_MANAGE} FROM inbox_case c WHERE c.id=$2",
                actor.account.id,
                case_id,
            ):
                raise PermissionDenied(
                    "permission_denied", "Nur die Verwaltung kann Zuständige auswählen."
                )
            rows = await conn.fetch(
                f"""SELECT u.id AS user_id,u.display_name FROM user_account u
                    WHERE strpos(lower(u.display_name),lower($1))>0 AND {_ELIGIBLE_ASSIGNEE}
                    ORDER BY lower(u.display_name),u.id LIMIT $3 OFFSET $4""",
                query.search,
                current.action_id,
                query.limit + 1,
                query.offset,
            )
            return Assignees(
                items=[
                    Assignee.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def update_case(
        self, actor: IdentityPrincipal, case_id: UUID, command: UpdateCase
    ) -> Case:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            current = await self._case(conn, actor.account.id, case_id)
            key = f"inbox.update:{actor.account.id}:{case_id}:{command.idempotency_key}"
            receipts = AsyncpgCommandReceiptRepository(conn)
            try:
                replay = await receipts.reserve(
                    idempotency_key=key,
                    command_type="inbox.updated",
                    request_hash=hashlib.sha256(
                        command.model_dump_json().encode()
                    ).hexdigest(),
                )
            except ApplicationError as error:
                if error.code == "idempotency_conflict":
                    raise Conflict(error.code, error.message) from error
                raise
            if replay is not None:
                if replay.get(
                    "requiresManagement"
                ) == "true" and not await conn.fetchval(
                    f"SELECT {_MANAGE} FROM inbox_case c WHERE c.id=$2",
                    actor.account.id,
                    case_id,
                ):
                    raise PermissionDenied(
                        "permission_denied",
                        "Nur die Verwaltung kann die Zuständigkeit ändern.",
                    )
                return current
            if current.revision != command.expected_revision:
                raise Conflict(
                    "revision_conflict", "Der Fall wurde inzwischen geändert."
                )
            if current.assignee_user_id != command.assignee_user_id:
                if not await conn.fetchval(
                    f"SELECT {_MANAGE} FROM inbox_case c WHERE c.id=$2",
                    actor.account.id,
                    case_id,
                ):
                    raise PermissionDenied(
                        "permission_denied",
                        "Nur die Verwaltung kann die Zuständigkeit ändern.",
                    )
                if command.assignee_user_id is not None:
                    eligible = await conn.fetchval(
                        f"SELECT EXISTS (SELECT 1 FROM user_account u WHERE u.id=$1 AND {_ELIGIBLE_ASSIGNEE})",
                        command.assignee_user_id,
                        current.action_id,
                    )
                    if not eligible:
                        raise PermissionDenied(
                            "invalid_assignee",
                            "Person kann diesem Fall nicht zugeordnet werden.",
                        )
            await conn.execute(
                """UPDATE inbox_case SET status=$2,assignee_user_id=$3,closure_note=$4,
                    closed_at=CASE WHEN $2='closed' THEN COALESCE(closed_at,now()) ELSE NULL END,
                    revision=revision+1,updated_at=now() WHERE id=$1""",
                case_id,
                command.status,
                command.assignee_user_id,
                command.closure_note,
            )
            # Preserve closure history on reopen without duplicating the immutable
            # incoming contact/message snapshot into receipts or audit.
            await conn.execute(
                """INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
                    VALUES($1,$2,$3,'inbox.updated','inbox_case',$4,$5,$6::jsonb)""",
                uuid4(),
                current.action_id,
                actor.account.id,
                case_id,
                key,
                json.dumps(
                    {
                        "status": command.status,
                        "assigneeUserId": str(command.assignee_user_id)
                        if command.assignee_user_id
                        else None,
                        "closureNote": command.closure_note,
                        "previousClosureNote": current.closure_note,
                        "revision": current.revision + 1,
                    }
                ),
            )
            await receipts.complete(
                idempotency_key=key,
                result={
                    "caseId": str(case_id),
                    "requiresManagement": "true"
                    if current.assignee_user_id != command.assignee_user_id
                    else "false",
                },
            )
            return await self._case(conn, actor.account.id, case_id)
