#!/usr/bin/env python3
"""Inbox job proof against real Core PostgreSQL and a provisioned Twenty instance."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4
from urllib.parse import urlsplit
from typing import Any

import asyncpg
import httpx

from leonaid.configuration import Settings
from leonaid.entrypoints.fastapi.platform import create_app
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)
from leonaid.adapters.postgres.outbox import AsyncpgOutboxQueue

from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.crm import PersonData, PersonUpdate
from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.application.outbox import OutboxWorker
from leonaid.domain.outbox import RetryPolicy
from leonaid.bootstrap.api import build_inbox_service
from leonaid.bootstrap.worker import build_worker
from leonaid.domain.identity import AccountStatus, IdentityPrincipal, UserAccount
from leonaid.modules.inbox.api import (
    InboxService,
    Case,
    SubmitCase,
    UpdateCase,
    ContactQuery,
    ConfirmContact,
)
from leonaid.modules.inbox.jobs import InboxContactError, InboxContactHandler


async def confirm_existing_contact(
    pool: asyncpg.Pool[Any], crm: TwentyCrmGateway, user_id: UUID, case_id: UUID
) -> None:
    service = build_inbox_service(pool, crm)
    actor = IdentityPrincipal(
        UserAccount(
            user_id,
            f"{user_id}@example.org",
            "Inbox worker proof",
            AccountStatus.ACTIVE,
        ),
        frozenset(),
        (),
    )
    before = await service.get_case(actor, case_id)
    candidates = await service.list_contact_candidates(
        actor, case_id, ContactQuery(given_name="Different")
    )
    assert len(candidates.items) == 1 and not candidates.truncated
    candidate = candidates.items[0]
    command = ConfirmContact(
        idempotency_key=uuid4(),
        expected_contact_revision=before.contact_revision,
        person_id=candidate.person_id,
        fingerprint=candidate.fingerprint,
        note="Kontakt nach manueller Prüfung bestätigt.",
    )
    for invalid, code in (
        (command.model_copy(update={"fingerprint": "0" * 64}), "contact_changed"),
        (
            command.model_copy(
                update={"expected_contact_revision": before.contact_revision + 1}
            ),
            "contact_revision_conflict",
        ),
    ):
        try:
            await service.confirm_contact(actor, case_id, invalid)
        except Conflict as error:
            assert error.code == code
        else:
            raise AssertionError("Stale contact confirmation succeeded")
    await crm.update_person(
        case_id,
        candidate.person_id,
        PersonUpdate(given_name="Changed"),
        correlation_id="inbox-contact-preview-changed",
    )
    try:
        try:
            await service.confirm_contact(actor, case_id, command)
        except Conflict as error:
            assert error.code == "contact_changed"
        else:
            raise AssertionError("An actual CRM edit did not invalidate the preview")
    finally:
        await crm.update_person(
            case_id,
            candidate.person_id,
            PersonUpdate(given_name="Different"),
            correlation_id="inbox-contact-preview-restored",
        )
    queue = AsyncpgOutboxQueue(pool)
    async with pool.acquire() as conn:
        job_id = await conn.fetchval(
            "SELECT contact_job_id FROM inbox_case WHERE id=$1", case_id
        )
    await queue.manual_retry(
        event_id=job_id, operator="inbox-contact-proof", now=datetime.now(timezone.utc)
    )
    claimed = await queue.claim_next(
        worker_id="inbox-contact-proof", now=datetime.now(timezone.utc)
    )
    assert claimed is not None and claimed.id == job_id
    try:
        await service.confirm_contact(actor, case_id, command)
    except Conflict as error:
        assert error.code == "contact_job_active"
    else:
        raise AssertionError("Manual confirmation overtook a claimed worker")
    assert await service.get_case(actor, case_id) == before
    await queue.fail(
        event_id=job_id,
        claim_token=claimed.claim_token,
        error_code="inbox_contact_needs_review",
        error_detail="inbox_contact_needs_review",
        failed_at=datetime.now(timezone.utc),
        available_at=datetime.now(timezone.utc),
        dead_letter=True,
    )
    # A real database constraint failure must roll back the local link AND queue.
    constraint = f"inbox_contact_proof_{uuid4().hex}"
    async with pool.acquire() as conn:
        await conn.execute(
            f"ALTER TABLE audit_event ADD CONSTRAINT {constraint} CHECK (event_type <> 'inbox.contact_confirmed' OR entity_id <> '{case_id}') NOT VALID"
        )
    try:
        try:
            await service.confirm_contact(actor, case_id, command)
        except asyncpg.CheckViolationError:
            pass
        else:
            raise AssertionError("Audit failure committed contact confirmation")
        assert await service.get_case(actor, case_id) == before
        async with pool.acquire() as conn:
            assert (
                await conn.fetchval(
                    "SELECT o.status FROM outbox_event o JOIN inbox_case c ON c.contact_job_id=o.id WHERE c.id=$1",
                    case_id,
                )
                == "dead_letter"
            )
    finally:
        async with pool.acquire() as conn:
            await conn.execute(f"ALTER TABLE audit_event DROP CONSTRAINT {constraint}")
    archive = TemporaryDirectory(prefix="inbox-contact-archive-")
    settings = Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "LEONAID_SURVEY_ERASURE_ARCHIVE_DIR": archive.name,
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-http-proof-secret-only-32-characters",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-http-proof-encryption-32-characters",
            "LEONAID_PUBLIC_BASE_URL": "https://inbox.leonaid.invalid",
            "LEONAID_ALLOWED_ORIGINS": "https://inbox.leonaid.invalid",
            "TWENTY_BASE_URL": os.environ["TWENTY_BASE_URL"],
            "TWENTY_INTEGRATION_API_KEY": os.environ["TWENTY_INTEGRATION_API_KEY"],
        }
    )
    token, session_id = uuid4().hex + uuid4().hex, uuid4()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO user_session(id,user_id,token_digest,expires_at,last_seen_at,fresh_login_at,device_hint,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$5,'Inbox contact proof',$5,$5)",
            session_id,
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    app = create_app(settings)
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="https://inbox.leonaid.invalid",
                headers={
                    "Cookie": f"{SESSION_COOKIE_NAME}={token}",
                    "Origin": "https://inbox.leonaid.invalid",
                },
            ) as client,
        ):
            path = f"/api/v1/inbox-cases/{case_id}"
            preview = await client.get(
                path + "/contact-candidates", params={"givenName": "Different"}
            )
            assert preview.status_code == 200, preview.text
            assert preview.headers["cache-control"] == "no-store"
            assert preview.json()["items"][0]["fingerprint"] == candidate.fingerprint
            response, first = await asyncio.gather(
                client.post(
                    path + "/contact-confirmation",
                    json=command.model_dump(mode="json", by_alias=True),
                ),
                service.confirm_contact(actor, case_id, command),
            )
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "no-store"
            replay = Case.model_validate_json(response.content)
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM user_session WHERE id=$1", session_id)
        archive.cleanup()

    assert first == replay and first.contact_status == "linked"
    assert first.contact_revision == before.contact_revision + 1
    assert first.revision == before.revision
    actual = await crm.get_person(
        candidate.person_id, correlation_id="inbox-confirm-no-overwrite"
    )
    assert actual is not None and actual.data.given_name == "Different"
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT o.status FROM outbox_event o JOIN inbox_case c ON c.contact_job_id=o.id WHERE c.id=$1",
                case_id,
            )
            == "completed"
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM audit_event WHERE entity_id=$1 AND event_type='inbox.contact_confirmed'",
                case_id,
            )
            == 1
        )
        await conn.execute(
            "DELETE FROM user_global_role WHERE user_id=$1 AND role='system_admin'",
            user_id,
        )
    try:
        for operation in (
            service.list_contact_candidates(actor, case_id, ContactQuery()),
            service.confirm_contact(actor, case_id, command),
        ):
            try:
                await operation
            except (PermissionDenied, ResourceNotFound):
                pass
            else:
                raise AssertionError("Revoked manager accessed contact confirmation")
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                user_id,
            )
    print(
        "PASS inbox manual contact: actual Twenty selection, stale preview/revision, atomic audit rollback, HTTP/direct concurrent replay, active-worker exclusion, completed queue and revoked manager"
    )


async def timeout_after_real_create(
    pool: asyncpg.Pool[Any],
    queue: AsyncpgOutboxQueue,
    service: InboxService,
    crm: TwentyCrmGateway,
) -> None:
    """Forward actual HTTP bytes, withholding only a real successful POST reply."""
    upstream = urlsplit(os.environ["TWENTY_BASE_URL"])
    assert upstream.scheme == "http" and upstream.hostname is not None
    committed = asyncio.Event()
    post_status: int | None = None
    connections: set[asyncio.Task[Any]] = set()

    async def forward(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal post_status
        task = asyncio.current_task()
        assert task is not None
        connections.add(task)
        peer = None
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            headers = dict(
                line.split(b":", 1) for line in head.split(b"\r\n")[1:] if b":" in line
            )
            length = next(
                (
                    int(value)
                    for name, value in headers.items()
                    if name.lower() == b"content-length"
                ),
                0,
            )
            body = await reader.readexactly(length)
            upstream_reader, peer = await asyncio.open_connection(
                upstream.hostname, upstream.port or 80
            )
            # A reverse proxy forwards the configured upstream authority, not
            # its own loopback listener's Host header.
            forwarded_head = b"\r\n".join(
                f"Host: {upstream.netloc}".encode()
                if line.lower().startswith(b"host:")
                else line
                for line in head.split(b"\r\n")
            )
            peer.write(forwarded_head + body)
            await peer.drain()
            response_head = await upstream_reader.readuntil(b"\r\n\r\n")
            response_headers = dict(
                line.split(b":", 1)
                for line in response_head.split(b"\r\n")[1:]
                if b":" in line
            )
            lowered = {
                name.lower(): value.strip().lower()
                for name, value in response_headers.items()
            }
            if lowered.get(b"transfer-encoding") == b"chunked":
                chunks = []
                while True:
                    line = await upstream_reader.readline()
                    chunks.append(line)
                    size = int(line.split(b";", 1)[0], 16)
                    if size == 0:
                        chunks.append(await upstream_reader.readuntil(b"\r\n"))
                        break
                    chunks.append(await upstream_reader.readexactly(size + 2))
                response_body = b"".join(chunks)
            else:
                response_body = await upstream_reader.readexactly(
                    int(lowered[b"content-length"])
                )
            if head.startswith(b"POST /rest/people "):
                post_status = int(response_head.split(b" ", 2)[1])
                if not 200 <= post_status < 300:
                    writer.write(response_head + response_body)
                    await writer.drain()
                    return
                committed.set()
                # Twenty has sent the complete success. Let the real gateway's
                # socket read expire without returning invented status or body.
                await asyncio.sleep(3)
            else:
                writer.write(response_head + response_body)
                await writer.drain()
        finally:
            if peer is not None:
                peer.close()
                await peer.wait_closed()
            writer.close()
            await writer.wait_closed()
            connections.discard(task)

    server = await asyncio.start_server(forward, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    command = SubmitCase(
        idempotency_key=uuid4(),
        subject="Inbox lost response",
        message="Synthetischer Eingang",
        given_name="Inbox",
        family_name=f"Proof-{uuid4()}",
        email=f"inbox-proof-{uuid4()}@example.org",
    )
    receipt = await service.submit(command)
    try:
        async with TwentyCrmGateway(
            TwentyGatewaySettings(
                base_url=f"http://127.0.0.1:{port}",
                api_key=SecretStr(os.environ["TWENTY_INTEGRATION_API_KEY"]),
                timeout_seconds=2.0,
                max_rate_limit_retries=0,
            )
        ) as delayed:
            worker = OutboxWorker(
                worker_id="inbox-lost-response",
                queue=queue,
                handlers={"inbox.contact_link.v1": InboxContactHandler(pool, delayed)},
                retry_policy=RetryPolicy(base_delay=timedelta(0)),
            )
            assert await worker.run_once()
            assert committed.is_set(), (
                f"Actual Twenty success must precede the timeout; POST status={post_status}"
            )
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM inbox_case WHERE public_reference=$1", receipt.reference
            )
            assert (
                row is not None
                and row["contact_status"] == "failed"
                and row["contact_error_code"] == "crm_timeout"
                and row["contact_started_at"] is not None
            )
        actual = await crm.get_person(
            row["contact_create_id"], correlation_id="inbox-timeout-committed"
        )
        assert actual is not None
        recovery = OutboxWorker(
            worker_id="inbox-timeout-recovery",
            queue=queue,
            handlers={"inbox.contact_link.v1": InboxContactHandler(pool, crm)},
            retry_policy=RetryPolicy(),
        )
        assert await recovery.run_once()
        state = await queue.state(row["contact_job_id"])
        assert state is not None and state.status == "completed" and state.attempts == 2
        matches = await crm.search_people(
            given_name=command.given_name,
            family_name=command.family_name,
            correlation_id="inbox-timeout-no-duplicate",
        )
        assert len(matches) == 1
        print(
            "PASS actual POST success with withheld response: gateway timeout, durable intent, exact-ID recovery, one person"
        )
    finally:
        server.close()
        await server.wait_closed()
        if connections:
            await asyncio.gather(*connections)


async def main(mode: str, state_path: Path) -> None:
    pool, queue, worker = await build_worker(
        database_url=os.environ["CORE_DATABASE_URL"],
        worker_id="inbox-live-proof",
        max_attempts=5,
        base_backoff_seconds=1,
        claim_lease_seconds=300,
    )
    service = build_inbox_service(pool)
    try:
        if mode == "expect-outage":
            user = uuid4()
            command = SubmitCase(
                idempotency_key=uuid4(),
                subject="Inbox worker proof",
                message="Synthetischer Eingang",
                given_name="Inbox",
                family_name=f"Proof-{uuid4()}",
                email=f"inbox-proof-{uuid4()}@example.org",
            )
            receipt = await service.submit(command)
            assert await service.submit(command) == receipt
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Inbox worker proof','active')",
                    user,
                    f"{user}@example.org",
                )
                await conn.execute(
                    "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                    user,
                )
                row = await conn.fetchrow(
                    "SELECT * FROM inbox_case WHERE public_reference=$1",
                    receipt.reference,
                )
                assert row is not None
            assert await worker.run_once()
            state = await queue.state(row["contact_job_id"])
            assert (
                state is not None and state.status == "pending" and state.attempts == 1
            )
            assert state.last_error_code in {"crm_unavailable", "crm_timeout"}
            actor = IdentityPrincipal(
                UserAccount(
                    user,
                    f"{user}@example.org",
                    "Inbox worker proof",
                    AccountStatus.ACTIVE,
                ),
                frozenset(),
                (),
            )
            case = await service.get_case(actor, row["id"])
            assert case.contact_status == "failed" and case.revision == 1
            edited = await service.update_case(
                actor,
                case.id,
                UpdateCase(
                    idempotency_key=uuid4(),
                    expected_revision=1,
                    status="in_progress",
                    assignee_user_id=user,
                ),
            )
            assert edited.revision == 2
            async with pool.acquire() as conn:
                assert (
                    await conn.fetchval(
                        "SELECT contact_started_at FROM inbox_case WHERE id=$1", case.id
                    )
                    is None
                )
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM inbox_case WHERE public_reference=$1",
                        receipt.reference,
                    )
                    == 1
                )
            state_path.write_text(
                json.dumps(
                    {
                        "caseId": str(case.id),
                        "jobId": str(row["contact_job_id"]),
                        "userId": str(user),
                        "createId": str(row["contact_create_id"]),
                    }
                )
            )
            print(
                "PASS inbox real Twenty outage: one confirmed case, editable, safe error, pending retry and no create intent"
            )
            return
        state = json.loads(state_path.read_text())
        case_id, job_id = UUID(state["caseId"]), UUID(state["jobId"])
        assert await worker.run_once()
        completed = await queue.state(job_id)
        assert completed is not None and completed.status == "completed"
        settings = TwentyGatewaySettings(
            base_url=os.environ["TWENTY_BASE_URL"],
            api_key=SecretStr(os.environ["TWENTY_INTEGRATION_API_KEY"]),
            max_rate_limit_retries=0,
        )
        async with TwentyCrmGateway(settings) as crm:
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM inbox_case WHERE id=$1", case_id
                )
                assert (
                    row is not None
                    and row["contact_status"] == "linked"
                    and row["revision"] == 2
                )
            person = await crm.get_person(
                UUID(state["createId"]), correlation_id="inbox-live-verify"
            )
            assert person is not None and person.twenty_id == row["twenty_person_id"]
            matches = await crm.search_people(
                given_name=row["given_name"],
                family_name=row["family_name"],
                correlation_id="inbox-live-count",
            )
            assert len(matches) == 1
            await timeout_after_real_create(pool, queue, service, crm)
            handler = InboxContactHandler(pool, crm)
            for scenario in (
                "committed_create",
                "unproven_create",
                "mismatch",
                "fenced",
            ):
                command = SubmitCase(
                    idempotency_key=uuid4(),
                    subject=f"Inbox {scenario}",
                    message="Synthetischer Eingang",
                    given_name="Inbox",
                    family_name=f"Proof-{uuid4()}",
                    email=f"inbox-proof-{uuid4()}@example.org",
                )
                receipt = await service.submit(command)
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM inbox_case WHERE public_reference=$1",
                        receipt.reference,
                    )
                    assert row is not None
                event = await queue.claim_next(
                    worker_id="inbox-recovery-proof", now=datetime.now(timezone.utc)
                )
                assert event is not None and event.id == row["contact_job_id"]
                expected = PersonData(
                    given_name=command.given_name,
                    family_name=command.family_name,
                    email=command.email,
                )
                if scenario in ("committed_create", "unproven_create", "mismatch"):
                    async with pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE inbox_case SET contact_started_at=now() WHERE id=$1",
                            row["id"],
                        )
                    if scenario != "unproven_create":
                        await crm.create_person(
                            row["contact_create_id"],
                            expected
                            if scenario == "committed_create"
                            else PersonData(
                                given_name="Different",
                                family_name=command.family_name,
                                email=command.email,
                            ),
                            correlation_id="inbox-live-external-commit",
                        )
                if scenario == "fenced":
                    newer = await queue.claim_next(
                        worker_id="inbox-replacement",
                        now=datetime.now(timezone.utc) + timedelta(seconds=301),
                    )
                    assert (
                        newer is not None
                        and newer.id == event.id
                        and newer.claim_token != event.claim_token
                    )
                    try:
                        await handler.handle(event)
                    except InboxContactError as error:
                        assert error.code == "inbox_contact_claim_lost"
                    else:
                        raise AssertionError("Stale claim wrote contact state")
                    event = newer
                if scenario in ("unproven_create", "mismatch"):
                    try:
                        await handler.handle(event)
                    except InboxContactError as error:
                        assert not error.retryable
                    else:
                        raise AssertionError("Unproven contact linked or recreated")
                    async with pool.acquire() as conn:
                        assert (
                            await conn.fetchval(
                                "SELECT contact_status FROM inbox_case WHERE id=$1",
                                row["id"],
                            )
                            == "needs_review"
                        )
                    await queue.fail(
                        event_id=event.id,
                        claim_token=event.claim_token,
                        error_code="inbox_contact_needs_review",
                        error_detail="inbox_contact_needs_review",
                        failed_at=datetime.now(timezone.utc),
                        available_at=datetime.now(timezone.utc),
                        dead_letter=True,
                    )
                    actual = await crm.get_person(
                        row["contact_create_id"],
                        correlation_id="inbox-live-no-overwrite",
                    )
                    assert (
                        actual is None
                        if scenario == "unproven_create"
                        else actual is not None
                        and actual.data.given_name == "Different"
                    )
                    if scenario == "mismatch":
                        await confirm_existing_contact(
                            pool, crm, UUID(state["userId"]), row["id"]
                        )
                else:
                    await handler.handle(event)
                    await handler.handle(event)
                    await queue.complete(
                        event_id=event.id,
                        claim_token=event.claim_token,
                        completed_at=datetime.now(timezone.utc),
                    )
                    async with pool.acquire() as conn:
                        assert (
                            await conn.fetchval(
                                "SELECT contact_status FROM inbox_case WHERE id=$1",
                                row["id"],
                            )
                            == "linked"
                        )
                    matches = await crm.search_people(
                        given_name=command.given_name,
                        family_name=command.family_name,
                        correlation_id="inbox-live-no-duplicates",
                    )
                    assert len(matches) == 1
        print(
            "PASS inbox restart: one contact, completed job, exact-ID recovery after external commit, unproven/mismatch clarification, no overwrite and fenced stale worker"
        )
    finally:
        try:
            await worker.close()
        finally:
            await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("expect-outage", "verify-after-restart"))
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.mode, args.state))
