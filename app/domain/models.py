"""LeonAid domain model — backend-independent.

These types are the *only* vocabulary in which the application layer (auth,
owner-scoping, endpoints) talks about data. They do NOT know Twenty: no REST
paths, no Twenty field names, no GraphQL `node/edges` shapes. The Twenty adapter
(app/adapters/twenty/) maps Twenty JSON <-> these objects and is the only place
that knows Twenty. That is what makes the system of record swappable
(see docs/architektur.md §6.4, ADR #9).

Deliberately plain `dataclasses` instead of Pydantic: the domain model stays free
of framework dependencies. The FastAPI layer validates incoming requests with
Pydantic and maps them onto these types (NewSponsor / SponsorPatch).

Note: the domain is German (Lions Club), but per project convention the code is
English. German labels shown to users (UI/PWA) are a presentation concern, mapped
at the edge — they are not part of the domain values here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import NewType

# IDs as NewType: type safety without nailing down a backend-specific format.
# Twenty returns UUID strings; another backend may return different strings —
# the rest of the app does not care.
MemberId = NewType("MemberId", str)
SponsorId = NewType("SponsorId", str)
CampaignId = NewType("CampaignId", str)


class Status(StrEnum):
    """Acquisition status of a sponsor (architektur.md §5).

    German UI labels map as: open=offen, contacted=kontaktiert,
    committed=zugesagt, declined=abgelehnt, done=erledigt.
    """

    OPEN = "open"
    CONTACTED = "contacted"
    COMMITTED = "committed"
    DECLINED = "declined"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class Member:
    """Club member. Not a Twenty user — exists only as a record and signs in
    exclusively to the PWA (architektur.md §2)."""

    id: MemberId
    name: str
    email: str  # login identity for the magic link
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class Campaign:
    """Campaign / "Aktion" (architektur.md §5). Multi-campaign by design."""

    id: CampaignId
    name: str
    active: bool
    starts_on: date | None = None
    ends_on: date | None = None
    boxes_target: int | None = None


@dataclass(frozen=True, slots=True)
class Sponsor:
    """Sponsor record. `owner` is the central security boundary: a member may
    only ever see/change their own sponsors (architektur.md §6.3) — the port
    enforces this via the mandatory `owner` argument."""

    id: SponsorId
    company: str
    phone: str
    owner: MemberId
    campaign: CampaignId
    status: Status = Status.OPEN
    contact_person: str | None = None
    email: str | None = None
    boxes_committed: int | None = None
    last_contacted: date | None = None
    note: str | None = None


# --- Input DTOs: what the PWA sends (no id/owner — the BFF sets those) --------


@dataclass(frozen=True, slots=True)
class NewSponsor:
    """New contact from the PWA. Only company + phone are required
    (architektur.md §7, "+ Neuer Kontakt")."""

    company: str
    phone: str
    contact_person: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class SponsorPatch:
    """Partial update from the PWA (PATCH /sponsors/:id, architektur.md §6.1).

    Sketch convention: a field whose value is ``None`` means "leave unchanged".
    (Sufficient for the MVP endpoints — there is no use case for deliberately
    setting a field to NULL.)
    """

    status: Status | None = None
    boxes_committed: int | None = None
    last_contacted: date | None = None


# --- GDPR / compliance: subject access (Art. 15) -----------------------------


@dataclass(frozen=True, slots=True)
class Note:
    """Note / call outcome attached to a sponsor. Relevant to subject access
    (Art. 15) because the free text may contain personal data."""

    id: str
    text: str
    created_at: date | None = None
    created_by: str | None = None  # member/orga; deliberately left free-form


@dataclass(frozen=True, slots=True)
class SponsorExport:
    """Full data about a sponsor for subject access (Art. 15) and possibly
    portability (Art. 20). The adapter assembles record + notes."""

    sponsor: Sponsor
    notes: list[Note]
