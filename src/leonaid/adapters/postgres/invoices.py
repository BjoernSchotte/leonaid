"""Transactional PostgreSQL repository for invoice issuing and snapshots."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.invoices import (
    InvoiceContext,
    InvoiceRecord,
    InvoiceRepository,
)
from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
    Money,
)
from leonaid.domain.invoices import (
    Invoice,
    InvoiceIssuerSnapshot,
    InvoiceLineSnapshot,
    InvoiceProfile,
    InvoiceStatus,
    TaxTreatment,
)
from leonaid.domain.documents import INVOICE_DOCUMENT_RENDER_REQUESTED

COMMAND_TYPE = "issue_invoice_v1"


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} besitzt kein gültiges JSON-Objekt.")
    return {str(key): item for key, item in value.items()}


def _json_array(value: object, *, label: str) -> list[dict[str, object]]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError(f"{label} besitzt keine gültige JSON-Liste.")
    return [
        {str(key): nested for key, nested in item.items()}
        for item in value
        if isinstance(item, dict)
    ]


class AsyncpgInvoiceRepository(InvoiceRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def context(
        self,
        *,
        action_id: UUID,
    ) -> InvoiceContext:
        async with self._pool.acquire() as connection:
            action = await self._action_row(connection, action_id)
            profile_row = await connection.fetchrow(
                """
                SELECT *
                FROM invoice_profile
                WHERE action_id = $1
                """,
                action_id,
            )
        return InvoiceContext(
            action_id=action_id,
            action_name=str(action["name"]),
            starts_on=action["starts_on"],
            ends_on=action["ends_on"],
            profile=(
                self._profile_from_row(profile_row) if profile_row is not None else None
            ),
            may_issue=False,
        )

    async def list_for_action(
        self,
        *,
        action_id: UUID,
    ) -> tuple[InvoiceRecord, ...]:
        async with self._pool.acquire() as connection:
            await self._action_row(connection, action_id)
            rows = await connection.fetch(
                """
                SELECT
                    invoice.*,
                    commitment.customer_snapshot
                FROM invoice
                JOIN commitment ON commitment.id = invoice.commitment_id
                WHERE invoice.action_id = $1
                ORDER BY invoice.issued_at DESC, invoice.number DESC
                """,
                action_id,
            )
        return tuple(self._record_from_row(row) for row in rows)

    async def issue(
        self,
        *,
        action_id: UUID,
        commitment_id: UUID,
        service_on: date,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Invoice:
        async with self._pool.acquire() as connection:
            for attempt in range(3):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._issue_once(
                            connection,
                            action_id=action_id,
                            commitment_id=commitment_id,
                            service_on=service_on,
                            actor_user_id=actor_user_id,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except asyncpg.SerializationError:
                    if attempt == 2:
                        raise Conflict(
                            "invoice_concurrent_retry",
                            "Die Rechnung wurde gleichzeitig verarbeitet. "
                            "Bitte versuche denselben Vorgang erneut.",
                        ) from None
        raise RuntimeError("Die Rechnungstransaktion wurde nicht ausgeführt.")

    async def _issue_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        commitment_id: UUID,
        service_on: date,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Invoice:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            idempotency_key,
        )
        replayed_invoice_id = await self._existing_command(
            connection,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replayed_invoice_id is not None:
            return await self._get(
                connection,
                replayed_invoice_id,
                replayed=True,
            )

        commitment_row = await connection.fetchrow(
            """
            SELECT
                commitment.*,
                charity_action.name AS action_name,
                charity_action.status AS action_status,
                charity_action.starts_on,
                charity_action.ends_on,
                EXISTS (
                    SELECT 1
                    FROM charity_action_capability
                    WHERE action_id = charity_action.id
                      AND capability = 'invoicing'
                ) AS invoicing_enabled
            FROM commitment
            JOIN charity_action
              ON charity_action.id = commitment.action_id
            WHERE commitment.id = $1
              AND commitment.action_id = $2
            FOR UPDATE OF commitment
            """,
            commitment_id,
            action_id,
        )
        if commitment_row is None:
            raise ResourceNotFound(
                "invoice_commitment_not_found",
                "Die prüfbereite Bestellung wurde nicht gefunden.",
            )
        if not bool(commitment_row["invoicing_enabled"]):
            raise Conflict(
                "invoice_capability_disabled",
                "Für diese Charity-Aktion sind Rechnungen nicht aktiviert.",
            )
        if str(commitment_row["action_status"]) == "archived":
            raise Conflict(
                "invoice_action_archived",
                "Für eine archivierte Charity-Aktion kann keine Rechnung mehr "
                "freigegeben werden.",
            )
        if not commitment_row["starts_on"] <= service_on <= commitment_row["ends_on"]:
            raise Conflict(
                "invoice_service_date_outside_action",
                "Das Leistungsdatum muss innerhalb des Aktionszeitraums liegen.",
            )

        existing = await connection.fetchrow(
            """
            SELECT invoice.*, commitment.customer_snapshot
            FROM invoice
            JOIN commitment ON commitment.id = invoice.commitment_id
            WHERE invoice.commitment_id = $1
            """,
            commitment_id,
        )
        if existing is not None:
            invoice = self._invoice_from_row(existing, replayed=True)
            await self._complete_command(
                connection,
                invoice_id=invoice.id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                completed_at=occurred_at,
            )
            return invoice

        profile_row = await connection.fetchrow(
            """
            SELECT *
            FROM invoice_profile
            WHERE action_id = $1
            FOR UPDATE
            """,
            action_id,
        )
        if profile_row is None:
            raise Conflict(
                "invoice_profile_missing",
                "Vor der ersten Freigabe müssen Träger, Steuerfall und "
                "Nummernkreis bestätigt werden.",
            )
        profile = self._profile_from_row(profile_row)
        line_rows = await connection.fetch(
            """
            SELECT
                id, offering_id, description_snapshot, quantity,
                unit_snapshot, pieces_per_unit_snapshot,
                unit_price_minor, line_total_minor
            FROM commitment_line
            WHERE commitment_id = $1
            ORDER BY id
            """,
            commitment_id,
        )
        commitment = self._commitment_from_rows(
            commitment_row,
            tuple(line_rows),
        )
        invoice = Invoice.issue(
            id=uuid4(),
            number=profile.next_invoice_number,
            commitment=commitment,
            profile=profile,
            approved_by_user_id=actor_user_id,
            issued_at=occurred_at,
            service_on=service_on,
        )
        await self._insert(
            connection,
            invoice=invoice,
            twenty_company_id=commitment_row["twenty_company_id"],
            twenty_person_id=commitment_row["twenty_person_id"],
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            request_id=request_id,
        )
        sequence_update = await connection.execute(
            """
            UPDATE invoice_profile
            SET next_number = next_number + 1,
                updated_at = $2
            WHERE id = $1
              AND next_number = $3
            """,
            profile.id,
            occurred_at,
            profile.next_number,
        )
        if sequence_update != "UPDATE 1":
            raise RuntimeError("Der Rechnungsnummernkreis wurde parallel verändert.")
        commitment_update = await connection.execute(
            """
            UPDATE commitment
            SET status = 'invoiced',
                updated_at = $2
            WHERE id = $1
              AND status = 'review_ready'
            """,
            commitment_id,
            occurred_at,
        )
        if commitment_update != "UPDATE 1":
            raise RuntimeError("Der Bestellstatus wurde parallel verändert.")
        return invoice

    @staticmethod
    async def _existing_command(
        connection: asyncpg.Connection[Any],
        *,
        idempotency_key: str,
        request_hash: str,
    ) -> UUID | None:
        inserted = await connection.fetchval(
            """
            INSERT INTO command_receipt (
                idempotency_key, command_type, request_hash
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING true
            """,
            idempotency_key,
            COMMAND_TYPE,
            request_hash,
        )
        if inserted:
            return None
        row = await connection.fetchrow(
            """
            SELECT command_type, request_hash, result
            FROM command_receipt
            WHERE idempotency_key = $1
            FOR UPDATE
            """,
            idempotency_key,
        )
        if row is None:
            raise RuntimeError("Der Rechnungs-Befehlsnachweis ist verschwunden.")
        if (
            str(row["command_type"]) != COMMAND_TYPE
            or str(row["request_hash"]) != request_hash
        ):
            raise Conflict(
                "idempotency_conflict",
                "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
            )
        result = _json_object(row["result"], label="Rechnungs-Befehlsnachweis")
        invoice_id = result.get("invoiceId")
        if invoice_id is None:
            raise RuntimeError("Der Rechnungs-Befehlsnachweis ist unvollständig.")
        return UUID(str(invoice_id))

    @staticmethod
    async def _complete_command(
        connection: asyncpg.Connection[Any],
        *,
        invoice_id: UUID,
        idempotency_key: str,
        request_hash: str,
        completed_at: datetime,
    ) -> None:
        updated = await connection.execute(
            """
            UPDATE command_receipt
            SET result = $2::jsonb,
                completed_at = $3
            WHERE idempotency_key = $1
              AND command_type = $4
              AND request_hash = $5
              AND result IS NULL
            """,
            idempotency_key,
            json.dumps({"invoiceId": str(invoice_id)}, separators=(",", ":")),
            completed_at,
            COMMAND_TYPE,
            request_hash,
        )
        if updated != "UPDATE 1":
            raise RuntimeError(
                "Der Rechnungs-Befehlsnachweis wurde nicht abgeschlossen."
            )

    async def _insert(
        self,
        connection: asyncpg.Connection[Any],
        *,
        invoice: Invoice,
        twenty_company_id: UUID | None,
        twenty_person_id: UUID | None,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
    ) -> None:
        tax_rate_basis_points = max(
            line.tax_rate_basis_points for line in invoice.lines
        )
        await connection.execute(
            """
            INSERT INTO invoice (
                id, action_id, commitment_id, number, status, issued_at,
                service_on, due_on, currency, net_minor, tax_minor,
                gross_minor, issuer_snapshot, recipient_snapshot,
                line_snapshot, tax_treatment, tax_rate_basis_points,
                tax_note, payment_reference, approved_by_user_id,
                document_version, idempotency_key, created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11,
                $12, $13::jsonb, $14::jsonb,
                $15::jsonb, $16, $17,
                $18, $19, $20,
                1, $21, $6, $6
            )
            """,
            invoice.id,
            invoice.action_id,
            invoice.commitment_id,
            invoice.number,
            invoice.status.value,
            invoice.issued_at,
            invoice.service_on,
            invoice.due_on,
            invoice.gross.currency,
            invoice.net.amount_minor,
            invoice.tax.amount_minor,
            invoice.gross.amount_minor,
            json.dumps(invoice.issuer.payload(), separators=(",", ":")),
            json.dumps(invoice.recipient.payload(), separators=(",", ":")),
            json.dumps(
                [line.payload() for line in invoice.lines],
                separators=(",", ":"),
            ),
            invoice.tax_treatment.value,
            tax_rate_basis_points,
            invoice.tax_note,
            invoice.payment_reference,
            invoice.approved_by_user_id,
            idempotency_key,
        )
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type,
                entity_type, entity_id, request_id, payload, occurred_at
            )
            VALUES (
                $1, $2, $3, 'invoice_issued',
                'invoice', $4, $5, $6::jsonb, $7
            )
            """,
            uuid4(),
            invoice.action_id,
            invoice.approved_by_user_id,
            invoice.id,
            request_id,
            json.dumps(
                {
                    "commitmentId": str(invoice.commitment_id),
                    "number": invoice.number,
                    "grossMinor": invoice.gross.amount_minor,
                    "currency": invoice.gross.currency,
                    "sequenceNumber": invoice.number,
                    "status": invoice.status.value,
                },
                separators=(",", ":"),
            ),
            invoice.issued_at,
        )
        document_id = uuid4()
        await connection.execute(
            """
            INSERT INTO generated_document (
                id, action_id, commitment_id, invoice_id,
                twenty_company_id, twenty_person_id,
                document_type, media_type, version, status,
                created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $6,
                'invoice_pdf', 'application/pdf', 1, 'pending',
                $7, $7
            )
            """,
            document_id,
            invoice.action_id,
            invoice.commitment_id,
            invoice.id,
            twenty_company_id,
            twenty_person_id,
            invoice.issued_at,
        )
        await connection.execute(
            """
            INSERT INTO outbox_event (
                id, aggregate_type, aggregate_id, event_type,
                idempotency_key, payload, available_at, created_at
            )
            VALUES (
                $1, 'generated_document', $2, $3,
                $4, $5::jsonb, $6, $6
            )
            """,
            uuid4(),
            document_id,
            INVOICE_DOCUMENT_RENDER_REQUESTED,
            f"invoice-document:{document_id}:v1",
            json.dumps({"documentId": str(document_id)}, separators=(",", ":")),
            invoice.issued_at,
        )
        await self._complete_command(
            connection,
            invoice_id=invoice.id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            completed_at=invoice.issued_at,
        )

    @staticmethod
    async def _action_row(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
    ) -> asyncpg.Record:
        row = await connection.fetchrow(
            """
            SELECT
                id, name, status, starts_on, ends_on,
                EXISTS (
                    SELECT 1
                    FROM charity_action_capability
                    WHERE action_id = charity_action.id
                      AND capability = 'invoicing'
                ) AS invoicing_enabled
            FROM charity_action
            WHERE id = $1
            """,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "invoice_action_not_found",
                "Die Charity-Aktion wurde nicht gefunden.",
            )
        if not bool(row["invoicing_enabled"]):
            raise Conflict(
                "invoice_capability_disabled",
                "Für diese Charity-Aktion sind Rechnungen nicht aktiviert.",
            )
        return row

    @staticmethod
    def _profile_from_row(row: asyncpg.Record) -> InvoiceProfile:
        return InvoiceProfile(
            id=row["id"],
            action_id=row["action_id"],
            issuer=InvoiceIssuerSnapshot(
                legal_name=str(row["legal_name"]),
                street_line_1=str(row["street_line_1"]),
                postal_code=str(row["postal_code"]),
                city=str(row["city"]),
                country_code=str(row["country_code"]),
                tax_identifier=str(row["tax_identifier"]),
                email=str(row["email"]),
            ),
            tax_treatment=TaxTreatment(str(row["tax_treatment"])),
            tax_rate_basis_points=int(row["tax_rate_basis_points"]),
            tax_note=str(row["tax_note"]),
            number_prefix=str(row["number_prefix"]),
            next_number=int(row["next_number"]),
            number_width=int(row["number_width"]),
            payment_terms_days=int(row["payment_terms_days"]),
            confirmed_at=row["confirmed_at"],
        )

    @staticmethod
    def _commitment_from_rows(
        header: asyncpg.Record,
        lines: tuple[asyncpg.Record, ...],
    ) -> Commitment:
        currency = str(header["currency"])
        recipient_value = header["invoice_recipient_snapshot"]
        delivery_value = header["delivery_recipient_snapshot"]
        return Commitment(
            id=header["id"],
            action_id=header["action_id"],
            source=CommitmentSource(str(header["source"])),
            status=CommitmentStatus(str(header["status"])),
            buyer=BuyerSnapshot.from_payload(
                _json_object(
                    header["customer_snapshot"],
                    label="Besteller-Snapshot",
                )
            ),
            invoice_recipient=(
                InvoiceRecipientSnapshot.from_payload(
                    _json_object(
                        recipient_value,
                        label="Rechnungsempfänger-Snapshot",
                    )
                )
                if recipient_value is not None
                else None
            ),
            lines=tuple(
                CommitmentLine(
                    id=row["id"],
                    offering_id=row["offering_id"],
                    description_snapshot=str(row["description_snapshot"]),
                    quantity=int(row["quantity"]),
                    unit_snapshot=OfferingUnit(str(row["unit_snapshot"])),
                    pieces_per_unit_snapshot=(
                        int(row["pieces_per_unit_snapshot"])
                        if row["pieces_per_unit_snapshot"] is not None
                        else None
                    ),
                    unit_price=Money(int(row["unit_price_minor"]), currency),
                    line_total=Money(int(row["line_total_minor"]), currency),
                )
                for row in lines
            ),
            total=Money(int(header["total_minor"]), currency),
            delivery_recipient=(
                DeliveryRecipientSnapshot.from_payload(
                    _json_object(
                        delivery_value,
                        label="Lieferempfänger-Snapshot",
                    )
                )
                if delivery_value is not None
                else None
            ),
            message=(
                str(header["message_snapshot"])
                if header["message_snapshot"] is not None
                else None
            ),
            public_reference=(
                str(header["public_reference"])
                if header["public_reference"] is not None
                else None
            ),
            idempotency_key=(
                str(header["idempotency_key"])
                if header["idempotency_key"] is not None
                else None
            ),
        )

    @staticmethod
    def _invoice_from_row(
        row: asyncpg.Record,
        *,
        replayed: bool = False,
    ) -> Invoice:
        currency = str(row["currency"])
        return Invoice(
            id=row["id"],
            action_id=row["action_id"],
            commitment_id=row["commitment_id"],
            number=str(row["number"]),
            status=InvoiceStatus(str(row["status"])),
            issued_at=row["issued_at"],
            service_on=row["service_on"],
            due_on=row["due_on"],
            issuer=InvoiceIssuerSnapshot.from_payload(
                _json_object(
                    row["issuer_snapshot"],
                    label="Rechnungsaussteller-Snapshot",
                )
            ),
            recipient=InvoiceRecipientSnapshot.from_payload(
                _json_object(
                    row["recipient_snapshot"],
                    label="Rechnungsempfänger-Snapshot",
                )
            ),
            lines=tuple(
                InvoiceLineSnapshot.from_payload(item)
                for item in _json_array(
                    row["line_snapshot"],
                    label="Rechnungspositions-Snapshot",
                )
            ),
            tax_treatment=TaxTreatment(str(row["tax_treatment"])),
            tax_note=str(row["tax_note"]),
            net=Money(int(row["net_minor"]), currency),
            tax=Money(int(row["tax_minor"]), currency),
            gross=Money(int(row["gross_minor"]), currency),
            payment_reference=str(row["payment_reference"]),
            approved_by_user_id=row["approved_by_user_id"],
            replayed=replayed,
        )

    @classmethod
    def _record_from_row(cls, row: asyncpg.Record) -> InvoiceRecord:
        buyer = BuyerSnapshot.from_payload(
            _json_object(
                row["customer_snapshot"],
                label="Besteller-Snapshot",
            )
        )
        return InvoiceRecord(
            invoice=cls._invoice_from_row(row),
            buyer_display_name=buyer.display_name,
        )

    @classmethod
    async def _get(
        cls,
        connection: asyncpg.Connection[Any],
        invoice_id: UUID,
        *,
        replayed: bool,
    ) -> Invoice:
        row = await connection.fetchrow(
            """
            SELECT invoice.*, commitment.customer_snapshot
            FROM invoice
            JOIN commitment ON commitment.id = invoice.commitment_id
            WHERE invoice.id = $1
            """,
            invoice_id,
        )
        if row is None:
            raise RuntimeError("Die bereits bestätigte Rechnung fehlt.")
        return cls._invoice_from_row(row, replayed=replayed)
