"""Issued campaign-token binding and the unconfigured-CRM HTTP boundary."""

import os
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.application.errors import PermissionDenied
from leonaid.application.public_orders import PublicOrderTokenCodec
from tools.public_orders.contract import order_body


async def prove_order_token(
    client: httpx.AsyncClient,
    pool: asyncpg.Pool[Any],
    payload: dict[str, Any],
) -> None:
    assert payload["submissionsAllowed"] is True
    action = payload["action"]
    form = action["orderForm"]
    token = form["accessToken"]
    alias = payload["orderAlias"]
    codec = PublicOrderTokenCodec(os.environ["LEONAID_SECRET_KEY"])
    claims = codec.verify(token, expected_alias=alias)
    assert claims.action_id == UUID(action["id"])
    assert claims.public_alias == alias
    assert payload["routeValue"] != alias
    for candidate, expected_alias in (
        (token, payload["routeValue"]),
        (token + "corrupt", alias),
    ):
        try:
            codec.verify(candidate, expected_alias=expected_alias)
        except PermissionDenied as error:
            assert error.code == "public_order_token_invalid"
        else:
            raise AssertionError("invalid campaign token binding accepted")
    offering = action["offerings"][0]
    body = order_body(
        token=token,
        command=uuid4(),
        given_name="Synthetic",
        family_name="Campaign",
        email="campaign-proof@leonaid.invalid",
        company_name=None,
        offering_id=UUID(offering["id"]),
        quoted_price=offering["unitPriceMinor"],
        website="synthetic-honeypot.invalid",
    )
    body["privacyNoticeVersion"] = form["privacyNoticeVersion"]
    before = await pool.fetchval("SELECT count(*) FROM commitment")
    unavailable = await client.post(
        f"/api/v1/public/actions/{alias}/orders",
        json=body,
        headers={"X-LeonAid-Order-Key": os.environ["LEONAID_ORDER_SUBMISSION_KEY"]},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "public_order_crm_unavailable"
    # This fixture intentionally has no CRM credentials. Core does not create
    # PublicOrderService, so HTTP rejection occurs BEFORE token verification.
    assert await pool.fetchval("SELECT count(*) FROM commitment") == before
    print(
        "core-campaign-order-token: HTTP-issued signature/action/alias verified with Core codec; wrong alias and corrupt token rejected by codec; HTTP fails closed with unconfigured CRM, commitments unchanged; HTTP token redemption and order creation remain pending"
    )
