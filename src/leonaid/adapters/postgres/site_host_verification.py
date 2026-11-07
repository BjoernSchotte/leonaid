"""Host checks, TLS approval and re-checks in PostgreSQL (specs/multi-domain §7.4, §9.1).

The network part of a check runs outside any transaction; its result is
applied afterwards in one short transaction that re-reads the host and
ignores the result when hostname or token changed in between (a re-add).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import ResourceNotFound
from leonaid.application.site_hosts import CheckTarget
from leonaid.domain.site_hosts import (
    TLS_APPROVED_STATUSES,
    HostCheckOutcome,
    SiteHostStatus,
    check_transition,
)

# Approvals of hosts that never had a certificate, per hour (§9.1).
TLS_NEW_APPROVALS_PER_HOUR = 10
TLS_APPROVAL_LOCK = 527062
# A host is re-checked when its last check is older than this.
RECHECK_AFTER = timedelta(hours=20)
SNAPSHOT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class CheckRecord:
    status: SiteHostStatus
    previous_status: SiteHostStatus
    message: str


@dataclass(frozen=True, slots=True)
class SiteHostIssue:
    """A host the operations view should show (§7.4)."""

    hostname: str
    status: SiteHostStatus
    failed_checks: int
    last_check_result: str | None
    last_checked_at: datetime | None
    live_bindings: int


@dataclass(frozen=True, slots=True)
class _HostState:
    status: SiteHostStatus
    token: str
    tls_approved: bool


class AsyncpgSiteHostVerification:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool
        self._snapshot: dict[str, _HostState] | None = None
        self._snapshot_at = 0.0
        self._snapshot_lock = asyncio.Lock()
        # Observable for tests: one query per refresh.
        self.snapshot_queries = 0

    async def target(self, host_id: UUID) -> CheckTarget:
        async with self._pool.acquire() as db:
            row = await db.fetchrow(
                "SELECT h.id, h.hostname, h.verification_token, h.status, "
                "EXISTS(SELECT 1 FROM site_binding b WHERE b.site_host_id=h.id "
                "AND b.valid_to IS NULL) AS live "
                "FROM site_host h WHERE h.id=$1",
                host_id,
            )
        if row is None:
            raise ResourceNotFound("site_host_not_found", "Host nicht gefunden.")
        return _target(row)

    async def due(self, now: datetime) -> list[CheckTarget]:
        """Hosts for the periodic re-check.

        Verified hosts wait for their certificate: 20 min in the first hour,
        then hourly, then every 6 h, then daily, so failed issuance stays well
        below Let's Encrypt's 5 failed validations per name and hour (each TLS
        check may start an ACME order). Active hosts and disabled hosts with
        live bindings once per day.
        """
        async with self._pool.acquire() as db:
            rows = await db.fetch(
                """
                SELECT h.id, h.hostname, h.verification_token, h.status,
                       EXISTS(SELECT 1 FROM site_binding b WHERE b.site_host_id=h.id
                              AND b.valid_to IS NULL) AS live
                FROM site_host h
                WHERE (h.status = 'verified' AND (
                        h.last_checked_at IS NULL
                        OR h.last_checked_at < $2::timestamptz - CASE
                          WHEN h.verified_at > $2::timestamptz - interval '1 hour' THEN interval '20 minutes'
                          WHEN h.verified_at > $2::timestamptz - interval '6 hours' THEN interval '1 hour'
                          WHEN h.verified_at > $2::timestamptz - interval '24 hours' THEN interval '6 hours'
                          ELSE interval '20 hours' END))
                   OR (h.status = 'active'
                       AND (h.last_checked_at IS NULL OR h.last_checked_at < $1))
                   OR (h.status = 'disabled'
                       AND (h.last_checked_at IS NULL OR h.last_checked_at < $1)
                       AND EXISTS(SELECT 1 FROM site_binding b
                                  WHERE b.site_host_id=h.id AND b.valid_to IS NULL))
                ORDER BY h.last_checked_at NULLS FIRST, h.hostname
                LIMIT 50
                """,
                now - RECHECK_AFTER,
                now,
            )
        return [_target(row) for row in rows]

    async def record(
        self,
        target: CheckTarget,
        outcome: HostCheckOutcome,
        *,
        now: datetime,
        actor_id: UUID | None,
        request_id: str,
    ) -> CheckRecord | None:
        """Apply one outcome; None when the host changed meanwhile."""
        async with self._pool.acquire() as db:
            async with db.transaction():
                await db.execute("SET LOCAL lock_timeout='3s'")
                row = await db.fetchrow(
                    "SELECT * FROM site_host WHERE id=$1 FOR UPDATE", target.id
                )
                if (
                    row is None
                    or row["hostname"] != target.hostname
                    or row["verification_token"] != target.token
                ):
                    return None
                live = await db.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM site_binding WHERE site_host_id=$1 "
                    "AND valid_to IS NULL)",
                    target.id,
                )
                previous = SiteHostStatus(row["status"])
                transition = check_transition(
                    status=previous,
                    has_live_bindings=bool(live),
                    consecutive_failures=row["consecutive_failures"],
                    failing_since=row["failing_since"],
                    outcome=outcome,
                    now=now,
                )
                message = outcome.message
                if (
                    previous is SiteHostStatus.DISABLED
                    and transition.status is SiteHostStatus.DISABLED
                    and not live
                ):
                    message = "Domain entfernt. Bitte neu eintragen, um sie zu prüfen."
                await db.execute(
                    """
                    UPDATE site_host
                    SET status=$2, consecutive_failures=$3, failing_since=$4,
                        last_checked_at=$5, last_check_result=$6,
                        verified_at=CASE WHEN $7 THEN $5 ELSE verified_at END,
                        revision=CASE WHEN status<>$2 THEN revision+1 ELSE revision END,
                        updated_at=clock_timestamp()
                    WHERE id=$1
                    """,
                    target.id,
                    transition.status.value,
                    transition.consecutive_failures,
                    transition.failing_since,
                    now,
                    message[:500],
                    transition.verified_now,
                )
                if transition.status is not previous:
                    await db.execute(
                        "INSERT INTO audit_event(id,action_id,actor_user_id,event_type,"
                        "entity_type,entity_id,request_id,payload) "
                        "VALUES($1,NULL,$2,'site_host.status_changed','site_host',$3,$4,$5::jsonb)",
                        uuid4(),
                        actor_id,
                        target.id,
                        request_id,
                        json.dumps(
                            {
                                "previousStatus": previous.value,
                                "status": transition.status.value,
                                "consecutiveFailures": transition.consecutive_failures,
                                "result": message[:200],
                            }
                        ),
                    )
                self.invalidate()
                return CheckRecord(transition.status, previous, message)

    # ---------- in-process snapshot (§9.1) ----------
    #
    # Caddy asks on every handshake for a name it has no certificate for, and
    # port 80 answers the check path for any requester. Both read this
    # snapshot of the few site hosts instead of the database, so a flood of
    # junk names or tokens costs no query. Refreshed at most every
    # SNAPSHOT_SECONDS by one request at a time; commands and checks of this
    # process invalidate it.

    async def _hosts(self) -> dict[str, _HostState]:
        now = time.monotonic()
        if self._snapshot is not None and now - self._snapshot_at < SNAPSHOT_SECONDS:
            return self._snapshot
        async with self._snapshot_lock:
            if (
                self._snapshot is not None
                and time.monotonic() - self._snapshot_at < SNAPSHOT_SECONDS
            ):
                return self._snapshot
            async with self._pool.acquire() as db:
                rows = await db.fetch(
                    "SELECT hostname, status, verification_token, tls_approved_at "
                    "FROM site_host"
                )
            self.snapshot_queries += 1
            self._snapshot = {
                row["hostname"]: _HostState(
                    SiteHostStatus(row["status"]),
                    row["verification_token"],
                    row["tls_approved_at"] is not None,
                )
                for row in rows
            }
            self._snapshot_at = time.monotonic()
            return self._snapshot

    def invalidate(self) -> None:
        self._snapshot = None

    async def answers(self, hostname: str, token: str) -> bool:
        """The check path of ``hostname`` with ``token`` belongs to us."""
        state = (await self._hosts()).get(hostname)
        return state is not None and hmac.compare_digest(
            state.token.encode(), token.encode()
        )

    async def approve_tls(self, hostname: str, now: datetime) -> bool:
        """Caddy's on-demand ``ask`` (§9.1): verified or active hosts only.

        A host that never had a certificate counts against at most
        TLS_NEW_APPROVALS_PER_HOUR new approvals per hour.
        """
        state = (await self._hosts()).get(hostname)
        if state is None or state.status not in TLS_APPROVED_STATUSES:
            return False
        if state.tls_approved:
            return True
        try:
            async with self._pool.acquire() as db:
                async with db.transaction():
                    await db.execute("SET LOCAL lock_timeout='3s'")
                    await db.execute(
                        "SELECT pg_advisory_xact_lock($1)", TLS_APPROVAL_LOCK
                    )
                    recent = await db.fetchval(
                        "SELECT count(*) FROM site_host WHERE tls_approved_at > $1",
                        now - timedelta(hours=1),
                    )
                    if int(recent) >= TLS_NEW_APPROVALS_PER_HOUR:
                        return False
                    approved = await db.fetchval(
                        "UPDATE site_host SET tls_approved_at=COALESCE(tls_approved_at,$2) "
                        "WHERE hostname=$1 AND status IN ('verified','active') "
                        "RETURNING true",
                        hostname,
                        now,
                    )
        except BaseException:
            self.invalidate()
            raise
        # Only a stored approval changes the snapshot; a refusal under the
        # hourly limit must not make every handshake reload it (review N1).
        if approved:
            self.invalidate()
        return bool(approved)

    async def issues(self) -> tuple[SiteHostIssue, ...]:
        async with self._pool.acquire() as db:
            rows = await db.fetch(
                """
                SELECT h.hostname, h.status, h.consecutive_failures,
                       h.last_check_result, h.last_checked_at,
                       (SELECT count(*) FROM site_binding b
                        WHERE b.site_host_id=h.id AND b.valid_to IS NULL) AS live
                FROM site_host h
                WHERE h.consecutive_failures > 0
                   OR (h.status = 'disabled' AND EXISTS(
                        SELECT 1 FROM site_binding b
                        WHERE b.site_host_id=h.id AND b.valid_to IS NULL))
                   OR h.status = 'verified'
                ORDER BY h.status = 'disabled' DESC, h.consecutive_failures DESC,
                         h.hostname
                LIMIT 50
                """
            )
        return tuple(
            SiteHostIssue(
                hostname=row["hostname"],
                status=SiteHostStatus(row["status"]),
                failed_checks=row["consecutive_failures"],
                last_check_result=row["last_check_result"],
                last_checked_at=row["last_checked_at"],
                live_bindings=int(row["live"]),
            )
            for row in rows
        )


def _target(row: asyncpg.Record) -> CheckTarget:
    return CheckTarget(
        id=row["id"],
        hostname=row["hostname"],
        token=row["verification_token"],
        status=SiteHostStatus(row["status"]),
        has_live_bindings=bool(row["live"]),
    )
