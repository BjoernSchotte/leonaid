"""Inbox persistence using the existing transactional outbox and receipts."""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import uuid4

import asyncpg

from leonaid.adapters.postgres.action_progress import AsyncpgCommandReceiptRepository
from leonaid.application.errors import ApplicationError, Conflict, ResourceNotFound
from leonaid.modules.inbox.api import Submission, SubmitCase


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
