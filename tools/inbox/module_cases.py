#!/usr/bin/env python3
"""Inbox cases for the module browser tests, added to the shared fixture.

The first fixture account becomes system administrator and may manage every
case; the second account stays unrelated and must not see them.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg

from leonaid.bootstrap.api import build_inbox_service
from leonaid.modules.inbox.api import INBOX_PRIVACY_NOTICE_VERSION, SubmitCase

FIXTURE = Path(os.environ.get("LEONAID_MODULE_FIXTURE", "/proof/module-fixture.json"))


async def main() -> None:
    fixture = json.loads(FIXTURE.read_text())
    manager = UUID(fixture["users"][0])
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2
    )
    assert pool is not None
    try:
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO user_global_role(user_id,role) VALUES($1,'system_admin')",
                manager,
            )
        inbox = build_inbox_service(pool)
        cases: dict[str, str] = {}
        for surface in ("web", "pwa"):
            receipt = await inbox.submit(
                SubmitCase(
                    privacy_consent=True,
                    privacy_notice_version=INBOX_PRIVACY_NOTICE_VERSION,
                    idempotency_key=uuid4(),
                    subject=f"Rückfrage zum Mittagstisch ({surface})",
                    message="Guten Tag,\nkönnen wir einen Termin abstimmen?",
                    given_name="Mara",
                    family_name=f"Browser-{surface}",
                    email=f"mara.{uuid4().hex[:8]}@example.org",
                )
            )
            async with pool.acquire() as connection:
                case_id = await connection.fetchval(
                    "SELECT id FROM inbox_case WHERE public_reference=$1",
                    receipt.reference,
                )
            cases[surface] = str(case_id)
    finally:
        await pool.close()
    fixture["cases"] = cases
    FIXTURE.write_text(json.dumps(fixture))
    FIXTURE.chmod(0o600)
    print("inbox-module-seed: two synthetic cases added to the module fixture")


if __name__ == "__main__":
    asyncio.run(main())
