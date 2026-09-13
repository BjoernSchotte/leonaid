"""Inbox persistence using the existing transactional outbox and receipts."""

from __future__ import annotations

from collections.abc import Callable
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
    SetMaterialReference,
    MaterialReference,
    MaterialReferences,
    SetTaskReference,
    TaskReference,
    TaskReferences,
    AddComment,
    Comment,
    CommentQuery,
    Comments,
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

from leonaid.modules.tasks.api import TaskService
from leonaid.modules.materials.api import MaterialService

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
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        tasks: Callable[[asyncpg.Connection[Any]], TaskService],
        materials: Callable[[asyncpg.Connection[Any]], MaterialService],
    ) -> None:
        self.pool = pool
        self.tasks = tasks
        self.materials = materials

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

    async def list_task_references(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> TaskReferences:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            await self._case(conn, actor.account.id, case_id)
            rows = await conn.fetch(
                "SELECT task_id FROM inbox_case_task WHERE case_id=$1 ORDER BY task_id LIMIT 100",
                case_id,
            )
            items = []
            tasks = self.tasks(conn)
            for row in rows:
                try:
                    task = await tasks.get_task(actor, row["task_id"])
                except ResourceNotFound:
                    task = None
                items.append(TaskReference(task_id=row["task_id"], task=task))
            return TaskReferences(items=items)

    async def set_task_reference(
        self, actor: IdentityPrincipal, case_id: UUID, command: SetTaskReference
    ) -> Case:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            current = await self._case(conn, actor.account.id, case_id)
            if command.present:
                # Same connection keeps reference and source authorization in the
                # transaction; no task data is copied into Inbox-owned tables.
                await self.tasks(conn).get_task(actor, command.task_id)
            key = f"inbox.task-reference:{actor.account.id}:{case_id}:{command.idempotency_key}"
            receipts = AsyncpgCommandReceiptRepository(conn)
            try:
                replay = await receipts.reserve(
                    idempotency_key=key,
                    command_type="inbox.task_reference_changed",
                    request_hash=hashlib.sha256(
                        command.model_dump_json().encode()
                    ).hexdigest(),
                )
            except ApplicationError as error:
                if error.code == "idempotency_conflict":
                    raise Conflict(error.code, error.message) from error
                raise
            if replay is not None:
                return current
            if current.revision != command.expected_revision:
                raise Conflict(
                    "revision_conflict", "Der Fall wurde inzwischen geändert."
                )
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM inbox_case_task WHERE case_id=$1 AND task_id=$2)",
                case_id,
                command.task_id,
            )
            if exists != command.present:
                if command.present:
                    count = await conn.fetchval(
                        "SELECT count(*) FROM inbox_case_task WHERE case_id=$1", case_id
                    )
                    if count >= 100:
                        raise Conflict(
                            "reference_limit",
                            "Höchstens 100 Aufgaben pro Fall möglich.",
                        )
                    await conn.execute(
                        "INSERT INTO inbox_case_task(case_id,task_id) VALUES($1,$2)",
                        case_id,
                        command.task_id,
                    )
                else:
                    await conn.execute(
                        "DELETE FROM inbox_case_task WHERE case_id=$1 AND task_id=$2",
                        case_id,
                        command.task_id,
                    )
                await conn.execute(
                    "UPDATE inbox_case SET revision=revision+1,updated_at=now() WHERE id=$1",
                    case_id,
                )
                await conn.execute(
                    """INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
                        VALUES($1,$2,$3,'inbox.task_reference_changed','inbox_case',$4,$5,
                            jsonb_build_object('taskId',$6::text,'present',$7::boolean))""",
                    uuid4(),
                    current.action_id,
                    actor.account.id,
                    case_id,
                    key,
                    str(command.task_id),
                    command.present,
                )
            await receipts.complete(
                idempotency_key=key, result={"caseId": str(case_id)}
            )
            return await self._case(conn, actor.account.id, case_id)

    async def list_material_references(
        self, actor: IdentityPrincipal, case_id: UUID
    ) -> MaterialReferences:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            await self._case(conn, actor.account.id, case_id)
            rows = await conn.fetch(
                "SELECT material_id,material_version FROM inbox_case_material WHERE case_id=$1 ORDER BY material_id,material_version LIMIT 100",
                case_id,
            )
            items = []
            materials = self.materials(conn)
            for row in rows:
                try:
                    file = await materials.get_version(
                        actor, row["material_id"], row["material_version"]
                    )
                except ResourceNotFound:
                    file = None
                items.append(
                    MaterialReference(
                        material_id=row["material_id"],
                        material_version=row["material_version"],
                        file=file,
                    )
                )
            return MaterialReferences(items=items)

    async def set_material_reference(
        self, actor: IdentityPrincipal, case_id: UUID, command: SetMaterialReference
    ) -> Case:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            current = await self._case(conn, actor.account.id, case_id)
            if command.present:
                await self.materials(conn).get_version(
                    actor, command.material_id, command.material_version
                )
            key = f"inbox.material-reference:{actor.account.id}:{case_id}:{command.idempotency_key}"
            receipts = AsyncpgCommandReceiptRepository(conn)
            try:
                replay = await receipts.reserve(
                    idempotency_key=key,
                    command_type="inbox.material_reference_changed",
                    request_hash=hashlib.sha256(
                        command.model_dump_json().encode()
                    ).hexdigest(),
                )
            except ApplicationError as error:
                if error.code == "idempotency_conflict":
                    raise Conflict(error.code, error.message) from error
                raise
            if replay is not None:
                return current
            if current.revision != command.expected_revision:
                raise Conflict(
                    "revision_conflict", "Der Fall wurde inzwischen geändert."
                )
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM inbox_case_material WHERE case_id=$1 AND material_id=$2 AND material_version=$3)",
                case_id,
                command.material_id,
                command.material_version,
            )
            if exists != command.present:
                if command.present:
                    count = await conn.fetchval(
                        "SELECT count(*) FROM inbox_case_material WHERE case_id=$1",
                        case_id,
                    )
                    if count >= 100:
                        raise Conflict(
                            "reference_limit",
                            "Höchstens 100 Dateiverweise pro Fall möglich.",
                        )
                    await conn.execute(
                        "INSERT INTO inbox_case_material(case_id,material_id,material_version) VALUES($1,$2,$3)",
                        case_id,
                        command.material_id,
                        command.material_version,
                    )
                else:
                    await conn.execute(
                        "DELETE FROM inbox_case_material WHERE case_id=$1 AND material_id=$2 AND material_version=$3",
                        case_id,
                        command.material_id,
                        command.material_version,
                    )
                await conn.execute(
                    "UPDATE inbox_case SET revision=revision+1,updated_at=now() WHERE id=$1",
                    case_id,
                )
                await conn.execute(
                    """INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
                        VALUES($1,$2,$3,'inbox.material_reference_changed','inbox_case',$4,$5,
                            jsonb_build_object('materialId',$6::text,'version',$7::bigint,'present',$8::boolean))""",
                    uuid4(),
                    current.action_id,
                    actor.account.id,
                    case_id,
                    key,
                    str(command.material_id),
                    command.material_version,
                    command.present,
                )
            await receipts.complete(
                idempotency_key=key, result={"caseId": str(case_id)}
            )
            return await self._case(conn, actor.account.id, case_id)

    async def list_comments(
        self, actor: IdentityPrincipal, case_id: UUID, query: CommentQuery
    ) -> Comments:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            await self._case(conn, actor.account.id, case_id)
            rows = await conn.fetch(
                "SELECT * FROM inbox_case_comment WHERE case_id=$1 ORDER BY created_at DESC,id DESC LIMIT $2 OFFSET $3",
                case_id,
                query.limit + 1,
                query.offset,
            )
            return Comments(
                items=[
                    Comment.model_validate(dict(row)) for row in rows[: query.limit]
                ],
                next_offset=query.offset + query.limit
                if len(rows) > query.limit and query.offset + query.limit <= 5000
                else None,
            )

    async def add_comment(
        self, actor: IdentityPrincipal, case_id: UUID, command: AddComment
    ) -> Comment:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._active(conn, actor.account.id)
            current = await self._case(conn, actor.account.id, case_id)
            key = (
                f"inbox.comment:{actor.account.id}:{case_id}:{command.idempotency_key}"
            )
            receipts = AsyncpgCommandReceiptRepository(conn)
            try:
                replay = await receipts.reserve(
                    idempotency_key=key,
                    command_type="inbox.commented",
                    request_hash=hashlib.sha256(
                        command.model_dump_json().encode()
                    ).hexdigest(),
                )
            except ApplicationError as error:
                if error.code == "idempotency_conflict":
                    raise Conflict(error.code, error.message) from error
                raise
            if replay is not None:
                row = await conn.fetchrow(
                    "SELECT * FROM inbox_case_comment WHERE id=$1 AND case_id=$2",
                    UUID(replay["commentId"]),
                    case_id,
                )
                if row is None:
                    raise ResourceNotFound("not_found", "Kommentar nicht gefunden.")
                return Comment.model_validate(dict(row))
            comment_id = uuid4()
            row = await conn.fetchrow(
                "INSERT INTO inbox_case_comment(id,case_id,author_user_id,body) VALUES($1,$2,$3,$4) RETURNING *",
                comment_id,
                case_id,
                actor.account.id,
                command.body,
            )
            assert row is not None
            await conn.execute(
                """INSERT INTO audit_event(id,action_id,actor_user_id,event_type,entity_type,entity_id,request_id,payload)
                    VALUES($1,$2,$3,'inbox.commented','inbox_case',$4,$5,jsonb_build_object('commentId',$6::text))""",
                uuid4(),
                current.action_id,
                actor.account.id,
                case_id,
                key,
                str(comment_id),
            )
            await receipts.complete(
                idempotency_key=key, result={"commentId": str(comment_id)}
            )
            return Comment.model_validate(dict(row))

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
