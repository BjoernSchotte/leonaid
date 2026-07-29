"""Transactional PostgreSQL boundary for public Krapfentaxi orders."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import asyncpg

from leonaid.application.errors import Conflict, RateLimited, ResourceNotFound
from leonaid.application.public_orders import (
    PublicOrderCommand,
    PublicOrderContext,
    PublicOrderCrmOutcome,
    PublicOrderDraft,
    PublicOrderRepository,
    PublicOrderResult,
    ResolvedPublicParty,
)
from leonaid.domain.action_templates import (
    OfferingStatus,
    OfferingUnit,
    OrderFormConfiguration,
)
from leonaid.domain.commitments import (
    BuyerSnapshot,
    Commitment,
    CommitmentLine,
    CommitmentSource,
    CommitmentStatus,
    DeliveryRecipientSnapshot,
    InvoiceRecipientSnapshot,
    Money,
    Offering,
)

COMMAND_TYPE = "create_public_order_v1"
RATE_LIMIT = 5
RATE_WINDOW = timedelta(minutes=10)


def _json_object(value: object, *, label: str) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} besitzt kein gültiges JSON-Objekt.")
    return {str(key): item for key, item in value.items()}


class AsyncpgPublicOrderCommand:
    def __init__(
        self,
        repository: AsyncpgPublicOrderRepository,
        connection: asyncpg.Connection[Any],
        existing_result: PublicOrderResult | None,
        idempotency_key: str,
        request_hash: str,
    ) -> None:
        self._repository = repository
        self._connection = connection
        self._existing_result = existing_result
        self._idempotency_key = idempotency_key
        self._request_hash = request_hash

    @property
    def existing_result(self) -> PublicOrderResult | None:
        return self._existing_result

    async def context(
        self,
        *,
        action_id: UUID,
        public_alias: str,
        evaluated_at: datetime,
    ) -> PublicOrderContext:
        return await self._repository._context(
            self._connection,
            action_id=action_id,
            public_alias=public_alias,
            evaluated_at=evaluated_at,
        )

    async def record_order(
        self,
        *,
        action_id: UUID,
        public_alias: str,
        party: ResolvedPublicParty,
        draft: PublicOrderDraft,
        idempotency_key: str,
        request_hash: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PublicOrderResult:
        if (
            idempotency_key != self._idempotency_key
            or request_hash != self._request_hash
        ):
            raise RuntimeError("Public-Order-Befehlsdaten wurden vertauscht.")
        return await self._repository._record_order(
            self._connection,
            action_id=action_id,
            public_alias=public_alias,
            party=party,
            draft=draft,
            idempotency_key=idempotency_key,
            request_id=request_id,
            occurred_at=occurred_at,
        )

    async def complete(self, result: PublicOrderResult) -> None:
        receipt = {
            "activityRecipientIds": [
                str(item) for item in result.activity_recipient_ids
            ],
            "commitmentId": str(result.commitment.id),
            "contactTwentyId": (
                str(result.contact_twenty_id)
                if result.contact_twenty_id is not None
                else None
            ),
            "crmOutcome": result.crm_outcome.value,
        }
        status = await self._connection.execute(
            """
            UPDATE command_receipt
            SET result = $2::jsonb,
                completed_at = CURRENT_TIMESTAMP
            WHERE idempotency_key = $1
              AND command_type = $3
              AND request_hash = $4
              AND result IS NULL
            """,
            self._idempotency_key,
            json.dumps(receipt, separators=(",", ":")),
            COMMAND_TYPE,
            self._request_hash,
        )
        if status != "UPDATE 1":
            raise RuntimeError(
                "Public-Order-Befehlsnachweis konnte nicht abgeschlossen werden."
            )


class AsyncpgPublicOrderRepository(PublicOrderRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def order_command(
        self,
        *,
        lock_key: str,
        idempotency_key: str,
        request_hash: str,
    ) -> AsyncIterator[PublicOrderCommand]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    lock_key,
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
                    idempotency_key,
                    COMMAND_TYPE,
                    request_hash,
                )
                existing: PublicOrderResult | None = None
                if not inserted:
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
                        raise RuntimeError(
                            "Public-Order-Befehlsnachweis ist verschwunden."
                        )
                    if (
                        str(row["command_type"]) != COMMAND_TYPE
                        or str(row["request_hash"]) != request_hash
                    ):
                        raise Conflict(
                            "idempotency_conflict",
                            "Diese Vorgangs-ID wurde bereits für andere Daten verwendet.",
                        )
                    if row["result"] is None:
                        raise Conflict(
                            "idempotency_incomplete",
                            "Die Bestellung wird bereits verarbeitet. "
                            "Bitte versuche es gleich erneut.",
                        )
                    existing = await self._replayed_result(connection, row["result"])
                yield AsyncpgPublicOrderCommand(
                    self,
                    connection,
                    existing,
                    idempotency_key,
                    request_hash,
                )

    async def admit_submission(
        self,
        *,
        action_id: UUID,
        idempotency_key: str,
        fingerprint_hash: str,
        attempted_at: datetime,
    ) -> None:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"public.rate:{action_id}:{fingerprint_hash}",
                )
                count = await connection.fetchval(
                    """
                    SELECT count(*)
                    FROM public_submission_attempt
                    WHERE action_id = $1
                      AND fingerprint_hash = $2
                      AND attempted_at >= $3
                    """,
                    action_id,
                    fingerprint_hash,
                    attempted_at - RATE_WINDOW,
                )
                if int(count) >= RATE_LIMIT:
                    raise RateLimited(
                        "public_order_rate_limited",
                        "Zu viele Bestellversuche. Bitte warte zehn Minuten.",
                    )
                await connection.execute(
                    """
                    INSERT INTO public_submission_attempt (
                        id, action_id, idempotency_key,
                        fingerprint_hash, attempted_at
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    uuid4(),
                    action_id,
                    idempotency_key,
                    fingerprint_hash,
                    attempted_at,
                )
                await connection.execute(
                    """
                    DELETE FROM public_submission_attempt
                    WHERE attempted_at < $1
                    """,
                    attempted_at - timedelta(days=1),
                )

    @staticmethod
    async def _context(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        public_alias: str,
        evaluated_at: datetime,
    ) -> PublicOrderContext:
        row = await connection.fetchrow(
            """
            SELECT
                action.id,
                action.name,
                action.status,
                action.publication_starts_at,
                action.publication_ends_at,
                alias.alias,
                form.status AS form_status,
                form.form_key,
                form.title,
                form.introduction,
                form.submit_label,
                form.require_company_name,
                form.require_contact_name,
                form.require_email,
                form.require_phone,
                form.require_delivery_address,
                form.require_billing_address,
                form.allow_message,
                EXISTS (
                    SELECT 1
                    FROM charity_action_capability
                    WHERE action_id = action.id
                      AND capability = 'ordering'
                ) AS ordering_enabled
            FROM charity_action AS action
            LEFT JOIN public_action_alias AS alias
              ON alias.action_id = action.id
            LEFT JOIN order_form_configuration AS form
              ON form.action_id = action.id
            WHERE action.id = $1
            FOR SHARE OF action
            """,
            action_id,
        )
        if row is None:
            raise ResourceNotFound(
                "public_order_action_not_found",
                "Diese öffentliche Aktion wurde nicht gefunden.",
            )
        if (
            str(row["status"]) != "active"
            or row["publication_starts_at"] is None
            or row["publication_ends_at"] is None
            or not (
                row["publication_starts_at"]
                <= evaluated_at
                <= row["publication_ends_at"]
            )
            or str(row["alias"] or "") != public_alias
        ):
            raise Conflict(
                "public_order_action_closed",
                "Über diese Adresse sind derzeit keine Bestellungen möglich.",
            )
        if not bool(row["ordering_enabled"]):
            raise Conflict(
                "public_order_ordering_disabled",
                "Für diese Aktion sind Bestellungen nicht aktiviert.",
            )
        if str(row["form_status"] or "") != "active":
            raise Conflict(
                "public_order_form_inactive",
                "Das Bestellformular ist derzeit nicht aktiv.",
            )
        return PublicOrderContext(
            action_id=row["id"],
            action_name=str(row["name"]),
            order_form=OrderFormConfiguration(
                form_key=str(row["form_key"]),
                title=str(row["title"]),
                introduction=str(row["introduction"]),
                submit_label=str(row["submit_label"]),
                require_company_name=bool(row["require_company_name"]),
                require_contact_name=bool(row["require_contact_name"]),
                require_email=bool(row["require_email"]),
                require_phone=bool(row["require_phone"]),
                require_delivery_address=bool(row["require_delivery_address"]),
                require_billing_address=bool(row["require_billing_address"]),
                allow_message=bool(row["allow_message"]),
            ),
        )

    async def _record_order(
        self,
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        public_alias: str,
        party: ResolvedPublicParty,
        draft: PublicOrderDraft,
        idempotency_key: str,
        request_id: str,
        occurred_at: datetime,
    ) -> PublicOrderResult:
        await self._context(
            connection,
            action_id=action_id,
            public_alias=public_alias,
            evaluated_at=occurred_at,
        )
        offerings = await self._offerings(
            connection,
            action_id=action_id,
            offering_ids=tuple(line.offering_id for line in draft.lines),
        )
        priced_lines: list[CommitmentLine] = []
        for line_draft in draft.lines:
            offering = offerings[line_draft.offering_id]
            if line_draft.quoted_unit_price_minor != offering.unit_price.amount_minor:
                raise Conflict(
                    "public_order_price_changed",
                    "Der Preis hat sich geändert. Lade die Seite neu und prüfe die Bestellung.",
                )
            priced_lines.append(
                CommitmentLine.price_from(
                    offering,
                    quantity=line_draft.quantity,
                    unit=line_draft.unit,
                    evaluated_at=occurred_at,
                )
            )
        total = Money(0, priced_lines[0].unit_price.currency)
        for priced_line in priced_lines:
            total = total.plus(priced_line.line_total)
        commitment_id = uuid4()
        commitment = Commitment(
            id=commitment_id,
            action_id=action_id,
            source=CommitmentSource.PUBLIC_FORM,
            status=CommitmentStatus.REVIEW_READY,
            buyer=party.buyer,
            invoice_recipient=draft.invoice_recipient,
            delivery_recipient=draft.delivery_recipient,
            message=draft.message,
            public_reference=f"LA-{commitment_id.hex.upper()}",
            lines=tuple(priced_lines),
            total=total,
            idempotency_key=idempotency_key,
        )
        await self._insert_commitment(
            connection,
            commitment=commitment,
            occurred_at=occurred_at,
        )
        consent_person_id = party.contact_twenty_id or party.buyer.person_id
        consent_company_id = (
            party.buyer.company_id if consent_person_id is None else None
        )
        await connection.execute(
            """
            INSERT INTO consent_record (
                id, action_id, commitment_id,
                twenty_company_id, twenty_person_id,
                normalized_recipient, purpose, channel,
                text_version, source, evidence_kind, legal_basis_status,
                granted_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                'public_order_fulfilment', 'email',
                $7, 'public_order_form',
                'notice_acknowledgement', 'confirmed', $8
            )
            """,
            uuid4(),
            action_id,
            commitment.id,
            consent_company_id,
            consent_person_id,
            draft.party.email,
            draft.privacy_notice_version,
            occurred_at,
        )
        recipient_ids = await self._activity_recipients(
            connection,
            action_id=action_id,
            buyer=party.buyer,
            evaluated_at=occurred_at,
        )
        activity_id = uuid4()
        await connection.execute(
            """
            INSERT INTO activity_event (
                id, action_id, event_type,
                twenty_company_id, twenty_person_id,
                payload, occurred_at
            )
            VALUES (
                $1, $2, 'public_order_received',
                $3, $4, $5::jsonb, $6
            )
            """,
            activity_id,
            action_id,
            party.buyer.company_id,
            party.buyer.person_id,
            json.dumps(
                {
                    "commitmentId": str(commitment.id),
                    "publicReference": commitment.public_reference,
                    "buyerDisplayName": commitment.buyer.display_name,
                    "totalMinor": commitment.total.amount_minor,
                    "currency": commitment.total.currency,
                    "totalBoxes": commitment.total_boxes,
                    "totalPieces": commitment.total_pieces,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            occurred_at,
        )
        if recipient_ids:
            await connection.executemany(
                """
                INSERT INTO activity_event_recipient (
                    activity_event_id, user_id
                )
                VALUES ($1, $2)
                """,
                [(activity_id, user_id) for user_id in recipient_ids],
            )
        await connection.execute(
            """
            INSERT INTO audit_event (
                id, action_id, actor_user_id, event_type,
                entity_type, entity_id, request_id, payload, occurred_at
            )
            VALUES (
                $1, $2, NULL, 'public_order_created',
                'commitment', $3, $4, $5::jsonb, $6
            )
            """,
            uuid4(),
            action_id,
            commitment.id,
            request_id,
            json.dumps(
                {
                    "source": commitment.source.value,
                    "crmOutcome": party.outcome.value,
                    "contactTwentyId": (
                        str(party.contact_twenty_id)
                        if party.contact_twenty_id is not None
                        else None
                    ),
                    "activityRecipientIds": [str(item) for item in recipient_ids],
                    "privacyNoticeVersion": draft.privacy_notice_version,
                    "privacyAcknowledged": draft.privacy_acknowledged,
                    "bindingOrderConfirmed": draft.binding_order_confirmed,
                },
                separators=(",", ":"),
            ),
            occurred_at,
        )
        return PublicOrderResult(
            commitment=commitment,
            crm_outcome=party.outcome,
            contact_twenty_id=party.contact_twenty_id,
            activity_recipient_ids=recipient_ids,
            replayed=False,
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
                "public_order_offering_not_found",
                "Mindestens ein ausgewähltes Angebot wurde nicht gefunden.",
            )
        return {
            row["id"]: Offering(
                id=row["id"],
                action_id=row["action_id"],
                code=str(row["code"]),
                name=str(row["name"]),
                status=OfferingStatus(str(row["status"])),
                pricing_unit=OfferingUnit(str(row["unit"])),
                allowed_quantity_units=frozenset(
                    OfferingUnit(str(item)) for item in row["allowed_quantity_units"]
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
            for row in rows
        }

    @staticmethod
    async def _insert_commitment(
        connection: asyncpg.Connection[Any],
        *,
        commitment: Commitment,
        occurred_at: datetime,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO commitment (
                id, action_id, twenty_company_id, twenty_person_id,
                source, status, customer_snapshot,
                invoice_recipient_snapshot, delivery_recipient_snapshot,
                message_snapshot, public_reference, currency, total_minor,
                idempotency_key, created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7::jsonb,
                $8::jsonb, $9::jsonb, $10, $11, $12, $13,
                $14, $15, $15
            )
            """,
            commitment.id,
            commitment.action_id,
            commitment.buyer.company_id,
            commitment.buyer.person_id,
            commitment.source.value,
            commitment.status.value,
            json.dumps(commitment.buyer.payload(), separators=(",", ":")),
            json.dumps(
                commitment.invoice_recipient.payload(),
                separators=(",", ":"),
            )
            if commitment.invoice_recipient is not None
            else None,
            json.dumps(
                commitment.delivery_recipient.payload(),
                separators=(",", ":"),
            )
            if commitment.delivery_recipient is not None
            else None,
            commitment.message,
            commitment.public_reference,
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

    @staticmethod
    async def _activity_recipients(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        buyer: BuyerSnapshot,
        evaluated_at: datetime,
    ) -> tuple[UUID, ...]:
        rows = await connection.fetch(
            """
            SELECT DISTINCT assignment.acquirer_user_id AS user_id
            FROM acquisition_assignment AS assignment
            JOIN user_account AS account
              ON account.id = assignment.acquirer_user_id
             AND account.status = 'active'
            JOIN action_membership AS membership
              ON membership.action_id = assignment.action_id
             AND membership.user_id = assignment.acquirer_user_id
             AND membership.role = 'acquirer'
             AND membership.active_from <= $4
             AND (
                membership.active_until IS NULL
                OR membership.active_until > $4
             )
            WHERE assignment.action_id = $1
              AND assignment.twenty_company_id IS NOT DISTINCT FROM $2
              AND assignment.twenty_person_id IS NOT DISTINCT FROM $3
            ORDER BY assignment.acquirer_user_id
            """,
            action_id,
            buyer.company_id,
            buyer.person_id,
            evaluated_at,
        )
        if rows:
            return tuple(row["user_id"] for row in rows)
        administrators = await connection.fetch(
            """
            SELECT DISTINCT membership.user_id
            FROM action_membership AS membership
            JOIN user_account AS account
              ON account.id = membership.user_id
             AND account.status = 'active'
            WHERE membership.action_id = $1
              AND membership.role = 'charity_admin'
              AND membership.active_from <= $2
              AND (
                membership.active_until IS NULL
                OR membership.active_until > $2
              )
            ORDER BY membership.user_id
            """,
            action_id,
            evaluated_at,
        )
        return tuple(row["user_id"] for row in administrators)

    async def _replayed_result(
        self,
        connection: asyncpg.Connection[Any],
        value: object,
    ) -> PublicOrderResult:
        payload = _json_object(value, label="Public-Order-Befehlsnachweis")
        try:
            commitment_id = UUID(str(payload["commitmentId"]))
            outcome = PublicOrderCrmOutcome(str(payload["crmOutcome"]))
            contact_value = payload.get("contactTwentyId")
            recipient_values = payload["activityRecipientIds"]
            if not isinstance(recipient_values, list):
                raise ValueError("recipients")
            recipient_ids = tuple(UUID(str(item)) for item in recipient_values)
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError(
                "Public-Order-Befehlsnachweis ist unvollständig."
            ) from error
        commitment = await self._commitment(
            connection,
            commitment_id=commitment_id,
            replayed=True,
        )
        return PublicOrderResult(
            commitment=commitment,
            crm_outcome=outcome,
            contact_twenty_id=(
                UUID(str(contact_value)) if contact_value is not None else None
            ),
            activity_recipient_ids=recipient_ids,
            replayed=True,
        )

    @staticmethod
    async def _commitment(
        connection: asyncpg.Connection[Any],
        *,
        commitment_id: UUID,
        replayed: bool,
    ) -> Commitment:
        row = await connection.fetchrow(
            """
            SELECT
                id, action_id, source, status, customer_snapshot,
                invoice_recipient_snapshot, delivery_recipient_snapshot,
                message_snapshot, public_reference, currency, total_minor,
                idempotency_key
            FROM commitment
            WHERE id = $1
            """,
            commitment_id,
        )
        if row is None:
            raise RuntimeError("Die bestätigte öffentliche Bestellung fehlt.")
        lines = await connection.fetch(
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
        invoice = row["invoice_recipient_snapshot"]
        delivery = row["delivery_recipient_snapshot"]
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
                    _json_object(invoice, label="Rechnungsempfänger-Snapshot")
                )
                if invoice is not None
                else None
            ),
            delivery_recipient=(
                DeliveryRecipientSnapshot.from_payload(
                    _json_object(delivery, label="Lieferempfänger-Snapshot")
                )
                if delivery is not None
                else None
            ),
            message=(
                str(row["message_snapshot"])
                if row["message_snapshot"] is not None
                else None
            ),
            public_reference=(
                str(row["public_reference"])
                if row["public_reference"] is not None
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
                for item in lines
            ),
            total=Money(int(row["total_minor"]), currency),
            idempotency_key=(
                str(row["idempotency_key"])
                if row["idempotency_key"] is not None
                else None
            ),
            replayed=replayed,
        )
