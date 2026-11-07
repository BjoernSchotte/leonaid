#!/usr/bin/env python3
"""Campaign host administration over HTTP and real PostgreSQL.

specs/multi-domain §7.1, §7.3, §7.7: only a system admin adds hosts and
binds editions; commands are idempotent and revision-checked; bindings are
never edited in place for segment or host (history rows); the partial
unique indexes refuse two roots, two live segments and two primaries.
Runs as a contract script in the schema gate (tools/schema/test.sh) and,
with CORE_DATABASE_URL set, under pytest.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.configuration import Settings
from leonaid.entrypoints.fastapi.platform import create_app

ADMIN = "https://app.hosts.leonaid.invalid"
PUBLIC = "https://hosts.leonaid.invalid"
API = "/api/v1/admin/site-hosts"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-site-hosts-proof-secret-only-32",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-site-hosts-proof-encrypt-32c",
            "LEONAID_PUBLIC_BASE_URL": ADMIN,
            "LEONAID_SITE_BASE_URL": PUBLIC,
            "LEONAID_ALLOWED_ORIGINS": ADMIN,
            "LEONAID_PUBLIC_ORIGINS": PUBLIC,
            "LEONAID_PUBLIC_DOMAIN_ALIASES": "www.hosts.leonaid.invalid",
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )


class Fixture:
    def __init__(self, connection: asyncpg.Connection) -> None:  # type: ignore[type-arg]
        self.db = connection
        self.tag = uuid4().hex[:8]
        self.users: list[UUID] = []
        self.actions: dict[str, UUID] = {}

    def host(self, name: str) -> str:
        return f"{name}-{self.tag}.example.org"

    async def user(self, name: str, *, system_admin: bool) -> str:
        user_id = uuid4()
        self.users.append(user_id)
        await self.db.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, $3, 'active')",
            user_id,
            f"{name}.{self.tag}@leonaid.invalid",
            name,
        )
        if system_admin:
            await self.db.execute(
                "INSERT INTO user_global_role (user_id, role) VALUES ($1, 'system_admin')",
                user_id,
            )
        token = f"site-hosts-proof-{name}-{self.tag}-{uuid4().hex}"
        now = datetime.now(timezone.utc)
        await self.db.execute(
            "INSERT INTO user_session (id, user_id, token_digest, expires_at, "
            "last_seen_at, fresh_login_at, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $5, $5, $5)",
            uuid4(),
            user_id,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
            now + timedelta(days=90),
            now,
        )
        return token

    async def action(
        self, name: str, status: str, starts: datetime, ends: datetime, *, cms: bool
    ) -> UUID:
        action_id = uuid4()
        self.actions[name] = action_id
        await self.db.execute(
            """
            INSERT INTO charity_action (
                id, carrier_name, name, purpose, status, starts_on, ends_on,
                archive_slug, publication_starts_at, publication_ends_at
            )
            VALUES ($1, 'Lions Club Proof', $2, 'Hosts', $3, $4, $5, $6, $7, $8)
            """,
            action_id,
            f"Lions Open {name} {self.tag}",
            status,
            starts.date(),
            ends.date(),
            f"lions-open-{name}-{self.tag}",
            starts,
            ends,
        )
        await self.db.execute(
            "INSERT INTO public_action_alias "
            "(alias, action_id, is_primary, enabled, campaign_redirect) "
            "VALUES ($1, $2, true, true, $3)",
            f"lionsopen{name}{self.tag}",
            action_id,
            cms,
        )
        return action_id

    async def cleanup(self) -> None:
        hosts = await self.db.fetch(
            "SELECT id FROM site_host WHERE hostname LIKE $1",
            f"%-{self.tag}.example.org",
        )
        ids = [row["id"] for row in hosts]
        await self.db.execute(
            "DELETE FROM audit_event WHERE entity_type='site_host' AND entity_id = ANY($1::uuid[])",
            ids,
        )
        await self.db.execute(
            "DELETE FROM site_binding WHERE site_host_id = ANY($1::uuid[])", ids
        )
        await self.db.execute(
            "UPDATE site_host SET redirect_to_host_id = NULL WHERE id = ANY($1::uuid[])",
            ids,
        )
        await self.db.execute("DELETE FROM site_host WHERE id = ANY($1::uuid[])", ids)
        actions = list(self.actions.values())
        await self.db.execute(
            "DELETE FROM public_action_alias WHERE action_id = ANY($1::uuid[])", actions
        )
        await self.db.execute(
            "DELETE FROM charity_action WHERE id = ANY($1::uuid[])", actions
        )
        await self.db.execute(
            "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])", self.users
        )
        await self.db.execute(
            "DELETE FROM user_global_role WHERE user_id = ANY($1::uuid[])", self.users
        )
        await self.db.execute(
            "DELETE FROM user_account WHERE id = ANY($1::uuid[])", self.users
        )


class Admin:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client = client
        self.token = token

    async def call(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        return await self.client.request(
            method,
            API + path,
            json=body,
            headers={
                "Origin": ADMIN,
                "Cookie": f"__Host-leonaid_session={self.token}",
            },
        )

    async def ok(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await self.call(method, path, body)
        assert response.status_code == 200, (method, path, response.text)
        result: dict[str, Any] = response.json()
        return result

    async def refused(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        status: int,
        code: str,
    ) -> None:
        response = await self.call(method, path, body)
        assert response.status_code == status, (path, response.text)
        assert response.json()["error"]["code"] == code, response.text


def command(**fields: Any) -> dict[str, Any]:
    return {"commandId": str(uuid4()), **fields}


async def unique_violation(db: asyncpg.Connection, sql: str, *args: Any) -> None:  # type: ignore[type-arg]
    try:
        async with db.transaction():
            await db.execute(sql, *args)
    except asyncpg.UniqueViolationError:
        return
    raise AssertionError(f"PostgreSQL accepted: {sql}")


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    fixture = Fixture(connection)
    now = datetime.now(timezone.utc)
    day = timedelta(days=1)
    try:
        admin_token = await fixture.user("sysadmin", system_admin=True)
        member_token = await fixture.user("member", system_admin=False)
        ended = await fixture.action(
            "2025", "completed", now - 400 * day, now - 30 * day, cms=True
        )
        running = await fixture.action(
            "2026", "active", now - day, now + 30 * day, cms=True
        )
        upcoming = await fixture.action(
            "2027", "scheduled", now + 300 * day, now + 330 * day, cms=False
        )
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=ADMIN
            ) as client:
                admin = Admin(client, admin_token)
                member = Admin(client, member_token)

                # D5: system admins only, reads and writes.
                await member.refused("GET", "", None, 403, "system_admin_required")
                await member.refused(
                    "POST",
                    "",
                    command(hostname=fixture.host("lionsopen")),
                    403,
                    "system_admin_required",
                )

                overview = await admin.ok("GET", "")
                assert overview["adminHost"] == "app.hosts.leonaid.invalid"
                assert overview["publicHost"] == "hosts.leonaid.invalid"
                assert overview["publicHostAliases"] == ["www.hosts.leonaid.invalid"]
                bindable = {item["id"]: item for item in overview["actions"]}
                assert bindable[str(ended)]["availability"] == "archive"
                assert bindable[str(running)]["availability"] == "published"
                assert bindable[str(upcoming)]["availability"] == "inactive"

                # Hostname rules: normalized, configured hosts refused.
                for reserved in (
                    "app.hosts.leonaid.invalid",
                    "x.app.hosts.leonaid.invalid",
                    "hosts.leonaid.invalid",
                    "WWW.hosts.leonaid.invalid",
                ):
                    await admin.refused(
                        "POST",
                        "",
                        command(hostname=reserved),
                        422,
                        "site_host_reserved",
                    )
                await admin.refused(
                    "POST",
                    "",
                    command(hostname="nas.local"),
                    422,
                    "site_host_special_use",
                )
                for invalid in (
                    "https://x.example.org",
                    "x.example.org:8443",
                    "x.example.org.",
                    "192.0.2.1",
                    "localhost",
                    "*.example.org",
                ):
                    await admin.refused(
                        "POST", "", command(hostname=invalid), 422, "site_host_invalid"
                    )
                add = command(hostname="  " + fixture.host("LionsOpen").upper() + " ")
                host = await admin.ok("POST", "", add)
                assert host["hostname"] == fixture.host("lionsopen"), host
                assert host["status"] == "pending"
                assert host["kind"] == "campaign"
                assert host["verificationPath"].startswith(
                    "/.well-known/leonaid-host-check/"
                )
                assert host["revision"] == 1
                # Same command id, same data: the same host, no second row.
                again = await admin.ok("POST", "", add)
                assert again["id"] == host["id"]
                await admin.refused(
                    "POST",
                    "",
                    {**add, "hostname": fixture.host("other")},
                    409,
                    "idempotency_conflict",
                )
                await admin.refused(
                    "POST",
                    "",
                    command(hostname=fixture.host("lionsopen")),
                    409,
                    "site_host_exists",
                )
                host_id = host["id"]

                # Bind 2025 (ended) at segment 2025 and 2026 at the root.
                host = await admin.ok(
                    "POST",
                    f"/{host_id}/bindings",
                    command(revision=1, actionId=str(ended), atRoot=False),
                )
                [first] = host["bindings"]
                expected_segment = str((now - 400 * day).year)
                assert first["segment"] == expected_segment, first
                assert first["isPrimary"] and not first["atRoot"]
                assert first["editionUrl"] == (
                    f"https://{fixture.host('lionsopen')}/{expected_segment}/"
                )
                await admin.refused(
                    "POST",
                    f"/{host_id}/bindings",
                    command(revision=1, actionId=str(running), atRoot=True),
                    409,
                    "site_host_revision_conflict",
                )
                await admin.refused(
                    "POST",
                    f"/{host_id}/bindings",
                    command(
                        revision=host["revision"],
                        actionId=str(running),
                        segment=expected_segment,
                        atRoot=True,
                    ),
                    409,
                    "site_edition_segment_taken",
                )
                for reserved in ("archive", "api", "impressum", "admin"):
                    await admin.refused(
                        "POST",
                        f"/{host_id}/bindings",
                        command(
                            revision=host["revision"],
                            actionId=str(running),
                            segment=reserved,
                            atRoot=True,
                        ),
                        422,
                        "site_edition_segment_reserved",
                    )
                host = await admin.ok(
                    "POST",
                    f"/{host_id}/bindings",
                    command(
                        revision=host["revision"],
                        actionId=str(running),
                        segment="2026",
                        atRoot=True,
                    ),
                )
                await admin.refused(
                    "POST",
                    f"/{host_id}/bindings",
                    command(revision=host["revision"], actionId=str(running)),
                    409,
                    "site_edition_action_bound",
                )
                await admin.refused(
                    "POST",
                    f"/{host_id}/bindings",
                    command(
                        revision=host["revision"],
                        actionId=str(upcoming),
                        segment="2027",
                        atRoot=True,
                    ),
                    409,
                    "site_edition_root_taken",
                )

                # Move the root to the follow-up (§7.7.4): binds it, flips roots.
                host = await admin.ok(
                    "PUT",
                    f"/{host_id}/root",
                    command(
                        revision=host["revision"],
                        actionId=str(upcoming),
                        segment="2027",
                    ),
                )
                roots = [item for item in host["bindings"] if item["atRoot"]]
                assert [item["actionId"] for item in roots] == [str(upcoming)], host
                assert {item["segment"] for item in host["bindings"]} == {
                    expected_segment,
                    "2026",
                    "2027",
                }
                await admin.refused(
                    "PUT",
                    f"/{host_id}/root",
                    command(revision=host["revision"], actionId=str(ended)),
                    409,
                    "site_edition_follow_up_ended",
                )

                # Segment change: history row, the new live row keeps the flags.
                old = next(
                    item for item in host["bindings"] if item["actionId"] == str(ended)
                )
                host = await admin.ok(
                    "PUT",
                    f"/{host_id}/bindings/{old['id']}/segment",
                    command(revision=host["revision"], segment="lions-open-2025"),
                )
                [retired] = host["history"]
                assert retired["id"] == old["id"]
                assert retired["endedReason"] == "segment_changed"
                assert retired["segment"] == expected_segment
                assert not retired["atRoot"] and not retired["isPrimary"]
                # The old path leads to the action's canonical URL (§7.7.5),
                # which is still pending → public host archive page.
                assert retired["targetUrl"] == (
                    f"{PUBLIC}/archive/lions-open-2025-{fixture.tag}"
                ), retired
                renamed = next(
                    item for item in host["bindings"] if item["actionId"] == str(ended)
                )
                assert renamed["segment"] == "lions-open-2025"
                assert renamed["isPrimary"]

                # Redirect host: www → campaign host; no editions, no chains.
                www = await admin.ok("POST", "", command(hostname=fixture.host("www")))
                www = await admin.ok(
                    "PUT",
                    f"/{www['id']}/redirect",
                    command(revision=www["revision"], targetHostId=host_id),
                )
                assert www["kind"] == "redirect"
                assert www["redirectToHostname"] == fixture.host("lionsopen")
                await admin.refused(
                    "POST",
                    f"/{www['id']}/bindings",
                    command(revision=www["revision"], actionId=str(running)),
                    409,
                    "site_host_is_redirect",
                )
                await admin.refused(
                    "PUT",
                    f"/{host_id}/redirect",
                    command(revision=host["revision"], targetHostId=www["id"]),
                    409,
                    "site_host_redirect_chain",
                )
                await admin.refused(
                    "PUT",
                    f"/{www['id']}/redirect",
                    command(revision=www["revision"], targetHostId=www["id"]),
                    422,
                    "site_host_redirect_self",
                )

                # Same campaign on a second host: not primary; then made primary.
                second = await admin.ok(
                    "POST", "", command(hostname=fixture.host("second"))
                )
                second = await admin.ok(
                    "POST",
                    f"/{second['id']}/bindings",
                    command(
                        revision=second["revision"], actionId=str(running), atRoot=True
                    ),
                )
                [mirror] = second["bindings"]
                assert not mirror["isPrimary"]
                second = await admin.ok(
                    "PUT",
                    f"/{second['id']}/bindings/{mirror['id']}/primary",
                    command(revision=second["revision"]),
                )
                assert second["bindings"][0]["isPrimary"]
                host = await admin.ok("GET", "")
                host = next(item for item in host["hosts"] if item["id"] == host_id)
                assert not next(
                    item
                    for item in host["bindings"]
                    if item["actionId"] == str(running)
                )["isPrimary"]

                # Unbinding the only (root) edition needs a confirmation.
                await admin.refused(
                    "DELETE",
                    f"/{second['id']}/bindings/{mirror['id']}",
                    command(revision=second["revision"]),
                    409,
                    "site_edition_root_only",
                )
                second = await admin.ok(
                    "DELETE",
                    f"/{second['id']}/bindings/{mirror['id']}",
                    command(revision=second["revision"], confirmRootRemoval=True),
                )
                assert second["bindings"] == []
                assert second["history"][0]["endedReason"] == "unbound"
                # The primary moved back to the remaining live binding.
                host = await admin.ok("GET", "")
                host = next(item for item in host["hosts"] if item["id"] == host_id)
                assert next(
                    item
                    for item in host["bindings"]
                    if item["actionId"] == str(running)
                )["isPrimary"]

                # Removal: refused while www redirects here; preview; remove.
                await admin.refused(
                    "DELETE",
                    f"/{host_id}",
                    command(revision=host["revision"]),
                    409,
                    "site_host_is_redirect_target",
                )
                preview = await admin.ok("GET", f"/{host_id}/removal-preview")
                assert preview["redirectHosts"] == [fixture.host("www")]
                urls = {item["actionId"]: item["newUrl"] for item in preview["items"]}
                assert urls[str(running)] == (
                    f"{PUBLIC}/campaigns/lions-open-2026-{fixture.tag}/"
                ), urls
                assert (
                    urls[str(ended)]
                    == f"{PUBLIC}/archive/lions-open-2025-{fixture.tag}"
                )
                assert urls[str(upcoming)] == f"{PUBLIC}/lionsopen2027{fixture.tag}"
                await admin.ok(
                    "DELETE", f"/{www['id']}", command(revision=www["revision"])
                )
                removed = await admin.ok(
                    "DELETE", f"/{host_id}", command(revision=host["revision"])
                )
                assert removed["status"] == "disabled"
                assert removed["bindings"] == []
                assert {item["endedReason"] for item in removed["history"]} >= {
                    "host_removed"
                }
                await admin.refused(
                    "POST",
                    f"/{host_id}/bindings",
                    command(revision=removed["revision"], actionId=str(running)),
                    409,
                    "site_host_disabled",
                )
                # Re-add: pending again with a new token.
                readded = await admin.ok(
                    "POST", "", command(hostname=fixture.host("lionsopen"))
                )
                assert readded["id"] == host_id
                assert readded["status"] == "pending"
                assert readded["verificationPath"] != host["verificationPath"]

        audit = await connection.fetch(
            "SELECT event_type FROM audit_event WHERE entity_type='site_host' "
            "AND entity_id=$1 ORDER BY occurred_at",
            UUID(host_id),
        )
        events = [row["event_type"] for row in audit]
        for expected in (
            "site_host.added",
            "site_edition.bound",
            "site_edition.root_released",
            "site_edition.segment_changed",
            "site_host.removed",
            "site_host.readded",
        ):
            assert expected in events, events

        # PostgreSQL refuses what the commands never write.
        admin_id = fixture.users[0]
        raw = await connection.fetchval(
            "INSERT INTO site_host(hostname,verification_token,created_by) "
            "VALUES($1,$2,$3) RETURNING id",
            fixture.host("raw"),
            "t" * 40,
            admin_id,
        )
        insert = (
            "INSERT INTO site_binding(site_host_id,action_id,edition_segment,at_root,"
            "is_primary,created_by) VALUES($1,$2,$3,$4,$5,$6)"
        )
        await connection.execute(insert, raw, ended, "a", True, False, admin_id)
        await unique_violation(
            connection, insert, raw, running, "b", True, False, admin_id
        )
        await unique_violation(
            connection, insert, raw, running, "a", False, False, admin_id
        )
        await unique_violation(
            connection, insert, raw, ended, "c", False, False, admin_id
        )
        await connection.execute(insert, raw, upcoming, "d", False, True, admin_id)
        other = await connection.fetchval(
            "INSERT INTO site_host(hostname,verification_token,created_by) "
            "VALUES($1,$2,$3) RETURNING id",
            fixture.host("raw2"),
            "t" * 40,
            admin_id,
        )
        await unique_violation(
            connection, insert, other, upcoming, "d", False, True, admin_id
        )

        # A verified host without verified_at; redirect host with editions;
        # a redirect to a redirect host (M5).
        async def check_violation(sql: str, *args: object) -> None:
            try:
                async with connection.transaction():
                    await connection.execute(sql, *args)
            except asyncpg.CheckViolationError:
                return
            raise AssertionError(f"PostgreSQL accepted: {sql}")

        await check_violation(
            "INSERT INTO site_host(hostname,status,verification_token,created_by) "
            "VALUES($1,'verified',$2,$3)",
            fixture.host("unverified"),
            "t" * 40,
            admin_id,
        )
        await check_violation(
            "UPDATE site_host SET redirect_to_host_id=$2 WHERE id=$1", raw, other
        )
        target = await connection.fetchval(
            "INSERT INTO site_host(hostname,verification_token,created_by) "
            "VALUES($1,$2,$3) RETURNING id",
            fixture.host("raw3"),
            "t" * 40,
            admin_id,
        )
        await connection.execute(
            "UPDATE site_host SET redirect_to_host_id=$2 WHERE id=$1", other, target
        )
        await check_violation(
            "UPDATE site_host SET redirect_to_host_id=$2 WHERE id=$1", target, raw
        )
        await check_violation(insert, other, running, "e", False, False, admin_id)
        for bad in ("Upper.example.org", "no_underscore.example.org", "single"):
            try:
                async with connection.transaction():
                    await connection.execute(
                        "INSERT INTO site_host(hostname,verification_token,created_by) "
                        "VALUES($1,$2,$3)",
                        bad,
                        "t" * 40,
                        admin_id,
                    )
            except asyncpg.CheckViolationError:
                continue
            raise AssertionError(f"PostgreSQL accepted hostname {bad}")
    finally:
        await fixture.cleanup()
        await connection.close()
    print(
        "site-hosts-api: OK: system-admin only, idempotent and revision-checked "
        "commands, history rows, redirect hosts, removal and re-add, indexes"
    )


def test_site_hosts_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
