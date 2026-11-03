#!/usr/bin/env python3
"""Inbox schema constraints and independent references against actual PostgreSQL."""

import asyncio
import os
from uuid import uuid4

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    transaction = conn.transaction()
    await transaction.start()
    try:
        owner, case, job, listing, task, material = [uuid4() for _ in range(6)]
        await conn.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Inbox proof','active')",
            owner,
            f"{owner}@example.org",
        )
        await conn.execute(
            "INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload) VALUES ($1,'inbox_case',$2,'inbox.contact_link.v1',$3,jsonb_build_object('caseId',$2::uuid::text))",
            job,
            case,
            f"inbox-contact:{case}",
        )
        await conn.execute(
            "INSERT INTO inbox_case(id,public_reference,subject,message,given_name,family_name,email,contact_create_id,contact_job_id) VALUES ($1,$2,'Kontaktanfrage','Synthetische Nachricht','Test','Person','test@example.org',$3,$4)",
            case,
            uuid4(),
            uuid4(),
            job,
        )
        row = await conn.fetchrow("SELECT * FROM inbox_case WHERE id=$1", case)
        assert (
            row is not None
            and row["status"] == "new"
            and row["contact_status"] == "pending"
        )
        assert row["received_at"].tzinfo is not None
        rejected = [
            "UPDATE inbox_case SET subject=' ' WHERE id=$1",
            "UPDATE inbox_case SET message=repeat('x',10001) WHERE id=$1",
            "UPDATE inbox_case SET given_name='' WHERE id=$1",
            "UPDATE inbox_case SET family_name='' WHERE id=$1",
            "UPDATE inbox_case SET email=NULL,phone=NULL WHERE id=$1",
            "UPDATE inbox_case SET phone=' ' WHERE id=$1",
            "UPDATE inbox_case SET revision=0 WHERE id=$1",
            "UPDATE inbox_case SET status='approved' WHERE id=$1",
            "UPDATE inbox_case SET status='closed' WHERE id=$1",
            "UPDATE inbox_case SET closure_note=' ' WHERE id=$1",
            "UPDATE inbox_case SET closed_at=now() WHERE id=$1",
            "UPDATE inbox_case SET contact_status='linked' WHERE id=$1",
            "UPDATE inbox_case SET contact_status='failed' WHERE id=$1",
            "UPDATE inbox_case SET contact_error_code='raw provider error' WHERE id=$1",
            "UPDATE inbox_case SET contact_revision=0 WHERE id=$1",
            "UPDATE inbox_case SET twenty_person_id=gen_random_uuid() WHERE id=$1",
            "UPDATE inbox_case SET contact_job_id=gen_random_uuid() WHERE id=$1",
            "UPDATE inbox_case SET assignee_user_id=gen_random_uuid() WHERE id=$1",
            "UPDATE inbox_case SET action_id=gen_random_uuid() WHERE id=$1",
        ]
        for sql in rejected:
            try:
                async with conn.transaction():
                    await conn.execute(sql, case)
            except asyncpg.IntegrityConstraintViolationError:
                pass
            else:
                raise AssertionError(sql)
        await conn.execute(
            "UPDATE inbox_case SET status='closed',closure_note='Anfrage beantwortet',closed_at=now(),revision=2 WHERE id=$1",
            case,
        )
        await conn.execute(
            "UPDATE inbox_case SET status='in_progress',closure_note=NULL,closed_at=NULL,revision=3,assignee_user_id=$2 WHERE id=$1",
            case,
            owner,
        )
        await conn.execute(
            "UPDATE inbox_case SET contact_status='failed',contact_error_code='crm_unavailable',contact_revision=2 WHERE id=$1",
            case,
        )
        assert (
            await conn.fetchval("SELECT status FROM inbox_case WHERE id=$1", case)
            == "in_progress"
        )
        await conn.execute(
            "UPDATE inbox_case SET contact_status='linked',contact_error_code=NULL,twenty_person_id=$2,contact_linked_at=now(),contact_revision=3 WHERE id=$1",
            case,
            uuid4(),
        )
        assert (
            await conn.fetchval("SELECT revision FROM inbox_case WHERE id=$1", case)
            == 3
        )
        await conn.execute(
            "INSERT INTO task_list(id,owner_user_id,title) VALUES ($1,$2,'Inbox tasks')",
            listing,
            owner,
        )
        await conn.execute(
            "INSERT INTO task(id,list_id,title,created_by) VALUES ($1,$2,'Follow up',$3)",
            task,
            listing,
            owner,
        )
        await conn.execute(
            "INSERT INTO material(id,owner_user_id,title) VALUES ($1,$2,'Existing file')",
            material,
            owner,
        )
        await conn.execute(
            "INSERT INTO material_version(material_id,version,filename,media_type,size_bytes,sha256,storage_bucket,object_key,storage_version_id,created_by) VALUES ($1,1,'file.txt','text/plain',1,$2,'synthetic-bucket',$3,'version1',$4)",
            material,
            "a" * 64,
            f"materials/{material}/1",
            owner,
        )
        await conn.execute(
            "INSERT INTO inbox_case_task(case_id,task_id) VALUES ($1,$2)", case, task
        )
        await conn.execute(
            "INSERT INTO inbox_case_material(case_id,material_id,material_version) VALUES ($1,$2,1)",
            case,
            material,
        )
        await conn.execute(
            "INSERT INTO inbox_case_comment(id,case_id,author_user_id,body) VALUES ($1,$2,$3,'Internal note')",
            uuid4(),
            case,
            owner,
        )
        await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for sql, args in (
            (
                "UPDATE inbox_case_material SET material_version=2 WHERE case_id=$1",
                (case,),
            ),
            ("UPDATE inbox_case_comment SET body=' ' WHERE case_id=$1", (case,)),
            ("UPDATE inbox_case_task SET task_id=$2 WHERE case_id=$1", (case, uuid4())),
            ("DELETE FROM outbox_event WHERE id=$1", (job,)),
        ):
            try:
                async with conn.transaction():
                    await conn.execute(sql, *args)
            except asyncpg.IntegrityConstraintViolationError:
                pass
            else:
                raise AssertionError(sql)
        await conn.execute("DELETE FROM inbox_case WHERE id=$1", case)
        assert await conn.fetchval("SELECT count(*) FROM task WHERE id=$1", task) == 1
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM material_version WHERE material_id=$1", material
            )
            == 1
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM inbox_case_comment WHERE case_id=$1", case
            )
            == 0
        )
        print(
            "PASS inbox schema: bounded snapshot, required job, close/reopen, independent contact state, exact references, comments and 23 invalid writes"
        )
    finally:
        await transaction.rollback()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
