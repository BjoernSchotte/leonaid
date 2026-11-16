#!/usr/bin/env python3
"""Order options (E-068): full app, real PostgreSQL.

Runs as a contract script in the schema gate (``tools/schema/test.sh``) and,
with ``CORE_DATABASE_URL`` set, under pytest. Proves:

- a manager replaces the offerings (sizes, prices, order deadline); the
  action revision guards the edit, existing orders keep their price, and an
  offering that orders contain cannot be removed, only switched off;
- the order form's optional consents and withdrawal notice are set, shown
  in the configuration and audited with their wording;
- a public order records the newsletter consent as an explicit consent and
  the photo consent on the order, with the wording's version;
- the delivery area is stored normalized and returned with the schedule.

Reuses the extra-donation proof's fixture (action, offering, legal version).
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
import httpx

from leonaid.domain.action_templates import consent_text_version
from leonaid.entrypoints.fastapi.platform import create_app

# Run as a contract script too (tools/schema/test.sh), not only under pytest.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.integration.test_order_donations_api import (  # noqa: E402
    BASE_URL,
    Fixture,
    Proof,
    settings,
)

NEWSLETTER = "Ja, informieren Sie mich per E-Mail über weitere Lions-Aktivitäten."
PHOTOS = "Fotos von der Auslieferung dürfen veröffentlicht werden."
WITHDRAWAL = (
    "Kein Widerrufsrecht: Krapfen sind schnell verderbliche Lebensmittel "
    "(§ 312g Abs. 2 Nr. 2 BGB)."
)
DEADLINE = "2099-02-02T16:00:00Z"


class OptionsProof(Proof):
    async def run(self) -> None:
        await self.offerings_are_replaced()
        await self.form_options_are_set()
        await self.a_public_order_records_the_consents()
        await self.the_delivery_area_is_stored()

    async def revision(self, action: UUID) -> int:
        response = await self.get(f"/api/v1/actions/{action}")
        assert response.status_code == 200, response.text
        revision: int = response.json()["revision"]
        return revision

    async def offerings_are_replaced(self) -> None:
        action = self.data.plain
        path = f"/api/v1/actions/{action}/offerings"
        old = str(self.data.offerings[action])
        # An order holds the 24-box at its price.
        ordered = await self.send(
            "POST",
            self.orders(action),
            self.order("options", action=action),
            self.key(),
        )
        assert ordered.status_code == 201, ordered.text
        order_id = ordered.json()["id"]

        def sizes(*, keep_old: bool) -> list[dict[str, object]]:
            sizes: list[dict[str, object]] = [
                {
                    "code": f"krapfenbox-{pieces}",
                    "name": f"Krapfenbox {pieces} Stück",
                    "unit": "box",
                    "piecesPerUnit": pieces,
                    "unitPriceMinor": pieces * 200,
                    "donationShareMinor": pieces * 100,
                    "active": True,
                    "availableFrom": "2026-11-16T00:00:00Z",
                    "availableUntil": DEADLINE,
                }
                for pieces in (10, 20)
            ]
            if keep_old:
                sizes.append(
                    {
                        "id": old,
                        "code": "krapfenbox-24",
                        "name": "Krapfenbox 24 Stück",
                        "unit": "box",
                        "piecesPerUnit": 24,
                        "unitPriceMinor": 3600,
                        "active": False,
                    }
                )
            return sizes

        revision = await self.revision(action)
        removed = await self.send(
            "PUT",
            path,
            {"expectedRevision": revision, "offerings": sizes(keep_old=False)},
        )
        self.error(removed, 409, "offering_in_use")
        stale = await self.send(
            "PUT",
            path,
            {"expectedRevision": revision + 5, "offerings": sizes(keep_old=True)},
        )
        self.error(stale, 409, "action_revision_conflict")
        replaced = await self.send(
            "PUT",
            path,
            {"expectedRevision": revision, "offerings": sizes(keep_old=True)},
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.headers["cache-control"] == "no-store"
        body = replaced.json()
        assert body["action"]["revision"] == revision + 1
        offerings = {item["code"]: item for item in body["offerings"]}
        assert sorted(offerings) == ["krapfenbox-10", "krapfenbox-20", "krapfenbox-24"]
        assert offerings["krapfenbox-10"]["unitPriceMinor"] == 2000
        assert offerings["krapfenbox-10"]["donationShareMinor"] == 1000
        assert offerings["krapfenbox-24"]["donationShareMinor"] is None
        assert offerings["krapfenbox-20"]["availableUntil"].startswith(
            "2099-02-02T16:00:00"
        )
        assert offerings["krapfenbox-24"]["id"] == old
        assert offerings["krapfenbox-24"]["status"] == "inactive"
        # The order keeps its line as it was taken.
        line = await self.db.fetchrow(
            "SELECT unit_price_minor, pieces_per_unit_snapshot FROM commitment_line "
            "WHERE commitment_id = $1",
            UUID(order_id),
        )
        assert line is not None
        assert (line["unit_price_minor"], line["pieces_per_unit_snapshot"]) == (
            3600,
            24,
        )
        # The same list again changes nothing, not even the revision.
        again = await self.send(
            "PUT",
            path,
            {
                "expectedRevision": revision + 1,
                "offerings": [
                    {key: value for key, value in item.items() if key != "status"}
                    | {"id": item["id"], "active": item["status"] == "active"}
                    for item in (
                        {
                            "id": offerings[code]["id"],
                            "code": code,
                            "name": offerings[code]["name"],
                            "unit": "box",
                            "piecesPerUnit": offerings[code]["piecesPerUnit"],
                            "unitPriceMinor": offerings[code]["unitPriceMinor"],
                            "donationShareMinor": offerings[code]["donationShareMinor"],
                            "status": offerings[code]["status"],
                            "availableFrom": offerings[code]["availableFrom"],
                            "availableUntil": offerings[code]["availableUntil"],
                        }
                        for code in sorted(offerings)
                    )
                ],
            },
        )
        assert again.status_code == 200, again.text
        assert again.json()["action"]["revision"] == revision + 1
        audit = await self.db.fetchval(
            "SELECT count(*) FROM audit_event WHERE action_id = $1 "
            "AND event_type = 'charity_action.offerings_changed'",
            action,
        )
        assert audit == 1

    async def form_options_are_set(self) -> None:
        path = f"/api/v1/actions/{self.data.action}/order-form/options"
        short = await self.send(
            "PUT", path, {"newsletterConsentText": "Ja.", "photoConsentText": None}
        )
        assert short.status_code == 422, short.text
        response = await self.send(
            "PUT",
            path,
            {
                "newsletterConsentText": NEWSLETTER,
                "photoConsentText": PHOTOS,
                "withdrawalNotice": WITHDRAWAL,
            },
        )
        assert response.status_code == 200, response.text
        form = response.json()["orderForm"]
        assert form["newsletterConsentText"] == NEWSLETTER
        assert form["photoConsentText"] == PHOTOS
        assert form["withdrawalNotice"] == WITHDRAWAL
        audit = await self.db.fetchval(
            "SELECT payload->>'withdrawalNotice' FROM audit_event "
            "WHERE action_id = $1 AND event_type = 'order_form_options_changed'",
            self.data.action,
        )
        assert audit == WITHDRAWAL

    async def a_public_order_records_the_consents(self) -> None:
        draft = replace(
            self.public_draft(None, mailbox="consents"),
            newsletter_consent=True,
            photo_consent=True,
        )
        order_id = await self.record_public(draft)
        consent = await self.db.fetchrow(
            "SELECT text_version, evidence_kind, channel, normalized_recipient "
            "FROM consent_record WHERE commitment_id = $1 "
            "AND purpose = 'club_newsletter'",
            UUID(order_id),
        )
        assert consent is not None
        assert consent["text_version"] == consent_text_version("newsletter", NEWSLETTER)
        assert consent["evidence_kind"] == "explicit_consent"
        assert consent["channel"] == "email"
        photos = await self.db.fetchrow(
            "SELECT photo_consent_at, photo_consent_text_version FROM commitment "
            "WHERE id = $1",
            UUID(order_id),
        )
        assert photos is not None and photos["photo_consent_at"] is not None
        assert photos["photo_consent_text_version"] == consent_text_version(
            "photos", PHOTOS
        )
        record = await self.record(order_id)
        assert record["commitment"]["photoConsentAt"] is not None
        # Without the ticks nothing is recorded.
        plain = await self.record_public(self.public_draft(None, mailbox="noconsent"))
        assert (
            await self.db.fetchval(
                "SELECT count(*) FROM consent_record WHERE commitment_id = $1 "
                "AND purpose = 'club_newsletter'",
                UUID(plain),
            )
            == 0
        )
        assert (await self.record(plain))["commitment"]["photoConsentAt"] is None

    async def the_delivery_area_is_stored(self) -> None:
        action = self.data.plain
        await self.db.execute(
            "INSERT INTO charity_action_capability (action_id, capability) "
            "VALUES ($1, 'delivery') ON CONFLICT DO NOTHING",
            action,
        )
        path = f"/api/v1/actions/{action}/delivery-configuration"
        current = await self.get(path)
        assert current.status_code == 200, current.text
        assert current.json()["postalCodes"] == []
        saved = await self.send(
            "PUT",
            path,
            {
                "expectedRevision": current.json()["revision"],
                "enabled": current.json()["enabled"],
                "timezone": current.json()["timezone"],
                "windows": [],
                "postalCodes": ["97 070", "97299", "97070"],
                "areaLabel": "Stadt und Landkreis Würzburg",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["postalCodes"] == ["97070", "97299"]
        assert saved.json()["areaLabel"] == "Stadt und Landkreis Würzburg"
        # A client that does not know the area keeps it.
        kept = await self.send(
            "PUT",
            path,
            {
                "expectedRevision": saved.json()["revision"],
                "enabled": saved.json()["enabled"],
                "timezone": saved.json()["timezone"],
                "windows": [],
            },
        )
        assert kept.status_code == 200, kept.text
        assert kept.json()["postalCodes"] == ["97070", "97299"]
        invalid = await self.send(
            "PUT",
            path,
            {
                "expectedRevision": kept.json()["revision"],
                "enabled": kept.json()["enabled"],
                "timezone": kept.json()["timezone"],
                "windows": [],
                "postalCodes": ["97!70"],
            },
        )
        self.error(invalid, 422, "delivery_postal_code_invalid")


async def main() -> None:
    os.environ.pop("LEONAID_SURVEY_ERASURE_ARCHIVE_DIR", None)
    data = Fixture()
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    pool: asyncpg.Pool[Any] = await asyncpg.create_pool(
        os.environ["CORE_DATABASE_URL"], min_size=1, max_size=2
    )
    try:
        await data.create(connection)
        app = create_app(settings())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE_URL
            ) as client:
                await OptionsProof(client, data, connection, pool).run()
    finally:
        await data.remove_legal_configuration(connection)
        await pool.close()
        await connection.close()
    print(
        "order-options-api: OK: offerings replaced with deadline and revision, "
        "orders keep their price, form consents audited and recorded, "
        "delivery area stored normalized"
    )


def test_order_options_api() -> None:
    if "CORE_DATABASE_URL" not in os.environ:
        import pytest

        pytest.skip("needs a migrated PostgreSQL in CORE_DATABASE_URL")
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
