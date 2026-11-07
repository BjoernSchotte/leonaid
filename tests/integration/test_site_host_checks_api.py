#!/usr/bin/env python3
"""Host check, TLS ask and operations view over HTTP and real PostgreSQL.

specs/multi-domain §7.4, §9.1: the check path answers only for a known
(host, token) pair; Prüfen moves pending → verified → active; the ask
endpoint approves verified and active hosts only, refuses proxied requests
and at most 10 first approvals per hour; failing hosts appear in the
operations view, and three failures over 72 h disable a host. Runs as a
contract script in the schema gate and, with CORE_DATABASE_URL, under pytest.
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
from leonaid.domain.site_hosts import HostCheckOutcome, check_answer
from leonaid.entrypoints.fastapi.platform import create_app

ADMIN = "https://app.checks.leonaid.invalid"
PUBLIC = "https://checks.leonaid.invalid"


def settings() -> Settings:
    return Settings.model_validate(
        {
            "LEONAID_ENV": "test",
            "CORE_DATABASE_URL": os.environ["CORE_DATABASE_URL"],
            "LEONAID_SECRET_KEY": "synthetic-host-checks-proof-secret-only-32",
            "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-host-checks-proof-encrypt-32c",
            "LEONAID_PUBLIC_BASE_URL": ADMIN,
            "LEONAID_SITE_BASE_URL": PUBLIC,
            "LEONAID_ALLOWED_ORIGINS": ADMIN,
            "LEONAID_PUBLIC_ORIGINS": PUBLIC,
            "TWENTY_BASE_URL": "http://127.0.0.1:9",
            "TWENTY_HEALTH_URL": "http://127.0.0.1:9/health",
            "RUSTFS_HEALTH_URL": "http://127.0.0.1:9/health",
            "OBJECT_STORAGE_ENDPOINT_URL": "http://127.0.0.1:9",
            "OBJECT_STORAGE_BUCKET": "leonaid",
            "OBJECT_STORAGE_ACCESS_KEY": "synthetic-proof",
            "OBJECT_STORAGE_SECRET_KEY": "synthetic-proof",
        }
    )


class FakeProbe:
    """Stands in for the network: the next outcome per hostname."""

    def __init__(self) -> None:
        self.outcomes: dict[str, HostCheckOutcome] = {}
        self.calls: list[str] = []

    async def check(
        self, hostname: str, token: str, *, tls: bool = True
    ) -> HostCheckOutcome:
        self.calls.append(hostname)
        return self.outcomes[hostname]


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    db = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    tag = uuid4().hex[:8]
    admin_id = uuid4()
    token = f"host-checks-proof-{tag}-{uuid4().hex}"
    hosts: list[UUID] = []

    def name(label: str) -> str:
        return f"{label}-{tag}.example.org"

    async def host(label: str, status: str = "pending", **fields: Any) -> UUID:
        host_id = uuid4()
        hosts.append(host_id)
        await db.execute(
            "INSERT INTO site_host(id,hostname,status,verification_token,created_by,"
            "consecutive_failures,failing_since,tls_approved_at,verified_at) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,"
            "CASE WHEN $3 IN ('verified','active') THEN now() END)",
            host_id,
            name(label),
            status,
            f"{label}-token-{tag}-{'x' * 24}",
            admin_id,
            fields.get("failures", 0),
            fields.get("since"),
            fields.get("approved"),
        )
        return host_id

    try:
        await db.execute(
            "INSERT INTO user_account (id, email, display_name, status) "
            "VALUES ($1, $2, 'Sys', 'active')",
            admin_id,
            f"sys.{tag}@leonaid.invalid",
        )
        await db.execute(
            "INSERT INTO user_global_role (user_id, role) VALUES ($1, 'system_admin')",
            admin_id,
        )
        now = datetime.now(timezone.utc)
        await db.execute(
            "INSERT INTO user_session (id, user_id, token_digest, expires_at, "
            "last_seen_at, fresh_login_at, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5, $5, $5, $5)",
            uuid4(),
            admin_id,
            hashlib.sha256(token.encode()).hexdigest(),
            now + timedelta(days=90),
            now,
        )
        krapfen = await host("krapfentaxi")
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            probe = FakeProbe()
            app.state.site_host_service._probe = probe
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://edge"
            ) as client:
                cookie = {"Cookie": f"__Host-leonaid_session={token}"}

                # The check path answers only for its own (host, token) pair.
                nonce = "ab" * 16
                path = (
                    f"/.well-known/leonaid-host-check/krapfentaxi-token-{tag}-"
                    f"{'x' * 24}?nonce={nonce}"
                )
                response = await client.get(
                    path, headers={"Host": name("krapfentaxi") + ":80"}
                )
                assert response.status_code == 200, response.text
                assert response.headers["cache-control"] == "no-store"
                secret = app.state.site_host_check_secret
                assert response.text == check_answer(
                    secret,
                    name("krapfentaxi"),
                    f"krapfentaxi-token-{tag}-{'x' * 24}",
                    nonce,
                )
                # Without a nonce, no answer: nothing to replay.
                response = await client.get(
                    path.split("?")[0], headers={"Host": name("krapfentaxi")}
                )
                assert response.status_code == 404
                for host_header in (name("other"), "app.checks.leonaid.invalid"):
                    response = await client.get(path, headers={"Host": host_header})
                    assert response.status_code == 404
                    assert response.json()["error"]["code"] == "site_host_check_unknown"

                async def ask(domain: str, **headers: str) -> int:
                    reply = await client.get(
                        "/internal/tls/ask", params={"domain": domain}, headers=headers
                    )
                    return reply.status_code

                # Pending: no certificate.
                assert await ask(name("krapfentaxi")) == 403

                # A flood of junk names and tokens costs no database query
                # beyond one snapshot refresh (review I2, M4).
                verification = app.state.site_host_verification
                verification.invalidate()
                before = verification.snapshot_queries
                for index in range(1000):
                    assert await ask(f"junk{index}-{tag}.example.net") == 403
                    response = await client.get(
                        f"/.well-known/leonaid-host-check/{'y' * 40}{index}"
                        f"?nonce={nonce}",
                        headers={"Host": f"junk{index}-{tag}.example.net"},
                    )
                    assert response.status_code == 404
                assert verification.snapshot_queries - before <= 1
                # Configured hosts never get an on-demand certificate.
                assert await ask("app.checks.leonaid.invalid") == 403
                assert await ask("checks.leonaid.invalid") == 403

                # Prüfen: name points here, no certificate yet → verified.
                probe.outcomes[name("krapfentaxi")] = HostCheckOutcome(
                    True, False, "Noch kein Zertifikat."
                )
                checked = await client.post(
                    f"/api/v1/admin/site-hosts/{krapfen}/check",
                    headers={
                        **cookie,
                        "Origin": ADMIN,
                        "Host": "app.checks.leonaid.invalid",
                    },
                )
                assert checked.status_code == 200, checked.text
                assert checked.json()["status"] == "verified"
                assert checked.json()["verifiedAt"] is not None
                assert checked.json()["lastCheckResult"] == "Noch kein Zertifikat."
                assert await ask(name("krapfentaxi")) == 200
                assert await ask(name("KrapfenTaxi")) == 200
                # Only Caddy's own request: a proxied one is refused.
                assert (
                    await ask(name("krapfentaxi"), **{"X-Forwarded-For": "1.2.3.4"})
                    == 403
                )
                assert await ask("not a host") == 403
                assert await ask(name("unknown")) == 403

                # Certificate there → active.
                probe.outcomes[name("krapfentaxi")] = HostCheckOutcome(True, True, "ok")
                checked = await client.post(
                    f"/api/v1/admin/site-hosts/{krapfen}/check",
                    headers={
                        **cookie,
                        "Origin": ADMIN,
                        "Host": "app.checks.leonaid.invalid",
                    },
                )
                assert checked.json()["status"] == "active", checked.text

                # Rate limit: 10 first approvals per hour, renewals unaffected.
                for index in range(9):
                    await host(f"burst{index}", "verified", approved=now)
                fresh = await host("fresh", "verified")
                assert await ask(name("fresh")) == 403
                assert await ask(name("krapfentaxi")) == 200
                await db.execute(
                    "UPDATE site_host SET tls_approved_at = now() - interval '2 hours' "
                    "WHERE hostname LIKE $1",
                    f"burst%-{tag}.example.org",
                )
                assert await ask(name("fresh")) == 200
                assert await db.fetchval(
                    "SELECT tls_approved_at IS NOT NULL FROM site_host WHERE id=$1",
                    fresh,
                )

                # Periodic re-check: an active host failing for 72 h is disabled
                # and stops getting certificates; operations shows it.
                lapsed = await host(
                    "lapsed",
                    "active",
                    failures=2,
                    since=now - timedelta(hours=80),
                    approved=now - timedelta(days=30),
                )
                await db.execute(
                    "UPDATE site_host SET last_checked_at = now() - interval '2 days' "
                    "WHERE id=$1",
                    lapsed,
                )
                for label in [f"burst{index}" for index in range(9)] + ["fresh"]:
                    probe.outcomes[name(label)] = HostCheckOutcome(True, True, "ok")
                probe.outcomes[name("lapsed")] = HostCheckOutcome(
                    False, None, "Der Name ist im DNS nicht auflösbar."
                )
                await app.state.site_host_service.recheck_due(request_id="proof")
                assert name("lapsed") in probe.calls
                # Back-off (review M2): a host checked just now is not due
                # again within 20 minutes, also while it waits for TLS.
                await db.execute(
                    "UPDATE site_host SET status='verified', tls_approved_at=NULL "
                    "WHERE id=$1",
                    fresh,
                )
                due = {
                    target.hostname
                    for target in await verification.due(datetime.now(timezone.utc))
                }
                assert name("fresh") not in due, due
                due = {
                    target.hostname
                    for target in await verification.due(
                        datetime.now(timezone.utc) + timedelta(minutes=21)
                    )
                }
                assert name("fresh") in due, due
                assert name("krapfentaxi") not in probe.calls[2:]
                assert (
                    await db.fetchval(
                        "SELECT status FROM site_host WHERE id=$1", lapsed
                    )
                    == "disabled"
                )
                assert await ask(name("lapsed")) == 403
                assert (
                    await db.fetchval(
                        "SELECT count(*) FROM audit_event WHERE entity_id=$1 "
                        "AND event_type='site_host.status_changed'",
                        lapsed,
                    )
                    == 1
                )
                overview = await client.get(
                    "/api/v1/admin/operations",
                    headers={**cookie, "Host": "app.checks.leonaid.invalid"},
                )
                assert overview.status_code == 200, overview.text
                listed = {
                    item["hostname"]: item for item in overview.json()["siteHosts"]
                }
                assert listed[name("lapsed")]["failedChecks"] == 3, listed
                assert listed[name("lapsed")]["status"] == "disabled"
                assert name("krapfentaxi") not in listed
    finally:
        await db.execute(
            "DELETE FROM audit_event WHERE entity_id = ANY($1::uuid[])", hosts
        )
        await db.execute("DELETE FROM site_host WHERE id = ANY($1::uuid[])", hosts)
        await db.execute("DELETE FROM user_session WHERE user_id=$1", admin_id)
        await db.execute("DELETE FROM user_global_role WHERE user_id=$1", admin_id)
        await db.execute("DELETE FROM user_account WHERE id=$1", admin_id)
        await db.close()
    print(
        "site-host-checks-api: OK: check path, pending → verified → active, ask "
        "approval and rate limit, proxied ask refused, lapsed host disabled"
    )


def test_site_host_checks_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
