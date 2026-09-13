"""Durable Inbox contact linking through the existing semantic CRM port."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import asyncpg

from leonaid.application.crm import (
    CrmGateway,
    CrmGatewayError,
    PersonData,
    PersonRecord,
)
from leonaid.application.outbox import OutboxWorker
from leonaid.domain.outbox import ClaimedOutboxEvent


class InboxContactError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class InboxContactHandler:
    def __init__(self, pool: asyncpg.Pool[Any], crm: CrmGateway | None) -> None:
        self.pool = pool
        self.crm = crm

    async def _locked_case(
        self, conn: asyncpg.Connection[Any], event: ClaimedOutboxEvent
    ) -> asyncpg.Record:
        owned = await conn.fetchval(
            "SELECT id FROM outbox_event WHERE id=$1 AND claim_token=$2 AND status='processing' FOR UPDATE",
            event.id,
            event.claim_token,
        )
        if owned is None:
            raise InboxContactError("inbox_contact_claim_lost", retryable=True)
        row = await conn.fetchrow(
            "SELECT * FROM inbox_case WHERE id=$1 AND contact_job_id=$2 FOR UPDATE",
            event.aggregate_id,
            event.id,
        )
        if row is None:
            raise InboxContactError("inbox_contact_case_missing")
        return row

    async def _state(
        self,
        event: ClaimedOutboxEvent,
        status: str,
        *,
        error_code: str | None = None,
        person: PersonRecord | None = None,
        clear_started: bool = False,
    ) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await self._locked_case(conn, event)
            if row["contact_status"] == "linked":
                return
            await conn.execute(
                """UPDATE inbox_case SET contact_status=$2,contact_error_code=$3,twenty_person_id=$4,
                    contact_linked_at=CASE WHEN $2='linked' THEN now() ELSE NULL END,
                    contact_started_at=CASE WHEN $5 THEN NULL ELSE contact_started_at END,
                    contact_revision=contact_revision+1 WHERE id=$1""",
                event.aggregate_id,
                status,
                error_code,
                person.twenty_id if person else None,
                clear_started,
            )
            await conn.execute(
                """INSERT INTO audit_event(id,action_id,event_type,entity_type,entity_id,request_id,payload)
                    VALUES($1,$2,'inbox.contact_link_changed','inbox_case',$3,$4,
                        jsonb_build_object('status',$5::text,'errorCode',$6::text,'jobId',$7::text))""",
                uuid4(),
                row["action_id"],
                event.aggregate_id,
                f"inbox.contact:{event.id}:{event.claim_token}",
                status,
                error_code,
                str(event.id),
            )

    @staticmethod
    def _matches(
        person: PersonRecord, row: asyncpg.Record, expected: PersonData
    ) -> bool:
        return person.twenty_id == row["contact_create_id"] and person.data == expected

    async def handle(self, event: ClaimedOutboxEvent) -> None:
        if (
            event.event_type != "inbox.contact_link.v1"
            or event.aggregate_type != "inbox_case"
            or event.payload != {"caseId": str(event.aggregate_id)}
        ):
            raise InboxContactError("inbox_contact_invalid_payload")
        async with self.pool.acquire() as conn, conn.transaction():
            row = await self._locked_case(conn, event)
        if row["contact_status"] == "linked":
            return
        if row["contact_status"] == "needs_review":
            raise InboxContactError("inbox_contact_needs_review")
        if self.crm is None:
            await self._state(event, "failed", error_code="inbox_crm_not_configured")
            raise InboxContactError("inbox_crm_not_configured", retryable=True)
        try:
            expected = PersonData(
                given_name=row["given_name"],
                family_name=row["family_name"],
                email=row["email"],
                phone=row["phone"],
            )
        except ValueError:
            await self._state(
                event, "needs_review", error_code="inbox_contact_invalid_snapshot"
            )
            raise InboxContactError("inbox_contact_invalid_snapshot") from None
        correlation = f"inbox.contact:{event.id}"
        creating = False
        try:
            person = await self.crm.get_person(
                row["contact_create_id"], correlation_id=correlation
            )
            if person is not None:
                if not self._matches(person, row, expected):
                    await self._state(
                        event,
                        "needs_review",
                        error_code="inbox_contact_snapshot_mismatch",
                    )
                    raise InboxContactError("inbox_contact_snapshot_mismatch")
                await self._state(event, "linked", person=person)
                return
            if row["contact_started_at"] is not None:
                await self._state(
                    event, "needs_review", error_code="inbox_contact_outcome_unproven"
                )
                raise InboxContactError("inbox_contact_outcome_unproven")
            # Commit the intent before external I/O. Claim checks fence every
            # state change; a replacement worker never starts a second create.
            async with self.pool.acquire() as conn, conn.transaction():
                current = await self._locked_case(conn, event)
                if current["contact_started_at"] is not None:
                    raise InboxContactError("inbox_contact_in_progress", retryable=True)
                await conn.execute(
                    "UPDATE inbox_case SET contact_started_at=now(),contact_status='pending',contact_error_code=NULL,contact_revision=contact_revision+1 WHERE id=$1",
                    event.aggregate_id,
                )
            creating = True
            person, _ = await self.crm.create_person(
                row["contact_create_id"], expected, correlation_id=correlation
            )
            if not self._matches(person, row, expected):
                await self._state(
                    event, "needs_review", error_code="inbox_contact_snapshot_mismatch"
                )
                raise InboxContactError("inbox_contact_snapshot_mismatch")
            await self._state(event, "linked", person=person)
        except CrmGatewayError as error:
            code = OutboxWorker.error_code(error)[:100]
            await self._state(
                event,
                "failed",
                error_code=code,
                clear_started=(
                    creating
                    and not error.outcome_unknown
                    and error.operation == "create_person"
                    and error.http_status is not None
                    and 400 <= error.http_status < 500
                ),
            )
            raise
