#!/usr/bin/env python3
"""Real PostgreSQL proof of atomic Inbox receipt, replay and bounded input."""

import asyncio
import json
import os
from uuid import uuid4

import asyncpg
from pydantic import ValidationError

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.modules.inbox.api import SubmitCase
from leonaid.bootstrap.api import build_inbox_service


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    service = build_inbox_service(pool)
    action = uuid4()
    commands = [
        SubmitCase(
            idempotency_key=uuid4(),
            subject="Kontaktanfrage",
            message=f"Synthetischer Eingang {action}",
            given_name="Test",
            family_name="Person",
            email="test@example.org",
        )
        for _ in range(4)
    ]
    general, scoped, failed, rejected = commands
    scoped = scoped.model_copy(update={"action_id": action})
    rejected = rejected.model_copy(update={"action_id": action})
    keys = [f"inbox.submit:{command.idempotency_key}" for command in commands]
    fault_constraint = f"inbox_proof_{failed.idempotency_key.hex}"
    try:
        async with pool.acquire() as conn:
            initial_jobs = await conn.fetchval(
                "SELECT count(*) FROM outbox_event WHERE event_type='inbox.contact_link.v1'"
            )
            await conn.execute(
                "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug,publication_starts_at,publication_ends_at) VALUES($1,'Synthetic','Inbox proof','Proof','active','2026-01-01','2026-12-31',$2,now()-interval '1 day',now()+interval '1 day')",
                action,
                f"inbox-{action}",
            )
        first, replay = await asyncio.gather(
            service.submit(general), service.submit(general)
        )
        assert first == replay
        assert set(first.model_dump()) == {"reference"}
        assert await service.submit(general) == first
        try:
            await service.submit(general.model_copy(update={"message": "Changed"}))
        except Conflict as error:
            assert error.code == "idempotency_conflict"
        else:
            raise AssertionError("Changed input reused a receipt")
        for changes in (
            {"subject": " "},
            {"message": "x" * 10001},
            {"given_name": ""},
            {"family_name": "\x00"},
            {"email": "broken"},
            {"email": None},
            {"phone": "call me"},
            {"phone": "0891234567"},
            {"phone": "+1 23"},
            {"phone": "1" * 16},
        ):
            try:
                await service.submit(general.model_copy(update=changes))
            except ValidationError:
                pass
            else:
                raise AssertionError(f"Unvalidated direct command: {changes.keys()}")
        phone = SubmitCase.model_validate(
            {**general.model_dump(), "email": None, "phone": "+49 (89) 1234567"}
        )
        assert phone.phone == "+49 (89) 1234567"
        scoped_result = await service.submit(scoped)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE charity_action SET publication_ends_at=now()-interval '1 second' WHERE id=$1",
                action,
            )
        assert await service.submit(scoped) == scoped_result
        try:
            await service.submit(rejected)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Closed publication accepted new submission")
        async with pool.acquire() as conn:
            # An actual database constraint rejects the last insert, after case/job
            # writes. No persistence port or server response is substituted.
            await conn.execute(
                f"ALTER TABLE audit_event ADD CONSTRAINT {fault_constraint} CHECK (request_id <> 'inbox.submit:{failed.idempotency_key}') NOT VALID"
            )
        try:
            await service.submit(failed)
        except asyncpg.CheckViolationError:
            pass
        else:
            raise AssertionError("Storage failure unexpectedly committed")
        finally:
            async with pool.acquire() as conn:
                await conn.execute(
                    f"ALTER TABLE audit_event DROP CONSTRAINT IF EXISTS {fault_constraint}"
                )
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM command_receipt WHERE idempotency_key=ANY($1::text[])",
                    keys,
                )
                == 2
            )
            rows = await conn.fetch(
                "SELECT c.*,o.payload,o.event_type FROM inbox_case c JOIN outbox_event o ON o.id=c.contact_job_id WHERE c.public_reference=ANY($1::uuid[])",
                [first.reference, scoped_result.reference],
            )
            assert len(rows) == 2
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM outbox_event WHERE event_type='inbox.contact_link.v1'"
                )
                == initial_jobs + 2
            )
            for row in rows:
                assert row["status"] == "new" and row["contact_status"] == "pending"
                assert (
                    row["contact_started_at"] is None
                    and row["twenty_person_id"] is None
                )
                assert row["message"] == general.message
                assert row["event_type"] == "inbox.contact_link.v1"
                assert json.loads(row["payload"]) == {"caseId": str(row["id"])}
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM audit_event WHERE request_id=ANY($1::text[])",
                    keys,
                )
                == 2
            )
            # The failed command must not leave a third case/job behind.
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM inbox_case WHERE message=$1 AND email=$2",
                    general.message,
                    general.email,
                )
                == 2
            )
        recovered = await service.submit(failed)
        assert recovered.reference not in (first.reference, scoped_result.reference)
        print(
            "PASS inbox submission: concurrent replay, changed-input conflict, direct validation, publication close, atomic storage-failure rollback and retry; no CRM/mail call"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                f"ALTER TABLE audit_event DROP CONSTRAINT IF EXISTS {fault_constraint}"
            )
            ids = await conn.fetch(
                "SELECT entity_id FROM audit_event WHERE request_id=ANY($1::text[])",
                keys,
            )
            case_ids = [row["entity_id"] for row in ids]
            await conn.execute(
                "DELETE FROM inbox_case WHERE id=ANY($1::uuid[])", case_ids
            )
            await conn.execute(
                "DELETE FROM outbox_event WHERE aggregate_type='inbox_case' AND aggregate_id=ANY($1::uuid[])",
                case_ids,
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE request_id=ANY($1::text[])", keys
            )
            await conn.execute(
                "DELETE FROM command_receipt WHERE idempotency_key=ANY($1::text[])",
                keys,
            )
            await conn.execute("DELETE FROM charity_action WHERE id=$1", action)
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
