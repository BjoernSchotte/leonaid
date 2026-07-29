"""PostgreSQL privacy evidence, suppression and data-subject workflows."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict
from leonaid.application.privacy import PrivacyRepository
from leonaid.domain.privacy import (
    ContactChannel,
    ConsentEvidenceKind,
    ConsentRecord,
    ErasureStatus,
    LegalBasisStatus,
    PrivacyErasureResult,
    PrivacyPurpose,
    PrivacyReference,
    PrivacyRetentionPolicy,
    PrivacySubjectReport,
    SuppressionEntry,
    subject_digest,
)


def _consent(row: asyncpg.Record) -> ConsentRecord:
    return ConsentRecord(
        id=row["id"],
        action_id=row["action_id"],
        commitment_id=row["commitment_id"],
        twenty_company_id=row["twenty_company_id"],
        twenty_person_id=row["twenty_person_id"],
        normalized_recipient=str(row["normalized_recipient"] or ""),
        purpose=PrivacyPurpose(str(row["purpose"])),
        channel=ContactChannel(str(row["channel"])),
        text_version=str(row["text_version"]),
        source=str(row["source"]),
        evidence_kind=ConsentEvidenceKind(str(row["evidence_kind"])),
        legal_basis_status=LegalBasisStatus(str(row["legal_basis_status"])),
        granted_at=row["granted_at"],
        revoked_at=row["revoked_at"],
    )


def _suppression(row: asyncpg.Record) -> SuppressionEntry:
    return SuppressionEntry(
        id=row["id"],
        normalized_recipient=str(row["normalized_recipient"]),
        channel=ContactChannel(str(row["channel"])),
        purpose=PrivacyPurpose(str(row["purpose"])),
        reason=str(row["reason"]),
        suppressed_at=row["suppressed_at"],
        consent_record_id=row["consent_record_id"],
    )


def _reference(
    row: asyncpg.Record,
    *,
    reference_type: str,
    label_column: str,
) -> PrivacyReference:
    return PrivacyReference(
        id=row["id"],
        reference_type=reference_type,
        action_id=row["action_id"],
        status=str(row["status"]) if row["status"] is not None else None,
        label=str(row[label_column]),
    )


class AsyncpgPrivacyRepository(PrivacyRepository):
    def __init__(self, pool: asyncpg.Pool[Any], *, subject_hmac_secret: str) -> None:
        self._pool = pool
        self._subject_hmac_secret = subject_hmac_secret

    async def subject_report(self, normalized_email: str) -> PrivacySubjectReport:
        async with self._pool.acquire() as connection:
            return await self._subject_report(connection, normalized_email)

    @staticmethod
    async def _subject_report(
        connection: asyncpg.Connection[Any],
        normalized_email: str,
    ) -> PrivacySubjectReport:
        retention = await AsyncpgPrivacyRepository._active_retention(connection)
        consents = await connection.fetch(
            """
            SELECT *
            FROM consent_record
            WHERE normalized_recipient = $1
            ORDER BY granted_at, id
            """,
            normalized_email,
        )
        suppressions = await connection.fetch(
            """
            SELECT *
            FROM suppression_entry
            WHERE normalized_recipient = $1
            ORDER BY suppressed_at, id
            """,
            normalized_email,
        )
        commitments = await connection.fetch(
            """
            SELECT
                id, action_id, status,
                COALESCE(public_reference, id::text) AS label,
                twenty_company_id, twenty_person_id
            FROM commitment
            WHERE lower(COALESCE(customer_snapshot ->> 'email', '')) = $1
               OR lower(COALESCE(invoice_recipient_snapshot ->> 'email', '')) = $1
               OR lower(COALESCE(delivery_recipient_snapshot ->> 'email', '')) = $1
            ORDER BY created_at, id
            """,
            normalized_email,
        )
        company_ids = {
            row["twenty_company_id"]
            for row in (*consents, *commitments)
            if row["twenty_company_id"] is not None
        }
        person_ids = {
            row["twenty_person_id"]
            for row in (*consents, *commitments)
            if row["twenty_person_id"] is not None
        }
        commitment_ids = [row["id"] for row in commitments]
        invoices = await connection.fetch(
            """
            SELECT id, action_id, status, number AS label
            FROM invoice
            WHERE commitment_id = ANY($1::uuid[])
               OR lower(COALESCE(recipient_snapshot ->> 'email', '')) = $2
            ORDER BY issued_at NULLS LAST, id
            """,
            commitment_ids,
            normalized_email,
        )
        invoice_ids = [row["id"] for row in invoices]
        documents = await connection.fetch(
            """
            SELECT
                id, action_id, status,
                COALESCE(filename, document_type || ' v' || version::text) AS label
            FROM generated_document
            WHERE commitment_id = ANY($1::uuid[])
               OR invoice_id = ANY($2::uuid[])
            ORDER BY created_at, id
            """,
            commitment_ids,
            invoice_ids,
        )
        assignments = await connection.fetch(
            """
            SELECT
                id, action_id, status,
                'Akquise-Zuordnung' AS label
            FROM acquisition_assignment
            WHERE twenty_company_id = ANY($1::uuid[])
               OR twenty_person_id = ANY($2::uuid[])
            ORDER BY created_at, id
            """,
            list(company_ids),
            list(person_ids),
        )
        activities = await connection.fetch(
            """
            SELECT
                id, action_id, outcome AS status,
                'Kontaktaktivität · ' || channel AS label
            FROM acquisition_activity
            WHERE commitment_id = ANY($1::uuid[])
               OR twenty_company_id = ANY($2::uuid[])
               OR twenty_person_id = ANY($3::uuid[])
            ORDER BY occurred_at, id
            """,
            commitment_ids,
            list(company_ids),
            list(person_ids),
        )
        return PrivacySubjectReport(
            normalized_recipient=normalized_email,
            retention=retention,
            twenty_company_ids=tuple(sorted(company_ids)),
            twenty_person_ids=tuple(sorted(person_ids)),
            consents=tuple(_consent(row) for row in consents),
            suppressions=tuple(_suppression(row) for row in suppressions),
            commitments=tuple(
                _reference(row, reference_type="commitment", label_column="label")
                for row in commitments
            ),
            invoices=tuple(
                _reference(row, reference_type="invoice", label_column="label")
                for row in invoices
            ),
            documents=tuple(
                _reference(row, reference_type="document", label_column="label")
                for row in documents
            ),
            assignments=tuple(
                _reference(row, reference_type="assignment", label_column="label")
                for row in assignments
            ),
            activities=tuple(
                _reference(row, reference_type="activity", label_column="label")
                for row in activities
            ),
        )

    @staticmethod
    async def _active_retention(
        connection: asyncpg.Connection[Any],
    ) -> PrivacyRetentionPolicy:
        row = await connection.fetchrow(
            """
            SELECT
                version.id,
                version.version,
                version.invoice_retention_days,
                version.commitment_retention_days,
                version.contact_retention_days,
                version.consent_evidence_retention_days,
                version.audit_retention_days
            FROM legal_configuration_state AS state
            JOIN legal_configuration_version AS version
              ON version.id = state.active_version_id
            FOR SHARE OF state, version
            """
        )
        if row is None:
            raise Conflict(
                "privacy_legal_configuration_missing",
                "Vor Datenschutzvorgängen muss eine Rechtsgrundlage "
                "mit Aufbewahrungsfristen aktiviert werden.",
            )
        return PrivacyRetentionPolicy(
            legal_configuration_version_id=row["id"],
            legal_configuration_version=int(row["version"]),
            invoice_days=int(row["invoice_retention_days"]),
            commitment_days=int(row["commitment_retention_days"]),
            contact_days=int(row["contact_retention_days"]),
            consent_evidence_days=int(row["consent_evidence_retention_days"]),
            audit_days=int(row["audit_retention_days"]),
        )

    async def revoke_consent(
        self,
        *,
        consent_id: UUID,
        actor_user_id: UUID,
        reason: str,
        request_id: str,
        occurred_at: datetime,
    ) -> ConsentRecord | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT *
                    FROM consent_record
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    consent_id,
                )
                if row is None:
                    return None
                await connection.execute(
                    """
                    UPDATE consent_record
                    SET revoked_at = COALESCE(revoked_at, $2)
                    WHERE id = $1
                    """,
                    consent_id,
                    occurred_at,
                )
                for purpose in (
                    PrivacyPurpose.ACQUISITION,
                    PrivacyPurpose.MARKETING,
                ):
                    await connection.execute(
                        """
                        INSERT INTO suppression_entry (
                            id, normalized_recipient, channel, purpose,
                            reason, suppressed_at, consent_record_id
                        )
                        VALUES ($1, $2, 'email', $3, $4, $5, $6)
                        ON CONFLICT (
                            normalized_recipient, channel, purpose
                        )
                        DO UPDATE SET
                            reason = EXCLUDED.reason,
                            suppressed_at = EXCLUDED.suppressed_at,
                            consent_record_id = EXCLUDED.consent_record_id
                        """,
                        uuid4(),
                        row["normalized_recipient"],
                        purpose.value,
                        reason,
                        occurred_at,
                        consent_id,
                    )
                await connection.execute(
                    """
                    INSERT INTO audit_event (
                        id, action_id, actor_user_id, event_type,
                        entity_type, entity_id, request_id, payload, occurred_at
                    )
                    VALUES (
                        $1, $2, $3, 'privacy_contact_suppressed',
                        'consent_record', $4, $5, $6::jsonb, $7
                    )
                    """,
                    uuid4(),
                    row["action_id"],
                    actor_user_id,
                    consent_id,
                    request_id,
                    json.dumps(
                        {
                            "channel": "email",
                            "purposes": ["acquisition", "marketing"],
                            "reason": reason,
                            "subjectHash": subject_digest(
                                str(row["normalized_recipient"]),
                                self._subject_hmac_secret,
                            ),
                        },
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
                updated = await connection.fetchrow(
                    "SELECT * FROM consent_record WHERE id = $1",
                    consent_id,
                )
                assert updated is not None
                return _consent(updated)

    async def suppressed_channels(
        self,
        recipients: tuple[tuple[str, ContactChannel], ...],
        *,
        purpose: PrivacyPurpose,
    ) -> frozenset[tuple[str, ContactChannel]]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT normalized_recipient, channel
                FROM suppression_entry
                WHERE purpose = $1
                  AND (normalized_recipient, channel) IN (
                      SELECT *
                      FROM unnest($2::text[], $3::text[])
                  )
                """,
                purpose.value,
                [item[0] for item in recipients],
                [item[1].value for item in recipients],
            )
        return frozenset(
            (
                str(row["normalized_recipient"]),
                ContactChannel(str(row["channel"])),
            )
            for row in rows
        )

    async def erase_subject(
        self,
        *,
        normalized_email: str,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
        open_decisions: tuple[str, ...],
    ) -> PrivacyErasureResult | None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                report = await self._subject_report(connection, normalized_email)
                if not report.found:
                    return None
                retention = report.retention
                retention_reasons = (
                    "Ausgestellte Rechnungen und ihre PDFs bleiben gemäß "
                    f"freigegebener Frist {retention.invoice_days} Tage erhalten.",
                    "Consent-Nachweise bleiben gemäß freigegebener Frist "
                    f"{retention.consent_evidence_days} Tage nachvollziehbar.",
                )
                commitment_ids = [item.id for item in report.commitments]
                company_ids = list(report.twenty_company_ids)
                person_ids = list(report.twenty_person_ids)
                invoices = tuple(item.id for item in report.invoices)
                documents = tuple(item.id for item in report.documents)

                commitment_status = await connection.execute(
                    """
                    UPDATE commitment
                    SET customer_snapshot = customer_snapshot || $2::jsonb,
                        invoice_recipient_snapshot = CASE
                            WHEN invoice_recipient_snapshot IS NULL THEN NULL
                            ELSE invoice_recipient_snapshot || $3::jsonb
                        END,
                        delivery_recipient_snapshot = CASE
                            WHEN delivery_recipient_snapshot IS NULL THEN NULL
                            ELSE delivery_recipient_snapshot || $3::jsonb
                        END,
                        message_snapshot = NULL,
                        updated_at = $4
                    WHERE id = ANY($1::uuid[])
                    """,
                    commitment_ids,
                    json.dumps(
                        {
                            "displayName": "Anonymisiert",
                            "email": None,
                            "phone": None,
                        }
                    ),
                    json.dumps(
                        {
                            "recipientName": "Anonymisiert",
                            "streetLine1": "Entfernt",
                            "postalCode": "00000",
                            "city": "Entfernt",
                            "email": None,
                            "phone": None,
                        }
                    ),
                    occurred_at,
                )
                activity_status = await connection.execute(
                    """
                    UPDATE acquisition_activity
                    SET note = NULL,
                        next_action_snapshot = NULL,
                        due_at_snapshot = NULL
                    WHERE commitment_id = ANY($1::uuid[])
                       OR twenty_company_id = ANY($2::uuid[])
                       OR twenty_person_id = ANY($3::uuid[])
                    """,
                    commitment_ids,
                    company_ids,
                    person_ids,
                )
                reminder_status = await connection.execute(
                    """
                    UPDATE acquisition_assignment
                    SET next_action = NULL,
                        due_at = NULL,
                        updated_at = $3
                    WHERE twenty_company_id = ANY($1::uuid[])
                       OR twenty_person_id = ANY($2::uuid[])
                    """,
                    company_ids,
                    person_ids,
                    occurred_at,
                )
                revoked_status = await connection.execute(
                    """
                    UPDATE consent_record
                    SET revoked_at = COALESCE(revoked_at, $2)
                    WHERE normalized_recipient = $1
                    """,
                    normalized_email,
                    occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO suppression_entry (
                        id, normalized_recipient, channel, purpose,
                        reason, suppressed_at
                    )
                    VALUES ($1, $2, 'email', 'acquisition', $3, $4)
                    ON CONFLICT (normalized_recipient, channel, purpose)
                    DO UPDATE SET
                        reason = EXCLUDED.reason,
                        suppressed_at = EXCLUDED.suppressed_at
                    """,
                    uuid4(),
                    normalized_email,
                    "Datenschutz-Löschworkflow abgeschlossen",
                    occurred_at,
                )
                case_id = uuid4()
                subject_hash = subject_digest(
                    normalized_email,
                    self._subject_hmac_secret,
                )
                counts = (
                    int(commitment_status.rsplit(" ", 1)[-1]),
                    int(activity_status.rsplit(" ", 1)[-1]),
                    int(reminder_status.rsplit(" ", 1)[-1]),
                    int(revoked_status.rsplit(" ", 1)[-1]),
                )
                await connection.execute(
                    """
                    INSERT INTO privacy_erasure_case (
                        id, subject_hash, requested_by_user_id, status,
                        anonymized_commitments, cleared_activity_notes,
                        cleared_reminders, revoked_consents,
                        retained_invoice_ids, retained_document_ids,
                        retention_reasons, open_decisions,
                        legal_configuration_version_id, retention_schedule,
                        requested_at, completed_at
                    )
                    VALUES (
                        $1, $2, $3, 'completed_with_retention',
                        $4, $5, $6, $7,
                        $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
                        $12, $13::jsonb, $14, $14
                    )
                    """,
                    case_id,
                    subject_hash,
                    actor_user_id,
                    *counts,
                    json.dumps([str(item) for item in invoices]),
                    json.dumps([str(item) for item in documents]),
                    json.dumps(retention_reasons, ensure_ascii=False),
                    json.dumps(open_decisions, ensure_ascii=False),
                    retention.legal_configuration_version_id,
                    json.dumps(
                        {
                            "legalConfigurationVersion": (
                                retention.legal_configuration_version
                            ),
                            "invoiceDays": retention.invoice_days,
                            "commitmentDays": retention.commitment_days,
                            "contactDays": retention.contact_days,
                            "consentEvidenceDays": retention.consent_evidence_days,
                            "auditDays": retention.audit_days,
                        },
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO audit_event (
                        id, actor_user_id, event_type, entity_type,
                        entity_id, request_id, payload, occurred_at
                    )
                    VALUES (
                        $1, $2, 'privacy_subject_anonymized',
                        'privacy_erasure_case', $3, $4, $5::jsonb, $6
                    )
                    """,
                    uuid4(),
                    actor_user_id,
                    case_id,
                    request_id,
                    json.dumps(
                        {
                            "subjectHash": subject_hash,
                            "anonymizedCommitments": counts[0],
                            "retainedInvoices": len(invoices),
                            "retainedDocuments": len(documents),
                            "crmDeletion": "pending_manual_review",
                        },
                        separators=(",", ":"),
                    ),
                    occurred_at,
                )
                return PrivacyErasureResult(
                    case_id=case_id,
                    subject_hash=subject_hash,
                    status=ErasureStatus.COMPLETED_WITH_RETENTION,
                    retention=retention,
                    anonymized_commitments=counts[0],
                    cleared_activity_notes=counts[1],
                    cleared_reminders=counts[2],
                    revoked_consents=counts[3],
                    retained_invoice_ids=invoices,
                    retained_document_ids=documents,
                    retention_reasons=retention_reasons,
                    open_decisions=open_decisions,
                    completed_at=occurred_at,
                )
