"""In-memory CRM backend — a fast, dependency-free fake for tests.

Implements both `CrmBackend` (member-scoped) and `CrmAdminBackend` (compliance),
backed by plain dicts. It is the *reference implementation* of the port contract:
the same contract test-suite that runs against this fake must also pass against
the real Twenty adapter (docs/architektur.md §6.2, §6.4).

Crucially, this fake ENFORCES owner-scoping exactly like the real adapter must —
that is the behaviour the cross-member isolation tests verify.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from app.domain.models import (
    Campaign,
    CampaignId,
    Member,
    MemberId,
    NewSponsor,
    Note,
    Sponsor,
    SponsorExport,
    SponsorId,
    SponsorPatch,
    Status,
)
from app.domain.ports import CrmError


class InMemoryCrm:
    """Satisfies both `CrmBackend` and `CrmAdminBackend` (verified structurally
    in the contract tests). One backing store serves both ports — exactly how the
    Twenty adapter will work; the member/admin separation is enforced by *what gets
    injected*, not by having two stores."""

    def __init__(
        self,
        *,
        members: Iterable[Member] = (),
        campaigns: Iterable[Campaign] = (),
        sponsors: Iterable[Sponsor] = (),
    ) -> None:
        self._members: dict[MemberId, Member] = {m.id: m for m in members}
        self._campaigns: dict[CampaignId, Campaign] = {c.id: c for c in campaigns}
        self._sponsors: dict[SponsorId, Sponsor] = {s.id: s for s in sponsors}
        self._notes: dict[SponsorId, list[Note]] = {}
        self._restricted: set[SponsorId] = set()
        self._seq = 0

    # --- internal helpers ----------------------------------------------------

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq}"

    def _owned(self, owner: MemberId, sponsor_id: SponsorId) -> Sponsor | None:
        """The single choke point for owner-scoping: return the sponsor only if
        it belongs to `owner`, else None."""
        sponsor = self._sponsors.get(sponsor_id)
        if sponsor is None or sponsor.owner != owner:
            return None
        return sponsor

    # --- CrmBackend (member-scoped) ------------------------------------------

    async def list_sponsors(
        self, owner: MemberId, campaign: CampaignId
    ) -> list[Sponsor]:
        return [
            s
            for s in self._sponsors.values()
            if s.owner == owner
            and s.campaign == campaign
            and s.id not in self._restricted
        ]

    async def get_sponsor(
        self, owner: MemberId, sponsor_id: SponsorId
    ) -> Sponsor | None:
        return self._owned(owner, sponsor_id)

    async def create_sponsor(
        self, owner: MemberId, campaign: CampaignId, data: NewSponsor
    ) -> Sponsor:
        sponsor_id = SponsorId(self._next_id("sp"))
        sponsor = Sponsor(
            id=sponsor_id,
            company=data.company,
            phone=data.phone,
            owner=owner,
            campaign=campaign,
            status=Status.OPEN,
            contact_person=data.contact_person,
            email=data.email,
        )
        self._sponsors[sponsor_id] = sponsor
        return sponsor

    async def update_sponsor(
        self, owner: MemberId, sponsor_id: SponsorId, patch: SponsorPatch
    ) -> Sponsor:
        sponsor = self._owned(owner, sponsor_id)
        if sponsor is None:
            raise CrmError(f"sponsor {sponsor_id} not found for this member")
        updated = replace(
            sponsor,
            status=patch.status if patch.status is not None else sponsor.status,
            boxes_committed=(
                patch.boxes_committed
                if patch.boxes_committed is not None
                else sponsor.boxes_committed
            ),
            last_contacted=(
                patch.last_contacted
                if patch.last_contacted is not None
                else sponsor.last_contacted
            ),
        )
        self._sponsors[sponsor_id] = updated
        return updated

    async def add_note(
        self, owner: MemberId, sponsor_id: SponsorId, text: str
    ) -> None:
        sponsor = self._owned(owner, sponsor_id)
        if sponsor is None:
            raise CrmError(f"sponsor {sponsor_id} not found for this member")
        self._notes.setdefault(sponsor_id, []).append(
            Note(id=self._next_id("nt"), text=text)
        )

    async def active_campaigns(self) -> list[Campaign]:
        return [c for c in self._campaigns.values() if c.active]

    async def find_member_by_email(self, email: str) -> Member | None:
        for member in self._members.values():
            if member.email.lower() == email.lower():
                return member
        return None

    async def get_member(self, member_id: MemberId) -> Member | None:
        return self._members.get(member_id)

    # --- CrmAdminBackend (NOT owner-scoped — admin/DPO) ----------------------

    async def get_sponsor_export(self, sponsor_id: SponsorId) -> SponsorExport | None:
        sponsor = self._sponsors.get(sponsor_id)
        if sponsor is None:
            return None
        return SponsorExport(
            sponsor=sponsor, notes=list(self._notes.get(sponsor_id, []))
        )

    async def destroy_sponsor(self, sponsor_id: SponsorId) -> None:
        # hard destroy + cascade (notes), idempotent
        self._sponsors.pop(sponsor_id, None)
        self._notes.pop(sponsor_id, None)
        self._restricted.discard(sponsor_id)

    async def set_processing_restricted(
        self, sponsor_id: SponsorId, restricted: bool
    ) -> None:
        if sponsor_id not in self._sponsors:
            raise CrmError(f"sponsor {sponsor_id} not found")
        if restricted:
            self._restricted.add(sponsor_id)
        else:
            self._restricted.discard(sponsor_id)
