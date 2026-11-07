"""Public reads of campaign hosts (specs/multi-domain §7.2, §7.3, §7.6).

What a campaign host serves, the canonical URL of actions, the permanent
edition URL for mails and the active hostnames for the public origin check.
Only ``active`` hosts are public.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import asyncpg

from leonaid.adapters.postgres.site_hosts import (
    _ACTION_COLUMNS,
    _ALIAS_JOIN,
    _BINDING_SELECT,
    CanonicalResolver,
    live_edition,
)
from leonaid.domain.site_hosts import (
    EditionAvailability,
    RootDecision,
    edition_canonical_url,
    edition_url,
    redirect_status,
    root_decision,
    serving_edition,
)


@dataclass(frozen=True, slots=True)
class PublicEdition:
    segment: str
    at_root: bool
    is_primary: bool
    archive_slug: str
    availability: EditionAvailability
    title: str
    starts_on: date
    ends_on: date
    edition_url: str
    canonical_url: str | None


@dataclass(frozen=True, slots=True)
class PublicHistory:
    segment: str
    archive_slug: str
    target_url: str
    status: int


@dataclass(frozen=True, slots=True)
class PublicSite:
    hostname: str
    kind: str
    redirect_to: str | None
    root: RootDecision | None
    editions: tuple[PublicEdition, ...]
    history: tuple[PublicHistory, ...]


class AsyncpgSiteDirectory:
    def __init__(self, pool: asyncpg.Pool[Any], canonical: CanonicalResolver) -> None:
        self._pool = pool
        self._canonical = canonical

    async def site(self, hostname: str) -> PublicSite | None:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as db:
            async with db.transaction(isolation="repeatable_read", readonly=True):
                host = await db.fetchrow(
                    "SELECT h.id, h.hostname, h.redirect_to_host_id, "
                    "t.hostname AS target, t.status AS target_status "
                    "FROM site_host h LEFT JOIN site_host t ON t.id = h.redirect_to_host_id "
                    "WHERE h.hostname=$1 AND h.status='active'",
                    hostname,
                )
                if host is None:
                    return None
                if host["redirect_to_host_id"] is not None:
                    if host["target_status"] != "active":
                        return None
                    return PublicSite(
                        hostname, "redirect", f"https://{host['target']}", None, (), ()
                    )
                rows = await db.fetch(
                    _BINDING_SELECT + " WHERE b.site_host_id=$1 "
                    "ORDER BY b.valid_from DESC, b.id",
                    host["id"],
                )
                live = [row for row in rows if row["valid_to"] is None]
                history = [row for row in rows if row["valid_to"] is not None]
                canonical = await self._canonical.for_actions(
                    db, {row["action_id"] for row in rows}, now
                )
        editions = [live_edition(row, now) for row in live]
        ended = sorted(
            (
                row
                for row, edition in zip(live, editions, strict=True)
                if edition.availability is EditionAvailability.ARCHIVE
            ),
            key=lambda row: (
                row["publication_ends_at"] or datetime.min.replace(tzinfo=timezone.utc),
                row["ends_on"],
            ),
            reverse=True,
        )
        public = tuple(
            PublicEdition(
                segment=row["edition_segment"],
                at_root=row["at_root"],
                is_primary=row["is_primary"],
                archive_slug=row["archive_slug"],
                availability=edition.availability,
                title=row["action_name"],
                starts_on=row["starts_on"],
                ends_on=row["ends_on"],
                edition_url=edition_url(edition),
                canonical_url=canonical.get(row["action_id"]),
            )
            for row, edition in zip(live, editions, strict=True)
            if edition.availability is not EditionAvailability.INACTIVE
        )
        live_segments = {row["edition_segment"] for row in live}
        seen: set[str] = set()
        moved: list[PublicHistory] = []
        # Newest first: the newest history row of a segment wins.
        for row in sorted(history, key=lambda item: item["valid_to"], reverse=True):
            segment = row["edition_segment"]
            if segment in live_segments or segment in seen:
                continue
            seen.add(segment)
            target = canonical.get(row["action_id"])
            if target is None:
                continue
            moved.append(
                PublicHistory(
                    segment, row["archive_slug"], target, redirect_status(target)
                )
            )
        return PublicSite(
            hostname=hostname,
            kind="campaign",
            redirect_to=None,
            root=root_decision(
                editions, ended_order=[row["edition_segment"] for row in ended]
            ),
            editions=public,
            history=tuple(moved),
        )

    async def canonical_urls(
        self, action_ids: Iterable[UUID]
    ) -> dict[UUID, str | None]:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as db:
            return await self._canonical.for_actions(db, action_ids, now)

    async def edition_link(self, action_id: UUID) -> str | None:
        """The permanent edition URL for an order confirmation (D8, §7.6).

        The edition of the canonical binding on its campaign host, else the
        action's page on the public host, else no link.
        """
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as db:
            rows = await db.fetch(
                _BINDING_SELECT + " WHERE b.action_id=$1 AND b.valid_to IS NULL",
                action_id,
            )
            edition = serving_edition([live_edition(row, now) for row in rows])
            if edition is not None:
                return edition_url(edition)
            action = await db.fetchrow(
                f"SELECT {_ACTION_COLUMNS} FROM charity_action AS a {_ALIAS_JOIN} "
                "WHERE a.id=$1",
                action_id,
            )
        if action is None:
            return None
        return self._canonical.public_fallback(action, now)

    async def campaign_host_urls(self, action_ids: Iterable[UUID]) -> dict[UUID, str]:
        """Canonical URLs of the actions that live on an active campaign host.

        Actions without one are absent: their pages stay on the public host.
        """
        ids = sorted(set(action_ids))
        if not ids:
            return {}
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as db:
            rows = await db.fetch(
                _BINDING_SELECT + " WHERE b.action_id = ANY($1::uuid[]) "
                "AND b.valid_to IS NULL AND h.status='active'",
                ids,
            )
        grouped: dict[UUID, list[Any]] = {}
        for row in rows:
            grouped.setdefault(row["action_id"], []).append(live_edition(row, now))
        result: dict[UUID, str] = {}
        for action_id, editions in grouped.items():
            edition = serving_edition(editions)
            if edition is not None:
                result[action_id] = edition_canonical_url(edition)
        return result

    async def campaign_host_url_for_slug(self, archive_slug: str) -> str | None:
        async with self._pool.acquire() as db:
            action_id = await db.fetchval(
                "SELECT id FROM charity_action WHERE archive_slug=$1", archive_slug
            )
        if action_id is None:
            return None
        return (await self.campaign_host_urls([action_id])).get(action_id)

    async def is_active(self, hostname: str) -> bool:
        async with self._pool.acquire() as db:
            return bool(
                await db.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM site_host WHERE hostname=$1 "
                    "AND status='active' AND redirect_to_host_id IS NULL)",
                    hostname,
                )
            )


class SiteHostPublicOrigins:
    """Public origins: the static list plus every active campaign host (§6.3).

    A host added a minute ago works without a restart (D7). Lookups are
    cached for 30 s, positive and negative.
    """

    TTL_SECONDS = 30.0

    def __init__(
        self,
        static: tuple[str, ...],
        directory: AsyncpgSiteDirectory,
        *,
        production: bool = True,
    ) -> None:
        self._production = production
        self._static = static
        self._directory = directory
        self._cache: dict[str, tuple[float, bool]] = {}

    async def allows(self, origin: str, request_host: str) -> bool:
        if origin.rstrip("/").casefold() in self._static:
            return True
        parts = urlsplit(origin.rstrip("/").casefold())
        # Production edges serve 443 only; dev stacks use another port.
        if (
            parts.scheme != "https"
            or not parts.hostname
            or (self._production and parts.port not in (None, 443))
        ):
            return False
        hostname = parts.hostname
        cached = self._cache.get(hostname)
        now = time.monotonic()
        if cached is not None and now - cached[0] < self.TTL_SECONDS:
            return cached[1]
        active = await self._directory.is_active(hostname)
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[hostname] = (now, active)
        return active


__all__ = [
    "AsyncpgSiteDirectory",
    "PublicEdition",
    "PublicHistory",
    "PublicSite",
    "SiteHostPublicOrigins",
]
