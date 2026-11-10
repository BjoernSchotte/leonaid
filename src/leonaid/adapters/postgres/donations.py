"""Transactional PostgreSQL repository for donations (ADR-0016).

Every command runs in one transaction and takes its locks in this order:
its idempotency key, the action row (shared), the legal configuration state
(shared), the donation's advisory lock and row, and last the ``donation``
series row a new number comes from (``retry.py``).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import asyncpg

from leonaid.adapters.postgres.document_series import allocate_document_number
from leonaid.adapters.postgres.documents import AsyncpgGeneratedDocumentRepository
from leonaid.adapters.postgres.invoice_deliveries import (
    AsyncpgInvoiceDeliveryRepository,
)
from leonaid.application.donations import (
    DonationDraft,
    DonationList,
    DonationPledgeDeliveryContext,
    DonationPledgeDeliveryDraft,
    DonationRecord,
)
from leonaid.application.errors import Conflict, ResourceNotFound
from leonaid.application.invoice_deliveries import (
    INVOICE_MAIL_SEND_REQUESTED,
    InvoiceDelivery,
)
from leonaid.domain.commitments import Money
from leonaid.domain.document_series import DocumentSeriesKind
from leonaid.domain.documents import (
    DOCUMENT_RENDER_REQUESTED,
    GeneratedDocument,
    GeneratedDocumentType,
)
from leonaid.domain.donations import (
    Donation,
    DonationCancellation,
    DonationPayment,
    DonationPaymentWithdrawal,
    DonationPledgeDocument,
    DonationSource,
    DonationStatus,
    DonorSnapshot,
    ReceivingBody,
)
from leonaid.domain.privacy import PrivacyReference

CREATE_COMMAND = "create_donation_v1"
PAYMENT_COMMAND = "record_donation_payment_v1"
PAYMENT_WITHDRAWAL_COMMAND = "withdraw_donation_payment_v1"
CANCEL_COMMAND = "cancel_donation_v1"
SEND_PLEDGE_COMMAND = "send_donation_pledge_v1"
PLEDGE_DOCUMENT_VERSION = 1

_DONATION_SQL = """
    SELECT
        donation.*,
        creator.display_name AS created_by_display_name,
        payer.display_name AS payment_recorded_by_display_name,
        canceller.display_name AS cancelled_by_display_name
    FROM donation
    LEFT JOIN user_account AS creator ON creator.id = donation.created_by_user_id
    LEFT JOIN user_account AS payer
      ON payer.id = donation.payment_recorded_by_user_id
    LEFT JOIN user_account AS canceller
      ON canceller.id = donation.cancelled_by_user_id
"""


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError("Ein gespeicherter Spenden-Snapshot ist ungültig.")
    return {str(key): item for key, item in value.items()}


def _pledge_document_of(
    documents: dict[UUID, GeneratedDocument], donation_id: UUID
) -> GeneratedDocument:
    """A donation and its pledge document are written in one transaction."""

    document = documents.get(donation_id)
    if document is None:
        raise RuntimeError("Eine Spende besitzt kein Dokument der Spendenzusage.")
    return document


async def active_receiving_body(
    connection: asyncpg.Connection[Any], *, lock: bool = False
) -> tuple[UUID, ReceivingBody] | None:
    """The receiving body of the active legal configuration, if it has one."""

    row = await connection.fetchrow(
        f"""
        SELECT version.id, version.donations
        FROM legal_configuration_state AS state
        JOIN legal_configuration_version AS version
          ON version.id = state.active_version_id
        {"FOR SHARE OF state" if lock else ""}
        """
    )
    if row is None or row["donations"] is None:
        return None
    return row["id"], ReceivingBody.from_payload(_json_object(row["donations"]))


async def insert_donation(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    draft: DonationDraft,
    actor_user_id: UUID | None,
    idempotency_key: str,
    request_id: str,
    occurred_at: datetime,
) -> Donation:
    """Stores a donation with its number and its pledge, in the caller's
    transaction. The caller holds the action row.

    Also used when a donation comes with an order (the order's transaction).
    """

    action = await connection.fetchrow(
        """
        SELECT
            name, purpose, carrier_name, status,
            EXISTS (
                SELECT 1 FROM charity_action_capability
                WHERE action_id = charity_action.id
                  AND capability = 'donations'
            ) AS donations_enabled
        FROM charity_action
        WHERE id = $1
        """,
        action_id,
    )
    if action is None:
        raise ResourceNotFound(
            "donation_action_not_found", "Die Charity-Aktion wurde nicht gefunden."
        )
    if not bool(action["donations_enabled"]):
        raise Conflict(
            "donation_capability_disabled",
            "Für diese Charity-Aktion sind Spenden nicht aktiviert.",
        )
    if str(action["status"]) == "archived":
        raise Conflict(
            "donation_action_archived",
            "Für eine archivierte Charity-Aktion kann keine Spende mehr erfasst "
            "werden.",
        )
    configured = await active_receiving_body(connection, lock=True)
    if configured is None:
        # No donation without a configured receiving body (D-D6): every
        # donation has a number and a pledge from its first moment.
        raise Conflict(
            "donation_receiving_body_missing",
            "In den rechtlichen Angaben fehlt der Teil „Spenden“ mit der "
            "empfangenden Körperschaft. Ein System-Admin muss ihn zuerst "
            "aktivieren.",
        )
    version_id, body = configured
    number = await allocate_document_number(
        connection,
        kind=DocumentSeriesKind.DONATION,
        prefix=body.pledge_prefix,
        width=body.number_width,
        occurred_at=occurred_at,
    )
    donation = Donation.pledge(
        id=uuid4(),
        action_id=action_id,
        number=number,
        donor=draft.donor,
        pledged=draft.pledged,
        source=draft.source,
        pledged_at=occurred_at,
        created_by_user_id=actor_user_id,
        commitment_id=draft.commitment_id,
        note=draft.note,
    )
    pledge = DonationPledgeDocument.issue(
        donation,
        body=body,
        action_name=str(action["name"]),
        action_purpose=str(action["purpose"]),
        carrier_name=str(action["carrier_name"]),
    )
    await connection.execute(
        """
        INSERT INTO donation (
            id, action_id, number, donor_snapshot, pledged_minor, currency,
            source, commitment_id, status, note, pledge_snapshot,
            legal_configuration_version_id, pledged_at, created_by_user_id,
            idempotency_key, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, 'pledged', $9,
                $10::jsonb, $11, $12, $13, $14, $12, $12)
        """,
        donation.id,
        action_id,
        donation.number,
        json.dumps(donation.donor.payload(), ensure_ascii=False, separators=(",", ":")),
        donation.pledged.amount_minor,
        donation.pledged.currency,
        donation.source.value,
        donation.commitment_id,
        donation.note,
        json.dumps(pledge.payload(), ensure_ascii=False, separators=(",", ":")),
        version_id,
        occurred_at,
        actor_user_id,
        idempotency_key,
    )
    document_id = uuid4()
    await connection.execute(
        """
        INSERT INTO generated_document (
            id, action_id, commitment_id, donation_id, twenty_company_id,
            twenty_person_id, document_type, media_type, version, status,
            created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'application/pdf', $8, 'pending',
                $9, $9)
        """,
        document_id,
        action_id,
        donation.commitment_id,
        donation.id,
        donation.donor.twenty_id
        if donation.donor.party_kind is not None
        and donation.donor.party_kind.value == "company"
        else None,
        donation.donor.twenty_id
        if donation.donor.party_kind is not None
        and donation.donor.party_kind.value == "person"
        else None,
        GeneratedDocumentType.DONATION_PLEDGE_PDF.value,
        PLEDGE_DOCUMENT_VERSION,
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
        f"document-render:{document_id}:v{PLEDGE_DOCUMENT_VERSION}",
        json.dumps({"documentId": str(document_id)}, separators=(",", ":")),
        occurred_at,
    )
    await _audit(
        connection,
        action_id=action_id,
        actor_user_id=actor_user_id,
        event_type="donation_pledged",
        donation_id=donation.id,
        request_id=request_id,
        # No donor data: the audit trail outlives an erasure.
        payload={
            "number": donation.number,
            "pledgedMinor": donation.pledged.amount_minor,
            "currency": donation.pledged.currency,
            "source": donation.source.value,
            "commitmentId": (
                str(donation.commitment_id) if donation.commitment_id else None
            ),
        },
        occurred_at=occurred_at,
    )
    return donation


async def _audit(
    connection: asyncpg.Connection[Any],
    *,
    action_id: UUID,
    actor_user_id: UUID | None,
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


class AsyncpgDonationRepository:
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    # --- reads --------------------------------------------------------------

    async def list_for_action(self, *, action_id: UUID) -> DonationList:
        async with self._pool.acquire() as connection:
            action = await connection.fetchrow(
                """
                SELECT
                    name,
                    EXISTS (
                        SELECT 1 FROM charity_action_capability
                        WHERE action_id = charity_action.id
                          AND capability = 'donations'
                    ) AS donations_enabled
                FROM charity_action WHERE id = $1
                """,
                action_id,
            )
            if action is None:
                raise ResourceNotFound(
                    "donation_action_not_found",
                    "Die Charity-Aktion wurde nicht gefunden.",
                )
            if not bool(action["donations_enabled"]):
                raise Conflict(
                    "donation_capability_disabled",
                    "Für diese Charity-Aktion sind Spenden nicht aktiviert.",
                )
            rows = await connection.fetch(
                f"""
                {_DONATION_SQL}
                WHERE donation.action_id = $1
                ORDER BY donation.pledged_at DESC, donation.number DESC
                """,
                action_id,
            )
            records = await self._records(connection, action_id, tuple(rows))
            configured = await active_receiving_body(connection)
        return DonationList(
            action_id=action_id,
            action_name=str(action["name"]),
            records=records,
            receiving_body_name=configured[1].legal_name if configured else None,
            may_manage=False,
            may_send=False,
        )

    async def donation_pledge_document(
        self, donation_id: UUID
    ) -> DonationPledgeDocument | None:
        async with self._pool.acquire() as connection:
            snapshot = await connection.fetchval(
                "SELECT pledge_snapshot FROM donation WHERE id = $1", donation_id
            )
        if snapshot is None:
            return None
        return DonationPledgeDocument.from_payload(_json_object(snapshot))

    async def _records(
        self,
        connection: asyncpg.Connection[Any],
        action_id: UUID,
        rows: tuple[asyncpg.Record, ...],
    ) -> tuple[DonationRecord, ...]:
        ids = [row["id"] for row in rows]
        withdrawals: dict[UUID, list[DonationPaymentWithdrawal]] = {}
        for item in await connection.fetch(
            """
            SELECT
                withdrawal.*,
                payer.display_name AS payment_recorded_by_display_name,
                withdrawer.display_name AS withdrawn_by_display_name
            FROM donation_payment_withdrawal AS withdrawal
            JOIN user_account AS payer
              ON payer.id = withdrawal.payment_recorded_by_user_id
            JOIN user_account AS withdrawer
              ON withdrawer.id = withdrawal.withdrawn_by_user_id
            WHERE withdrawal.donation_id = ANY($1::uuid[])
            ORDER BY withdrawal.withdrawn_at, withdrawal.id
            """,
            ids,
        ):
            withdrawals.setdefault(item["donation_id"], []).append(
                DonationPaymentWithdrawal(
                    id=item["id"],
                    amount=Money(int(item["received_minor"]), "EUR"),
                    received_on=item["received_on"],
                    note=(
                        str(item["payment_note"])
                        if item["payment_note"] is not None
                        else None
                    ),
                    recorded_by_user_id=item["payment_recorded_by_user_id"],
                    recorded_at=item["payment_recorded_at"],
                    reason=str(item["reason_snapshot"]),
                    withdrawn_by_user_id=item["withdrawn_by_user_id"],
                    withdrawn_at=item["withdrawn_at"],
                    recorded_by_display_name=str(
                        item["payment_recorded_by_display_name"]
                    ),
                    withdrawn_by_display_name=str(item["withdrawn_by_display_name"]),
                )
            )
        documents = {
            item["donation_id"]: AsyncpgGeneratedDocumentRepository._document(item)
            for item in await connection.fetch(
                """
                SELECT DISTINCT ON (donation_id) *
                FROM generated_document
                WHERE donation_id = ANY($1::uuid[])
                  AND document_type = 'donation_pledge_pdf'
                ORDER BY donation_id, version DESC
                """,
                ids,
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
              AND document.document_type = 'donation_pledge_pdf'
            ORDER BY delivery.requested_at DESC, delivery.id
            """,
            ids,
        ):
            deliveries.setdefault(item["donation_id"], []).append(
                AsyncpgInvoiceDeliveryRepository._delivery(item)
            )
        return tuple(
            DonationRecord(
                donation=self._donation(row, tuple(withdrawals.get(row["id"], ()))),
                pledge_document=_pledge_document_of(documents, row["id"]),
                pledge_deliveries=tuple(deliveries.get(row["id"], ())),
            )
            for row in rows
        )

    @staticmethod
    def _donation(
        row: asyncpg.Record,
        withdrawals: tuple[DonationPaymentWithdrawal, ...] = (),
        *,
        replayed: bool = False,
    ) -> Donation:
        payment = (
            DonationPayment(
                amount=Money(int(row["received_minor"]), str(row["currency"])),
                received_on=row["received_on"],
                note=(
                    str(row["payment_note"])
                    if row["payment_note"] is not None
                    else None
                ),
                recorded_by_user_id=row["payment_recorded_by_user_id"],
                recorded_at=row["payment_recorded_at"],
                recorded_by_display_name=(
                    str(row["payment_recorded_by_display_name"])
                    if row["payment_recorded_by_display_name"] is not None
                    else None
                ),
            )
            if row["received_minor"] is not None
            else None
        )
        cancellation = (
            DonationCancellation(
                reason=str(row["cancel_reason"]),
                cancelled_by_user_id=row["cancelled_by_user_id"],
                cancelled_at=row["cancelled_at"],
                cancelled_by_display_name=(
                    str(row["cancelled_by_display_name"])
                    if row["cancelled_by_display_name"] is not None
                    else None
                ),
            )
            if row["cancelled_at"] is not None
            else None
        )
        return Donation(
            id=row["id"],
            action_id=row["action_id"],
            number=str(row["number"]),
            donor=DonorSnapshot.from_payload(_json_object(row["donor_snapshot"])),
            pledged=Money(int(row["pledged_minor"]), str(row["currency"])),
            source=DonationSource(str(row["source"])),
            status=DonationStatus(str(row["status"])),
            pledged_at=row["pledged_at"],
            created_by_user_id=row["created_by_user_id"],
            commitment_id=row["commitment_id"],
            note=str(row["note"]) if row["note"] is not None else None,
            payment=payment,
            cancellation=cancellation,
            payment_withdrawals=withdrawals,
            created_by_display_name=(
                str(row["created_by_display_name"])
                if row["created_by_display_name"] is not None
                else None
            ),
            replayed=replayed,
        )

    async def _record(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        donation_id: UUID,
        lock: bool = False,
        replayed: bool = False,
    ) -> DonationRecord:
        if lock:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"donation:{donation_id}",
            )
            await connection.execute(
                "SELECT id FROM donation WHERE id = $1 AND action_id = $2 FOR UPDATE",
                donation_id,
                action_id,
            )
        row = await connection.fetchrow(
            f"{_DONATION_SQL} WHERE donation.id = $1 AND donation.action_id = $2",
            donation_id,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "donation_not_found",
                "Die Spende wurde in dieser Charity-Aktion nicht gefunden.",
            )
        record = (await self._records(connection, action_id, (row,)))[0]
        if not replayed:
            return record
        return DonationRecord(
            donation=self._donation(
                row, record.donation.payment_withdrawals, replayed=True
            ),
            pledge_document=record.pledge_document,
            pledge_deliveries=record.pledge_deliveries,
        )

    # --- commands -----------------------------------------------------------

    @staticmethod
    async def _begin(
        connection: asyncpg.Connection[Any],
        *,
        command_type: str,
        idempotency_key: str,
        request_hash: str,
    ) -> UUID | None:
        """Takes the key's lock; returns the donation of a replayed command."""

        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", idempotency_key
        )
        inserted = await connection.fetchval(
            """
            INSERT INTO command_receipt (idempotency_key, command_type, request_hash)
            VALUES ($1, $2, $3)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING true
            """,
            idempotency_key,
            command_type,
            request_hash,
        )
        if inserted:
            return None
        row = await connection.fetchrow(
            """
            SELECT command_type, request_hash, result
            FROM command_receipt WHERE idempotency_key = $1 FOR UPDATE
            """,
            idempotency_key,
        )
        if (
            row is None
            or str(row["command_type"]) != command_type
            or str(row["request_hash"]) != request_hash
        ):
            raise Conflict(
                "idempotency_conflict",
                "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
            )
        result = _json_object(row["result"] or {})
        if "donationId" not in result:
            raise RuntimeError("Der Spenden-Befehlsnachweis ist unvollständig.")
        return UUID(str(result["donationId"]))

    @staticmethod
    async def _complete(
        connection: asyncpg.Connection[Any],
        *,
        idempotency_key: str,
        donation_id: UUID,
        extra: dict[str, str] | None = None,
        occurred_at: datetime,
    ) -> None:
        updated = await connection.execute(
            """
            UPDATE command_receipt
            SET result = $2::jsonb, completed_at = $3
            WHERE idempotency_key = $1 AND completed_at IS NULL
            """,
            idempotency_key,
            json.dumps(
                {"donationId": str(donation_id), **(extra or {})},
                separators=(",", ":"),
            ),
            occurred_at,
        )
        if updated != "UPDATE 1":
            raise RuntimeError("Der Spenden-Befehlsnachweis blieb unvollständig.")

    async def create(
        self,
        *,
        action_id: UUID,
        draft: DonationDraft,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                replayed = await self._begin(
                    connection,
                    command_type=CREATE_COMMAND,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return await self._record(
                        connection,
                        action_id=action_id,
                        donation_id=replayed,
                        replayed=True,
                    )
                await connection.execute(
                    "SELECT id FROM charity_action WHERE id = $1 FOR SHARE", action_id
                )
                donation = await insert_donation(
                    connection,
                    action_id=action_id,
                    draft=draft,
                    actor_user_id=actor_user_id,
                    idempotency_key=idempotency_key,
                    request_id=request_id,
                    occurred_at=occurred_at,
                )
                await self._complete(
                    connection,
                    idempotency_key=idempotency_key,
                    donation_id=donation.id,
                    occurred_at=occurred_at,
                )
                return await self._record(
                    connection, action_id=action_id, donation_id=donation.id
                )

    async def record_payment(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        amount: Money,
        received_on: date,
        note: str | None,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                replayed = await self._begin(
                    connection,
                    command_type=PAYMENT_COMMAND,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return await self._record(
                        connection,
                        action_id=action_id,
                        donation_id=replayed,
                        replayed=True,
                    )
                record = await self._record(
                    connection, action_id=action_id, donation_id=donation_id, lock=True
                )
                paid = record.donation.record_payment(
                    amount=amount,
                    received_on=received_on,
                    note=note,
                    recorded_by_user_id=actor_user_id,
                    recorded_at=occurred_at,
                )
                assert paid.payment is not None
                await connection.execute(
                    """
                    UPDATE donation
                    SET status = 'paid', received_minor = $2, received_on = $3,
                        payment_note = $4, payment_recorded_by_user_id = $5,
                        payment_recorded_at = $6, updated_at = $6
                    WHERE id = $1 AND status = 'pledged'
                    """,
                    donation_id,
                    paid.payment.amount.amount_minor,
                    paid.payment.received_on,
                    paid.payment.note,
                    actor_user_id,
                    occurred_at,
                )
                await _audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="donation_payment_recorded",
                    donation_id=donation_id,
                    request_id=request_id,
                    payload={
                        "number": paid.number,
                        "pledgedMinor": paid.pledged.amount_minor,
                        "receivedMinor": paid.payment.amount.amount_minor,
                        "receivedOn": paid.payment.received_on.isoformat(),
                        "hasNote": paid.payment.note is not None,
                    },
                    occurred_at=occurred_at,
                )
                await self._complete(
                    connection,
                    idempotency_key=idempotency_key,
                    donation_id=donation_id,
                    occurred_at=occurred_at,
                )
                return await self._record(
                    connection, action_id=action_id, donation_id=donation_id
                )

    async def withdraw_payment(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        reason: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                replayed = await self._begin(
                    connection,
                    command_type=PAYMENT_WITHDRAWAL_COMMAND,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return await self._record(
                        connection,
                        action_id=action_id,
                        donation_id=replayed,
                        replayed=True,
                    )
                record = await self._record(
                    connection, action_id=action_id, donation_id=donation_id, lock=True
                )
                _reopened, withdrawal = record.donation.withdraw_payment(
                    id=uuid4(),
                    reason=reason,
                    withdrawn_by_user_id=actor_user_id,
                    withdrawn_at=occurred_at,
                )
                await connection.execute(
                    """
                    INSERT INTO donation_payment_withdrawal (
                        id, action_id, donation_id, received_minor, received_on,
                        payment_note, payment_recorded_by_user_id,
                        payment_recorded_at, reason_snapshot,
                        withdrawn_by_user_id, withdrawn_at
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    """,
                    withdrawal.id,
                    action_id,
                    donation_id,
                    withdrawal.amount.amount_minor,
                    withdrawal.received_on,
                    withdrawal.note,
                    withdrawal.recorded_by_user_id,
                    withdrawal.recorded_at,
                    withdrawal.reason,
                    actor_user_id,
                    occurred_at,
                )
                await connection.execute(
                    """
                    UPDATE donation
                    SET status = 'pledged', received_minor = NULL,
                        received_on = NULL, payment_note = NULL,
                        payment_recorded_by_user_id = NULL,
                        payment_recorded_at = NULL, updated_at = $2
                    WHERE id = $1 AND status = 'paid'
                    """,
                    donation_id,
                    occurred_at,
                )
                await _audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="donation_payment_withdrawn",
                    donation_id=donation_id,
                    request_id=request_id,
                    payload={
                        "number": record.donation.number,
                        "receivedMinor": withdrawal.amount.amount_minor,
                        "receivedOn": withdrawal.received_on.isoformat(),
                        "recordedByUserId": str(withdrawal.recorded_by_user_id),
                        "reason": withdrawal.reason,
                    },
                    occurred_at=occurred_at,
                )
                await self._complete(
                    connection,
                    idempotency_key=idempotency_key,
                    donation_id=donation_id,
                    occurred_at=occurred_at,
                )
                return await self._record(
                    connection, action_id=action_id, donation_id=donation_id
                )

    async def cancel(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        reason: str,
        actor_user_id: UUID,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> DonationRecord:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                replayed = await self._begin(
                    connection,
                    command_type=CANCEL_COMMAND,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
                if replayed is not None:
                    return await self._record(
                        connection,
                        action_id=action_id,
                        donation_id=replayed,
                        replayed=True,
                    )
                record = await self._record(
                    connection, action_id=action_id, donation_id=donation_id, lock=True
                )
                cancelled = record.donation.cancel(
                    reason=reason,
                    cancelled_by_user_id=actor_user_id,
                    cancelled_at=occurred_at,
                )
                assert cancelled.cancellation is not None
                await connection.execute(
                    """
                    UPDATE donation
                    SET status = 'cancelled', cancel_reason = $2,
                        cancelled_by_user_id = $3, cancelled_at = $4,
                        updated_at = $4
                    WHERE id = $1 AND status = 'pledged'
                    """,
                    donation_id,
                    cancelled.cancellation.reason,
                    actor_user_id,
                    occurred_at,
                )
                await _audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="donation_cancelled",
                    donation_id=donation_id,
                    request_id=request_id,
                    payload={
                        "number": cancelled.number,
                        "pledgedMinor": cancelled.pledged.amount_minor,
                        "reason": cancelled.cancellation.reason,
                    },
                    occurred_at=occurred_at,
                )
                await self._complete(
                    connection,
                    idempotency_key=idempotency_key,
                    donation_id=donation_id,
                    occurred_at=occurred_at,
                )
                return await self._record(
                    connection, action_id=action_id, donation_id=donation_id
                )

    # --- pledge delivery ------------------------------------------------------

    async def pledge_delivery_context(
        self, *, action_id: UUID, donation_id: UUID
    ) -> DonationPledgeDeliveryContext:
        async with self._pool.acquire() as connection:
            return await self.read_pledge_delivery_context(
                connection, action_id=action_id, donation_id=donation_id
            )

    @staticmethod
    async def read_pledge_delivery_context(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        donation_id: UUID,
        document_may_be_pending: bool = False,
    ) -> DonationPledgeDeliveryContext:
        row = await connection.fetchrow(
            """
            SELECT
                donation.number, donation.status, donation.pledged_minor,
                donation.currency,
                donation.donor_snapshot ->> 'name' AS donor_name,
                donation.donor_snapshot ->> 'email' AS donor_email,
                donation.pledge_snapshot -> 'body' ->> 'legalName' AS body_name,
                action.name AS action_name,
                document.id AS document_id
            FROM donation
            JOIN charity_action AS action ON action.id = donation.action_id
            LEFT JOIN LATERAL (
                SELECT id FROM generated_document
                WHERE generated_document.donation_id = donation.id
                  AND generated_document.document_type = 'donation_pledge_pdf'
                  AND generated_document.status = ANY($3::text[])
                ORDER BY generated_document.version DESC
                LIMIT 1
            ) AS document ON true
            WHERE donation.id = $1 AND donation.action_id = $2
            """,
            donation_id,
            action_id,
            ["available", "pending"] if document_may_be_pending else ["available"],
        )
        if row is None:
            raise ResourceNotFound(
                "donation_not_found",
                "Die Spende wurde in dieser Charity-Aktion nicht gefunden.",
            )
        if str(row["status"]) == "cancelled":
            raise Conflict(
                "donation_cancelled",
                "Die Zusage einer stornierten Spende wird nicht versendet.",
            )
        if row["document_id"] is None:
            raise Conflict(
                "donation_pledge_document_not_ready",
                "Das PDF der Spendenzusage ist noch nicht versandbereit.",
            )
        email = str(row["donor_email"] or "").strip().casefold()
        if not email:
            raise Conflict(
                "donation_donor_email_missing",
                "Für diesen Spender ist keine E-Mail-Adresse gespeichert.",
            )
        return DonationPledgeDeliveryContext(
            action_id=action_id,
            action_name=str(row["action_name"]),
            donation_id=donation_id,
            number=str(row["number"]),
            document_id=row["document_id"],
            donor_name=str(row["donor_name"]),
            donor_email=email,
            body_name=str(row["body_name"]),
            amount_minor=int(row["pledged_minor"]),
            currency=str(row["currency"]),
        )

    async def send_pledge(
        self, draft: DonationPledgeDeliveryDraft, *, request_id: str
    ) -> InvoiceDelivery:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                return await self.send_pledge_in(
                    connection, draft, request_id=request_id
                )

    async def send_pledge_in(
        self,
        connection: asyncpg.Connection[Any],
        draft: DonationPledgeDeliveryDraft,
        *,
        request_id: str,
    ) -> InvoiceDelivery:
        """Queues the pledge mail inside the caller's transaction. The mail
        job waits for a PDF that is still being rendered."""

        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            draft.idempotency_key,
        )
        inserted = await connection.fetchval(
            """
            INSERT INTO command_receipt (idempotency_key, command_type, request_hash)
            VALUES ($1, $2, $3)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING true
            """,
            draft.idempotency_key,
            SEND_PLEDGE_COMMAND,
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
                or str(row["command_type"]) != SEND_PLEDGE_COMMAND
                or str(row["request_hash"]) != draft.request_hash
            ):
                raise Conflict(
                    "idempotency_conflict",
                    "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
                )
            result = _json_object(row["result"] or {})
            return await AsyncpgInvoiceDeliveryRepository._get(
                connection, UUID(str(result["deliveryId"]))
            )
        current = await connection.fetchrow(
            """
            SELECT donation.status,
                   donation.donor_snapshot ->> 'email' AS donor_email
            FROM donation
            JOIN generated_document AS document
              ON document.id = $3
             AND document.donation_id = donation.id
             AND document.document_type = 'donation_pledge_pdf'
             AND document.status IN ('available', 'pending')
            WHERE donation.id = $1 AND donation.action_id = $2
            FOR UPDATE OF donation, document
            """,
            draft.donation_id,
            draft.action_id,
            draft.document_id,
        )
        if current is None:
            raise ResourceNotFound(
                "donation_delivery_context_changed",
                "Spende und Dokument gehören nicht mehr zusammen.",
            )
        if str(current["status"]) == "cancelled":
            raise Conflict(
                "donation_cancelled",
                "Die Zusage einer stornierten Spende wird nicht versendet.",
            )
        if str(current["donor_email"] or "").casefold() != draft.recipient_email:
            raise Conflict(
                "donation_delivery_recipient_changed",
                "Der Empfänger stimmt nicht mehr mit dem Versandauftrag überein.",
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
                outbox_event_id, idempotency_key, recipient_email_snapshot,
                subject_snapshot, text_snapshot, requested_by_user_id,
                requested_at, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $11)
            """,
            draft.id,
            draft.action_id,
            draft.donation_id,
            draft.document_id,
            draft.outbox_event_id,
            draft.idempotency_key,
            draft.recipient_email,
            draft.subject,
            draft.text,
            draft.requested_by_user_id,
            draft.requested_at,
        )
        await _audit(
            connection,
            action_id=draft.action_id,
            actor_user_id=draft.requested_by_user_id,
            event_type="donation_pledge_delivery_requested",
            donation_id=draft.donation_id,
            request_id=request_id,
            payload={
                "deliveryId": str(draft.id),
                "documentId": str(draft.document_id),
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
                {"donationId": str(draft.donation_id), "deliveryId": str(draft.id)},
                separators=(",", ":"),
            ),
            draft.requested_at,
        )
        return await AsyncpgInvoiceDeliveryRepository._get(connection, draft.id)

    async def retry_pledge_delivery(
        self,
        *,
        action_id: UUID,
        donation_id: UUID,
        delivery_id: UUID,
        actor_user_id: UUID,
        request_id: str,
        occurred_at: datetime,
    ) -> InvoiceDelivery:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT delivery.outbox_event_id, event.status, mail.sent_at
                    FROM invoice_delivery AS delivery
                    JOIN outbox_event AS event
                      ON event.id = delivery.outbox_event_id
                    LEFT JOIN mail_delivery AS mail
                      ON mail.outbox_event_id = event.id
                    WHERE delivery.id = $1
                      AND delivery.action_id = $2
                      AND delivery.donation_id = $3
                    FOR UPDATE OF delivery, event
                    """,
                    delivery_id,
                    action_id,
                    donation_id,
                )
                if row is None:
                    raise ResourceNotFound(
                        "donation_delivery_not_found",
                        "Der Versand wurde nicht gefunden.",
                    )
                if row["sent_at"] is not None:
                    raise Conflict(
                        "invoice_delivery_already_sent",
                        "Dieser Versand wurde bereits bestätigt und wird nicht "
                        "noch einmal zugestellt.",
                    )
                if str(row["status"]) != "dead_letter":
                    raise Conflict(
                        "invoice_delivery_not_retryable",
                        "Nur ein endgültig fehlgeschlagener Versand kann "
                        "manuell neu gestartet werden.",
                    )
                await connection.execute(
                    """
                    UPDATE outbox_event
                    SET status = 'pending', available_at = $2,
                        dead_lettered_at = NULL, claim_token = NULL,
                        claimed_by = NULL, completed_at = NULL,
                        manual_retry_count = manual_retry_count + 1,
                        last_manual_retry_at = $2, last_manual_retry_by = $3
                    WHERE id = $1 AND status = 'dead_letter'
                    """,
                    row["outbox_event_id"],
                    occurred_at,
                    str(actor_user_id),
                )
                await _audit(
                    connection,
                    action_id=action_id,
                    actor_user_id=actor_user_id,
                    event_type="donation_pledge_delivery_retried",
                    donation_id=donation_id,
                    request_id=request_id,
                    payload={"deliveryId": str(delivery_id)},
                    occurred_at=occurred_at,
                )
                return await AsyncpgInvoiceDeliveryRepository._get(
                    connection, delivery_id
                )


class DonationPrivacyContributor:
    """Donations in the privacy subject report.

    A donation, its pledge and later its receipt are tax records of the
    receiving body: like issued invoices they stay unchanged for the approved
    retention period. The erasure therefore changes nothing here; the report
    names the donations so the person handling the request sees what is kept
    and why.
    """

    async def references(
        self, connection: object, normalized_email: str
    ) -> tuple[PrivacyReference, ...]:
        rows = await cast("asyncpg.Connection[Any]", connection).fetch(
            """
            SELECT id, action_id, status, number
            FROM donation
            WHERE lower(donor_snapshot ->> 'email') = $1
            ORDER BY pledged_at, id
            """,
            normalized_email,
        )
        return tuple(
            PrivacyReference(
                id=row["id"],
                reference_type="donation",
                action_id=row["action_id"],
                status=str(row["status"]),
                label=f"Spendenzusage {row['number']}",
            )
            for row in rows
        )

    async def anonymize(
        self, connection: object, normalized_email: str, occurred_at: datetime
    ) -> int:
        return 0
