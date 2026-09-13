"""Seed isolated active/inactive public actions without an order form."""

import argparse
from pathlib import Path
import asyncio
import json
import os
from uuid import uuid4
import asyncpg


async def main(output: Path):
    c = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    result = {}
    async with c.transaction():
        admin_id = uuid4()
        await c.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Public Inbox Testverwaltung','active')",
            admin_id,
            f"public-inbox-{admin_id.hex}@example.invalid",
        )
        for kind in ["active", "inactive"]:
            aid = uuid4()
            alias = f"inbox-{kind}-{aid.hex[:8]}"
            slug = alias + "-2026"
            await c.execute(
                "INSERT INTO charity_action(id,carrier_name,name,purpose,status,starts_on,ends_on,archive_slug,publication_starts_at,publication_ends_at) VALUES($1,'Synthetischer Testclub',$2,'Gemeinsamer Mittagstisch und persönliche Unterstützung.','active','2026-01-01','2026-12-31',$3,now()-interval '2 days',now()+interval '1 day')",
                aid,
                "Mittagstisch " + kind,
                slug,
            )
            await c.execute(
                "INSERT INTO beneficiary(id,action_id,organization_name,public_description,sort_order) VALUES($1,$2,'Synthetischer Mittagstisch','Gemeinsame Mahlzeiten vor Ort.',0)",
                uuid4(),
                aid,
            )
            await c.execute(
                "INSERT INTO action_membership(id,action_id,user_id,role,active_from) VALUES($1,$2,$3,'charity_admin',now()-interval '1 day')",
                uuid4(),
                aid,
                admin_id,
            )
            if kind == "inactive":
                await c.execute(
                    "UPDATE charity_action SET publication_ends_at=now()-interval '1 day' WHERE id=$1",
                    aid,
                )
            await c.execute(
                "INSERT INTO public_action_alias(alias,action_id) VALUES($1,$2)",
                alias,
                aid,
            )
            result[kind] = {"id": str(aid), "alias": alias, "slug": slug}
    output.write_text(json.dumps(result))
    print("Public action fixture written")
    await c.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args().output))
