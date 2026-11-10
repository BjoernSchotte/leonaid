"""Postgres persistence of donation receipts (ADR-0016, spec §8.5).

A receipt takes its number from the installation's ``donation_receipt``
series in the transaction that issues it, together with the frozen snapshot
and the pending PDF. It is never changed afterwards, only declared void.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.document_series import allocate_document_number
from leonaid.adapters.postgres.documents import AsyncpgGeneratedDocumentRepository
from leonaid.adapters.postgres.invoice_deliveries import (
    AsyncpgInvoiceDeliveryRepository,
)
from leonaid.application.donation_receipts import (
    DonationReceiptDeliveryDraft,
    receipt_mail,
)
from leonaid.application.donations import DonationReceiptRecord, DonationRecord
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.invoice_deliveries import (
    INVOICE_MAIL_SEND_REQUESTED,
    InvoiceDelivery,
)
from leonaid.domain.calendar import local_day
from leonaid.domain.document_series import DocumentSeriesKind
from leonaid.domain.documents import DOCUMENT_RENDER_REQUESTED, GeneratedDocumentType
from leonaid.domain.donation_receipts import (
    DonationReceipt,
    DonationReceiptDocument,
    DonationReceiptVoid,
    ReceiptVoidEvidence,
    notice_valid_until,
    require_no_valid_receipt,
)
from leonaid.domain.donations import DonationStatus, ReceivingBody

if TYPE_CHECKING:
    from leonaid.adapters.postgres.donations import AsyncpgDonationRepository

ISSUE_RECEIPT_COMMAND = "issue_donation_receipt_v1"
VOID_RECEIPT_COMMAND = "void_donation_receipt_v1"
SEND_RECEIPT_COMMAND = "send_donation_receipt_v1"

NOTICE_NAMES = {
    "freistellungsbescheid": "Freistellungsbescheid",
    "koerperschaftsteuer_anlage": "Körperschaftsteuerbescheid",
    "feststellung_60a": "Feststellungsbescheid nach § 60a AO",
}


def _json_object(value: object) -> dict[str, object]:
    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise RuntimeError("Ein gespeicherter Snapshot der Bestätigung ist ungültig.")
    return {str(key): item for key, item in decoded.items()}


def notice_expired_conflict(body: ReceivingBody) -> Conflict:
    """Names the notice, its last day and where to enter the new one."""

    return Conflict(
        "donation_receipt_notice_expired",
        f"Der {NOTICE_NAMES[body.notice_kind.value]} vom "
        f"{body.notice_date.strftime('%d.%m.%Y')} trägt Zuwendungsbestätigungen "
        f"nur bis zum {notice_valid_until(body).strftime('%d.%m.%Y')} "
        "(§ 63 Abs. 5 AO). Ein System-Admin muss unter „Rechtliches“ im Teil "
        "„Spenden“ den neuen Bescheid eintragen und aktivieren.",
    )


def _receipt(row: asyncpg.Record) -> DonationReceipt:
    void = None
    if row["voided_at"] is not None:
        void = DonationReceiptVoid(
            reason=str(row["void_reason"]),
            evidence=ReceiptVoidEvidence(str(row["void_evidence"])),
            voided_by_user_id=row["voided_by_user_id"],
            voided_at=row["voided_at"],
            voided_by_display_name=(
                str(row["voided_by_display_name"])
                if row["voided_by_display_name"] is not None
                else None
            ),
        )
    return DonationReceipt(
        id=row["id"],
        donation_id=row["donation_id"],
        action_id=row["action_id"],
        number=str(row["number"]),
        document_version=int(row["document_version"]),
        document=DonationReceiptDocument.from_payload(_json_object(row["snapshot"])),
        issued_by_user_id=row["issued_by_user_id"],
        void=void,
        issued_by_display_name=(
            str(row["issued_by_display_name"])
            if row["issued_by_display_name"] is not None
            else None
        ),
    )


async def load_receipts(
    connection: asyncpg.Connection[Any], donation_ids: list[UUID]
) -> dict[UUID, tuple[DonationReceiptRecord, ...]]:
    """The receipts of the given donations, newest first, with their PDF and
    their mail deliveries."""

    rows = await connection.fetch(
        """
        SELECT
            receipt.*,
            issuer.display_name AS issued_by_display_name,
            voider.display_name AS voided_by_display_name
        FROM donation_receipt AS receipt
        LEFT JOIN user_account AS issuer ON issuer.id = receipt.issued_by_user_id
        LEFT JOIN user_account AS voider ON voider.id = receipt.voided_by_user_id
        WHERE receipt.donation_id = ANY($1::uuid[])
        ORDER BY receipt.donation_id, receipt.document_version DESC
        """,
        donation_ids,
    )
    if not rows:
        return {}
    documents = {
        (item["donation_id"], int(item["version"])): (
            AsyncpgGeneratedDocumentRepository._document(item)
        )
        for item in await connection.fetch(
            """
            SELECT * FROM generated_document
            WHERE donation_id = ANY($1::uuid[])
              AND document_type = 'donation_receipt_pdf'
            """,
            donation_ids,
        )
    }
    deliveries: dict[UUID, list[InvoiceDelivery]] = {}
    for item in await connection.fetch(
        """
        SELECT
            delivery.*,
            document.document_type,
            event.status AS outbox_status,
            event.attempts,
            event.last_error_code,
            event.last_error_detail,
            mail.message_id,
            mail.sent_at
        FROM invoice_delivery AS delivery
        JOIN generated_document AS document
          ON document.id = delivery.generated_document_id
        JOIN outbox_event AS event ON event.id = delivery.outbox_event_id
        LEFT JOIN mail_delivery AS mail ON mail.outbox_event_id = event.id
        WHERE delivery.donation_id = ANY($1::uuid[])
          AND document.document_type = 'donation_receipt_pdf'
        ORDER BY delivery.requested_at DESC, delivery.id
        """,
        donation_ids,
    ):
        deliveries.setdefault(item["generated_document_id"], []).append(
            AsyncpgInvoiceDeliveryRepository._delivery(item)
        )
    result: dict[UUID, list[DonationReceiptRecord]] = {}
    for row in rows:
        receipt = _receipt(row)
        document = documents.get((receipt.donation_id, receipt.document_version))
        if document is None:
            raise RuntimeError("Eine Zuwendungsbestätigung besitzt kein Dokument.")
        result.setdefault(receipt.donation_id, []).append(
            DonationReceiptRecord(
                receipt=receipt,
                document=document,
                deliveries=tuple(deliveries.get(document.id, ())),
            )
        )
    return {key: tuple(value) for key, value in result.items()}


async def _audit(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    actor_user_id: UUID,
    event_type: str,
    donation_id: UUID,
    request_id: str,
    payload: dict[str, object],
    occurred_at: datetime,
) -> None:
    await connection.execute(
        """
        INSERT INTO audit_event (
            id, action_id, actor_user_id, event_type,
            entity_type, entity_id, request_id, payload, occurred_at
        )
        VALUES ($1, $2, $3, $4, 'donation', $5, $6, $7::jsonb, $8)
        """,
        uuid4(),
        action_id,
        actor_user_id,
        event_type,
        donation_id,
        request_id,
        json.dumps(payload, separators=(",", ":")),
        occurred_at,
    )


class AsyncpgDonationReceiptRepository:
    def __init__(
        self, pool: asyncpg.Pool[Any], donations: AsyncpgDonationRepository
    ) -> None:
        self._pool = pool
        self._donations = donations

    async def donation_receipt_document(
        self, donation_id: UUID, version: int
    ) -> DonationReceiptDocument | None:
        async with self._pool.acquire() as connection:
            snapshot = await connection.fetchval(
                """
                SELECT snapshot FROM donation_receipt
                WHERE donation_id = $1 AND document_version = $2
                """,
                donation_id,
                version,
            )
        if snapshot is None:
            return None
        return DonationReceiptDocument.from_payload(_json_object(snapshot))

    async def issue(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord:
        # Imported here: the donations adapter loads receipts from this module.
        from leonaid.adapters.postgres.donations import active_receiving_body

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                replayed = await self._donations._begin(
                    connection,
                    command_type=ISSUE_RECEIPT_COMMAND,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return await self._donations._record(
                        connection,
                        action_id=action_id,
                        donation_id=replayed,
                        replayed=True,
                    )
                record = await self._donations._record(
                    connection, action_id=action_id, donation_id=donation_id, lock=True
                )
                donation = record.donation
                if donation.status is not DonationStatus.PAID:
                    raise Conflict(
                        "donation_receipt_requires_payment",
                        "Eine Zuwendungsbestätigung gibt es erst nach dem "
                        "Zahlungseingang.",
                    )
                require_no_valid_receipt(
                    tuple(item.receipt for item in record.receipts)
                )
                configured = await active_receiving_body(connection, lock=True)
                if configured is None:
                    raise Conflict(
                        "donation_receiving_body_missing",
                        "In den rechtlichen Angaben fehlt der Teil „Spenden“ mit "
                        "der empfangenden Körperschaft. Ein System-Admin muss "
                        "ihn zuerst aktivieren.",
                    )
                version_id, body = configured
                # The receipt states the notice in force today, of the body
                # that received the money. Another legal entity cannot
                # confirm a donation that went to the first one's account.
                pledge = await self._donations.donation_pledge_document_in(
                    connection, donation_id
                )
                if pledge is None or not body.same_entity(pledge.body):
                    pledged_to = pledge.body.legal_name if pledge else "unbekannt"
                    raise Conflict(
                        "donation_receipt_body_changed",
                        f"Diese Spende ging an „{pledged_to}“. Die aktive "
                        "Rechtskonfiguration nennt als empfangende Körperschaft "
                        f"„{body.legal_name}“. Eine andere Körperschaft kann die "
                        "Spende nicht bestätigen: Die Zuwendungsbestätigung "
                        "stellt die Körperschaft aus, die das Geld erhalten hat.",
                    )
                # Before a number is taken: a notice that is too old carries
                # no receipt (§ 63 Abs. 5 AO, D-D9).
                if local_day(occurred_at) > notice_valid_until(body):
                    raise notice_expired_conflict(body)
                number = await allocate_document_number(
                    connection,
                    kind=DocumentSeriesKind.DONATION_RECEIPT,
                    prefix=body.receipt_prefix,
                    width=body.number_width,
                    occurred_at=occurred_at,
                )
                receipt_id = uuid4()
                document = DonationReceiptDocument.issue(
                    donation,
                    receipt_id=receipt_id,
                    number=number,
                    body=body,
                    issued_at=occurred_at,
                )
                version = len(record.receipts) + 1
                await connection.execute(
                    """
                    INSERT INTO donation_receipt (
                        id, action_id, donation_id, number, document_version,
                        issued_on, issued_at, issued_by_user_id, snapshot,
                        legal_configuration_version_id, idempotency_key,
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11,
                            $7)
                    """,
                    receipt_id,
                    action_id,
                    donation_id,
                    number,
                    version,
                    document.issued_on,
                    occurred_at,
                    actor_user_id,
                    json.dumps(
                        document.payload(), ensure_ascii=False, separators=(",", ":")
                    ),
                    version_id,
                    idempotency_key,
                )
                document_id = uuid4()
                await connection.execute(
                    """
                    INSERT INTO generated_document (
                        id, action_id, commitment_id, donation_id,
                        twenty_company_id, twenty_person_id, document_type,
                        media_type, version, status, created_at, updated_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 'application/pdf', $8,
                            'pending', $9, $9)
                    """,
                    document_id,
                    action_id,
                    donation.commitment_id,
                    donation_id,
                    donation.donor.twenty_id
                    if donation.donor.party_kind is not None
                    and donation.donor.party_kind.value == "company"
                    else None,
                    donation.donor.twenty_id
                    if donation.donor.party_kind is not None
                    and donation.donor.party_kind.value == "person"
                    else None,
                    GeneratedDocumentType.DONATION_RECEIPT_PDF.value,
                    version,
                    occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO outbox_event (
                        id, aggregate_type, aggregate_id, event_type,
                        idempotency_key, payload, available_at, created_at
                    )
                    VALUES ($1, 'generated_document', $2, $3, $4, $5::jsonb, $6, $6)
                    """,
                    uuid4(),
                    document_id,
                    DOCUMENT_RENDER_REQUESTED,
                    f"document-render:{document_id}:v{version}",
                    json.dumps({"documentId": str(document_id)}, separators=(",", ":")),
                    occurred_at,
                )
                await _audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="donation_receipt_issued",
                    donation_id=donation_id,
                    request_id=request_id,
                    # No donor data: the audit trail outlives an erasure.
                    payload={
                        "number": number,
                        "donationNumber": donation.number,
                        "receiptId": str(receipt_id),
                        "amountMinor": document.amount.amount_minor,
                        "receivedOn": document.received_on.isoformat(),
                        "signing": body.signing.value,
                    },
                    occurred_at=occurred_at,
                )
                await self._donations._complete(
                    connection,
                    idempotency_key=idempotency_key,
                    donation_id=donation_id,
                    occurred_at=occurred_at,
                )
                return await self._donations._record(
                    connection, action_id=action_id, donation_id=donation_id
                )

    async def void(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        receipt_id: UUID,
        reason: str,
        evidence: ReceiptVoidEvidence,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                replayed = await self._donations._begin(
                    connection,
                    command_type=VOID_RECEIPT_COMMAND,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return await self._donations._record(
                        connection,
                        action_id=action_id,
                        donation_id=replayed,
                        replayed=True,
                    )
                record = await self._donations._record(
                    connection, action_id=action_id, donation_id=donation_id, lock=True
                )
                current = next(
                    (
                        item.receipt
                        for item in record.receipts
                        if item.receipt.id == receipt_id
                    ),
                    None,
                )
                if current is None:
                    raise ResourceNotFound(
                        "donation_receipt_not_found",
                        "Die Zuwendungsbestätigung wurde bei dieser Spende nicht "
                        "gefunden.",
                    )
                voided = current.declare_void(
                    reason=reason,
                    evidence=evidence,
                    voided_by_user_id=actor_user_id,
                    voided_at=occurred_at,
                )
                assert voided.void is not None
                await connection.execute(
                    """
                    UPDATE donation_receipt
                    SET voided_at = $2, void_reason = $3, void_evidence = $4,
                        voided_by_user_id = $5
                    WHERE id = $1 AND voided_at IS NULL
                    """,
                    receipt_id,
                    occurred_at,
                    voided.void.reason,
                    voided.void.evidence.value,
                    actor_user_id,
                )
                await _audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="donation_receipt_voided",
                    donation_id=donation_id,
                    request_id=request_id,
                    payload={
                        "number": current.number,
                        "receiptId": str(receipt_id),
                        "evidence": voided.void.evidence.value,
                    },
                    occurred_at=occurred_at,
                )
                await self._donations._complete(
                    connection,
                    idempotency_key=idempotency_key,
                    donation_id=donation_id,
                    occurred_at=occurred_at,
                )
                return await self._donations._record(
                    connection, action_id=action_id, donation_id=donation_id
                )

    async def send(
        self, draft: DonationReceiptDeliveryDraft, *, request_id: str
    ) -> InvoiceDelivery:
        """Queues the mail with the receipt PDF. Only a valid receipt made by
        the machine procedure goes out by mail; one signed by hand is printed."""

        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    draft.idempotency_key,
                )
                inserted = await connection.fetchval(
                    """
                    INSERT INTO command_receipt (
                        idempotency_key, command_type, request_hash
                    )
                    VALUES ($1, $2, $3)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    RETURNING true
                    """,
                    draft.idempotency_key,
                    SEND_RECEIPT_COMMAND,
                    draft.request_hash,
                )
                if not inserted:
                    row = await connection.fetchrow(
                        """
                        SELECT command_type, request_hash, result
                        FROM command_receipt WHERE idempotency_key = $1 FOR UPDATE
                        """,
                        draft.idempotency_key,
                    )
                    if (
                        row is None
                        or str(row["command_type"]) != SEND_RECEIPT_COMMAND
                        or str(row["request_hash"]) != draft.request_hash
                    ):
                        raise Conflict(
                            "idempotency_conflict",
                            "Diese Vorgangs-ID wurde bereits für andere Daten "
                            "verwendet.",
                        )
                    result = _json_object(row["result"] or {})
                    return await AsyncpgInvoiceDeliveryRepository._get(
                        connection, UUID(str(result["deliveryId"]))
                    )
                record = await self._donations._record(
                    connection,
                    action_id=draft.action_id,
                    donation_id=draft.donation_id,
                    lock=True,
                )
                item = next(
                    (
                        candidate
                        for candidate in record.receipts
                        if candidate.receipt.id == draft.receipt_id
                    ),
                    None,
                )
                if item is None:
                    raise ResourceNotFound(
                        "donation_receipt_not_found",
                        "Die Zuwendungsbestätigung wurde bei dieser Spende nicht "
                        "gefunden.",
                    )
                receipt = item.receipt
                if not receipt.valid:
                    raise Conflict(
                        "donation_receipt_void",
                        "Eine für ungültig erklärte Zuwendungsbestätigung wird "
                        "nicht versendet.",
                    )
                if not receipt.document.signed_by_machine:
                    raise Conflict(
                        "donation_receipt_signed_by_hand",
                        "Diese Zuwendungsbestätigung wird von Hand "
                        "unterschrieben. Drucken Sie sie aus und geben Sie das "
                        "unterschriebene Original weiter.",
                    )
                if item.document.status.value != "available":
                    raise Conflict(
                        "donation_receipt_document_not_ready",
                        "Das PDF der Zuwendungsbestätigung ist noch nicht "
                        "versandbereit.",
                    )
                email = (receipt.document.donor.email or "").strip().casefold()
                if not email:
                    raise Conflict(
                        "donation_donor_email_missing",
                        "Für diesen Spender ist keine E-Mail-Adresse gespeichert.",
                    )
                action_name = str(
                    await connection.fetchval(
                        "SELECT name FROM charity_action WHERE id = $1",
                        draft.action_id,
                    )
                )
                subject, text = receipt_mail(
                    number=receipt.number,
                    action_name=action_name,
                    donor_name=receipt.document.donor.name,
                    body_name=receipt.document.body.legal_name,
                    amount_minor=receipt.document.amount.amount_minor,
                    currency=receipt.document.amount.currency,
                    received_on_label=receipt.document.received_on.strftime("%d.%m.%Y"),
                )
                await connection.execute(
                    """
                    INSERT INTO outbox_event (
                        id, aggregate_type, aggregate_id, event_type,
                        idempotency_key, payload, available_at, created_at
                    )
                    VALUES ($1, 'invoice_delivery', $2, $3, $4, $5::jsonb, $6, $6)
                    """,
                    draft.outbox_event_id,
                    draft.id,
                    INVOICE_MAIL_SEND_REQUESTED,
                    f"invoice-delivery:{draft.id}:v1",
                    json.dumps({"deliveryId": str(draft.id)}, separators=(",", ":")),
                    draft.requested_at,
                )
                await connection.execute(
                    """
                    INSERT INTO invoice_delivery (
                        id, action_id, donation_id, generated_document_id,
                        outbox_event_id, idempotency_key,
                        recipient_email_snapshot, subject_snapshot,
                        text_snapshot, requested_by_user_id, requested_at,
                        created_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)
                    """,
                    draft.id,
                    draft.action_id,
                    draft.donation_id,
                    item.document.id,
                    draft.outbox_event_id,
                    draft.idempotency_key,
                    email,
                    subject,
                    text,
                    draft.requested_by_user_id,
                    draft.requested_at,
                )
                await _audit(
                    connection,
                    action_id=draft.action_id,
                    actor_user_id=draft.requested_by_user_id,
                    event_type="donation_receipt_delivery_requested",
                    donation_id=draft.donation_id,
                    request_id=request_id,
                    payload={
                        "deliveryId": str(draft.id),
                        "receiptId": str(receipt.id),
                        "documentId": str(item.document.id),
                    },
                    occurred_at=draft.requested_at,
                )
                await connection.execute(
                    """
                    UPDATE command_receipt
                    SET result = $2::jsonb, completed_at = $3
                    WHERE idempotency_key = $1 AND completed_at IS NULL
                    """,
                    draft.idempotency_key,
                    json.dumps(
                        {
                            "donationId": str(draft.donation_id),
                            "deliveryId": str(draft.id),
                        },
                        separators=(",", ":"),
                    ),
                    draft.requested_at,
                )
                return await AsyncpgInvoiceDeliveryRepository._get(connection, draft.id)
