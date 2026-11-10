#!/usr/bin/env python3
"""Real PostgreSQL, FastAPI and Twenty contract for POC-072."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.application.public_orders import PublicOrderTokenCodec

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ARCHIVED_ACTION_ID = UUID("20000000-0000-4000-8000-000000000002")
OFFERING_ID = UUID("70000000-0000-4000-8000-000000000001")
MUSTERWERK_ID = UUID("40000000-0000-4000-8000-000000000001")
MARA_ID = UUID("50000000-0000-4000-8000-000000000001")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
COMMAND_NAMESPACE = UUID("5657756c-cd86-4800-8a47-153261f525ab")
TWIN_COMPANIES = (
    (UUID("40000000-0000-4000-8000-00000000f072"), "POC072 Zwilling-Werk GmbH"),
    (UUID("40000000-0000-4000-8000-00000000f073"), "POC072 Zwilling Werk GmbH"),
)
PUBLIC_REFERENCE = re.compile(r"^LA-[A-F0-9]{32}$")
PRIVACY_NOTICE_VERSION = "public-order-golden-v1"
PRIVACY_NOTICE_TEXT = (
    "Wir verarbeiten Ihre Angaben ausschließlich zur Durchführung, "
    "Abrechnung und Zustellung Ihrer Krapfentaxi-Bestellung."
)


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def command_id(label: str) -> UUID:
    return uuid5(COMMAND_NAMESPACE, label)


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Error response has no stable contract")
    return str(error.get("code"))


def json_object(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ContractFailure("Persisted JSON evidence is not an object")
    return {str(key): item for key, item in value.items()}


async def twenty_record(
    client: httpx.AsyncClient,
    collection: str,
    record_id: UUID,
) -> dict[str, Any]:
    response = await client.get(f"/rest/{collection}/{record_id}")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    record: object = None
    if isinstance(data, dict):
        if len(data) == 1:
            nested = next(iter(data.values()))
            record = nested if isinstance(nested, dict) else data
        else:
            record = data
    if not isinstance(record, dict):
        raise ContractFailure(f"Twenty {collection} record is missing")
    return record


async def twenty_collection(
    client: httpx.AsyncClient,
    collection: str,
) -> list[dict[str, Any]]:
    response = await client.get(f"/rest/{collection}", params={"limit": 100})
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    records = data.get(collection) if isinstance(data, dict) else None
    if not isinstance(records, list) or not all(
        isinstance(record, dict) for record in records
    ):
        raise ContractFailure(f"Twenty {collection} list is missing")
    return records


async def public_context(
    api: httpx.AsyncClient,
) -> tuple[str, dict[str, Any]]:
    response = await api.get(
        "/api/v1/public/actions/alias/krapfentaxi",
        headers={"X-Request-ID": "poc072:public-context"},
    )
    response.raise_for_status()
    if response.headers.get("cache-control") != "private, no-store":
        raise ContractFailure("Form token was served as publicly cacheable")
    payload = response.json()
    action = payload.get("action") if isinstance(payload, dict) else None
    form = action.get("orderForm") if isinstance(action, dict) else None
    offerings = action.get("offerings") if isinstance(action, dict) else None
    if (
        payload.get("availability") != "published"
        or payload.get("submissionsAllowed") is not True
        or not isinstance(form, dict)
        or not isinstance(form.get("accessToken"), str)
        or not isinstance(offerings, list)
        or len(offerings) != 1
        or offerings[0].get("id") != str(OFFERING_ID)
        or offerings[0].get("unitPriceMinor") != 3_600
        or form.get("requireCompanyName") is not False
        or form.get("requireDeliveryAddress") is not True
        or form.get("requireBillingAddress") is not True
        or form.get("privacyNoticeVersion") != PRIVACY_NOTICE_VERSION
        or form.get("privacyNoticeText") != PRIVACY_NOTICE_TEXT
        or form.get("legalBasis")
        != "Vertragserfüllung für die öffentliche Golden-Bestellung."
        or form.get("privacyContactEmail") != "datenschutz@leonaid.invalid"
    ):
        raise ContractFailure("Public context has no complete order contract")
    return str(form["accessToken"]), offerings[0]


def order_body(
    *,
    token: str,
    command: UUID,
    given_name: str,
    family_name: str,
    email: str,
    company_name: str | None,
    quantity: int = 2,
    offering_id: UUID = OFFERING_ID,
    quoted_price: int = 3_600,
    website: str | None = None,
) -> dict[str, object]:
    recipient = company_name or f"{given_name} {family_name}"
    return {
        "accessToken": token,
        "commandId": str(command),
        "party": {
            "companyName": company_name,
            "givenName": given_name,
            "familyName": family_name,
            "email": email,
            "phone": "0821 123456",
        },
        "deliveryRecipient": {
            "recipientName": recipient,
            "streetLine1": "Lieferweg 72",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
        },
        "invoiceRecipient": {
            "recipientName": recipient,
            "streetLine1": "Rechnungsweg 72",
            "postalCode": "86150",
            "city": "Augsburg",
            "countryCode": "DE",
            "email": email,
        },
        "lines": [
            {
                "offeringId": str(offering_id),
                "quantity": quantity,
                "unit": "box",
                "quotedUnitPriceMinor": quoted_price,
            }
        ],
        "message": "Bitte am Empfang abgeben.",
        "privacyAcknowledged": True,
        "bindingOrderConfirmed": True,
        "privacyNoticeVersion": PRIVACY_NOTICE_VERSION,
        "website": website,
    }


async def submit(
    api: httpx.AsyncClient,
    body: Mapping[str, object],
    *,
    label: str,
    forwarded_for: str,
    user_agent: str | None = None,
) -> httpx.Response:
    return await api.post(
        "/api/v1/public/actions/krapfentaxi/orders",
        json=body,
        headers={
            "X-Request-ID": f"poc072:{label}",
            "X-LeonAid-Order-Key": require_env("LEONAID_ORDER_SUBMISSION_KEY"),
            "X-Forwarded-For": forwarded_for,
            "User-Agent": user_agent or f"LeonAid Contract/{label}",
        },
    )


async def assignment_snapshot(
    connection: asyncpg.Connection[Any],
) -> tuple[tuple[str, str, str | None, str | None], ...]:
    rows = await connection.fetch(
        """
        SELECT id, acquirer_user_id, twenty_company_id, twenty_person_id
        FROM acquisition_assignment
        WHERE action_id = $1
        ORDER BY id
        """,
        ACTION_ID,
    )
    return tuple(
        (
            str(row["id"]),
            str(row["acquirer_user_id"]),
            (
                str(row["twenty_company_id"])
                if row["twenty_company_id"] is not None
                else None
            ),
            (
                str(row["twenty_person_id"])
                if row["twenty_person_id"] is not None
                else None
            ),
        )
        for row in rows
    )


async def assert_activity(
    connection: asyncpg.Connection[Any],
    *,
    commitment_id: UUID,
    expected_recipient_ids: set[UUID],
) -> None:
    row = await connection.fetchrow(
        """
        SELECT id, action_id, event_type, twenty_company_id, twenty_person_id
        FROM activity_event
        WHERE payload ->> 'commitmentId' = $1
        """,
        str(commitment_id),
    )
    if (
        row is None
        or row["action_id"] != ACTION_ID
        or str(row["event_type"]) != "public_order_received"
    ):
        raise ContractFailure("Public order created no ActivityEvent")
    recipients = await connection.fetch(
        """
        SELECT user_id
        FROM activity_event_recipient
        WHERE activity_event_id = $1
        ORDER BY user_id
        """,
        row["id"],
    )
    if {item["user_id"] for item in recipients} != expected_recipient_ids:
        raise ContractFailure(
            "ActivityEvent was not addressed to the responsible users"
        )


async def assert_commitment(
    connection: asyncpg.Connection[Any],
    payload: Mapping[str, object],
    *,
    expected_company_id: UUID | None,
    expected_person: bool,
    expected_quantity: int,
) -> asyncpg.Record:
    commitment_id = UUID(str(payload["commitmentId"]))
    row = await connection.fetchrow(
        """
        SELECT
            id, action_id, twenty_company_id, twenty_person_id,
            source, status, customer_snapshot, invoice_recipient_snapshot,
            delivery_recipient_snapshot, message_snapshot,
            public_reference, currency, total_minor
        FROM commitment
        WHERE id = $1
        """,
        commitment_id,
    )
    line = await connection.fetchrow(
        """
        SELECT
            offering_id, quantity, unit_snapshot,
            pieces_per_unit_snapshot, unit_price_minor, line_total_minor
        FROM commitment_line
        WHERE commitment_id = $1
        """,
        commitment_id,
    )
    reference = str(payload["publicReference"])
    if (
        row is None
        or line is None
        or row["action_id"] != ACTION_ID
        or (
            expected_company_id is not None
            and row["twenty_company_id"] != expected_company_id
        )
        or (expected_person and row["twenty_company_id"] is not None)
        or (not expected_person and row["twenty_company_id"] is None)
        or (row["twenty_person_id"] is not None) is not expected_person
        or str(row["source"]) != "public_form"
        or str(row["status"]) != "review_ready"
        or str(row["public_reference"]) != reference
        or not PUBLIC_REFERENCE.fullmatch(reference)
        or row["delivery_recipient_snapshot"] is None
        or row["invoice_recipient_snapshot"] is None
        or str(row["message_snapshot"]) != "Bitte am Empfang abgeben."
        or str(row["currency"]) != "EUR"
        or int(row["total_minor"]) != expected_quantity * 3_600
        or line["offering_id"] != OFFERING_ID
        or int(line["quantity"]) != expected_quantity
        or str(line["unit_snapshot"]) != "box"
        or int(line["pieces_per_unit_snapshot"]) != 24
        or int(line["unit_price_minor"]) != 3_600
        or int(line["line_total_minor"]) != expected_quantity * 3_600
    ):
        raise ContractFailure("Commitment snapshots, line items or price are wrong")
    audit = await connection.fetchrow(
        """
        SELECT payload
        FROM audit_event
        WHERE entity_type = 'commitment'
          AND entity_id = $1
          AND event_type = 'public_order_created'
        """,
        commitment_id,
    )
    if (
        audit is None
        or json_object(audit["payload"]).get("privacyNoticeVersion")
        != PRIVACY_NOTICE_VERSION
        or json_object(audit["payload"]).get("privacyAcknowledged") is not True
        or json_object(audit["payload"]).get("bindingOrderConfirmed") is not True
    ):
        raise ContractFailure("Consent and form version are not audited")
    evidence = await connection.fetchrow(
        """
        SELECT *
        FROM consent_record
        WHERE commitment_id = $1
        """,
        commitment_id,
    )
    customer = json_object(row["customer_snapshot"])
    if (
        evidence is None
        or evidence["action_id"] != ACTION_ID
        or str(evidence["normalized_recipient"])
        != str(customer.get("email", "")).casefold()
        or str(evidence["purpose"]) != "public_order_fulfilment"
        or str(evidence["channel"]) != "email"
        or str(evidence["text_version"]) != PRIVACY_NOTICE_VERSION
        or str(evidence["source"]) != "public_order_form"
        or str(evidence["evidence_kind"]) != "notice_acknowledgement"
        or str(evidence["legal_basis_status"]) != "confirmed"
        or evidence["granted_at"] is None
        or (
            (evidence["twenty_company_id"] is None)
            == (evidence["twenty_person_id"] is None)
        )
    ):
        raise ContractFailure("Privacy notice was not stored as versioned evidence")
    return row


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    assignments_before = await assignment_snapshot(connection)
    public_commitments_before = int(
        await connection.fetchval(
            "SELECT count(*) FROM commitment WHERE source = 'public_form'"
        )
    )
    company_count_before = 0
    person_count_before = 0

    async with (
        httpx.AsyncClient(
            base_url=require_env("API_BASE_URL").rstrip("/"),
            timeout=90,
        ) as api,
        httpx.AsyncClient(
            base_url=require_env("TWENTY_BASE_URL").rstrip("/"),
            headers={
                "Authorization": f"Bearer {require_env('TWENTY_INTEGRATION_API_KEY')}"
            },
            timeout=90,
        ) as twenty,
    ):
        # Two existing CRM companies whose names share one match key, written
        # around LeonAid (no stored key) as the Twenty UI would.
        for twin_id, twin_name in TWIN_COMPANIES:
            created_twin = await twenty.post(
                "/rest/companies",
                json={"id": str(twin_id), "name": twin_name},
            )
            if created_twin.status_code not in {200, 201}:
                raise ContractFailure("Twenty twin company could not be created")
        companies_before = await twenty_collection(twenty, "companies")
        people_before = await twenty_collection(twenty, "people")
        company_count_before = len(companies_before)
        person_count_before = len(people_before)

        active_configuration_id = await connection.fetchval(
            "SELECT active_version_id FROM legal_configuration_state"
        )
        if active_configuration_id is None:
            raise ContractFailure("Golden data has no active legal basis")
        await connection.execute(
            "UPDATE legal_configuration_state SET active_version_id = NULL"
        )
        disabled = await api.get(
            "/api/v1/public/actions/alias/krapfentaxi",
            headers={"X-Request-ID": "poc072:missing-legal-configuration"},
        )
        disabled.raise_for_status()
        disabled_payload = disabled.json()
        disabled_action = (
            disabled_payload.get("action")
            if isinstance(disabled_payload, dict)
            else None
        )
        if (
            not isinstance(disabled_action, dict)
            or disabled_payload.get("submissionsAllowed") is not False
            or disabled_action.get("orderForm") is not None
            or disabled.headers.get("cache-control")
            != "public, max-age=15, stale-while-revalidate=30"
        ):
            raise ContractFailure(
                "Public form stayed open without an active legal basis"
            )
        await connection.execute(
            """
            UPDATE legal_configuration_state
            SET active_version_id = $1
            """,
            active_configuration_id,
        )

        token, _offering = await public_context(api)

        stale_notice_body = order_body(
            token=token,
            command=command_id("stale-privacy-notice"),
            company_name="Musterwerk GmbH",
            given_name="Mara",
            family_name="Muster",
            email="mara.muster@musterwerk.leonaid.invalid",
        )
        stale_notice_body["privacyNoticeVersion"] = "public-order-stale-v0"
        stale_notice = await submit(
            api,
            stale_notice_body,
            label="stale-privacy-notice",
            forwarded_for="203.0.113.71",
        )
        if (
            stale_notice.status_code != 409
            or error_code(stale_notice) != "public_order_privacy_notice_changed"
        ):
            raise ContractFailure("Stale privacy notice was not rejected fail-closed")

        existing_body = order_body(
            token=token,
            command=command_id("existing-company"),
            company_name="Musterwerk GmbH",
            given_name="Mara",
            family_name="Muster",
            email="mara.muster@musterwerk.leonaid.invalid",
            quantity=1,
        )
        await expect_feed_push(connection)
        existing = await submit(
            api,
            existing_body,
            label="existing-company",
            forwarded_for="203.0.113.72",
        )
        existing.raise_for_status()
        existing_payload = existing.json()
        if (
            existing.status_code != 201
            or existing_payload["crmOutcome"] != "reused"
            or existing_payload["replayed"] is not False
            or existing_payload["totalBoxes"] != 1
            or existing_payload["totalPieces"] != 24
        ):
            raise ContractFailure("Existing company was not reused unambiguously")
        existing_row = await assert_commitment(
            connection,
            existing_payload,
            expected_company_id=MUSTERWERK_ID,
            expected_person=False,
            expected_quantity=1,
        )
        await assert_activity(
            connection,
            commitment_id=existing_row["id"],
            expected_recipient_ids={ANNA_ID},
        )
        await assert_feed_push(connection)

        new_company_body = order_body(
            token=token,
            command=command_id("new-company-concurrent"),
            company_name="POC072 Lichtblick Manufaktur GmbH",
            given_name="Nora",
            family_name="Lichtblick",
            email="nora.lichtblick@leonaid.invalid",
            quantity=2,
        )
        concurrent = await asyncio.gather(
            submit(
                api,
                new_company_body,
                label="new-company-a",
                forwarded_for="203.0.113.73",
            ),
            submit(
                api,
                new_company_body,
                label="new-company-b",
                forwarded_for="203.0.113.73",
            ),
        )
        for response in concurrent:
            response.raise_for_status()
        company_payloads = [response.json() for response in concurrent]
        if (
            {response.status_code for response in concurrent} != {200, 201}
            or {item["replayed"] for item in company_payloads} != {False, True}
            or {item["crmOutcome"] for item in company_payloads} != {"created"}
            or len({item["commitmentId"] for item in company_payloads}) != 1
            or len({item["publicReference"] for item in company_payloads}) != 1
        ):
            raise ContractFailure("Double submit did not produce an idempotent result")
        company_payload = company_payloads[0]
        company_row = await assert_commitment(
            connection,
            company_payload,
            expected_company_id=None,
            expected_person=False,
            expected_quantity=2,
        )
        if company_row["twenty_company_id"] is None:
            raise ContractFailure("New company is missing on the commitment")
        await assert_activity(
            connection,
            commitment_id=company_row["id"],
            expected_recipient_ids={KLARA_ID},
        )

        person_body = order_body(
            token=token,
            command=command_id("new-private-person"),
            company_name=None,
            given_name="Nina",
            family_name="Öffentlich",
            email="nina.oeffentlich@leonaid.invalid",
            quantity=3,
        )
        person = await submit(
            api,
            person_body,
            label="new-private-person",
            forwarded_for="203.0.113.74",
        )
        person.raise_for_status()
        person_payload = person.json()
        if (
            person_payload["crmOutcome"] != "created"
            or person_payload["replayed"] is not False
        ):
            raise ContractFailure("Private person was not created in a controlled way")
        person_row = await assert_commitment(
            connection,
            person_payload,
            expected_company_id=None,
            expected_person=True,
            expected_quantity=3,
        )
        await assert_activity(
            connection,
            commitment_id=person_row["id"],
            expected_recipient_ids={KLARA_ID},
        )

        ambiguous = await submit(
            api,
            order_body(
                token=token,
                command=command_id("ambiguous-company"),
                company_name="poc072 ZWILLING werk gmbh",
                given_name="Zora",
                family_name="Zwilling",
                email="zora.zwilling@leonaid.invalid",
            ),
            label="ambiguous-company",
            forwarded_for="203.0.113.80",
        )
        if (
            ambiguous.status_code != 409
            or error_code(ambiguous) != "public_order_party_ambiguous"
        ):
            raise ContractFailure("Ambiguous company was not rejected as a conflict")

        # The second spelling differs from the CRM name ("Bäckerstübchen" vs
        # "Baeckerstuebchen"); only the stored match key can find it.
        variant_first = await submit(
            api,
            order_body(
                token=token,
                command=command_id("variant-company-first"),
                quantity=1,
                company_name="POC072 Bäckerstübchen GmbH",
                given_name="Vera",
                family_name="Variante",
                email="vera.variante@leonaid.invalid",
            ),
            label="variant-company-first",
            forwarded_for="203.0.113.81",
        )
        variant_first.raise_for_status()
        variant_first_payload = variant_first.json()
        variant_again = await submit(
            api,
            order_body(
                token=token,
                command=command_id("variant-company-again"),
                quantity=1,
                company_name="poc072 BAECKERSTUEBCHEN gmbh",
                given_name="Vera",
                family_name="Variante",
                email="vera.variante@leonaid.invalid",
            ),
            label="variant-company-again",
            forwarded_for="203.0.113.82",
        )
        variant_again.raise_for_status()
        variant_again_payload = variant_again.json()
        variant_first_row = await assert_commitment(
            connection,
            variant_first_payload,
            expected_company_id=None,
            expected_person=False,
            expected_quantity=1,
        )
        variant_again_row = await assert_commitment(
            connection,
            variant_again_payload,
            expected_company_id=variant_first_row["twenty_company_id"],
            expected_person=False,
            expected_quantity=1,
        )
        if (
            variant_first_payload["crmOutcome"] != "created"
            or variant_again_payload["crmOutcome"] != "reused"
            or variant_again_row["id"] == variant_first_row["id"]
        ):
            raise ContractFailure(
                "Spelling variant of a company was not reused via the match key"
            )

        changed_body = order_body(
            token=token,
            command=command_id("new-company-concurrent"),
            company_name="POC072 Lichtblick Manufaktur GmbH",
            given_name="Nora",
            family_name="Lichtblick",
            email="nora.lichtblick@leonaid.invalid",
            quantity=4,
        )
        idempotency_conflict = await submit(
            api,
            changed_body,
            label="idempotency-conflict",
            forwarded_for="203.0.113.75",
        )
        if (
            idempotency_conflict.status_code != 409
            or error_code(idempotency_conflict) != "idempotency_conflict"
        ):
            raise ContractFailure("Command ID accepted different order data")

        price_body = order_body(
            token=token,
            command=command_id("manipulated-price"),
            company_name="Musterwerk GmbH",
            given_name="Mara",
            family_name="Muster",
            email="mara.muster@musterwerk.leonaid.invalid",
            quoted_price=1,
        )
        manipulated = await submit(
            api,
            price_body,
            label="manipulated-price",
            forwarded_for="203.0.113.76",
        )
        if (
            manipulated.status_code != 409
            or error_code(manipulated) != "public_order_price_changed"
        ):
            raise ContractFailure("Manipulated price was not rejected on the server")

        await connection.execute(
            "UPDATE offering SET status = 'inactive' WHERE id = $1",
            OFFERING_ID,
        )
        inactive = await submit(
            api,
            order_body(
                token=token,
                command=command_id("inactive-offering"),
                company_name="Musterwerk GmbH",
                given_name="Mara",
                family_name="Muster",
                email="mara.muster@musterwerk.leonaid.invalid",
            ),
            label="inactive-offering",
            forwarded_for="203.0.113.77",
        )
        await connection.execute(
            "UPDATE offering SET status = 'active' WHERE id = $1",
            OFFERING_ID,
        )
        if (
            inactive.status_code != 422
            or error_code(inactive) != "offering_not_available"
        ):
            raise ContractFailure("Inactive offering was not rejected on the server")

        # The golden action delivers (delivery capability), so Core must
        # require the delivery recipient that the transport schema now allows
        # to be omitted for pickup or donation campaigns.
        without_delivery = order_body(
            token=token,
            command=command_id("missing-delivery-recipient"),
            company_name="Musterwerk GmbH",
            given_name="Mara",
            family_name="Muster",
            email="mara.muster@musterwerk.leonaid.invalid",
        )
        without_delivery.pop("deliveryRecipient")
        missing_delivery = await submit(
            api,
            without_delivery,
            label="missing-delivery-recipient",
            forwarded_for="203.0.113.79",
        )
        if (
            missing_delivery.status_code != 422
            or error_code(missing_delivery)
            != "public_order_delivery_recipient_required"
        ):
            raise ContractFailure(
                "Delivery action accepted an order without a delivery address"
            )

        archived_token = PublicOrderTokenCodec(require_env("LEONAID_SECRET_KEY")).issue(
            ARCHIVED_ACTION_ID, "krapfentaxi"
        )
        archived = await submit(
            api,
            order_body(
                token=archived_token,
                command=command_id("archived-action"),
                company_name="Musterwerk GmbH",
                given_name="Mara",
                family_name="Muster",
                email="mara.muster@musterwerk.leonaid.invalid",
            ),
            label="archived-action",
            forwarded_for="203.0.113.78",
        )
        if (
            archived.status_code != 409
            or error_code(archived) != "public_order_action_closed"
        ):
            raise ContractFailure("Archived action accepted an order")

        spam_fingerprint = "203.0.113.250"
        for index in range(5):
            rejected = await submit(
                api,
                order_body(
                    token=token,
                    command=command_id(f"honeypot-{index}"),
                    company_name=None,
                    given_name="Bot",
                    family_name=f"Signal {index}",
                    email=f"bot-{index}@leonaid.invalid",
                    website="https://spam.invalid",
                ),
                label=f"honeypot-{index}",
                forwarded_for=spam_fingerprint,
                user_agent="LeonAid Contract/Rate-Limit",
            )
            if (
                rejected.status_code != 409
                or error_code(rejected) != "public_order_rejected"
            ):
                raise ContractFailure("Honeypot signal was not safely discarded")
        limited = await submit(
            api,
            order_body(
                token=token,
                command=command_id("rate-limited"),
                company_name=None,
                given_name="Bot",
                family_name="Limit",
                email="bot-limit@leonaid.invalid",
                website="https://spam.invalid",
            ),
            label="rate-limited",
            forwarded_for=spam_fingerprint,
            user_agent="LeonAid Contract/Rate-Limit",
        )
        if (
            limited.status_code != 429
            or error_code(limited) != "public_order_rate_limited"
        ):
            raise ContractFailure("Rate limit was not enforced on the server")

        company_twenty_id = company_row["twenty_company_id"]
        person_twenty_id = person_row["twenty_person_id"]
        company_record = await twenty_record(
            twenty,
            "companies",
            company_twenty_id,
        )
        new_people = await twenty_collection(twenty, "people")
        company_contacts = [
            item
            for item in new_people
            if item.get("companyId") == str(company_twenty_id)
            and item.get("name", {}).get("firstName") == "Nora"
            and item.get("name", {}).get("lastName") == "Lichtblick"
        ]
        person_record = await twenty_record(
            twenty,
            "people",
            person_twenty_id,
        )
        if (
            company_record.get("name") != "POC072 Lichtblick Manufaktur GmbH"
            or len(company_contacts) != 1
            or company_contacts[0].get("emails", {}).get("primaryEmail")
            != "nora.lichtblick@leonaid.invalid"
            or person_record.get("name", {}).get("firstName") != "Nina"
            or person_record.get("name", {}).get("lastName") != "Öffentlich"
            or person_record.get("companyId") not in {None, ""}
        ):
            raise ContractFailure(
                "Twenty does not contain exactly the expected CRM data"
            )
        musterwerk = await twenty_record(twenty, "companies", MUSTERWERK_ID)
        mara = await twenty_record(twenty, "people", MARA_ID)
        if (
            musterwerk.get("name") != "Musterwerk GmbH"
            or musterwerk.get("address", {}).get("addressPostcode") != "10115"
            or mara.get("emails", {}).get("primaryEmail")
            != "mara.muster@musterwerk.leonaid.invalid"
        ):
            raise ContractFailure("Reuse silently overwrote existing CRM data")
        if (
            len(await twenty_collection(twenty, "companies"))
            != company_count_before + 2
            or len(await twenty_collection(twenty, "people")) != person_count_before + 3
        ):
            raise ContractFailure("CRM records were not created exactly once")

    await assert_no_push(connection)
    assignments_after = await assignment_snapshot(connection)
    if assignments_after != assignments_before:
        raise ContractFailure("Public orders changed assignments")
    created_count = await connection.fetchval(
        """
        SELECT count(*)
        FROM commitment
        WHERE id = ANY($1::uuid[])
        """,
        [
            UUID(str(existing_payload["commitmentId"])),
            UUID(str(company_payload["commitmentId"])),
            UUID(str(person_payload["commitmentId"])),
            UUID(str(variant_first_payload["commitmentId"])),
            UUID(str(variant_again_payload["commitmentId"])),
        ],
    )
    if int(created_count) != 5:
        raise ContractFailure("Retry or rejection created extra commitments")
    public_commitments_after = int(
        await connection.fetchval(
            "SELECT count(*) FROM commitment WHERE source = 'public_form'"
        )
    )
    if public_commitments_after != public_commitments_before + 5:
        raise ContractFailure("Rejected or duplicate requests created commitments")
    fingerprints = await connection.fetch(
        """
        SELECT DISTINCT fingerprint_hash
        FROM public_submission_attempt
        WHERE action_id = $1
        """,
        ACTION_ID,
    )
    if not fingerprints or any(
        not re.fullmatch(r"[0-9a-f]{64}", str(row["fingerprint_hash"]))
        for row in fingerprints
    ):
        raise ContractFailure("Rate limit does not store pseudonymized signals")
    print(
        "public-orders-contract: OK:",
        "active legal basis, company/person, server-side price,",
        "idempotency, archive/inactive, spam/rate and ActivityEvents proven",
    )


PUSH_PROOF_SESSION = UUID("95620000-0000-4000-8000-0000000000a1")
PUSH_PROOF_DEVICE = UUID("95620000-0000-4000-8000-0000000000a2")


async def expect_feed_push(connection: asyncpg.Connection[Any]) -> None:
    """Anna asked for pushes about "Neues" and has a device (ADR-0017)."""

    await connection.execute(
        "UPDATE feature_flag SET enabled = true, revision = revision + 1 "
        "WHERE key = 'pwa.push'"
    )
    await connection.execute(
        """
        INSERT INTO user_session (
            id, user_id, token_digest, expires_at, last_seen_at,
            fresh_login_at, device_hint, created_at, updated_at
        )
        VALUES ($1, $2, repeat('9', 64), now() + interval '1 day', now(),
                now(), 'POC072 push', now(), now())
        ON CONFLICT DO NOTHING
        """,
        PUSH_PROOF_SESSION,
        ANNA_ID,
    )
    await connection.execute(
        """
        INSERT INTO push_subscription (
            id, user_id, session_id, endpoint, p256dh, auth, vapid_public_key
        )
        VALUES ($1, $2, $3, 'https://fcm.googleapis.com/fcm/send/poc072',
                decode(repeat('04', 65), 'hex'), decode(repeat('00', 16), 'hex'),
                repeat('A', 87))
        ON CONFLICT DO NOTHING
        """,
        PUSH_PROOF_DEVICE,
        ANNA_ID,
        PUSH_PROOF_SESSION,
    )
    await connection.execute(
        "INSERT INTO push_preference (user_id, kind, enabled) "
        "VALUES ($1, 'feed', true) ON CONFLICT DO NOTHING",
        ANNA_ID,
    )


async def assert_feed_push(connection: asyncpg.Connection[Any]) -> None:
    """The order for Anna's sponsor asked for exactly one push, for her.

    The job names a member, a kind and a count; nothing of the order. The
    proof removes the job before a worker can act on it and switches the
    flag off again, so the later orders of this contract ask for none.
    """

    rows = await connection.fetch(
        "SELECT aggregate_id, payload FROM outbox_event "
        "WHERE event_type = 'push.notification.v1'"
    )
    payloads = [json.loads(row["payload"]) for row in rows]
    if payloads != [{"userId": str(ANNA_ID), "kind": "feed", "count": 1}] or [
        row["aggregate_id"] for row in rows
    ] != [ANNA_ID]:
        raise ContractFailure("Public order asked for no push for its acquirer")
    await connection.execute(
        "DELETE FROM outbox_event WHERE event_type = 'push.notification.v1'"
    )
    await connection.execute(
        "UPDATE feature_flag SET enabled = false, revision = revision + 1 "
        "WHERE key = 'pwa.push'"
    )


async def assert_no_push(connection: asyncpg.Connection[Any]) -> None:
    """With the flag off, or for members who did not ask, nothing is queued."""

    count = await connection.fetchval(
        "SELECT count(*) FROM outbox_event WHERE event_type = 'push.notification.v1'"
    )
    if count != 0:
        raise ContractFailure("A push was queued although nobody may get one")
    await connection.execute("DELETE FROM push_preference WHERE user_id = $1", ANNA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE id = $1", PUSH_PROOF_SESSION
    )


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
