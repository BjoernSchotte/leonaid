"""Backend ports: the CRM as a swappable system of record.

`CrmBackend` is the interface the entire application layer programs against.
Implementations ("adapters") live under ``app/adapters/``:

  - ``app/adapters/twenty/``  -> talks to Twenty (httpx, REST/GraphQL, API key)
  - ``app/adapters/memory/``  -> in-memory fake for fast, stable tests

If Twenty is replaced after the PoC (e.g. by the Mayflower CRM clone,
architektur.md §14), exactly *one* new adapter is written that satisfies these
protocols — auth, owner-scoping, endpoints and the PWA stay untouched. That is
the whole point of the port (ADR #9).

They are ``typing.Protocol``s (structural): an adapter does not inherit, it only
has to match the shape. That keeps the Twenty adapter and the in-memory fake
decoupled.

All methods are ``async`` — matching FastAPI (async) + httpx (architektur.md §6).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.domain.models import (
    Campaign,
    CampaignId,
    Member,
    MemberId,
    NewSponsor,
    Sponsor,
    SponsorExport,
    SponsorId,
    SponsorPatch,
)


class CrmError(Exception):
    """Base class for backend errors.

    Adapters translate backend-specific failures (Twenty HTTP status, timeouts,
    rate limits) into these domain exceptions — above the adapter no ``httpx``
    error ever escapes. Part of the decoupling against API drift (risk #1, §11).
    """


@runtime_checkable
class CrmBackend(Protocol):
    """Contract for the system of record (the swappable member/PWA slice).

    SECURITY CONTRACT (architektur.md §6.3): for every sponsor-related operation
    ``owner`` is MANDATORY and MUST be enforced hard — a member may neither read
    nor change another member's sponsors. The owner sits in the signature on
    purpose, so it cannot be forgotten. Every adapter must pass the same contract
    test ("member A never gets B's sponsor").

    Deliberately NOT here (see §6.4): auth/session/token storage (own table/Redis,
    backend-free) and the orga/admin side (runs directly in the Twenty desktop,
    past the BFF). Compliance/admin operations live in `CrmAdminBackend` below.
    """

    # --- sponsors (always owner-scoped) --------------------------------------

    async def list_sponsors(
        self, owner: MemberId, campaign: CampaignId
    ) -> list[Sponsor]:
        """All sponsors of the member in this campaign (GET /sponsors)."""
        ...

    async def get_sponsor(
        self, owner: MemberId, sponsor_id: SponsorId
    ) -> Sponsor | None:
        """A sponsor — only if it belongs to the member, else ``None``
        (GET /sponsors/:id)."""
        ...

    async def create_sponsor(
        self, owner: MemberId, campaign: CampaignId, data: NewSponsor
    ) -> Sponsor:
        """Create a sponsor; owner = member, campaign = given campaign
        (POST /sponsors)."""
        ...

    async def update_sponsor(
        self, owner: MemberId, sponsor_id: SponsorId, patch: SponsorPatch
    ) -> Sponsor:
        """Change status / boxes / date — only on the member's own sponsor
        (PATCH /sponsors/:id). Raises CrmError if not owned."""
        ...

    async def add_note(
        self, owner: MemberId, sponsor_id: SponsorId, text: str
    ) -> None:
        """Attach a note to one of the member's own sponsors
        (POST /sponsors/:id/notes). Raises CrmError if not owned."""
        ...

    # --- campaigns -----------------------------------------------------------

    async def active_campaigns(self) -> list[Campaign]:
        """Active campaign(s) (GET /campaigns/active)."""
        ...

    # --- members (lookup only; auth/session do NOT live in the CRM backend) --

    async def find_member_by_email(self, email: str) -> Member | None:
        """Find a member by email for the magic-link login (POST /auth/request).

        Note: this just looks up. Anti-enumeration ("respond identically whether
        or not the email exists") is the API layer's job, not the backend's.
        """
        ...

    async def get_member(self, member_id: MemberId) -> Member | None:
        """Member by id — for GET /me."""
        ...


@runtime_checkable
class CrmAdminBackend(Protocol):
    """Compliance/admin operations on the system of record (GDPR).

    DELIBERATELY SEPARATE from `CrmBackend`: these methods are *not* owner-scoped
    — they act on behalf of the data subject (sponsor) across owner boundaries.
    Authorization ("is this an admin/DPO request?") is enforced by the API layer,
    not by an ``owner`` argument. Because it is its own port, a member code path
    cannot call these methods at all (it is only ever injected `CrmBackend`).

    IMPORTANT: the **deletion log** and the **suppression list** (§9) do NOT live
    here — they are backend-independent BFF-owned stores (like auth/session). This
    port only provides the CRM operations; writing the log is the application's job.
    """

    async def get_sponsor_export(self, sponsor_id: SponsorId) -> SponsorExport | None:
        """All data about a sponsor incl. notes — subject access (Art. 15).
        Not owner-scoped (admin/DPO)."""
        ...

    async def destroy_sponsor(self, sponsor_id: SponsorId) -> None:
        """Permanent deletion (hard destroy) incl. cascade to notes/attachments —
        erasure (Art. 17). The caller then writes the deletion-log entry."""
        ...

    async def set_processing_restricted(
        self, sponsor_id: SponsorId, restricted: bool
    ) -> None:
        """Restrict/lift processing (Art. 18) — marks the sponsor as restricted so
        the application excludes it from all call lists. Raises CrmError if absent."""
        ...
