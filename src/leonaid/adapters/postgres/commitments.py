"""Transactional PostgreSQL repository for server-priced commitments."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.commitments import (
    CommitmentCaptureContext,
    CommitmentDraft,
    CommitmentRecord,
    CommitmentRepository,
)
from leonaid.application.errors import Conflict, PermissionDenied, ResourceNotFound
from leonaid.domain.action_templates import OfferingStatus, OfferingUnit
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentSource,
    CommitmentStatus,
    InvoiceRecipientSnapshot,
    Money,
    Offering,
)

COMMAND_TYPE = "create_commitment_v1"


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} besitzt kein gültiges JSON-Objekt.")
    return {str(key): item for key, item in value.items()}


class AsyncpgCommitmentRepository(CommitmentRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def capture_context(
        self,
        *,
        action_id: UUID,
        evaluated_at: datetime,
    ) -> CommitmentCaptureContext:
        async with self._pool.acquire() as connection:
            action = await connection.fetchrow(
                """
                SELECT
                    name,
                    status,
                    EXISTS (
                        SELECT 1
                        FROM charity_action_capability
                        WHERE action_id = charity_action.id
                          AND capability = 'ordering'
                    ) AS ordering_enabled
                FROM charity_action
                WHERE id = $1
                """,
                action_id,
            )
            if action is None:
                raise ResourceNotFound(
                    "commitment_action_not_found",
                    "Die Charity-Aktion wurde nicht gefunden.",
                )
            if not bool(action["ordering_enabled"]):
                raise Conflict(
                    "commitment_ordering_disabled",
                    "Für diese Charity-Aktion sind Bestellungen nicht aktiviert.",
                )
            if str(action["status"]) not in {"draft", "scheduled", "active"}:
                raise Conflict(
                    "commitment_action_closed",
                    "Für diese Charity-Aktion können keine Bestellungen mehr erfasst werden.",
                )
            rows = await connection.fetch(
                """
                SELECT
                    id, action_id, code, name, status, unit,
                    allowed_quantity_units, pieces_per_unit,
                    unit_price_minor, currency,
                    available_from, available_until
                FROM offering
                WHERE action_id = $1
                ORDER BY name, id
                """,
                action_id,
            )
            offerings = tuple(
                offering
                for row in rows
                if (offering := self._offering_from_row(row)).available_at(evaluated_at)
            )
            return CommitmentCaptureContext(
                action_id=action_id,
                action_name=str(action["name"]),
                offerings=offerings,
            )

    async def list_for_action(
        self,
        *,
        action_id: UUID,
    ) -> tuple[CommitmentRecord, ...]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT
                    commitment.id,
                    commitment.action_id,
                    commitment.source,
                    commitment.status,
                    commitment.customer_snapshot,
                    commitment.invoice_recipient_snapshot,
                    commitment.currency,
                    commitment.total_minor,
                    commitment.idempotency_key,
                    commitment.created_at,
                    creator.display_name AS captured_by_display_name,
                    commitment_line.id AS line_id,
                    commitment_line.offering_id,
                    commitment_line.description_snapshot,
                    commitment_line.quantity,
                    commitment_line.unit_snapshot,
                    commitment_line.pieces_per_unit_snapshot,
                    commitment_line.unit_price_minor,
                    commitment_line.line_total_minor
                FROM commitment
                JOIN commitment_line
                  ON commitment_line.commitment_id = commitment.id
                LEFT JOIN LATERAL (
                    SELECT actor_user_id
                    FROM audit_event
                    WHERE entity_type = 'commitment'
                      AND entity_id = commitment.id
                      AND event_type = 'commitment_created'
                    ORDER BY occurred_at, id
                    LIMIT 1
                ) AS creation_event ON true
                LEFT JOIN user_account AS creator
                  ON creator.id = creation_event.actor_user_id
                WHERE commitment.action_id = $1
                ORDER BY
                    commitment.created_at DESC,
                    commitment.id DESC,
                    commitment_line.id
                """,
                action_id,
            )
        headers: dict[UUID, asyncpg.Record] = {}
        line_rows: dict[UUID, list[asyncpg.Record]] = {}
        for row in rows:
            commitment_id = row["id"]
            headers.setdefault(commitment_id, row)
            line_rows.setdefault(commitment_id, []).append(row)
        return tuple(
            self._record_from_rows(header, tuple(line_rows[commitment_id]))
            for commitment_id, header in headers.items()
        )

    async def create(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        source: CommitmentSource,
        status: CommitmentStatus,
        draft: CommitmentDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Commitment:
        async with self._pool.acquire() as connection:
            for attempt in range(3):
                try:
                    async with connection.transaction(isolation="serializable"):
                        return await self._create_once(
                            connection,
                            action_id=action_id,
                            actor_user_id=actor_user_id,
                            source=source,
                            status=status,
                            draft=draft,
                            idempotency_key=idempotency_key,
                            request_hash=request_hash,
                            request_id=request_id,
                            occurred_at=occurred_at,
                        )
                except asyncpg.SerializationError:
                    if attempt == 2:
                        raise Conflict(
                            "commitment_concurrent_retry",
                            "Die Bestellung wurde gleichzeitig verarbeitet. "
                            "Bitte versuche denselben Vorgang erneut.",
                        ) from None
            raise RuntimeError("Die Commitment-Transaktion wurde nicht ausgeführt.")

    async def _create_once(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID,
        source: CommitmentSource,
        status: CommitmentStatus,
        draft: CommitmentDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> Commitment:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            idempotency_key,
        )
        replayed = await self._existing_command(
            connection,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replayed is not None:
            return await self._get(
                connection,
                replayed,
                replayed=True,
            )

        action = await connection.fetchrow(
            """
            SELECT
                status,
                EXISTS (
                    SELECT 1
                    FROM charity_action_capability
                    WHERE action_id = charity_action.id
                      AND capability = 'ordering'
                ) AS ordering_enabled
            FROM charity_action
            WHERE id = $1
            FOR SHARE
            """,
            action_id,
        )
        if action is None:
            raise ResourceNotFound(
                "commitment_action_not_found",
                "Die Charity-Aktion wurde nicht gefunden.",
            )
        if not bool(action["ordering_enabled"]):
            raise Conflict(
                "commitment_ordering_disabled",
                "Für diese Charity-Aktion sind Bestellungen nicht aktiviert.",
            )
        if str(action["status"]) not in {"draft", "scheduled", "active"}:
            raise Conflict(
                "commitment_action_closed",
                "Für diese Charity-Aktion können keine Bestellungen mehr erfasst werden.",
            )
        if source is CommitmentSource.ACQUISITION:
            await self._require_assignment(
                connection,
                action_id=action_id,
                actor_user_id=actor_user_id,
                buyer=draft.buyer,
            )

        offerings = await self._offerings(
            connection,
            action_id=action_id,
            offering_ids=tuple(line.offering_id for line in draft.lines),
        )
        priced_lines = tuple(
            CommitmentLine.price_from(
                offerings[line.offering_id],
                quantity=line.quantity,
                unit=line.unit,
                evaluated_at=occurred_at,
            )
            for line in draft.lines
        )
        total = Money(0, priced_lines[0].unit_price.currency)
        for line in priced_lines:
            total = total.plus(line.line_total)
        commitment = Commitment(
            id=uuid4(),
            action_id=action_id,
            source=source,
            status=status,
            buyer=draft.buyer,
            invoice_recipient=draft.invoice_recipient,
            lines=priced_lines,
            total=total,
            idempotency_key=idempotency_key,
        )
        await self._insert(
            connection,
            commitment=commitment,
            actor_user_id=actor_user_id,
            request_id=request_id,
            request_hash=request_hash,
            occurred_at=occurred_at,
        )
        return commitment

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
            raise RuntimeError("Der Commitment-Befehlsnachweis ist verschwunden.")
        if (
            str(row["command_type"]) != COMMAND_TYPE
            or str(row["request_hash"]) != request_hash
        ):
            raise Conflict(
                "idempotency_conflict",
                "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
            )
        result = _json_object(row["result"], label="Commitment-Befehlsnachweis")
        commitment_id = result.get("commitmentId")
        if commitment_id is None:
            raise RuntimeError("Der Commitment-Befehlsnachweis ist unvollständig.")
        return UUID(str(commitment_id))

    @staticmethod
    async def _require_assignment(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID,
        buyer: BuyerSnapshot,
    ) -> None:
        assigned = await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM acquisition_assignment
                WHERE action_id = $1
                  AND acquirer_user_id = $2
                  AND twenty_company_id IS NOT DISTINCT FROM $3
                  AND twenty_person_id IS NOT DISTINCT FROM $4
            )
            """,
            action_id,
            actor_user_id,
            buyer.company_id,
            buyer.person_id,
        )
        if not assigned:
            raise PermissionDenied(
                "commitment_party_not_assigned",
                "Der Sponsor ist dir für diese Charity-Aktion nicht zugeordnet.",
            )

    @staticmethod
    async def _offerings(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        offering_ids: tuple[UUID, ...],
    ) -> dict[UUID, Offering]:
        rows = await connection.fetch(
            """
            SELECT
                id, action_id, code, name, status, unit,
                allowed_quantity_units, pieces_per_unit,
                unit_price_minor, currency,
                available_from, available_until
            FROM offering
            WHERE action_id = $1
              AND id = ANY($2::uuid[])
            FOR SHARE
            """,
            action_id,
            list(offering_ids),
        )
        if len(rows) != len(offering_ids):
            raise ResourceNotFound(
                "commitment_offering_not_found",
                "Mindestens ein ausgewähltes Angebot wurde nicht gefunden.",
            )
        return {
            row["id"]: AsyncpgCommitmentRepository._offering_from_row(row)
            for row in rows
        }

    @staticmethod
    def _offering_from_row(row: asyncpg.Record) -> Offering:
        return Offering(
            id=row["id"],
            action_id=row["action_id"],
            code=str(row["code"]),
            name=str(row["name"]),
            status=OfferingStatus(str(row["status"])),
            pricing_unit=OfferingUnit(str(row["unit"])),
            allowed_quantity_units=frozenset(
                OfferingUnit(str(value)) for value in row["allowed_quantity_units"]
            ),
            pieces_per_unit=(
                int(row["pieces_per_unit"])
                if row["pieces_per_unit"] is not None
                else None
            ),
            unit_price=Money(
                int(row["unit_price_minor"]),
                str(row["currency"]),
            ),
            available_from=row["available_from"],
            available_until=row["available_until"],
        )

    @staticmethod
    def _record_from_rows(
        header: asyncpg.Record,
        lines: tuple[asyncpg.Record, ...],
    ) -> CommitmentRecord:
        currency = str(header["currency"])
        recipient_value = header["invoice_recipient_snapshot"]
        commitment = Commitment(
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
                    id=row["line_id"],
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
            idempotency_key=(
                str(header["idempotency_key"])
                if header["idempotency_key"] is not None
                else None
            ),
        )
        return CommitmentRecord(
            commitment=commitment,
            created_at=header["created_at"],
            captured_by_display_name=(
                str(header["captured_by_display_name"])
                if header["captured_by_display_name"] is not None
                else None
            ),
        )

    @staticmethod
    async def _insert(
        connection: asyncpg.Connection[Any],
        *,
        commitment: Commitment,
        actor_user_id: UUID,
        request_id: str,
        request_hash: str,
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO commitment (
                id, action_id, twenty_company_id, twenty_person_id,
                source, status, customer_snapshot,
                invoice_recipient_snapshot, currency, total_minor,
                idempotency_key, created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4,
                $5, $6, $7::jsonb,
                $8::jsonb, $9, $10,
                $11, $12, $12
            )
            """,
            commitment.id,
            commitment.action_id,
            commitment.buyer.company_id,
            commitment.buyer.person_id,
            commitment.source.value,
            commitment.status.value,
            json.dumps(commitment.buyer.payload(), separators=(",", ":")),
            (
                json.dumps(
                    commitment.invoice_recipient.payload(),
                    separators=(",", ":"),
                )
                if commitment.invoice_recipient is not None
                else None
            ),
            commitment.total.currency,
            commitment.total.amount_minor,
            commitment.idempotency_key,
            occurred_at,
        )
        await connection.executemany(
            """
            INSERT INTO commitment_line (
                id, commitment_id, offering_id, description_snapshot,
                quantity, unit_snapshot, pieces_per_unit_snapshot,
                unit_price_minor, line_total_minor
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            [
                (
                    line.id,
                    commitment.id,
                    line.offering_id,
                    line.description_snapshot,
                    line.quantity,
                    line.unit_snapshot.value,
                    line.pieces_per_unit_snapshot,
                    line.unit_price.amount_minor,
                    line.line_total.amount_minor,
                )
                for line in commitment.lines
            ],
        )
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type,
                entity_type, entity_id, request_id, payload, occurred_at
            )
            VALUES (
                $1, $2, $3, 'commitment_created',
                'commitment', $4, $5, $6::jsonb, $7
            )
            """,
            uuid4(),
            commitment.action_id,
            actor_user_id,
            commitment.id,
            request_id,
            json.dumps(
                {
                    "source": commitment.source.value,
                    "status": commitment.status.value,
                    "lineCount": len(commitment.lines),
                    "totalMinor": commitment.total.amount_minor,
                    "currency": commitment.total.currency,
                },
                separators=(",", ":"),
            ),
            occurred_at,
        )
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
            commitment.idempotency_key,
            json.dumps(
                {"commitmentId": str(commitment.id)},
                separators=(",", ":"),
            ),
            occurred_at,
            COMMAND_TYPE,
            request_hash,
        )
        if updated != "UPDATE 1":
            raise RuntimeError(
                "Der Commitment-Befehlsnachweis wurde nicht abgeschlossen."
            )

    @staticmethod
    async def _get(
        connection: asyncpg.Connection[Any],
        commitment_id: UUID,
        *,
        replayed: bool,
    ) -> Commitment:
        row = await connection.fetchrow(
            """
            SELECT
                id, action_id, source, status,
                customer_snapshot, invoice_recipient_snapshot,
                currency, total_minor, idempotency_key
            FROM commitment
            WHERE id = $1
            """,
            commitment_id,
        )
        if row is None:
            raise RuntimeError("Das bereits bestätigte Commitment fehlt.")
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
        currency = str(row["currency"])
        recipient_value = row["invoice_recipient_snapshot"]
        return Commitment(
            id=row["id"],
            action_id=row["action_id"],
            source=CommitmentSource(str(row["source"])),
            status=CommitmentStatus(str(row["status"])),
            buyer=BuyerSnapshot.from_payload(
                _json_object(row["customer_snapshot"], label="Besteller-Snapshot")
            ),
            invoice_recipient=(
                InvoiceRecipientSnapshot.from_payload(
                    _json_object(recipient_value, label="Rechnungsempfänger-Snapshot")
                )
                if recipient_value is not None
                else None
            ),
            lines=tuple(
                CommitmentLine(
                    id=item["id"],
                    offering_id=item["offering_id"],
                    description_snapshot=str(item["description_snapshot"]),
                    quantity=int(item["quantity"]),
                    unit_snapshot=OfferingUnit(str(item["unit_snapshot"])),
                    pieces_per_unit_snapshot=(
                        int(item["pieces_per_unit_snapshot"])
                        if item["pieces_per_unit_snapshot"] is not None
                        else None
                    ),
                    unit_price=Money(int(item["unit_price_minor"]), currency),
                    line_total=Money(int(item["line_total_minor"]), currency),
                )
                for item in line_rows
            ),
            total=Money(int(row["total_minor"]), currency),
            idempotency_key=(
                str(row["idempotency_key"])
                if row["idempotency_key"] is not None
                else None
            ),
            replayed=replayed,
        )
