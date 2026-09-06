"""Seed a disposable admin session for live public policy propagation proof."""

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

from tools.invoices.contract import seed_sessions


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        tokens = await seed_sessions(connection)
        Path(sys.argv[1]).write_text(f"KLARA_SESSION={tokens['klara_fresh']}\n")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
