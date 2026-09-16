#!/usr/bin/env python3
"""Knowledge revision and reference constraints on real PostgreSQL, rolled back."""

import asyncio
import json
import os
from uuid import uuid4

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    transaction = conn.transaction()
    await transaction.start()
    try:
        owner, page, listing, task = (uuid4() for _ in range(4))
        await conn.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Knowledge proof','active')",
            owner,
            f"{owner}@example.org",
        )
        await conn.execute(
            "INSERT INTO task_list(id,owner_user_id,title) VALUES ($1,$2,'Reference list')",
            listing,
            owner,
        )
        await conn.execute(
            "INSERT INTO task(id,list_id,title,created_by) VALUES ($1,$2,'Referenced task',$3)",
            task,
            listing,
            owner,
        )
        await conn.execute(
            "INSERT INTO knowledge_page(id,owner_user_id) VALUES ($1,$2)", page, owner
        )
        await conn.execute(
            "INSERT INTO knowledge_page_revision(page_id,revision,title,content,created_by) VALUES ($1,1,'First title',$2::jsonb,$3)",
            page,
            '{"type":"doc","content":[{"type":"paragraph"}]}',
            owner,
        )
        await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        await conn.execute(
            "INSERT INTO knowledge_page_task(page_id,revision,task_id) VALUES ($1,1,$2)",
            page,
            task,
        )
        rejected = (
            (
                "INSERT INTO knowledge_page(id,owner_user_id) VALUES ($1,$2)",
                uuid4(),
                owner,
            ),
            (
                "UPDATE knowledge_page_revision SET content=$2::jsonb WHERE page_id=$1",
                page,
                json.dumps({"type": "doc", "text": "x" * 1048576}),
            ),
            ("UPDATE knowledge_page SET revision=2 WHERE id=$1", page),
            ("DELETE FROM knowledge_page_revision WHERE page_id=$1", page),
            ("DELETE FROM task WHERE id=$1", task),
            (
                "UPDATE knowledge_page_revision SET content=$2::jsonb WHERE page_id=$1",
                page,
                "{}",
            ),
            (
                "UPDATE knowledge_page_revision SET content=$2::jsonb WHERE page_id=$1",
                page,
                "[]",
            ),
            (
                "UPDATE knowledge_page_revision SET content=$2::jsonb WHERE page_id=$1",
                page,
                '{"type":"text"}',
            ),
            ("UPDATE knowledge_page_revision SET title=' ' WHERE page_id=$1", page),
            ("UPDATE knowledge_page_revision SET revision=0 WHERE page_id=$1", page),
            (
                "INSERT INTO knowledge_page_task(page_id,revision,task_id) VALUES ($1,1,$2)",
                page,
                uuid4(),
            ),
            (
                "INSERT INTO knowledge_page_member(page_id,user_id,access) VALUES ($1,$2,'admin')",
                page,
                owner,
            ),
        )
        for sql, *values in rejected:
            try:
                async with conn.transaction():
                    await conn.execute(sql, *values)
            except asyncpg.IntegrityConstraintViolationError:
                pass
            else:
                raise AssertionError(f"Constraint missing: {sql}")
        await conn.execute(
            "INSERT INTO knowledge_page_revision(page_id,revision,title,content,created_by) VALUES ($1,2,'Second title',$2::jsonb,$3)",
            page,
            '{"type":"doc","content":[]}',
            owner,
        )
        await conn.execute("UPDATE knowledge_page SET revision=2 WHERE id=$1", page)
        assert (
            await conn.fetchval(
                "SELECT r.title FROM knowledge_page p JOIN knowledge_page_revision r ON (r.page_id,r.revision)=(p.id,p.revision) WHERE p.id=$1",
                page,
            )
            == "Second title"
        )
        assert (
            await conn.fetchval(
                "SELECT title FROM knowledge_page_revision WHERE page_id=$1 AND revision=1",
                page,
            )
            == "First title"
        )
        # Removing a reference or the page must never delete the referenced task.
        await conn.execute("DELETE FROM knowledge_page WHERE id=$1", page)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM knowledge_page_revision WHERE page_id=$1", page
            )
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM knowledge_page_task WHERE page_id=$1", page
            )
            == 0
        )
        assert await conn.fetchval("SELECT count(*) FROM task WHERE id=$1", task) == 1
        print(
            "PASS knowledge current revision, history, document root, explicit access and stable task references"
        )
    finally:
        await transaction.rollback()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
