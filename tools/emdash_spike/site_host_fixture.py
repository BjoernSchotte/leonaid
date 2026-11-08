"""Campaign hosts for the full-stack proof (specs/multi-domain §7, §14).

``activate``: krapfentaxi.test is an active campaign host with the published
Krapfentaxi campaign at "/" (segment 2026); www.krapfentaxi.test redirects
there. ``disable``: krapfentaxi.test lapses (status disabled) while Caddy
still holds its certificate. ``reactivate``: active again, and the public
inbox rate attempts cleared for the next round. The host check itself is proven against real
PostgreSQL in tests/integration; here the states are set directly.
"""

from __future__ import annotations

import asyncio
import os
import sys
from uuid import UUID

import asyncpg

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
SYSTEM_ID = UUID("10000000-0000-4000-8000-000000000001")
HOST_ID = UUID("95600000-0000-4000-8000-000000000001")
WWW_ID = UUID("95600000-0000-4000-8000-000000000002")


async def main() -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    try:
        if sys.argv[1] == "activate":
            async with connection.transaction():
                await connection.execute(
                    "INSERT INTO site_host (id, hostname, status, verification_token, "
                    "verified_at, created_by) VALUES "
                    "($1, 'krapfentaxi.test', 'active', repeat('a', 43), now(), $3), "
                    "($2, 'www.krapfentaxi.test', 'active', repeat('b', 43), now(), $3)",
                    HOST_ID,
                    WWW_ID,
                    SYSTEM_ID,
                )
                await connection.execute(
                    "UPDATE site_host SET redirect_to_host_id=$1 WHERE id=$2",
                    HOST_ID,
                    WWW_ID,
                )
                await connection.execute(
                    "INSERT INTO site_binding (site_host_id, action_id, "
                    "edition_segment, at_root, is_primary, created_by) "
                    "VALUES ($1, $2, '2026', true, true, $3)",
                    HOST_ID,
                    ACTION_ID,
                    SYSTEM_ID,
                )
        elif sys.argv[1] in ("disable", "reactivate"):
            status = "disabled" if sys.argv[1] == "disable" else "active"
            await connection.execute(
                "UPDATE site_host SET status=$2 WHERE id=$1", HOST_ID, status
            )
            if sys.argv[1] == "reactivate":
                # The second (admin-only) round is a new visitor: the first
                # round's public inbox attempts would trip its 5/10 min limit.
                await connection.execute(
                    "DELETE FROM security_rate_attempt WHERE scope = 'inbox.public.submit'"
                )
        else:
            raise SystemExit("usage: site_host_fixture.py activate|disable|reactivate")
    finally:
        await connection.close()
    print(f"site-host-fixture: {sys.argv[1]}")


if __name__ == "__main__":
    asyncio.run(main())
