#!/usr/bin/env python3
"""Material version ownership and references against real PostgreSQL, rolled back."""

import asyncio
import os
from uuid import uuid4

import asyncpg


async def main() -> None:
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    transaction = conn.transaction()
    await transaction.start()
    try:
        owner, material, other = (uuid4() for _ in range(3))
        await conn.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES ($1,$2,'Material proof','active')",
            owner,
            f"{owner}@example.org",
        )
        for identifier in (material, other):
            await conn.execute(
                "INSERT INTO material(id,owner_user_id,title) VALUES ($1,$2,'Shared file')",
                identifier,
                owner,
            )
            await conn.execute(
                """INSERT INTO material_version(material_id,version,filename,media_type,size_bytes,
                    sha256,storage_bucket,object_key,storage_version_id,created_by)
                    VALUES ($1,1,'preparation.txt','text/plain',12,$2,'existing-bucket',$3,'stored-v1',$4)""",
                identifier,
                "a" * 64,
                f"materials/{identifier}/1",
                owner,
            )
        await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        pages = [uuid4(), uuid4()]
        await conn.execute("SET CONSTRAINTS knowledge_page_current_revision DEFERRED")
        for page in pages:
            await conn.execute(
                "INSERT INTO knowledge_page(id,owner_user_id) VALUES ($1,$2)",
                page,
                owner,
            )
            await conn.execute(
                """INSERT INTO knowledge_page_revision(page_id,revision,title,content,created_by)
                    VALUES ($1,1,'Reference page','{"type":"doc","content":[]}'::jsonb,$2)""",
                page,
                owner,
            )
            await conn.execute(
                "INSERT INTO knowledge_page_material(page_id,revision,material_id,material_version) VALUES ($1,1,$2,1)",
                page,
                material,
            )
        await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
        rejected = [
            ("UPDATE material SET current_version=2 WHERE id=$1", material),
            ("UPDATE material SET title=' ' WHERE id=$1", material),
            ("UPDATE material SET access_revision=0 WHERE id=$1", material),
            ("UPDATE material SET revision=0 WHERE id=$1", material),
            ("UPDATE material_version SET version=0 WHERE material_id=$1", material),
            ("UPDATE material_version SET size_bytes=0 WHERE material_id=$1", material),
            (
                "UPDATE material_version SET size_bytes=26214401 WHERE material_id=$1",
                material,
            ),
            ("UPDATE material_version SET sha256='bad' WHERE material_id=$1", material),
            (
                "UPDATE material_version SET storage_version_id='null' WHERE material_id=$1",
                material,
            ),
            (
                "UPDATE material_version SET storage_version_id=' ' WHERE material_id=$1",
                material,
            ),
            ("UPDATE material_version SET filename=' ' WHERE material_id=$1", material),
            (
                "UPDATE material_version SET object_key=' ' WHERE material_id=$1",
                material,
            ),
            (
                "UPDATE material_version SET storage_bucket=' ' WHERE material_id=$1",
                material,
            ),
            (
                "UPDATE material_version SET media_type=' ' WHERE material_id=$1",
                material,
            ),
            ("DELETE FROM material_version WHERE material_id=$1", material),
            ("DELETE FROM material WHERE id=$1", material),
            (
                "UPDATE knowledge_page_material SET material_version=99 WHERE material_id=$1",
                material,
            ),
            (
                "UPDATE knowledge_page_material SET revision=99 WHERE material_id=$1",
                material,
            ),
            (
                "INSERT INTO material_member(material_id,user_id,access) VALUES ($1,$2,'admin')",
                material,
                owner,
            ),
            (
                "INSERT INTO material_member(material_id,user_id,access) VALUES ($1,$2,'viewer')",
                material,
                uuid4(),
            ),
            (
                "UPDATE material_version SET object_key=$2 WHERE material_id=$1",
                other,
                f"materials/{material}/1",
            ),
        ]
        for sql, *values in rejected:
            try:
                async with conn.transaction():
                    await conn.execute(sql, *values)
            except asyncpg.IntegrityConstraintViolationError:
                pass
            else:
                raise AssertionError(f"Constraint missing: {sql}")
        await conn.execute(
            """INSERT INTO material_version(material_id,version,filename,media_type,size_bytes,
                sha256,storage_bucket,object_key,storage_version_id,created_by)
                VALUES ($1,2,'preparation.txt','text/plain',24,$2,'existing-bucket',$3,'stored-v2',$4)""",
            material,
            "b" * 64,
            f"materials/{material}/2",
            owner,
        )
        await conn.execute(
            "UPDATE material SET current_version=2,revision=revision+1 WHERE id=$1",
            material,
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM knowledge_page_material WHERE material_id=$1 AND material_version=1",
                material,
            )
            == 2
        )
        assert (
            await conn.fetchval(
                "SELECT sha256 FROM material_version WHERE material_id=$1 AND version=1",
                material,
            )
            == "a" * 64
        )
        await conn.execute("DELETE FROM knowledge_page WHERE id=ANY($1::uuid[])", pages)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM knowledge_page_material WHERE material_id=$1",
                material,
            )
            == 0
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM material_version WHERE material_id=$1", material
            )
            == 2
        )
        print(
            "PASS material head/version metadata, exact references from two pages, independent file lifetime and 21 invalid writes rejected"
        )
    finally:
        await transaction.rollback()
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
