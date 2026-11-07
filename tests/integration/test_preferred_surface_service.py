#!/usr/bin/env python3
"""Start-area choice in the identity service against real PostgreSQL.

specs/multi-domain §6.7: ``IdentityQueryService.set_preferred_surface``
stores a surface only when the member has a role for it (else 409
``preferred_surface_unavailable`` and nothing is stored), clears it with
``None`` and answers with the landing path of the new choice. Runs as a
contract script in the schema gate (tools/schema/test.sh) and, with
CORE_DATABASE_URL set, under pytest.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.identity import AsyncpgIdentityRepository
from leonaid.application.errors import AuthenticationRequired, Conflict
from leonaid.application.identity import IdentityQueryService, PreferredSurface


class Proof:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection
        self.tag = uuid4().hex[:8]
        self.users: list[UUID] = []
        self.action_id = uuid4()

    async def action(self) -> None:
        await self.connection.execute(
            """
            INSERT INTO charity_action (
                id, carrier_name, name, purpose, status, starts_on, ends_on,
                archive_slug
            )
            VALUES ($1, 'Lions Club Proof', $2, 'Startbereich', 'active',
                    '2026-01-01', '2099-12-31', $3)
            """,
            self.action_id,
            f"Startbereich {self.tag}",
            f"startbereich-{self.tag}",
        )

    async def member(self, name: str, *roles: str) -> str:
        """A member with these action roles and a live session; its token."""
        user_id = uuid4()
        self.users.append(user_id)
        await self.connection.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, $3, 'active')",
            user_id,
            f"{name}.{self.tag}@leonaid.invalid",
            name,
        )
        for role in roles:
            await self.connection.execute(
                "INSERT INTO action_membership "
                "(id, action_id, user_id, role, active_from) "
                "VALUES ($1, $2, $3, $4, now() - interval '1 day')",
                uuid4(),
                self.action_id,
                user_id,
                role,
            )
        token = f"preferred-surface-proof-{name}-{self.tag}-{uuid4().hex}"
        started = datetime.now(timezone.utc)
        await self.connection.execute(
            "INSERT INTO user_session (id, user_id, token_digest, expires_at, "
            "last_seen_at, fresh_login_at, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $5, $5, $5)",
            uuid4(),
            user_id,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
            started + timedelta(days=90),
            started,
        )
        return token

    async def stored(self, token: str) -> str | None:
        return await self.connection.fetchval(
            "SELECT account.preferred_surface FROM user_account AS account "
            "JOIN user_session AS session ON session.user_id = account.id "
            "WHERE session.token_digest = $1",
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )

    async def cleanup(self) -> None:
        await self.connection.execute(
            "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])", self.users
        )
        await self.connection.execute(
            "DELETE FROM action_membership WHERE user_id = ANY($1::uuid[])",
            self.users,
        )
        await self.connection.execute(
            "DELETE FROM user_account WHERE id = ANY($1::uuid[])", self.users
        )
        await self.connection.execute(
            "DELETE FROM charity_action WHERE id = $1", self.action_id
        )


async def refused(
    service: IdentityQueryService,
    token: str,
    surface: PreferredSurface,
) -> None:
    try:
        await service.set_preferred_surface(token, surface)
    except Conflict as error:
        assert error.code == "preferred_surface_unavailable", error.code
    else:
        raise AssertionError(f"{surface} was stored without a role for it")


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2, command_timeout=10
    )
    assert pool is not None
    repository = AsyncpgIdentityRepository(pool)
    service = IdentityQueryService(
        repository, delivery_navigation=repository.manages_delivery
    )
    async with pool.acquire() as connection:
        proof = Proof(connection)
        try:
            await proof.action()
            both = await proof.member("both", "acquirer", "charity_admin")
            acquirer = await proof.member("acquirer", "acquirer")
            admin = await proof.member("admin", "charity_admin")

            # Both apps: the default is the PWA; the admin app can be chosen,
            # the answer already carries the new landing path, and None
            # returns to the default rule.
            assert (await service.current_identity(both)).landing_path == "/app/"
            chosen = await service.set_preferred_surface(both, PreferredSurface.WEB)
            assert chosen.preferred_surface == PreferredSurface.WEB
            assert chosen.landing_path == "/admin/", chosen.landing_path
            assert await proof.stored(both) == "web"
            reread = await service.current_identity(both)
            assert reread.landing_path == "/admin/"
            assert reread.preferred_surface == PreferredSurface.WEB
            back = await service.set_preferred_surface(both, None)
            assert back.preferred_surface is None
            assert back.landing_path == "/app/", back.landing_path
            assert await proof.stored(both) is None
            pwa = await service.set_preferred_surface(both, PreferredSurface.PWA)
            assert pwa.landing_path == "/app/"
            assert await proof.stored(both) == "pwa"

            # One app only: the other surface is refused and nothing stored.
            await refused(service, acquirer, PreferredSurface.WEB)
            assert await proof.stored(acquirer) is None
            assert (await service.current_identity(acquirer)).landing_path == "/app/"
            await refused(service, admin, PreferredSurface.PWA)
            assert await proof.stored(admin) is None
            assert (await service.current_identity(admin)).landing_path == "/admin/"
            # Its own app and the reset stay allowed.
            own = await service.set_preferred_surface(admin, PreferredSurface.WEB)
            assert own.landing_path == "/admin/"
            assert await proof.stored(admin) == "web"
            await service.set_preferred_surface(admin, None)
            assert await proof.stored(admin) is None

            # Without a valid session nothing changes.
            for token in (None, "", "unknown-session-token-of-enough-length-0001"):
                try:
                    await service.set_preferred_surface(token, PreferredSurface.WEB)
                except AuthenticationRequired:
                    pass
                else:
                    raise AssertionError("stored without a session")
        finally:
            await proof.cleanup()
    await pool.close()
    print("preferred-surface-service: OK: role check, store, reset and landing path")


def test_preferred_surface_service() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("CORE_DATABASE_URL is not set")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
