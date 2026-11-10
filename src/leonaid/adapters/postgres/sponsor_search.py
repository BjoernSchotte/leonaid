"""PostgreSQL side of the sponsor search index (``sponsor_search_entry``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, cast
from uuid import UUID

import asyncpg

from leonaid.application.crm import CrmPartyKind
from leonaid.application.sponsor_search import (
    PartyKey,
    SponsorParty,
    SponsorSearchIndex,
    SyncState,
)
from leonaid.domain.privacy import PrivacyReference

# One worker at a time runs the sync (session advisory lock).
SPONSOR_SEARCH_SYNC_LOCK = 527064

# $1 kind, $2 ids, $3 names, $4 cities, $5 synced_at. An erased entry keeps
# its marker: the sync must not bring the name back while Twenty still has
# the party.
_WRITE = """
INSERT INTO sponsor_search_entry (
    party_kind, twenty_id, display_name, city, synced_at
)
SELECT $1::text, party.twenty_id, party.display_name, party.city, $5
FROM unnest($2::uuid[], $3::text[], $4::text[])
    AS party(twenty_id, display_name, city)
ON CONFLICT (party_kind, twenty_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    city = EXCLUDED.city,
    synced_at = EXCLUDED.synced_at
WHERE sponsor_search_entry.erased_at IS NULL
"""

# The same write for a new assignment: it ends an erasure marker.
_WRITE_FOR_NEW_ASSIGNMENT = _WRITE.replace(
    "    synced_at = EXCLUDED.synced_at\n",
    "    synced_at = EXCLUDED.synced_at,\n    erased_at = NULL\n",
).replace("WHERE sponsor_search_entry.erased_at IS NULL\n", "")

_REFRESH = """
UPDATE sponsor_search_entry AS entry
SET display_name = party.display_name,
    city = party.city,
    synced_at = $5
FROM unnest($2::uuid[], $3::text[], $4::text[])
    AS party(twenty_id, display_name, city)
WHERE entry.party_kind = $1
  AND entry.twenty_id = party.twenty_id
  AND entry.erased_at IS NULL
"""

# The parties the privacy erasure treats as the subject's: those of the
# orders and of the consent records that carry the e-mail address. Every one
# gets the marker, also a party without an entry (first full pass not done,
# worker without CRM key, Twenty down): otherwise the next full pass would
# write its name. The full pass deletes markers of parties without an
# assignment.
_ERASE_SUBJECT_PARTIES = """
WITH subject AS (
    SELECT twenty_company_id, twenty_person_id
    FROM commitment
    WHERE lower(COALESCE(customer_snapshot ->> 'email', '')) = $1
       OR lower(COALESCE(invoice_recipient_snapshot ->> 'email', '')) = $1
       OR lower(COALESCE(delivery_recipient_snapshot ->> 'email', '')) = $1
    UNION
    SELECT twenty_company_id, twenty_person_id
    FROM consent_record
    WHERE normalized_recipient = $1
),
party AS (
    SELECT 'company' AS party_kind, twenty_company_id AS twenty_id
    FROM subject
    WHERE twenty_company_id IS NOT NULL
    UNION
    SELECT 'person', twenty_person_id
    FROM subject
    WHERE twenty_person_id IS NOT NULL
)
INSERT INTO sponsor_search_entry (
    party_kind, twenty_id, display_name, city, synced_at, erased_at
)
SELECT party_kind, twenty_id, NULL, NULL, $2, $2
FROM party
-- A fixed order keeps this from deadlocking with a batch of the sync.
ORDER BY party_kind, twenty_id
ON CONFLICT (party_kind, twenty_id) DO UPDATE
SET display_name = NULL,
    city = NULL,
    erased_at = EXCLUDED.erased_at
WHERE sponsor_search_entry.erased_at IS NULL
"""


def _affected(status: str) -> int:
    return int(status.rsplit(" ", 1)[-1])


def _columns(
    parties: tuple[SponsorParty, ...],
) -> dict[CrmPartyKind, tuple[list[UUID], list[str], list[str | None]]]:
    by_kind: dict[CrmPartyKind, tuple[list[UUID], list[str], list[str | None]]] = {}
    for party in parties:
        ids, names, cities = by_kind.setdefault(party.key.kind, ([], [], []))
        ids.append(party.key.twenty_id)
        names.append(party.display_name)
        cities.append(party.city)
    return by_kind


async def write_sponsor_search_entries(
    connection: asyncpg.Connection[Any],
    parties: tuple[SponsorParty, ...],
    *,
    synced_at: datetime,
    new_assignment: bool = False,
) -> int:
    """Add or update entries on the caller's transaction.

    An erased entry stays erased, except with ``new_assignment``: the caller
    just created an assignment for the party.
    """

    statement = _WRITE_FOR_NEW_ASSIGNMENT if new_assignment else _WRITE
    written = 0
    for kind, (ids, names, cities) in _columns(parties).items():
        written += _affected(
            await connection.execute(
                statement, kind.value, ids, names, cities, synced_at
            )
        )
    return written


class AsyncpgSponsorSearchIndex(SponsorSearchIndex):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def exclusive_run(self) -> AsyncIterator[bool]:
        async with self._pool.acquire() as connection:
            acquired = bool(
                await connection.fetchval(
                    "SELECT pg_try_advisory_lock($1)", SPONSOR_SEARCH_SYNC_LOCK
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.fetchval(
                        "SELECT pg_advisory_unlock($1)", SPONSOR_SEARCH_SYNC_LOCK
                    )

    async def sync_state(self) -> SyncState:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT full_pass_completed_at, full_pass_after_kind,
                       full_pass_after_id, changed_pass_read_until
                FROM sponsor_search_sync
                """
            )
        if row is None:
            raise RuntimeError("sponsor_search_sync has no row.")
        after = (
            PartyKey(
                CrmPartyKind(str(row["full_pass_after_kind"])),
                row["full_pass_after_id"],
            )
            if row["full_pass_after_kind"] is not None
            else None
        )
        return SyncState(
            full_pass_completed_at=row["full_pass_completed_at"],
            full_pass_after=after,
            changed_read_until=row["changed_pass_read_until"],
        )

    async def delete_unreferenced(self) -> int:
        async with self._pool.acquire() as connection:
            status = await connection.execute(
                """
                DELETE FROM sponsor_search_entry AS entry
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM acquisition_assignment AS assignment
                    WHERE entry.twenty_id = coalesce(
                            assignment.twenty_company_id,
                            assignment.twenty_person_id
                          )
                      AND entry.party_kind = CASE
                            WHEN assignment.twenty_company_id IS NOT NULL
                            THEN 'company'
                            ELSE 'person'
                          END
                )
                """
            )
        return _affected(status)

    async def referenced_parties(
        self, after: PartyKey | None, limit: int
    ) -> tuple[PartyKey, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT party_kind, twenty_id
                FROM (
                    SELECT 'company' AS party_kind, twenty_company_id AS twenty_id
                    FROM acquisition_assignment
                    WHERE twenty_company_id IS NOT NULL
                    UNION
                    SELECT 'person', twenty_person_id
                    FROM acquisition_assignment
                    WHERE twenty_person_id IS NOT NULL
                ) AS party
                WHERE $1::text IS NULL
                   OR (party_kind, twenty_id) > ($1::text, $2::uuid)
                ORDER BY party_kind, twenty_id
                LIMIT $3
                """,
                after.kind.value if after is not None else None,
                after.twenty_id if after is not None else None,
                limit,
            )
        return tuple(
            PartyKey(CrmPartyKind(str(row["party_kind"])), row["twenty_id"])
            for row in rows
        )

    async def store_full_batch(
        self,
        read: tuple[PartyKey, ...],
        found: tuple[SponsorParty, ...],
        *,
        synced_at: datetime,
    ) -> tuple[int, int]:
        if not read:
            return 0, 0
        present = {party.key for party in found}
        deleted = 0
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                written = await write_sponsor_search_entries(
                    connection, found, synced_at=synced_at
                )
                gone: dict[CrmPartyKind, list[UUID]] = {}
                for key in read:
                    if key not in present:
                        gone.setdefault(key.kind, []).append(key.twenty_id)
                for kind, ids in gone.items():
                    deleted += _affected(
                        await connection.execute(
                            "DELETE FROM sponsor_search_entry "
                            "WHERE party_kind = $1 AND twenty_id = ANY($2::uuid[])",
                            kind.value,
                            ids,
                        )
                    )
                await connection.execute(
                    "UPDATE sponsor_search_sync "
                    "SET full_pass_after_kind = $1, full_pass_after_id = $2",
                    read[-1].kind.value,
                    read[-1].twenty_id,
                )
        return written, deleted

    async def finish_full_pass(self, completed_at: datetime) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE sponsor_search_sync "
                "SET full_pass_completed_at = $1, "
                "full_pass_after_kind = NULL, full_pass_after_id = NULL",
                completed_at,
            )

    async def finish_changed_pass(self, read_until: datetime) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE sponsor_search_sync SET changed_pass_read_until = $1",
                read_until,
            )

    async def refresh(
        self, parties: tuple[SponsorParty, ...], *, synced_at: datetime
    ) -> int:
        if not parties:
            return 0
        refreshed = 0
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                for kind, (ids, names, cities) in _columns(parties).items():
                    refreshed += _affected(
                        await connection.execute(
                            _REFRESH, kind.value, ids, names, cities, synced_at
                        )
                    )
        return refreshed


class SponsorSearchPrivacyContributor:
    """Removes the name and city of an erased party from the search index.

    Every party of the subject gets a marker row (``erased_at``) without any
    personal data, whether it had an entry or not: the party still exists in
    Twenty until the manual CRM deletion, and the sync must not copy its name
    back. The marker ends with a new assignment for the party; the nightly
    full pass deletes it once Twenty no longer has the party or its last
    assignment is gone. The index adds no reference of its own to
    the subject report: it holds a name only for parties with an assignment,
    and the report lists those assignments already.
    """

    async def references(
        self, connection: object, normalized_email: str
    ) -> tuple[PrivacyReference, ...]:
        return ()

    async def anonymize(
        self, connection: object, normalized_email: str, occurred_at: datetime
    ) -> int:
        status = await cast("asyncpg.Connection[Any]", connection).execute(
            _ERASE_SUBJECT_PARTIES, normalized_email, occurred_at
        )
        return _affected(status)
