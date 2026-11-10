"""Invoice profiles follow the active legal configuration (spec §5.3).

Every action with the ``invoicing`` capability gets its profile from the
active legal configuration: when the action gets the capability and when a
legal configuration is activated. Without an active legal configuration no
profile can be confirmed, so none is created and issuing answers
``invoice_profile_missing``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg

from leonaid.adapters.postgres.document_series import ensure_series
from leonaid.domain.document_series import DocumentSeriesKind


async def ensure_invoice_profiles(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID | None = None,
) -> None:
    """Creates the missing profile of one action, or of every action.

    Existing profiles are not touched: the activation of a legal
    configuration updates them itself.
    """

    active = await connection.fetchrow(
        """
        SELECT version.number_prefix, version.number_width
        FROM legal_configuration_state AS state
        JOIN legal_configuration_version AS version
          ON version.id = state.active_version_id
        FOR SHARE OF state
        """
    )
    # The share lock waits for a running activation, which then finds this
    # action's capability, or makes the activation wait for this profile.
    if active is None:
        return
    await connection.execute(
        """
        INSERT INTO invoice_profile (
            id, action_id, legal_configuration_version_id, legal_name,
            street_line_1, postal_code, city, country_code, tax_identifier,
            email, tax_treatment, tax_rate_basis_points, tax_note,
            number_prefix, next_number, number_width, payment_terms_days,
            bank_account_holder, iban, bic, confirmed_at
        )
        SELECT
            gen_random_uuid(), capability.action_id, version.id,
            version.legal_name, version.street_line_1, version.postal_code,
            version.city, version.country_code, version.tax_identifier,
            version.issuer_email, version.tax_treatment,
            version.tax_rate_basis_points, version.tax_note,
            version.number_prefix, 1, version.number_width,
            version.payment_terms_days, version.bank_account_holder,
            version.iban, version.bic, state.updated_at
        FROM charity_action_capability AS capability
        CROSS JOIN legal_configuration_state AS state
        JOIN legal_configuration_version AS version
          ON version.id = state.active_version_id
        WHERE capability.capability = 'invoicing'
          AND ($1::uuid IS NULL OR capability.action_id = $1)
        ON CONFLICT (action_id) DO NOTHING
        """,
        action_id,
    )
    await ensure_series(
        connection,
        kind=DocumentSeriesKind.INVOICE,
        prefix=str(active["number_prefix"]),
        width=int(active["number_width"]),
    )
