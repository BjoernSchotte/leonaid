#!/usr/bin/env python3
"""Real PostgreSQL migration and constraint proof for POC-021."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

import asyncpg

EXPECTED_TABLES = {
    "acquisition_activity",
    "acquisition_assignment",
    "acquisition_assignment_history",
    "action_archive_slug_reservation",
    "action_invitation",
    "action_membership",
    "action_template_capability",
    "action_template_offering",
    "action_template_order_form",
    "action_template_snapshot",
    "action_template_version",
    "activity_event",
    "activity_event_recipient",
    "alembic_version",
    "audit_event",
    "beneficiary",
    "charity_action",
    "charity_action_capability",
    "command_receipt",
    "commitment",
    "commitment_line",
    "consent_record",
    "generated_document",
    "inbox_case",
    "inbox_case_comment",
    "inbox_case_material",
    "inbox_case_task",
    "feature_flag",
    "invoice",
    "invoice_cancellation",
    "invoice_delivery",
    "invoice_profile",
    "knowledge_page",
    "knowledge_page_material",
    "knowledge_page_member",
    "knowledge_page_revision",
    "knowledge_page_task",
    "login_challenge",
    "mail_delivery",
    "material",
    "material_member",
    "material_version",
    "offering",
    "order_form_configuration",
    "outbox_event",
    "payment_record",
    "public_action_alias",
    "privacy_erasure_case",
    "suppression_entry",
    "task",
    "task_epic",
    "task_list",
    "task_list_member",
    "task_personal_order_state",
    "task_personal_plan",
    "task_tag",
    "task_tag_assignment",
    "user_account",
    "user_global_role",
    "user_session",
}

USER_A = "10000000-0000-4000-8000-000000000004"
USER_B = "10000000-0000-4000-8000-000000000005"
ACTION = "20000000-0000-4000-8000-000000000001"
COMPANY = "40000000-0000-4000-8000-000000000001"
ASSIGNMENT_A = "60000000-0000-4000-8000-000000000001"
ASSIGNMENT_B = "60000000-0000-4000-8000-000000000002"
AUDIT = "d0000000-0000-4000-8000-000000000001"
OUTBOX = "e0000000-0000-4000-8000-000000000001"
INVITATION = "41000000-0000-4000-8000-000000000041"
SESSION = "42000000-0000-4000-8000-000000000041"
LOGIN_CHALLENGE = "43000000-0000-4000-8000-000000000041"


class SchemaError(RuntimeError):
    """The migrated schema did not enforce a required invariant."""


async def expect_database_error(
    operation: Callable[[], Awaitable[Any]],
    label: str,
    *,
    sqlstate: str | None = None,
    constraint: str | None = None,
    message: str | None = None,
) -> None:
    """The operation fails; when given, with this SQLSTATE, constraint, message."""

    try:
        await operation()
    except asyncpg.PostgresError as error:
        details = {
            "sqlstate": (sqlstate, getattr(error, "sqlstate", None)),
            "constraint": (constraint, getattr(error, "constraint_name", None)),
            "message": (message, str(error)),
        }
        wrong = {
            name: actual
            for name, (expected, actual) in details.items()
            if expected is not None and actual != expected
        }
        if wrong:
            raise SchemaError(
                f"{label}: rejected for another reason: {wrong}"
            ) from error
        return
    raise SchemaError(f"constraint was not enforced: {label}")


async def verify_tables(connection: asyncpg.Connection[Any], legacy: bool) -> None:
    rows = await connection.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        """
    )
    tables = {str(row["table_name"]) for row in rows}
    missing = EXPECTED_TABLES - tables
    if missing:
        raise SchemaError(f"core tables missing: {sorted(missing)}")
    revision = await connection.fetchval("SELECT version_num FROM alembic_version")
    if revision != "0020_account_status_admin":
        raise SchemaError(f"unexpected Alembic head: {revision}")
    if legacy:
        marker = await connection.fetchrow(
            "SELECT label, payload FROM previous_schema_snapshot WHERE id = 1"
        )
        if (
            marker is None
            or marker["label"] != "leonaid-core-v0"
            or marker["payload"]["amountMinor"] != 7200
            or marker["payload"]["actionId"] != ACTION
        ):
            raise SchemaError("data from the previous snapshot was lost")
        migrated_invoice = await connection.fetchrow(
            """
            SELECT
                action_id, status, recipient_snapshot, line_snapshot,
                issuer_snapshot, tax_treatment, tax_rate_basis_points,
                payment_reference
            FROM invoice
            WHERE id = '99000000-0000-4000-8000-000000000001'
            """
        )
        if (
            migrated_invoice is None
            or str(migrated_invoice["action_id"]) != ACTION
            or migrated_invoice["status"] != "issued"
            or migrated_invoice["recipient_snapshot"]["recipientName"]
            != "Legacy Sponsor GmbH"
            or migrated_invoice["recipient_snapshot"]["streetLine1"] != "Altweg 7"
            or migrated_invoice["line_snapshot"][0]["description"] != "Krapfenbox"
            or migrated_invoice["line_snapshot"][0]["grossMinor"] != 7200
            or migrated_invoice["issuer_snapshot"]["city"]
            != "MIGRATION_REVIEW_REQUIRED"
            or migrated_invoice["tax_treatment"] != "tax_exempt"
            or migrated_invoice["tax_rate_basis_points"] != 0
            or migrated_invoice["payment_reference"] != "LEGACY-0001"
        ):
            raise SchemaError(
                "legacy invoice was not fully migrated to the new snapshot contract"
            )
        invoice_dates = {
            str(row["number"]): (row["issued_on"], row["due_on"])
            for row in await connection.fetch(
                """
                SELECT number, issued_on, due_on FROM invoice
                WHERE number IN ('LEGACY-0001', 'LEGACY-0002')
                """
            )
        }
        # Backfilled with the UTC day of issued_at: LEGACY-0002 was issued at
        # 23:30 UTC on 16 November (already the 17th in Berlin).
        if invoice_dates != {
            "LEGACY-0001": (date(2026, 11, 16), date(2026, 11, 30)),
            "LEGACY-0002": (date(2026, 11, 16), date(2026, 11, 30)),
        }:
            raise SchemaError(f"invoice dates were not backfilled: {invoice_dates}")


async def insert_foundation(connection: asyncpg.Connection[Any]) -> None:
    await connection.executemany(
        """
        INSERT INTO user_account (id, email, display_name, status)
        VALUES ($1, $2, $3, 'active')
        """,
        [
            (USER_A, "anna.akquise@leonaid.invalid", "Anna Akquise"),
            (USER_B, "bernd.binder@leonaid.invalid", "Bernd Binder"),
        ],
    )
    await connection.execute(
        """
        INSERT INTO charity_action (
            id, carrier_name, name, purpose, status, starts_on, ends_on,
            archive_slug, goal_value, actual_value, goal_unit, currency
        )
        VALUES (
            $1, 'Lions Club Beispielstadt', 'Krapfentaxi 2026',
            'Synthetischer Golden-Data-Nachweis', 'active', $2, $3,
            'krapfentaxi-2026', 100000, 0, 'cent', 'EUR'
        )
        """,
        ACTION,
        date(2026, 9, 1),
        date(2026, 11, 15),
    )
    await connection.execute(
        """
        INSERT INTO charity_action_capability (action_id, capability)
        VALUES ($1, 'invoicing')
        """,
        ACTION,
    )


async def verify_constraints(connection: asyncpg.Connection[Any]) -> None:
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE charity_action
            SET publication_starts_at = CURRENT_TIMESTAMP,
                publication_ends_at = NULL
            WHERE id = $1
            """,
            ACTION,
        ),
        "incomplete publication window",
    )
    await expect_database_error(
        lambda: connection.execute(
            "UPDATE charity_action SET revision = 0 WHERE id = $1",
            ACTION,
        ),
        "non-positive action revision",
    )
    await connection.execute(
        """
        INSERT INTO public_action_alias (alias, action_id)
        VALUES ('krapfentaxi', $1)
        """,
        ACTION,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO public_action_alias (alias, action_id)
            VALUES ('krapfentaxi-zwei', $1)
            """,
            ACTION,
        ),
        "more than one public alias per action",
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE charity_action
            SET archive_slug = 'krapfentaxi-neu'
            WHERE id = $1
            """,
            ACTION,
        ),
        "mutable archive slug",
    )
    disposable_action = "20000000-0000-4000-8000-000000000099"
    reused_action = "20000000-0000-4000-8000-000000000098"
    await connection.execute(
        """
        INSERT INTO charity_action (
            id, carrier_name, name, purpose, status, starts_on, ends_on,
            archive_slug, goal_value, actual_value, goal_unit, currency
        )
        VALUES (
            $1, 'Lions Club Beispielstadt', 'Reservierungstest',
            'Beweist dauerhafte öffentliche Adressen.', 'draft', $2, $3,
            'dauerhaft-reserviert', NULL, 0, NULL, NULL
        )
        """,
        disposable_action,
        date(2027, 1, 1),
        date(2027, 1, 31),
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO public_action_alias (alias, action_id)
            VALUES ('archive', $1)
            """,
            disposable_action,
        ),
        "reserved public alias",
    )
    await connection.execute(
        "DELETE FROM charity_action WHERE id = $1",
        disposable_action,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO charity_action (
                id, carrier_name, name, purpose, status, starts_on, ends_on,
                archive_slug, goal_value, actual_value, goal_unit, currency
            )
            VALUES (
                $1, 'Lions Club Beispielstadt', 'Wiederverwendungstest',
                'Darf die Adresse nicht übernehmen.', 'draft', $2, $3,
                'dauerhaft-reserviert', NULL, 0, NULL, NULL
            )
            """,
            reused_action,
            date(2028, 1, 1),
            date(2028, 1, 31),
        ),
        "reuse of a deleted archive slug",
    )
    templates = await connection.fetch(
        """
        SELECT template_key, version
        FROM action_template_version
        ORDER BY template_key
        """
    )
    if [tuple(row.values()) for row in templates] != [
        ("blank", 1),
        ("krapfentaxi", 1),
    ]:
        raise SchemaError("built-in PoC templates are missing or unexpected")
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE action_template_version
            SET display_name = 'Manipuliert'
            WHERE template_key = 'krapfentaxi' AND version = 1
            """
        ),
        "mutation of a published template version",
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO offering (
                id, action_id, code, name, status, unit,
                allowed_quantity_units, pieces_per_unit,
                unit_price_minor, currency
            )
            VALUES (
                '70000000-0000-4000-8000-000000000099', $1,
                'ungueltig', 'Ungültig', 'active', 'box',
                ARRAY['box']::text[], 24, -1, 'EUR'
            )
            """,
            ACTION,
        ),
        "negative minor units",
    )
    await connection.execute(
        """
        INSERT INTO offering (
            id, action_id, code, name, status, unit,
            allowed_quantity_units, pieces_per_unit,
            unit_price_minor, currency
        )
        VALUES (
            '70000000-0000-4000-8000-000000000001', $1,
            'krapfenbox-24', 'Krapfenbox', 'active', 'box',
            ARRAY['box']::text[], 24, 3600, 'EUR'
        )
        """,
        ACTION,
    )
    await connection.execute(
        """
        INSERT INTO commitment (
            id, action_id, twenty_company_id, source, status,
            customer_snapshot, invoice_recipient_snapshot,
            currency, total_minor, idempotency_key
        )
        VALUES (
            '80000000-0000-4000-8000-000000000001', $1, $2,
            'acquisition', 'invoiced',
            '{"partyKind":"company","twentyId":"40000000-0000-4000-8000-000000000001","displayName":"Musterwerk GmbH","email":null}'::jsonb,
            '{"recipientName":"Musterwerk GmbH","streetLine1":"Werkstraße 1","postalCode":"86150","city":"Augsburg","countryCode":"DE","email":null}'::jsonb,
            'EUR', 7200, 'poc090:schema:commitment'
        )
        """,
        ACTION,
        COMPANY,
    )
    await connection.execute(
        """
        INSERT INTO commitment_line (
            id, commitment_id, offering_id, description_snapshot,
            quantity, unit_snapshot, pieces_per_unit_snapshot,
            unit_price_minor, line_total_minor
        )
        VALUES (
            '81000000-0000-4000-8000-000000000001',
            '80000000-0000-4000-8000-000000000001',
            '70000000-0000-4000-8000-000000000001',
            'Krapfenbox', 2, 'box', 24, 3600, 7200
        )
        """
    )
    await connection.execute(
        """
        INSERT INTO invoice_profile (
            id, action_id, legal_name, street_line_1, postal_code, city,
            country_code, tax_identifier, email, tax_treatment,
            tax_rate_basis_points, tax_note, number_prefix, next_number,
            number_width, payment_terms_days, confirmed_at,
            bank_account_holder, iban, bic
        )
        VALUES (
            '96000000-0000-4000-8000-000000000001', $1,
            'Lions Hilfswerk LeonAid Golden e.V.', 'Clubweg 1', '86150',
            'Augsburg', 'DE', '103/999/99999', 'finanzen@leonaid.invalid',
            'small_business', 0,
            'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.',
            'KT26-', 2, 4, 14, CURRENT_TIMESTAMP,
            'Lions Hilfswerk LeonAid Golden e.V.',
            'DE89370400440532013000', 'COBADEFFXXX'
        )
        """,
        ACTION,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE invoice_profile
            SET tax_rate_basis_points = 1900
            WHERE action_id = $1
            """,
            ACTION,
        ),
        "tax rate despite small-business VAT exemption",
    )
    await connection.execute(
        """
        INSERT INTO invoice (
            id, action_id, commitment_id, number, status, issued_at,
            service_on, due_on, currency, net_minor, tax_minor,
            gross_minor, issuer_snapshot, payment_details_snapshot,
            recipient_snapshot,
            line_snapshot, tax_treatment, tax_rate_basis_points,
            tax_note, payment_reference, approved_by_user_id,
            document_version, idempotency_key, issued_on
        )
        VALUES (
            '90000000-0000-4000-8000-000000000001', $1,
            '80000000-0000-4000-8000-000000000001', 'KT26-0001',
            'issued', CURRENT_TIMESTAMP, '2026-11-15', '2026-11-29',
            'EUR', 7200, 0, 7200,
            '{"legalName":"Lions Hilfswerk LeonAid Golden e.V.","streetLine1":"Clubweg 1","postalCode":"86150","city":"Augsburg","countryCode":"DE","taxIdentifier":"103/999/99999","email":"finanzen@leonaid.invalid"}'::jsonb,
            '{"accountHolder":"Lions Hilfswerk LeonAid Golden e.V.","iban":"DE89370400440532013000","bic":"COBADEFFXXX"}'::jsonb,
            '{"recipientName":"Musterwerk GmbH","streetLine1":"Werkstraße 1","postalCode":"86150","city":"Augsburg","countryCode":"DE","email":null}'::jsonb,
            '[{"description":"Krapfenbox","quantity":2,"unit":"box","unitPriceGrossMinor":3600,"taxRateBasisPoints":0,"netMinor":7200,"taxMinor":0,"grossMinor":7200,"currency":"EUR"}]'::jsonb,
            'small_business', 0,
            'Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.',
            'KT26-0001', $2, 2, 'poc090:schema:invoice', '2026-11-15'
        )
        """,
        ACTION,
        USER_A,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE invoice
            SET recipient_snapshot =
                jsonb_set(recipient_snapshot::jsonb, '{streetLine1}', '"Neu 9"')
            WHERE number = 'KT26-0001'
            """
        ),
        "changed snapshot of an issued invoice",
    )
    await expect_database_error(
        lambda: connection.execute(
            "UPDATE invoice SET issued_on = issued_on + 1 WHERE number = 'KT26-0001'"
        ),
        "changed invoice date of an issued invoice",
        sqlstate="23000",
        message="issued invoice snapshots are immutable",
    )
    # The CHECK, not the immutability trigger: a new row with a due date
    # before its invoice date. CHECK constraints run before the unique
    # index on the commitment, so nothing else can reject it first.
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO invoice (
                id, action_id, commitment_id, number, status, issued_at,
                service_on, due_on, currency, net_minor, tax_minor,
                gross_minor, issuer_snapshot, payment_details_snapshot,
                recipient_snapshot,
                line_snapshot, tax_treatment, tax_rate_basis_points,
                tax_note, payment_reference, approved_by_user_id,
                document_version, issued_on
            )
            SELECT
                '90000000-0000-4000-8000-000000000003', action_id,
                commitment_id, 'KT26-0003', status, issued_at,
                service_on, issued_on - 1, currency, net_minor, tax_minor,
                gross_minor, issuer_snapshot, payment_details_snapshot,
                recipient_snapshot,
                line_snapshot, tax_treatment, tax_rate_basis_points,
                tax_note, 'KT26-0003', approved_by_user_id,
                document_version, issued_on
            FROM invoice
            WHERE number = 'KT26-0001'
            """
        ),
        "due date before the invoice date",
        sqlstate="23514",
        constraint="ck_invoice_due_on_after_issued_on",
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO invoice (
                id, action_id, commitment_id, number, status, issued_at,
                service_on, due_on, currency, net_minor, tax_minor,
                gross_minor, issuer_snapshot, payment_details_snapshot,
                recipient_snapshot,
                line_snapshot, tax_treatment, tax_rate_basis_points,
                tax_note, payment_reference, approved_by_user_id,
                document_version, issued_on
            )
            SELECT
                '90000000-0000-4000-8000-000000000002', action_id,
                commitment_id, 'KT26-0002', status, issued_at,
                service_on, due_on, currency, net_minor, tax_minor,
                gross_minor, issuer_snapshot, payment_details_snapshot,
                recipient_snapshot,
                line_snapshot, tax_treatment, tax_rate_basis_points,
                tax_note, 'KT26-0002', approved_by_user_id,
                document_version, issued_on
            FROM invoice
            WHERE number = 'KT26-0001'
            """
        ),
        "second invoice for the same commitment",
    )
    await connection.execute(
        "UPDATE invoice SET status = 'cancelled' WHERE number = 'KT26-0001'"
    )
    preserved_number = await connection.fetchval(
        "SELECT number FROM invoice WHERE status = 'cancelled'"
    )
    if preserved_number != "KT26-0001":
        raise SchemaError("cancellation replaced the issued invoice number")
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO acquisition_assignment (
                id, action_id, twenty_company_id, twenty_person_id,
                acquirer_user_id
            )
            VALUES (
                '60000000-0000-4000-8000-000000000099', $1, $2,
                '50000000-0000-4000-8000-000000000001', $3
            )
            """,
            ACTION,
            COMPANY,
            USER_A,
        ),
        "more than one CRM party",
    )
    await connection.execute(
        """
        INSERT INTO acquisition_assignment (
            id, action_id, twenty_company_id, acquirer_user_id
        )
        VALUES ($1, $2, $3, $4)
        """,
        ASSIGNMENT_A,
        ACTION,
        COMPANY,
        USER_A,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE acquisition_assignment
            SET revision = 0
            WHERE id = $1
            """,
            ASSIGNMENT_A,
        ),
        "non-positive assignment revision",
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            INSERT INTO acquisition_assignment (
                id, action_id, twenty_company_id, acquirer_user_id
            )
            VALUES (
                '60000000-0000-4000-8000-000000000098', $1, $2, $3
            )
            """,
            ACTION,
            COMPANY,
            USER_A,
        ),
        "duplicate acquirer assignment",
    )
    await connection.execute(
        """
        INSERT INTO acquisition_assignment (
            id, action_id, twenty_company_id, acquirer_user_id
        )
        VALUES ($1, $2, $3, $4)
        """,
        ASSIGNMENT_B,
        ACTION,
        COMPANY,
        USER_B,
    )
    await expect_database_error(
        lambda: connection.execute(
            "UPDATE charity_action SET status = 'draft' WHERE id = $1",
            ACTION,
        ),
        "backward action status transition",
    )
    await connection.execute(
        """
        INSERT INTO action_invitation (
            id,
            action_id,
            invited_by_user_id,
            email_snapshot,
            display_name_snapshot,
            action_name_snapshot,
            invited_by_name_snapshot,
            role_snapshot,
            status,
            token_digest,
            code_digest,
            expires_at
        )
        VALUES (
            $1, $2, $3, 'invite@leonaid.invalid', 'Invite Golden',
            'Krapfentaxi 2026', 'Anna Akquise', 'acquirer', 'pending',
            $4, $5, CURRENT_TIMESTAMP + INTERVAL '30 minutes'
        )
        """,
        INVITATION,
        ACTION,
        USER_A,
        "a" * 64,
        "b" * 64,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE action_invitation
            SET email_snapshot = 'changed@leonaid.invalid'
            WHERE id = $1
            """,
            INVITATION,
        ),
        "changed invitation snapshot",
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE action_invitation
            SET status = 'accepted'
            WHERE id = $1
            """,
            INVITATION,
        ),
        "incomplete invitation acceptance",
    )
    await connection.execute(
        """
        INSERT INTO user_session (
            id,
            user_id,
            token_digest,
            expires_at,
            last_seen_at,
            fresh_login_at,
            device_hint,
            created_at,
            updated_at
        )
        VALUES (
            $1, $2, $3, CURRENT_TIMESTAMP + INTERVAL '90 days',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'POC-042 schema proof',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        SESSION,
        USER_A,
        "c" * 64,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE user_session
            SET fresh_login_at = created_at - INTERVAL '1 second'
            WHERE id = $1
            """,
            SESSION,
        ),
        "fresh login before session start",
    )
    await connection.execute(
        """
        INSERT INTO login_challenge (
            id,
            user_id,
            purpose,
            email_snapshot,
            token_digest,
            code_digest,
            status,
            expires_at,
            created_at,
            updated_at
        )
        VALUES (
            $1, $2, 'login', 'anna.akquise@leonaid.invalid',
            $3, $4, 'pending', CURRENT_TIMESTAMP + INTERVAL '10 minutes',
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        """,
        LOGIN_CHALLENGE,
        USER_A,
        "d" * 64,
        "e" * 64,
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE login_challenge
            SET email_snapshot = 'changed@leonaid.invalid'
            WHERE id = $1
            """,
            LOGIN_CHALLENGE,
        ),
        "changed login snapshot",
    )
    await expect_database_error(
        lambda: connection.execute(
            """
            UPDATE login_challenge
            SET status = 'consumed'
            WHERE id = $1
            """,
            LOGIN_CHALLENGE,
        ),
        "partially consumed login challenge",
    )


async def verify_transactionality(connection: asyncpg.Connection[Any]) -> None:
    transaction = connection.transaction()
    await transaction.start()
    await connection.execute(
        "UPDATE charity_action SET actual_value = 7200 WHERE id = $1",
        ACTION,
    )
    await connection.execute(
        """
        INSERT INTO audit_event (
            id, action_id, actor_user_id, event_type, entity_type,
            entity_id, request_id, payload
        )
        VALUES ($1, $2, $3, 'goal.updated', 'charity_action', $2, $4, $5::jsonb)
        """,
        AUDIT,
        ACTION,
        USER_A,
        "poc021:system-admin:golden-v1",
        '{"actualValueMinor":7200}',
    )
    await connection.execute(
        """
        INSERT INTO outbox_event (
            id, aggregate_type, aggregate_id, event_type,
            idempotency_key, payload
        )
        VALUES ($1, 'charity_action', $2, 'goal.updated', $3, $4::jsonb)
        """,
        OUTBOX,
        ACTION,
        "poc021:goal:20000000-0000-4000-8000-000000000001:7200",
        '{"actualValueMinor":7200}',
    )
    await transaction.rollback()
    rolled_back = await connection.fetchrow(
        """
        SELECT
          (SELECT actual_value FROM charity_action WHERE id = $1) AS value,
          (SELECT count(*) FROM audit_event WHERE id = $2) AS audits,
          (SELECT count(*) FROM outbox_event WHERE id = $3) AS outbox
        """,
        ACTION,
        AUDIT,
        OUTBOX,
    )
    if rolled_back != {"value": 0, "audits": 0, "outbox": 0}:
        raise SchemaError(f"rollback was not atomic: {dict(rolled_back or {})}")

    async with connection.transaction():
        await connection.execute(
            "UPDATE charity_action SET actual_value = 7200 WHERE id = $1",
            ACTION,
        )
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type, entity_type,
                entity_id, request_id, payload
            )
            VALUES ($1, $2, $3, 'goal.updated', 'charity_action', $2, $4, $5::jsonb)
            """,
            AUDIT,
            ACTION,
            USER_A,
            "poc021:system-admin:golden-v1",
            '{"actualValueMinor":7200}',
        )
        await connection.execute(
            """
            INSERT INTO outbox_event (
                id, aggregate_type, aggregate_id, event_type,
                idempotency_key, payload
            )
            VALUES ($1, 'charity_action', $2, 'goal.updated', $3, $4::jsonb)
            """,
            OUTBOX,
            ACTION,
            "poc021:goal:20000000-0000-4000-8000-000000000001:7200",
            '{"actualValueMinor":7200}',
        )
    committed = await connection.fetchrow(
        """
        SELECT
          (SELECT actual_value FROM charity_action WHERE id = $1) AS value,
          (SELECT count(*) FROM audit_event WHERE id = $2) AS audits,
          (SELECT count(*) FROM outbox_event WHERE id = $3) AS outbox
        """,
        ACTION,
        AUDIT,
        OUTBOX,
    )
    if committed != {"value": 7200, "audits": 1, "outbox": 1}:
        raise SchemaError(f"commit was not atomic: {dict(committed or {})}")

    occurred_at = await connection.fetchval(
        "SELECT occurred_at FROM audit_event WHERE id = $1",
        AUDIT,
    )
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise SchemaError("audit timestamp is not timezone-aware")


async def run(legacy: bool) -> None:
    connection = await asyncpg.connect(os.environ["CORE_DATABASE_URL"], timeout=10)
    try:
        await verify_tables(connection, legacy)
        await insert_foundation(connection)
        await verify_constraints(connection)
        await verify_transactionality(connection)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy", action="store_true")
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments.legacy))
    except (KeyError, OSError, SchemaError, asyncpg.PostgresError) as error:
        print(
            "poc021-schema: ERROR: "
            "requestId=poc021:system-admin:golden-v1 "
            f"type={type(error).__name__}",
            file=sys.stderr,
        )
        return 1
    mode = "upgrade from previous snapshot" if arguments.legacy else "build from empty"
    print(
        f"poc021-schema: OK: {mode}, constraints, timezone-aware data "
        "and transactional audit/outbox"
    )
    return 0
