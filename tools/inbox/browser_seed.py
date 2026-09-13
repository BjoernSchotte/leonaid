"""Seed synthetic Inbox browser cases in an explicitly owned test stack."""

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
from pydantic import SecretStr
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue
from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.crm import PersonData
from leonaid.modules.inbox.jobs import InboxContactHandler, InboxContactError

from leonaid.bootstrap.api import build_inbox_service, build_task_service
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.domain.sessions import SESSION_LIFETIME, session_token_digest
from leonaid.modules.inbox.api import AddComment, SubmitCase, UpdateCase
from leonaid.modules.tasks.api import CreateList, CreateTask, SetListMember


async def main(output: Path) -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    try:
        users = [uuid4(), uuid4()]
        tokens = [uuid4().hex + uuid4().hex for _ in users]
        names = ["Inbox Verwaltung", "Inbox Bearbeitung"]
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            for user, token, name in zip(users, tokens, names):
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,$3,'active')",
                    user,
                    f"{user}@example.org",
                    name,
                )
                await conn.execute(
                    "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,'Inbox browser proof',$5,$5)",
                    uuid4(),
                    user,
                    session_token_digest(token),
                    now + SESSION_LIFETIME,
                    now,
                )
            await conn.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                users[0],
            )
        actor = IdentityPrincipal(
            UserAccount(
                users[0], f"{users[0]}@example.org", names[0], AccountStatus.ACTIVE
            ),
            frozenset(),
            (),
        )
        inbox = build_inbox_service(pool)
        receipt = await inbox.submit(
            SubmitCase(
                idempotency_key=uuid4(),
                subject="Unterstützung beim gemeinsamen Mittagstisch",
                message="Guten Tag,\nwir möchten einen barrierefreien gemeinsamen Mittagstisch vorbereiten. Können wir einen Termin zur Abstimmung vereinbaren?\nVielen Dank!",
                given_name="Mara",
                family_name=f"Browser-{uuid4()}",
                email="mara@example.org",
            )
        )
        async with pool.acquire() as conn:
            case_id = await conn.fetchval(
                "SELECT id FROM inbox_case WHERE public_reference=$1", receipt.reference
            )
        # Deliberate uncertain-create fixture: real handler must stop for review.
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE inbox_case SET contact_started_at=now() WHERE id=$1 RETURNING *",
                case_id,
            )
        assert row is not None
        queue = AsyncpgOutboxQueue(pool)
        event = await queue.claim_next(
            worker_id="inbox-browser-fixture", now=datetime.now(timezone.utc)
        )
        assert event is not None and event.id == row["contact_job_id"]
        async with TwentyCrmGateway(
            TwentyGatewaySettings(
                base_url=os.environ["TWENTY_BASE_URL"],
                api_key=SecretStr(os.environ["TWENTY_INTEGRATION_API_KEY"]),
            )
        ) as crm:
            try:
                await InboxContactHandler(pool, crm).handle(event)
            except InboxContactError as error:
                assert not error.retryable
            else:
                raise AssertionError("Uncertain create did not require review")
            await queue.fail(
                event_id=event.id,
                claim_token=event.claim_token,
                error_code="inbox_contact_needs_review",
                error_detail="inbox_contact_needs_review",
                failed_at=now,
                available_at=now,
                dead_letter=True,
            )
            await crm.create_person(
                row["contact_create_id"],
                PersonData(
                    given_name=row["given_name"],
                    family_name=row["family_name"],
                    email=row["email"],
                ),
                correlation_id="inbox-browser-existing-contact",
            )
        await inbox.update_case(
            actor,
            case_id,
            UpdateCase(
                idempotency_key=uuid4(),
                expected_revision=1,
                status="new",
                assignee_user_id=users[1],
            ),
        )
        await inbox.add_comment(
            actor,
            case_id,
            AddComment(
                idempotency_key=uuid4(),
                body="Termin und barrierefreien Zugang gemeinsam prüfen.",
            ),
        )
        tasks = build_task_service(pool)
        task_list = await tasks.create_list(
            actor,
            CreateList(idempotency_key=uuid4(), title="Inbox Browser Vorbereitung"),
        )
        task = await tasks.create_task(
            actor,
            task_list.id,
            CreateTask(idempotency_key=uuid4(), title="Barrierefreien Zugang prüfen"),
        )
        await tasks.set_list_member(
            actor,
            task_list.id,
            SetListMember(
                idempotency_key=uuid4(),
                expected_revision=task_list.revision,
                user_id=users[1],
                access="editor",
            ),
        )
        output.write_text(
            json.dumps(
                {
                    "users": [str(value) for value in users],
                    "sessions": tokens,
                    "caseId": str(case_id),
                    "reference": str(receipt.reference),
                    "taskId": str(task.id),
                    "listId": str(task_list.id),
                }
            )
        )
        output.chmod(0o600)
        print("Inbox browser fixture written to private output file")
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args().output))
