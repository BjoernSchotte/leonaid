from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from leonaid.application.commitments import CommitmentLineDraft
from leonaid.application.errors import PermissionDenied
from leonaid.application.public_orders import (
    PublicOrderDraft,
    PublicOrderPartyDraft,
    PublicOrderTokenCodec,
    public_order_fingerprint,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
)
from leonaid.domain.errors import DomainInvariantError

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
OFFERING_ID = UUID("70000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
SECRET = "public-order-unit-test-secret-at-least-32-characters"
PRIVACY_NOTICE_VERSION = "public-order-poc-2026-07"


def public_order() -> PublicOrderDraft:
    return PublicOrderDraft(
        party=PublicOrderPartyDraft(
            company_name="  Musterwerk   GmbH ",
            given_name=" Erika ",
            family_name=" Musterfrau ",
            email="ERIKA@MUSTERWERK.INVALID",
            phone=" 0821 123456 ",
        ),
        delivery_recipient=DeliveryRecipientSnapshot(
            recipient_name="Musterwerk Wareneingang",
            street_line_1="Lieferweg 4",
            postal_code="86150",
            city="Augsburg",
        ),
        invoice_recipient=InvoiceRecipientSnapshot(
            recipient_name="Musterwerk Rechnungseingang",
            street_line_1="Zahlweg 9",
            postal_code="86150",
            city="Augsburg",
            email="rechnung@musterwerk.invalid",
        ),
        lines=(
            CommitmentLineDraft(
                offering_id=OFFERING_ID,
                quantity=2,
                unit=OfferingUnit.BOX,
                quoted_unit_price_minor=3_600,
            ),
        ),
        message=" Bitte am Empfang abgeben. ",
        privacy_acknowledged=True,
        binding_order_confirmed=True,
        privacy_notice_version=PRIVACY_NOTICE_VERSION,
    )


def test_public_order_token_round_trip_is_alias_bound_and_expires() -> None:
    codec = PublicOrderTokenCodec(SECRET, ttl=timedelta(hours=2))
    token = codec.issue(ACTION_ID, "krapfentaxi", issued_at=NOW)

    claims = codec.verify(
        token,
        expected_alias="krapfentaxi",
        evaluated_at=NOW + timedelta(minutes=30),
    )

    assert claims.action_id == ACTION_ID
    assert claims.public_alias == "krapfentaxi"
    assert claims.issued_at == NOW
    assert claims.expires_at == NOW + timedelta(hours=2)

    with pytest.raises(PermissionDenied) as wrong_alias:
        codec.verify(
            token,
            expected_alias="lions-open",
            evaluated_at=NOW + timedelta(minutes=30),
        )
    assert wrong_alias.value.code == "public_order_token_invalid"

    with pytest.raises(PermissionDenied) as expired:
        codec.verify(
            token,
            expected_alias="krapfentaxi",
            evaluated_at=NOW + timedelta(hours=2),
        )
    assert expired.value.code == "public_order_token_invalid"


def test_public_order_token_rejects_tampering() -> None:
    codec = PublicOrderTokenCodec(SECRET)
    token = codec.issue(ACTION_ID, "krapfentaxi", issued_at=NOW)
    payload, signature = token.split(".", 1)
    replacement = "A" if payload[-1] != "A" else "B"
    tampered = f"{payload[:-1]}{replacement}.{signature}"

    with pytest.raises(PermissionDenied) as captured:
        codec.verify(
            tampered,
            expected_alias="krapfentaxi",
            evaluated_at=NOW,
        )
    assert captured.value.code == "public_order_token_invalid"


def test_public_order_normalizes_party_and_hashes_material_fields() -> None:
    order = public_order()

    assert order.party.company_name == "Musterwerk GmbH"
    assert order.party.given_name == "Erika"
    assert order.party.family_name == "Musterfrau"
    assert order.party.email == "erika@musterwerk.invalid"
    assert order.party.phone == "+49821123456"
    assert order.message == "Bitte am Empfang abgeben."

    original = order.request_hash(
        action_id=ACTION_ID,
        public_alias="krapfentaxi",
    )
    repriced = replace(
        order,
        lines=(
            replace(
                order.lines[0],
                quoted_unit_price_minor=3_700,
            ),
        ),
    ).request_hash(
        action_id=ACTION_ID,
        public_alias="krapfentaxi",
    )

    assert original != repriced


@pytest.mark.parametrize(
    ("changes", "code"),
    (
        ({"privacy_acknowledged": False}, "public_order_privacy_required"),
        (
            {"binding_order_confirmed": False},
            "public_order_confirmation_required",
        ),
        (
            {"privacy_notice_version": "INVALID VERSION"},
            "public_order_privacy_notice_version_invalid",
        ),
        (
            {
                "lines": (
                    CommitmentLineDraft(
                        offering_id=OFFERING_ID,
                        quantity=1,
                        unit=OfferingUnit.BOX,
                    ),
                ),
            },
            "public_order_quote_required",
        ),
    ),
)
def test_public_order_requires_current_notices_confirmation_and_quote(
    changes: dict[str, object],
    code: str,
) -> None:
    order = public_order()

    with pytest.raises(DomainInvariantError) as captured:
        replace(order, **changes)
    assert captured.value.code == code


def test_public_order_fingerprint_is_stable_and_does_not_expose_client_data() -> None:
    fingerprint = public_order_fingerprint(
        SECRET,
        forwarded_for="10.0.0.7, 203.0.113.42",
        client_host="127.0.0.1",
        user_agent="Golden Browser/2026",
    )
    repeated = public_order_fingerprint(
        SECRET,
        forwarded_for="10.0.0.7, 203.0.113.42",
        client_host="127.0.0.1",
        user_agent="Golden Browser/2026",
    )
    changed = public_order_fingerprint(
        SECRET,
        forwarded_for="10.0.0.7, 203.0.113.43",
        client_host="127.0.0.1",
        user_agent="Golden Browser/2026",
    )

    assert fingerprint == repeated
    assert changed != fingerprint
    assert len(fingerprint) == 64
    assert "203.0.113.42" not in fingerprint
    assert "Golden Browser" not in fingerprint


def test_public_order_rejects_an_invalid_phone_before_calling_the_crm() -> None:
    with pytest.raises(DomainInvariantError) as captured:
        replace(
            public_order().party,
            phone="keine Telefonnummer",
        )

    assert captured.value.code == "public_order_phone_invalid"
