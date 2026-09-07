"""Change real restored Core membership while the browser keeps its session."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from uuid import UUID

import asyncpg


async def wait_for(path: Path) -> None:
    async with asyncio.timeout(90):
        while not path.is_file():
            await asyncio.sleep(0.1)


async def main() -> None:
    control = Path("/proof/recovery-control")
    database = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        rows = await database.fetch(
            "SELECT id, active_until FROM action_membership WHERE user_id=$1 AND action_id=$2 AND role='charity_admin'",
            UUID("10000000-0000-4000-8000-000000000002"),
            UUID("20000000-0000-4000-8000-000000000001"),
        )
        assert len(rows) == 1
        membership = rows[0]
        for name in ("chromium", "firefox", "webkit"):
            await wait_for(control / f"{name}-ready")
            try:
                await database.execute(
                    "UPDATE action_membership SET active_until=clock_timestamp() WHERE id=$1",
                    membership["id"],
                )
                (control / f"{name}-revoked").touch()
                await wait_for(control / f"{name}-denied")
            finally:
                await database.execute(
                    "UPDATE action_membership SET active_until=$2 WHERE id=$1",
                    membership["id"],
                    membership["active_until"],
                )
            (control / f"{name}-restored").touch()
        print(
            "recovery-authority: current restored Core membership expired and restored for three live browser sessions"
        )
    finally:
        await database.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print(
            "recovery-authority: failed; identities and private state omitted",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
