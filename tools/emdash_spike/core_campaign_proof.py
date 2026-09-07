"""Live PostgreSQL prerequisite; not HTTP, rendering or order-submit evidence."""

import asyncio
import os
from datetime import timedelta
from uuid import UUID

import asyncpg
import httpx

from leonaid.adapters.postgres.actions import AsyncpgCharityActionRepository
from leonaid.application.actions import CharityActionService, PublicActionAvailability
from leonaid.application.errors import ResourceNotFound


async def main() -> None:
    pool = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2
    )
    assert pool is not None
    try:
        repository = AsyncpgCharityActionRepository(pool)
        service = CharityActionService(repository)
        action = await repository.get(UUID("20000000-0000-4000-8000-000000000001"))
        assert action is not None and action.publication_window is not None
        window = action.publication_window
        middle = window.starts_at + (window.ends_at - window.starts_at) / 2
        management = await repository.get_management(action.id)
        assert management is not None and management.public_alias is not None
        alias = await service.resolve_public_alias(
            management.public_alias.value, evaluated_at=middle
        )
        campaign = await service.resolve_public_campaign(
            action.archive_slug, evaluated_at=middle
        )
        assert campaign.availability is PublicActionAvailability.PUBLISHED
        assert campaign.action == alias.action
        assert campaign.offerings == alias.offerings
        assert campaign.order_form == alias.order_form
        assert campaign.submissions_allowed == alias.submissions_allowed
        assert campaign.route_value == action.archive_slug
        assert campaign.canonical_path == f"/campaigns/{action.archive_slug}/"
        assert campaign.route_path == campaign.canonical_path
        async with httpx.AsyncClient(base_url="http://api:8000", timeout=10) as client:
            legacy_alias = await client.get(
                f"/api/v1/public/actions/alias/{management.public_alias.value}"
            )
            legacy_archive = await client.get(
                f"/api/v1/public/actions/archive/{action.archive_slug}"
            )
            assert legacy_alias.status_code == 200
            assert legacy_archive.status_code == 200
            assert legacy_alias.json()["routeKind"] == "alias"
            assert legacy_archive.json()["routeKind"] == "archive"
            assert (
                legacy_archive.json()["canonicalPath"]
                == f"/archive/{action.archive_slug}"
            )
        if campaign.submissions_allowed:
            assert campaign.order_alias == management.public_alias.value
        for instant in (
            window.starts_at - timedelta(microseconds=1),
            window.ends_at + timedelta(microseconds=1),
        ):
            denied = await service.resolve_public_campaign(
                action.archive_slug, evaluated_at=instant
            )
            assert denied.availability is PublicActionAvailability.INACTIVE
            assert denied.action is None and not denied.offerings
            assert denied.order_form is None and denied.order_alias is None
            assert not denied.submissions_allowed
        # Actual committed Core withdrawal must be observed on the next call,
        # not only when a different evaluation timestamp is passed in.
        try:
            await pool.execute(
                "UPDATE charity_action SET publication_starts_at = NULL, publication_ends_at = NULL WHERE id = $1",
                action.id,
            )
            withdrawn = await service.resolve_public_campaign(
                action.archive_slug, evaluated_at=middle
            )
            assert withdrawn.action is None and not withdrawn.submissions_allowed
        finally:
            await pool.execute(
                "UPDATE charity_action SET publication_starts_at = $2, publication_ends_at = $3 WHERE id = $1",
                action.id,
                window.starts_at,
                window.ends_at,
            )
        assert (
            await service.resolve_public_campaign(
                action.archive_slug, evaluated_at=middle
            )
        ) == campaign
        for suffix in (2, 3):
            other = await repository.get(UUID(f"20000000-0000-4000-8000-{suffix:012d}"))
            assert other is not None
            denied = await service.resolve_public_campaign(
                other.archive_slug, evaluated_at=middle
            )
            assert denied.action is None and not denied.submissions_allowed
        try:
            await service.resolve_public_campaign("no-such-synthetic-campaign")
        except ResourceNotFound:
            pass
        else:
            raise AssertionError("Missing campaign was exposed")
        print(
            "core-campaign: real PostgreSQL active alias parity, stable URL, order-alias binding, expired/future/draft/archive concealment and missing slug passed; HTTP/public renderer remain pending"
        )
    finally:
        await pool.close()


asyncio.run(main())
