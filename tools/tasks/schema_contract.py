#!/usr/bin/env python3
"""Real PostgreSQL task constraints; all synthetic rows are rolled back."""

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import asyncpg


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    transaction = connection.transaction()
    await transaction.start()
    try:
        owner, first, second, epic, task = (uuid4() for _ in range(5))
        await connection.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, 'Task schema proof', 'active')",
            owner,
            f"{owner}@leonaid.invalid",
        )
        for list_id in (first, second):
            await connection.execute(
                "INSERT INTO task_list (id, owner_user_id, title) VALUES ($1, $2, 'List')",
                list_id,
                owner,
            )
        await connection.execute(
            "INSERT INTO task_epic (id, list_id, title) VALUES ($1, $2, 'Epic')",
            epic,
            first,
        )
        now = await connection.fetchval("SELECT now()")
        due, deferred = now - timedelta(days=1), now + timedelta(days=1)
        await connection.execute(
            "INSERT INTO task (id, list_id, epic_id, title, created_by, due_at, deferred_until) "
            "VALUES ($1, $2, $3, 'Task', $4, $5, $6)",
            task,
            first,
            epic,
            owner,
            due,
            deferred,
        )
        row = await connection.fetchrow("SELECT * FROM task WHERE id = $1", task)
        assert row is not None and row["status"] == "open" and row["revision"] == 1
        assert row["due_at"] == due and row["deferred_until"] == deferred
        await connection.execute(
            "INSERT INTO task_personal_plan(task_id,user_id,state,planned_on) VALUES($1,$2,'scheduled',current_date)",
            task,
            owner,
        )
        # Each rejected write gets a real PostgreSQL savepoint.
        rejected = (
            ("UPDATE task SET list_id = $2 WHERE id = $1", task, second),
            ("UPDATE task SET status = $2 WHERE id = $1", task, "custom"),
            ("UPDATE task SET title = $2 WHERE id = $1", task, "   "),
            ("UPDATE task SET revision = $2 WHERE id = $1", task, 0),
            ("UPDATE task SET assignee_user_id = $2 WHERE id = $1", task, uuid4()),
            ("DELETE FROM task_epic WHERE id = $1", epic),
            ("DELETE FROM task_list WHERE id = $1", first),
            (
                "UPDATE task_personal_plan SET planned_on=NULL WHERE task_id=$1 AND user_id=$2",
                task,
                owner,
            ),
            (
                "UPDATE task_personal_plan SET state='someday' WHERE task_id=$1 AND user_id=$2",
                task,
                owner,
            ),
            (
                "UPDATE task_personal_plan SET revision=0 WHERE task_id=$1 AND user_id=$2",
                task,
                owner,
            ),
        )
        for sql, *values in rejected:
            try:
                async with connection.transaction():
                    await connection.execute(sql, *values)
            except asyncpg.IntegrityConstraintViolationError:
                pass
            else:
                raise AssertionError(f"Constraint missing for {sql}")
        await connection.execute(
            "UPDATE task SET epic_id = NULL, status = 'done' WHERE id = $1", task
        )
        await connection.execute("DELETE FROM task_epic WHERE id = $1", epic)
        assert (
            await connection.fetchval("SELECT count(*) FROM task WHERE id = $1", task)
            == 1
        )
        print(
            "PASS: independent dates, personal plan constraints, one same-list epic, revisions, status, references and safe deletion"
        )
    finally:
        await transaction.rollback()
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
