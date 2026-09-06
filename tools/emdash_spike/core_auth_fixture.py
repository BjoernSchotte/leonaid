"""Prepare/revoke synthetic real Core sessions for the CMS HTTP boundary proof."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from tools.identity.contract import FINN_ID, KLARA_ID, SYSTEM_ID, create_session


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        now = datetime.now(timezone.utc)
        if sys.argv[1] == "prepare":
            tokens = {
                name: await create_session(connection, user_id, now=now)
                for name, user_id in [
                    ("system", SYSTEM_ID),
                    ("charity", KLARA_ID),
                    ("finance", FINN_ID),
                ]
            }
            path = Path(sys.argv[2])
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump(tokens, output)
        elif sys.argv[1] == "revoke":
            await connection.execute(
                "UPDATE user_session SET revoked_at=$1 WHERE user_id=$2", now, SYSTEM_ID
            )
            await connection.execute(
                "DELETE FROM action_membership WHERE user_id=$1", KLARA_ID
            )
        else:
            raise ValueError("unknown fixture operation")
    finally:
        await connection.close()
    print("emdash-core-auth-fixture: OK: synthetic state updated")


if __name__ == "__main__":
    asyncio.run(main())
