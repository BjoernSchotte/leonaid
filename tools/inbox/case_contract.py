#!/usr/bin/env python3
"""Current Inbox authorization and revisioned case workflow on real PostgreSQL."""

import asyncio
import json
import os
from uuid import uuid4
from typing import Literal

import asyncpg
from pydantic import ValidationError

from leonaid.application.errors import (
    AuthenticationRequired,
    Conflict,
    PermissionDenied,
    ResourceNotFound,
)
from leonaid.bootstrap.api import build_inbox_service
from leonaid.domain.identity import (
    AccountStatus,
    GlobalRole,
    IdentityPrincipal,
    UserAccount,
)
from leonaid.modules.inbox.api import AssigneeQuery, CaseQuery, SubmitCase, UpdateCase


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=4
    )
    assert pool is not None
    service = build_inbox_service(pool)
    actors = [
        IdentityPrincipal(
            UserAccount(
                uuid4(), f"{uuid4()}@example.org", "Inbox proof", AccountStatus.ACTIVE
            ),
            frozenset({GlobalRole.SYSTEM_ADMIN}),
            (),
        )
        for _ in range(5)
    ]
    admin, manager, assigned, replacement, outsider = actors
    users = [actor.account.id for actor in actors]
    actions = [uuid4(), uuid4()]
    marker = f"Inbox case proof {actions[0]}"
    commands = [
        SubmitCase(
            idempotency_key=uuid4(),
            action_id=action,
            subject=marker,
            message="Synthetische Nachricht",
            given_name="Test",
            family_name="Person",
            email="test@example.org",
        )
        for action in [None, *actions]
    ]
    keys = [f"inbox.submit:{command.idempotency_key}" for command in commands]
    case_ids = []
    try:
        async with pool.acquire() as conn:
            for actor in actors:
                await conn.execute(
                    "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,$3,'active')",
                    actor.account.id,
                    actor.account.email,
                    marker,
                )
            await conn.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                admin.account.id,
            )
            for action in actions:
                await conn.execute(
                    "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug,publication_starts_at,publication_ends_at) VALUES($1,'Synthetic','Inbox proof','Proof','active','2026-01-01','2026-12-31',$2,now()-interval '1 day',now()+interval '1 day')",
                    action,
                    f"inbox-case-{action}",
                )
            for actor, role in [
                (manager, "charity_admin"),
                (assigned, "driver"),
                (replacement, "acquirer"),
            ]:
                await conn.execute(
                    "INSERT INTO action_membership(id,user_id,action_id,role,active_from) VALUES($1,$2,$3,$4,now()-interval '1 day')",
                    uuid4(),
                    actor.account.id,
                    actions[0],
                    role,
                )
        receipts = [await service.submit(command) for command in commands]
        async with pool.acquire() as conn:
            for receipt in receipts:
                case_ids.append(
                    await conn.fetchval(
                        "SELECT id FROM inbox_case WHERE public_reference=$1",
                        receipt.reference,
                    )
                )
        general, scoped, foreign = case_ids
        candidate_query = AssigneeQuery(search=marker, limit=1)
        first = await service.list_assignees(manager, scoped, candidate_query)
        assert len(first.items) == 1 and first.next_offset == 1
        candidates = await service.list_assignees(
            manager, scoped, AssigneeQuery(search=marker)
        )
        assert {item.user_id for item in candidates.items} == set(users[:4])
        second = await service.list_assignees(
            manager, scoped, AssigneeQuery(search=marker, offset=1, limit=1)
        )
        assert len(second.items) == 1 and second.items[0] != first.items[0]
        assert not (
            await service.list_assignees(manager, scoped, AssigneeQuery(search="%"))
        ).items
        general_candidates = await service.list_assignees(
            admin, general, AssigneeQuery(search=marker)
        )
        assert {item.user_id for item in general_candidates.items} == set(users)
        try:
            await service.list_assignees(manager, foreign, AssigneeQuery())
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Candidate search disclosed another action")
        try:
            await service.list_assignees(
                manager, scoped, AssigneeQuery.model_construct(limit=101)
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Direct candidate query bypassed limits")
        query = CaseQuery(search=marker, limit=1)
        page = await service.list_cases(admin, query)
        assert len(page.items) == 1 and page.next_offset == 1
        all_cases = await service.list_cases(admin, CaseQuery(search=marker))
        assert {item.id for item in all_cases.items} == set(case_ids)
        assert {
            item.id
            for item in (
                await service.list_cases(manager, CaseQuery(search=marker))
            ).items
        } == {scoped}
        for actor in [assigned, replacement, outsider]:
            assert not (await service.list_cases(actor, CaseQuery(search=marker))).items
            for case_id in case_ids:
                try:
                    await service.get_case(actor, case_id)
                except ResourceNotFound:
                    pass
                else:
                    raise AssertionError(
                        "Membership or forged principal role disclosed private case"
                    )
        try:
            await service.get_case(manager, foreign)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Other action leaked")
        assignment = UpdateCase(
            idempotency_key=uuid4(),
            expected_revision=1,
            status="in_progress",
            assignee_user_id=assigned.account.id,
        )
        current = await service.update_case(manager, scoped, assignment)
        assert current.revision == 2
        try:
            await service.list_assignees(assigned, scoped, AssigneeQuery())
        except PermissionDenied:
            pass
        else:
            raise AssertionError("Assigned reader enumerated accounts")
        assert await service.update_case(manager, scoped, assignment) == current
        assert (await service.list_cases(assigned, CaseQuery(for_me=True))).items == [
            current
        ]
        try:
            await service.update_case(
                assigned,
                scoped,
                UpdateCase(
                    idempotency_key=uuid4(),
                    expected_revision=2,
                    status="in_progress",
                    assignee_user_id=replacement.account.id,
                ),
            )
        except PermissionDenied:
            pass
        else:
            raise AssertionError("Assignee changed access")
        close = UpdateCase(
            idempotency_key=uuid4(),
            expected_revision=2,
            status="closed",
            assignee_user_id=assigned.account.id,
            closure_note="Anfrage beantwortet",
        )
        closed = await service.update_case(assigned, scoped, close)
        assert closed.closed_at is not None and closed.revision == 3
        try:
            UpdateCase.model_validate(
                {**close.model_dump(), "message": "Overwrite original"}
            )
        except ValidationError:
            pass
        else:
            raise AssertionError("Snapshot edit accepted")
        reopened = await service.update_case(
            assigned,
            scoped,
            UpdateCase(
                idempotency_key=uuid4(),
                expected_revision=3,
                status="in_progress",
                assignee_user_id=assigned.account.id,
            ),
        )
        assert (
            reopened.closed_at is None
            and reopened.closure_note is None
            and reopened.revision == 4
        )
        async with pool.acquire() as conn:
            history = await conn.fetch(
                "SELECT payload FROM audit_event WHERE entity_id=$1 AND event_type='inbox.updated'",
                scoped,
            )
            assert any(
                json.loads(row["payload"])["previousClosureNote"] == close.closure_note
                for row in history
            )
            await conn.execute(
                "UPDATE inbox_case SET contact_status='failed',contact_error_code='crm_unavailable',contact_revision=2 WHERE id=$1",
                scoped,
            )
        statuses: tuple[Literal["in_progress", "closed"], ...] = (
            "in_progress",
            "closed",
        )
        contenders = [
            UpdateCase(
                idempotency_key=uuid4(),
                expected_revision=4,
                status=status,
                assignee_user_id=assigned.account.id,
                closure_note="Erledigt" if status == "closed" else None,
            )
            for status in statuses
        ]
        results = await asyncio.gather(
            *(service.update_case(assigned, scoped, command) for command in contenders),
            return_exceptions=True,
        )
        assert sum(isinstance(result, Conflict) for result in results) == 1
        after = await service.get_case(assigned, scoped)
        assert (
            after.revision == 5
            and after.contact_revision == 2
            and after.contact_status == "failed"
        )
        assert (after.message, after.given_name, after.email) == (
            commands[1].message,
            commands[1].given_name,
            commands[1].email,
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1",
                replacement.account.id,
            )
        assert replacement.account.id not in {
            item.user_id
            for item in (
                await service.list_assignees(manager, scoped, AssigneeQuery())
            ).items
        }
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_account SET status='active' WHERE id=$1",
                replacement.account.id,
            )
        # Expiring assignment membership removes every access path, including replay.
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE action_membership SET active_until=now()-interval '1 second' WHERE user_id=$1",
                assigned.account.id,
            )
        assert assigned.account.id not in {
            item.user_id
            for item in (
                await service.list_assignees(manager, scoped, AssigneeQuery())
            ).items
        }
        assert not (await service.list_cases(assigned, CaseQuery())).items
        try:
            await service.update_case(assigned, scoped, close)
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Revoked member replayed case command")
        invalid = UpdateCase(
            idempotency_key=uuid4(),
            expected_revision=5,
            status="in_progress",
            assignee_user_id=outsider.account.id,
        )
        try:
            await service.update_case(manager, scoped, invalid)
        except PermissionDenied as error:
            assert error.code == "invalid_assignee"
        else:
            raise AssertionError("Unrelated user assigned into action")
        moved = await service.update_case(
            manager,
            scoped,
            invalid.model_copy(update={"assignee_user_id": replacement.account.id}),
        )
        assert moved.revision == 6
        assert (await service.get_case(replacement, scoped)).id == scoped
        self_assignment = UpdateCase(
            idempotency_key=uuid4(),
            expected_revision=6,
            status="in_progress",
            assignee_user_id=manager.account.id,
        )
        await service.update_case(manager, scoped, self_assignment)
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE action_membership SET role='driver' WHERE user_id=$1",
                manager.account.id,
            )
        assert (
            await service.get_case(manager, scoped)
        ).assignee_user_id == manager.account.id
        try:
            await service.update_case(manager, scoped, self_assignment)
        except PermissionDenied:
            pass
        else:
            raise AssertionError("Assignment replay bypassed lost management rights")
        try:
            await service.list_assignees(manager, scoped, AssigneeQuery())
        except PermissionDenied:
            pass
        else:
            raise AssertionError("Revoked manager enumerated accounts")
        # General cases can be deliberately delegated by the global administrator.
        delegated = await service.update_case(
            admin,
            general,
            UpdateCase(
                idempotency_key=uuid4(),
                expected_revision=1,
                status="in_progress",
                assignee_user_id=outsider.account.id,
            ),
        )
        assert await service.get_case(outsider, general) == delegated
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE user_account SET status='suspended' WHERE id=$1",
                outsider.account.id,
            )
            await conn.execute(
                "DELETE FROM user_global_role WHERE user_id=$1", admin.account.id
            )
            await conn.execute(
                "UPDATE action_membership SET active_until=now()-interval '1 second' WHERE user_id=$1",
                manager.account.id,
            )
        for actor in [admin, manager]:
            assert not (await service.list_cases(actor, CaseQuery(search=marker))).items
        try:
            await service.get_case(outsider, general)
        except AuthenticationRequired:
            pass
        else:
            raise AssertionError("Suspended assignee retained access")
        print(
            "PASS inbox cases: current roles/assignment, private search, authorized candidate pagination and revocation, action isolation, close/reopen audit, concurrent revision conflict, immutable input, independent CRM state and revoked replay"
        )
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "DELETE FROM inbox_case WHERE id=ANY($1::uuid[])", case_ids
            )
            await conn.execute(
                "DELETE FROM outbox_event WHERE aggregate_type='inbox_case' AND aggregate_id=ANY($1::uuid[])",
                case_ids,
            )
            await conn.execute(
                "DELETE FROM audit_event WHERE entity_id=ANY($1::uuid[])", case_ids
            )
            await conn.execute(
                "DELETE FROM command_receipt WHERE idempotency_key=ANY($1::text[]) OR idempotency_key LIKE ANY($2::text[])",
                keys,
                [f"inbox.update:{user}:%" for user in users],
            )
            await conn.execute(
                "DELETE FROM action_membership WHERE action_id=ANY($1::uuid[])", actions
            )
            await conn.execute(
                "DELETE FROM charity_action WHERE id=ANY($1::uuid[])", actions
            )
            await conn.execute(
                "DELETE FROM user_global_role WHERE user_id=ANY($1::uuid[])", users
            )
            await conn.execute(
                "DELETE FROM user_account WHERE id=ANY($1::uuid[])", users
            )
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
