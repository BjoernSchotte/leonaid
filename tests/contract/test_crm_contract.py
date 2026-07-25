"""Contract tests for the CRM backend port.

These tests encode the *contract* every `CrmBackend` / `CrmAdminBackend` adapter
must satisfy — above all the security-critical property: a member never sees or
touches another member's data ("abgrasen" / cross-member leak is the GAU).

They are parametrised over a list of backend factories. Today only the in-memory
fake is present. When the Twenty adapter exists, add its factory to ``BACKENDS``
(e.g. against a throwaway test workspace) and the exact same suite must stay green.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import pytest

from app.adapters.memory.repository import InMemoryCrm
from app.domain.models import (
    Campaign,
    CampaignId,
    Member,
    MemberId,
    NewSponsor,
    Sponsor,
    SponsorId,
    SponsorPatch,
    Status,
)
from app.domain.ports import CrmAdminBackend, CrmBackend, CrmError


class _CrmAll(CrmBackend, CrmAdminBackend, Protocol):
    """Test-only view of a backend that implements both ports — which every real
    adapter does. In production the member path is only ever injected `CrmBackend`
    and the admin path only `CrmAdminBackend`; the combined view exists purely so
    these tests can exercise both sides of one store."""


# --- fixed test world --------------------------------------------------------

MEMBER_A = MemberId("m-a")
MEMBER_B = MemberId("m-b")
CAMPAIGN = CampaignId("c-1")
CAMPAIGN_OLD = CampaignId("c-0")
SPONSOR_A = SponsorId("sp-a")  # owned by A, active campaign
SPONSOR_B = SponsorId("sp-b")  # owned by B, active campaign
SPONSOR_A_OLD = SponsorId("sp-a-old")  # owned by A, but old campaign


@dataclass
class World:
    """A freshly seeded backend plus the known IDs the tests assert against."""

    backend: _CrmAll


def _in_memory_world() -> World:
    members = [
        Member(id=MEMBER_A, name="Alice", email="alice@example.org"),
        Member(id=MEMBER_B, name="Bob", email="bob@example.org"),
    ]
    campaigns = [
        Campaign(id=CAMPAIGN, name="Krapfentaxi 2026", active=True),
        Campaign(id=CAMPAIGN_OLD, name="Old Campaign", active=False),
    ]
    sponsors = [
        Sponsor(
            id=SPONSOR_A, company="Bakery A", phone="+49 1",
            owner=MEMBER_A, campaign=CAMPAIGN,
        ),
        Sponsor(
            id=SPONSOR_B, company="Bakery B", phone="+49 2",
            owner=MEMBER_B, campaign=CAMPAIGN,
        ),
        Sponsor(
            id=SPONSOR_A_OLD, company="Bakery A2", phone="+49 3",
            owner=MEMBER_A, campaign=CAMPAIGN_OLD,
        ),
    ]
    return World(
        backend=InMemoryCrm(members=members, campaigns=campaigns, sponsors=sponsors)
    )


# Add new adapter factories here — the same suite must pass against each.
BACKENDS: list[Callable[[], World]] = [_in_memory_world]


@pytest.fixture(
    params=BACKENDS,
    ids=lambda f: f.__name__.removeprefix("_").removesuffix("_world"),
)
def world(request: pytest.FixtureRequest) -> World:
    factory: Callable[[], World] = request.param
    return factory()


# --- structural: one store satisfies both ports ------------------------------


def test_backend_satisfies_both_protocols(world: World) -> None:
    assert isinstance(world.backend, CrmBackend)
    assert isinstance(world.backend, CrmAdminBackend)


# --- THE core property: cross-member isolation -------------------------------


async def test_member_lists_only_own_sponsors(world: World) -> None:
    listed = await world.backend.list_sponsors(MEMBER_A, CAMPAIGN)
    ids = {s.id for s in listed}
    assert SPONSOR_A in ids
    assert SPONSOR_B not in ids  # B's sponsor must never appear in A's list


async def test_get_other_members_sponsor_returns_none(world: World) -> None:
    # A tries to read B's sponsor by id (IDOR attempt) -> None (endpoint maps to 404)
    assert await world.backend.get_sponsor(MEMBER_A, SPONSOR_B) is None
    # sanity: A can read its own
    assert await world.backend.get_sponsor(MEMBER_A, SPONSOR_A) is not None


async def test_update_other_members_sponsor_raises(world: World) -> None:
    with pytest.raises(CrmError):
        await world.backend.update_sponsor(
            MEMBER_A, SPONSOR_B, SponsorPatch(status=Status.DONE)
        )


async def test_add_note_to_other_members_sponsor_raises(world: World) -> None:
    with pytest.raises(CrmError):
        await world.backend.add_note(MEMBER_A, SPONSOR_B, "should not be allowed")


# --- write paths force owner = caller ----------------------------------------


async def test_create_forces_owner_to_caller(world: World) -> None:
    created = await world.backend.create_sponsor(
        MEMBER_A, CAMPAIGN, NewSponsor(company="New Co", phone="+49 9")
    )
    assert created.owner == MEMBER_A
    assert created.campaign == CAMPAIGN
    assert created.status is Status.OPEN
    # and it shows up in A's list, not B's
    a_ids = {s.id for s in await world.backend.list_sponsors(MEMBER_A, CAMPAIGN)}
    b_ids = {s.id for s in await world.backend.list_sponsors(MEMBER_B, CAMPAIGN)}
    assert created.id in a_ids
    assert created.id not in b_ids


async def test_update_persists_only_given_fields(world: World) -> None:
    updated = await world.backend.update_sponsor(
        MEMBER_A, SPONSOR_A, SponsorPatch(status=Status.COMMITTED, boxes_committed=5)
    )
    assert updated.status is Status.COMMITTED
    assert updated.boxes_committed == 5
    assert updated.company == "Bakery A"  # untouched


# --- campaign scoping --------------------------------------------------------


async def test_list_scoped_to_campaign(world: World) -> None:
    listed = await world.backend.list_sponsors(MEMBER_A, CAMPAIGN)
    ids = {s.id for s in listed}
    assert SPONSOR_A in ids
    assert SPONSOR_A_OLD not in ids  # different campaign


async def test_active_campaigns_only_active(world: World) -> None:
    active = await world.backend.active_campaigns()
    ids = {c.id for c in active}
    assert CAMPAIGN in ids
    assert CAMPAIGN_OLD not in ids


async def test_find_member_by_email_is_case_insensitive(world: World) -> None:
    found = await world.backend.find_member_by_email("ALICE@example.org")
    assert found is not None and found.id == MEMBER_A
    assert await world.backend.find_member_by_email("nobody@example.org") is None


# --- GDPR: Art. 18 restriction excludes from call lists ----------------------


async def test_restricted_sponsor_excluded_from_member_list(world: World) -> None:
    await world.backend.set_processing_restricted(SPONSOR_A, True)
    listed = {s.id for s in await world.backend.list_sponsors(MEMBER_A, CAMPAIGN)}
    assert SPONSOR_A not in listed
    # lifting restriction brings it back
    await world.backend.set_processing_restricted(SPONSOR_A, False)
    listed = {s.id for s in await world.backend.list_sponsors(MEMBER_A, CAMPAIGN)}
    assert SPONSOR_A in listed


# --- GDPR: admin port is intentionally NOT owner-scoped ----------------------


async def test_admin_export_is_not_owner_scoped(world: World) -> None:
    # DPO can export any sponsor regardless of owner — that is the point of Art. 15
    export = await world.backend.get_sponsor_export(SPONSOR_B)
    assert export is not None
    assert export.sponsor.id == SPONSOR_B


async def test_admin_destroy_removes_and_cascades_notes(world: World) -> None:
    await world.backend.add_note(MEMBER_A, SPONSOR_A, "called, will think about it")
    before = await world.backend.get_sponsor_export(SPONSOR_A)
    assert before is not None and before.notes  # note present

    await world.backend.destroy_sponsor(SPONSOR_A)  # erasure (Art. 17)

    assert await world.backend.get_sponsor_export(SPONSOR_A) is None  # gone + cascaded
    assert await world.backend.get_sponsor(MEMBER_A, SPONSOR_A) is None
