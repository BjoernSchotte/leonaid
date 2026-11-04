#!/usr/bin/env python3
"""Write a fresh Charity-Admin session (Klara, golden data) for the browser proof.

The public order spec uses it only to switch the delivery windows of the
golden action on and off again around its last case.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

from tools.identity.contract import KLARA_ID, create_session


async def main(output: Path) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        token = await create_session(
            connection, KLARA_ID, now=datetime.now(timezone.utc)
        )
    finally:
        await connection.close()
    output.write_text(f"KLARA_SESSION={token}\n", encoding="utf-8")
    output.chmod(0o600)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
    print("public-orders-admin-session: OK")
