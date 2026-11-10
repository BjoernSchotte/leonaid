"""The sponsor search index and the sync that keeps it in step with Twenty.

Twenty stays the system of record for companies and people, and core keeps no
other copy of a CRM party. The one exception is ``sponsor_search_entry``: the
name and the city of every party that has an acquisition assignment, so the
core search can find sponsors without a CRM call per keystroke
(specs/mails-documents-donations-push §9, D-S1).

The index is filled in three ways:

- when an assignment is created, with the name core just read from Twenty;
- by the changed pass: parties that Twenty changed in the last 30 minutes and
  that are in the index;
- by the full pass, once a night: every referenced party is read again in ID
  batches. It adds missing entries and deletes entries without an assignment
  or without a CRM record. Polling cannot see a delete in Twenty; this pass
  is what removes such parties (D-S2).

One run spends at most ``SYNC_REQUEST_BUDGET`` CRM requests and stops on the
first 429: Twenty allows 100 requests a minute, the gateway counts them per
process, and the API needs the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from leonaid.application.crm import CrmGatewayError, CrmPartyKind

# CRM requests one run may spend.
SYNC_REQUEST_BUDGET = 30
# Parties per ID read; one read is one CRM request.
SYNC_ID_BATCH = 50
# The changed pass asks for parties changed within this window. It is twice
# the loop interval, so one missed run loses nothing.
CHANGED_WINDOW = timedelta(minutes=30)
# Seconds between two runs, and after a run that left a full pass unfinished.
# The short pause keeps the loop at SYNC_REQUEST_BUDGET requests a minute.
SYNC_INTERVAL_SECONDS = 15 * 60.0
SYNC_CONTINUE_SECONDS = 60.0
# A full pass is due once a day after this local time.
FULL_PASS_LOCAL_TIME = time(3, 0)


@dataclass(frozen=True, slots=True)
class PartyKey:
    """A CRM party. The full pass walks them ordered by kind, then id."""

    kind: CrmPartyKind
    twenty_id: UUID


# The widths of sponsor_search_entry; a longer CRM value is cut.
NAME_MAX_LENGTH = 401
CITY_MAX_LENGTH = 200


@dataclass(frozen=True, slots=True)
class SponsorParty:
    """What the index keeps of a CRM party: its name and its city."""

    key: PartyKey
    display_name: str
    city: str | None

    def __post_init__(self) -> None:
        name = " ".join(self.display_name.split())[:NAME_MAX_LENGTH].rstrip()
        if not name:
            raise ValueError("A sponsor search entry needs a name.")
        object.__setattr__(self, "display_name", name)
        city = " ".join((self.city or "").split())[:CITY_MAX_LENGTH].rstrip()
        object.__setattr__(self, "city", city or None)


@dataclass(frozen=True, slots=True)
class SponsorPartyPage:
    parties: tuple[SponsorParty, ...]
    # None after the last page.
    next_cursor: str | None


class SponsorPartySource(Protocol):
    """Reads of the sync. Every call is exactly one CRM request.

    Parties without a name are left out, as if the CRM did not have them.
    """

    async def sponsor_parties_by_id(
        self,
        kind: CrmPartyKind,
        twenty_ids: tuple[UUID, ...],
        *,
        correlation_id: str,
    ) -> tuple[SponsorParty, ...]:
        """At most ``SYNC_ID_BATCH`` ids."""
        ...

    async def sponsor_parties_changed_since(
        self,
        kind: CrmPartyKind,
        updated_since: datetime,
        *,
        cursor: str | None,
        correlation_id: str,
    ) -> SponsorPartyPage: ...


@dataclass(frozen=True, slots=True)
class SyncState:
    full_pass_completed_at: datetime | None
    # Where an unfinished full pass continues; None between passes.
    full_pass_after: PartyKey | None


class SponsorSearchIndex(Protocol):
    def exclusive_run(self) -> AbstractAsyncContextManager[bool]:
        """Yield True for the one worker that may run the sync now."""
        ...

    async def sync_state(self) -> SyncState: ...

    async def delete_unreferenced(self) -> int:
        """Delete the entries of parties without an assignment."""
        ...

    async def referenced_parties(
        self, after: PartyKey | None, limit: int
    ) -> tuple[PartyKey, ...]:
        """Parties with an assignment, in ``PartyKey`` order after ``after``."""
        ...

    async def store_full_batch(
        self,
        read: tuple[PartyKey, ...],
        found: tuple[SponsorParty, ...],
        *,
        synced_at: datetime,
    ) -> tuple[int, int]:
        """Write one batch of the full pass and move its cursor, atomically.

        Entries of ``found`` are written (an erased entry stays erased), the
        entries of ``read`` that the CRM no longer has are deleted. Returns
        (written, deleted).
        """
        ...

    async def finish_full_pass(self, completed_at: datetime) -> None: ...

    async def refresh(
        self, parties: tuple[SponsorParty, ...], *, synced_at: datetime
    ) -> int:
        """Update the entries that exist and are not erased; add none."""
        ...


@dataclass(frozen=True, slots=True)
class SyncReport:
    # "skipped" (another worker runs), "full" or "changed".
    mode: str
    requests: int = 0
    written: int = 0
    deleted: int = 0
    # False when the budget, a 429 or a CRM error ended the pass early.
    complete: bool = True
    rate_limited: bool = False
    # Stable code of the CRM error that ended the run, if any.
    crm_error: str | None = None

    @property
    def continue_soon(self) -> bool:
        """An unfinished full pass goes on after the short pause."""
        return self.mode == "full" and not self.complete


def full_pass_due(completed_at: datetime | None, now: datetime, zone: ZoneInfo) -> bool:
    """True when no full pass finished since the last 03:00 local time."""

    if completed_at is None:
        return True
    local_now = now.astimezone(zone)
    scheduled = datetime.combine(local_now.date(), FULL_PASS_LOCAL_TIME, zone)
    if scheduled > local_now:
        scheduled -= timedelta(days=1)
    return completed_at < scheduled


class _Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0

    @property
    def left(self) -> bool:
        return self.spent < self.limit


class SponsorSearchSync:
    def __init__(
        self,
        index: SponsorSearchIndex,
        source: SponsorPartySource,
        *,
        zone: ZoneInfo,
        request_budget: int = SYNC_REQUEST_BUDGET,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if request_budget < 1:
            raise ValueError("The sync needs a budget of at least one request.")
        self._index = index
        self._source = source
        self._zone = zone
        self._request_budget = request_budget
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def run_once(self, *, force_full: bool = False) -> SyncReport:
        """One bounded run: the full pass when it is due, else the changed pass."""

        async with self._index.exclusive_run() as acquired:
            if not acquired:
                return SyncReport(mode="skipped")
            now = self._clock()
            state = await self._index.sync_state()
            budget = _Budget(self._request_budget)
            if (
                force_full
                or state.full_pass_after is not None
                or full_pass_due(state.full_pass_completed_at, now, self._zone)
            ):
                return await self._full_pass(state, budget, now)
            return await self._changed_pass(budget, now)

    async def _full_pass(
        self, state: SyncState, budget: _Budget, now: datetime
    ) -> SyncReport:
        deleted = await self._index.delete_unreferenced()
        written = 0
        after = state.full_pass_after
        stopped: CrmGatewayError | None = None
        complete = False
        while True:
            keys = await self._index.referenced_parties(after, SYNC_ID_BATCH)
            if not keys:
                await self._index.finish_full_pass(now)
                complete = True
                break
            if not budget.left:
                break
            # One request reads one kind; the keys arrive ordered by kind.
            batch = tuple(key for key in keys if key.kind is keys[0].kind)
            budget.spent += 1
            try:
                found = await self._source.sponsor_parties_by_id(
                    batch[0].kind,
                    tuple(key.twenty_id for key in batch),
                    correlation_id=f"sponsor-search:full:{now:%Y%m%dT%H%M%S}",
                )
            except CrmGatewayError as error:
                stopped = error
                break
            batch_written, batch_deleted = await self._index.store_full_batch(
                batch, found, synced_at=now
            )
            written += batch_written
            deleted += batch_deleted
            after = batch[-1]
        return _report("full", budget, written, deleted, complete, stopped)

    async def _changed_pass(self, budget: _Budget, now: datetime) -> SyncReport:
        since = now - CHANGED_WINDOW
        written = 0
        stopped: CrmGatewayError | None = None
        complete = True
        for kind in CrmPartyKind:
            cursor: str | None = None
            while True:
                if not budget.left:
                    complete = False
                    break
                budget.spent += 1
                try:
                    page = await self._source.sponsor_parties_changed_since(
                        kind,
                        since,
                        cursor=cursor,
                        correlation_id=f"sponsor-search:changed:{now:%Y%m%dT%H%M%S}",
                    )
                except CrmGatewayError as error:
                    stopped = error
                    break
                written += await self._index.refresh(page.parties, synced_at=now)
                cursor = page.next_cursor
                if cursor is None:
                    break
            if stopped is not None or not complete:
                complete = False
                break
        return _report("changed", budget, written, 0, complete, stopped)


def _report(
    mode: str,
    budget: _Budget,
    written: int,
    deleted: int,
    complete: bool,
    stopped: CrmGatewayError | None,
) -> SyncReport:
    return SyncReport(
        mode=mode,
        requests=budget.spent,
        written=written,
        deleted=deleted,
        complete=complete and stopped is None,
        rate_limited=stopped is not None and stopped.http_status == 429,
        crm_error=stopped.code if stopped is not None else None,
    )
