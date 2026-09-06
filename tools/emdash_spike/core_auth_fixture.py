"""Prepare/revoke synthetic real Core sessions for the CMS HTTP boundary proof."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID
from pathlib import Path

import asyncpg

from tools.identity.contract import FINN_ID, KLARA_ID, SYSTEM_ID, create_session


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        now = datetime.now(timezone.utc)
        if sys.argv[1] in {"prepare", "prepare-races"}:
            actors = (
                [
                    (operation, SYSTEM_ID)
                    for operation in [
                        "update",
                        "restore",
                        "discard",
                        "publish",
                        "unpublish",
                        "create",
                    ]
                ]
                if sys.argv[1] == "prepare-races"
                else [
                    ("system", SYSTEM_ID),
                    ("charity", KLARA_ID),
                    ("finance", FINN_ID),
                ]
            )
            tokens = {
                name: await create_session(connection, user_id, now=now)
                for name, user_id in actors
            }
            path = Path(sys.argv[2])
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump(tokens, output)
        elif sys.argv[1] == "rename":
            await connection.execute(
                "UPDATE user_account SET email='renamed-system@leonaid.invalid' WHERE id=$1",
                SYSTEM_ID,
            )
        elif sys.argv[1] == "revoke":
            await connection.execute(
                "UPDATE user_session SET revoked_at=$1 WHERE user_id=$2", now, SYSTEM_ID
            )
            await connection.execute(
                "DELETE FROM action_membership WHERE user_id=$1", KLARA_ID
            )
        elif sys.argv[1] == "prepare-publication":
            for suffix, action_status in [(41, "draft"), (42, "scheduled")]:
                await connection.execute(
                    """INSERT INTO charity_action
                    (id, carrier_name, name, purpose, status, starts_on, ends_on,
                     publication_starts_at, publication_ends_at, archive_slug)
                    VALUES ($1, 'Synthetic carrier', 'Synthetic campaign', 'Synthetic proof',
                            $2, $3, $3, $4, $5, $6)""",
                    UUID(f"20000000-0000-4000-8000-{suffix:012d}"),
                    action_status,
                    now.date(),
                    now - timedelta(days=1),
                    now + timedelta(days=1),
                    f"synthetic-publication-{suffix}",
                )
                await connection.execute(
                    """INSERT INTO beneficiary
                    (id, action_id, organization_name, public_description, sort_order)
                    VALUES ($1, $2, 'Synthetic beneficiary', 'Synthetic proof', 0)""",
                    UUID(f"30000000-0000-4000-8000-{suffix:012d}"),
                    UUID(f"20000000-0000-4000-8000-{suffix:012d}"),
                )
        elif sys.argv[1].startswith("publication-"):
            mode = sys.argv[1].removeprefix("publication-")
            if mode not in {
                "open",
                "future",
                "expired",
                "none",
                "completed",
                "archived",
            }:
                raise ValueError("unknown publication fixture state")
            starts: datetime | None = now - timedelta(days=1)
            ends: datetime | None = now + timedelta(days=1)
            if mode == "future":
                starts, ends = now + timedelta(days=1), now + timedelta(days=2)
            elif mode == "expired":
                starts, ends = now - timedelta(days=2), now - timedelta(days=1)
            elif mode == "none":
                starts = ends = None
            action_status = mode if mode in {"completed", "archived"} else "active"
            await connection.execute(
                "UPDATE charity_action SET status=$1, publication_starts_at=$2, publication_ends_at=$3 WHERE id=$4",
                action_status,
                starts,
                ends,
                UUID("20000000-0000-4000-8000-000000000001"),
            )
        else:
            raise ValueError("unknown fixture operation")
    finally:
        await connection.close()
    print("emdash-core-auth-fixture: OK: synthetic state updated")


if __name__ == "__main__":
    asyncio.run(main())
