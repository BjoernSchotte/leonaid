"""Real PostgreSQL aggregates for role-aware dashboards."""

from __future__ import annotations

import json
from zoneinfo import ZoneInfo
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from leonaid.domain.action_templates import OfferingUnit
from leonaid.domain.calendar import (
    INSTALLATION_TIME_ZONE,
    local_day,
    local_day_bounds,
)
from leonaid.domain.commitments import UnitQuantity
from leonaid.application.dashboard import (
    AcquirerDashboard,
    CharityAdminDashboard,
    CommitmentCounts,
    DashboardRepository,
    DashboardSnapshot,
    DELIVERY_WINDOW_LIMIT,
    DeliveryOverview,
    DeliveryWindowLoad,
    GoalProgress,
    InvoiceCounts,
    ORDER_VALUE_WEEKS,
    OrderValueWeek,
    PipelineCounts,
    ReminderCounts,
    progress_basis_points,
)


def _integer(row: asyncpg.Record, key: str) -> int:
    return int(row[key] or 0)


def _pipeline(row: asyncpg.Record) -> PipelineCounts:
    return PipelineCounts(
        open=_integer(row, "open"),
        contacted=_integer(row, "contacted"),
        committed=_integer(row, "committed"),
        declined=_integer(row, "declined"),
        handed_over=_integer(row, "handed_over"),
    )


class AsyncpgDashboardRepository(DashboardRepository):
    def __init__(self, pool: asyncpg.Pool[Any]) -> None:
        self._pool = pool

    async def snapshot(
        self,
        *,
        action_id: UUID,
        actor_user_id: UUID,
        include_acquirer: bool,
        include_charity_admin: bool,
        evaluated_at: datetime,
    ) -> DashboardSnapshot | None:
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("Dashboard-Zeitpunkt muss eine Zeitzone enthalten.")

        async with self._pool.acquire() as connection:
            async with connection.transaction(
                isolation="repeatable_read",
                readonly=True,
            ):
                action = await connection.fetchrow(
                    """
                    SELECT id, name, goal_value, actual_value, goal_unit, currency
                    FROM charity_action
                    WHERE id = $1
                    """,
                    action_id,
                )
                if action is None:
                    return None

                beneficiaries = await connection.fetch(
                    """
                    SELECT organization_name FROM beneficiary
                    WHERE action_id = $1
                    ORDER BY sort_order, id
                    """,
                    action_id,
                )

                acquirer: AcquirerDashboard | None = None
                if include_acquirer:
                    personal_pipeline = await self._pipeline(
                        connection,
                        action_id=action_id,
                        actor_user_id=actor_user_id,
                    )
                    reminders = await connection.fetchrow(
                        """
                        SELECT
                            count(*) FILTER (
                                WHERE due_at IS NOT NULL
                                  AND due_at < $3
                            ) AS overdue,
                            count(*) FILTER (
                                WHERE due_at IS NOT NULL
                                  AND due_at >= $3 AND due_at < $4
                            ) AS today,
                            count(*) FILTER (
                                WHERE due_at IS NOT NULL
                                  AND due_at >= $4
                            ) AS upcoming,
                            count(*) FILTER (WHERE due_at IS NULL) AS unscheduled
                        FROM acquisition_assignment
                        WHERE action_id = $1
                          AND acquirer_user_id = $2
                          AND status <> 'handed_over'
                        """,
                        action_id,
                        actor_user_id,
                        *local_day_bounds(local_day(evaluated_at)),
                    )
                    activity_count = await connection.fetchval(
                        """
                        SELECT count(*)
                        FROM acquisition_activity
                        WHERE action_id = $1
                          AND actor_user_id = $2
                        """,
                        action_id,
                        actor_user_id,
                    )
                    if reminders is None:
                        raise RuntimeError("Reminder-Aggregat fehlt.")
                    acquirer = AcquirerDashboard(
                        pipeline=personal_pipeline,
                        reminders=ReminderCounts(
                            overdue=_integer(reminders, "overdue"),
                            today=_integer(reminders, "today"),
                            upcoming=_integer(reminders, "upcoming"),
                            unscheduled=_integer(reminders, "unscheduled"),
                        ),
                        activity_count=int(activity_count or 0),
                    )

                charity_admin: CharityAdminDashboard | None = None
                if include_charity_admin:
                    pipeline = await self._pipeline(
                        connection,
                        action_id=action_id,
                        actor_user_id=None,
                    )
                    today = local_day(evaluated_at)
                    commitments = await self._commitments(connection, action_id)
                    invoices = await self._invoices(connection, action_id, today=today)
                    charity_admin = CharityAdminDashboard(
                        pipeline=pipeline,
                        commitments=commitments,
                        invoices=invoices,
                        order_value_weeks=await self._order_value_weeks(
                            connection, action_id, today=today
                        ),
                        delivery=await self._delivery(
                            connection, action_id, evaluated_at=evaluated_at
                        ),
                    )

        actual_value = Decimal(action["actual_value"])
        target_value = (
            Decimal(action["goal_value"]) if action["goal_value"] is not None else None
        )
        currency = str(action["currency"])
        return DashboardSnapshot(
            action_id=UUID(str(action["id"])),
            action_name=str(action["name"]),
            beneficiaries=tuple(
                str(item["organization_name"]) for item in beneficiaries
            ),
            goal=GoalProgress(
                actual_value=actual_value,
                target_value=target_value,
                unit=str(action["goal_unit"]) if action["goal_unit"] else None,
                currency=currency,
                progress_basis_points=progress_basis_points(
                    actual_value,
                    target_value,
                ),
            ),
            currency=currency,
            acquirer=acquirer,
            charity_admin=charity_admin,
            generated_at=evaluated_at,
        )

    @staticmethod
    async def _pipeline(
        connection: asyncpg.Connection[Any],
        *,
        action_id: UUID,
        actor_user_id: UUID | None,
    ) -> PipelineCounts:
        row = await connection.fetchrow(
            """
            SELECT
                count(*) FILTER (WHERE status = 'open') AS open,
                count(*) FILTER (WHERE status = 'contacted') AS contacted,
                count(*) FILTER (WHERE status = 'committed') AS committed,
                count(*) FILTER (WHERE status = 'declined') AS declined,
                count(*) FILTER (WHERE status = 'handed_over') AS handed_over
            FROM acquisition_assignment
            WHERE action_id = $1
              AND ($2::uuid IS NULL OR acquirer_user_id = $2)
            """,
            action_id,
            actor_user_id,
        )
        if row is None:
            raise RuntimeError("Pipeline-Aggregat fehlt.")
        return _pipeline(row)

    @staticmethod
    async def _commitments(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
    ) -> CommitmentCounts:
        row = await connection.fetchrow(
            """
            WITH commitment_summary AS (
                SELECT
                    count(*) FILTER (WHERE status = 'draft') AS draft,
                    count(*) FILTER (
                        WHERE status = 'review_ready'
                    ) AS review_ready,
                    count(*) FILTER (
                        WHERE status = 'confirmed'
                    ) AS confirmed,
                    count(*) FILTER (
                        WHERE status = 'invoiced'
                    ) AS invoiced,
                    count(*) FILTER (
                        WHERE status = 'cancelled'
                    ) AS cancelled,
                    coalesce(sum(total_minor) FILTER (
                        WHERE status <> 'cancelled'
                    ), 0) AS active_total_minor,
                    array_remove(array_agg(DISTINCT currency), NULL)
                        AS currencies
                FROM commitment
                WHERE action_id = $1
            ),
            line_summary AS (
                SELECT
                    coalesce(sum(
                        CASE
                            WHEN commitment.status <> 'cancelled'
                             AND line.unit_snapshot = 'box'
                            THEN line.quantity
                            ELSE 0
                        END
                    ), 0) AS total_boxes,
                    coalesce(sum(
                        CASE
                            WHEN commitment.status <> 'cancelled'
                            THEN line.quantity * coalesce(
                                line.pieces_per_unit_snapshot,
                                CASE
                                    WHEN line.unit_snapshot = 'piece' THEN 1
                                    ELSE 0
                                END
                            )
                            ELSE 0
                        END
                    ), 0) AS total_pieces
                FROM commitment
                JOIN commitment_line AS line
                  ON line.commitment_id = commitment.id
                WHERE commitment.action_id = $1
            )
            SELECT
                commitment_summary.*,
                line_summary.total_boxes,
                line_summary.total_pieces,
                (
                    SELECT coalesce(
                        jsonb_object_agg(unit_totals.unit, unit_totals.quantity),
                        '{}'::jsonb
                    )::text
                    FROM (
                        SELECT
                            line.unit_snapshot AS unit,
                            sum(line.quantity) AS quantity
                        FROM commitment
                        JOIN commitment_line AS line
                          ON line.commitment_id = commitment.id
                        WHERE commitment.action_id = $1
                          AND commitment.status <> 'cancelled'
                        GROUP BY line.unit_snapshot
                    ) AS unit_totals
                ) AS quantities_by_unit
            FROM commitment_summary
            CROSS JOIN line_summary
            """,
            action_id,
        )
        if row is None:
            raise RuntimeError("Bestell-Aggregat fehlt.")
        currencies = tuple(str(item) for item in (row["currencies"] or ()))
        if len(currencies) > 1:
            raise RuntimeError("Bestellungen enthalten mehrere Währungen.")
        return CommitmentCounts(
            draft=_integer(row, "draft"),
            review_ready=_integer(row, "review_ready"),
            confirmed=_integer(row, "confirmed"),
            invoiced=_integer(row, "invoiced"),
            cancelled=_integer(row, "cancelled"),
            active_total_minor=_integer(row, "active_total_minor"),
            total_boxes=_integer(row, "total_boxes"),
            total_pieces=_integer(row, "total_pieces"),
            quantities=UnitQuantity.summarize(
                (OfferingUnit(str(unit)), int(quantity))
                for unit, quantity in json.loads(
                    str(row["quantities_by_unit"] or "{}")
                ).items()
            ),
        )

    @staticmethod
    async def _invoices(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
        *,
        today: date,
    ) -> InvoiceCounts:
        row = await connection.fetchrow(
            """
            WITH latest_delivery AS (
                SELECT DISTINCT ON (delivery.invoice_id)
                    delivery.invoice_id,
                    event.status AS outbox_status,
                    mail.sent_at
                FROM invoice_delivery AS delivery
                JOIN outbox_event AS event
                  ON event.id = delivery.outbox_event_id
                LEFT JOIN mail_delivery AS mail
                  ON mail.outbox_event_id = event.id
                WHERE delivery.action_id = $1
                ORDER BY
                    delivery.invoice_id,
                    delivery.requested_at DESC,
                    delivery.created_at DESC,
                    delivery.id DESC
            )
            SELECT
                count(*) FILTER (
                    WHERE status IN ('issued', 'sent') AND due_on < $2
                ) AS overdue,
                coalesce(sum(gross_minor) FILTER (
                    WHERE status IN ('issued', 'sent') AND due_on < $2
                ), 0) AS overdue_amount_minor,
                count(*) FILTER (
                    WHERE status <> 'cancelled'
                      AND latest_delivery.outbox_status = 'dead_letter'
                      AND latest_delivery.sent_at IS NULL
                ) AS delivery_failed,
                count(*) FILTER (WHERE status = 'issued') AS issued,
                count(*) FILTER (WHERE status = 'sent') AS sent,
                count(*) FILTER (WHERE status = 'paid') AS paid,
                count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
                coalesce(sum(gross_minor) FILTER (
                    WHERE status IN ('issued', 'sent', 'paid')
                ), 0) AS invoiced_amount_minor,
                coalesce(sum(gross_minor) FILTER (
                    WHERE status IN ('issued', 'sent')
                ), 0) AS open_amount_minor,
                array_remove(array_agg(DISTINCT currency), NULL) AS currencies
            FROM invoice
            LEFT JOIN latest_delivery
              ON latest_delivery.invoice_id = invoice.id
            WHERE invoice.action_id = $1
            """,
            action_id,
            today,
        )
        if row is None:
            raise RuntimeError("Rechnungs-Aggregat fehlt.")
        currencies = tuple(str(item) for item in (row["currencies"] or ()))
        if len(currencies) > 1:
            raise RuntimeError("Rechnungen enthalten mehrere Währungen.")
        return InvoiceCounts(
            issued=_integer(row, "issued"),
            sent=_integer(row, "sent"),
            paid=_integer(row, "paid"),
            cancelled=_integer(row, "cancelled"),
            invoiced_amount_minor=_integer(row, "invoiced_amount_minor"),
            open_amount_minor=_integer(row, "open_amount_minor"),
            overdue=_integer(row, "overdue"),
            overdue_amount_minor=_integer(row, "overdue_amount_minor"),
            delivery_failed=_integer(row, "delivery_failed"),
        )

    @staticmethod
    async def _order_value_weeks(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
        *,
        today: date,
    ) -> tuple[OrderValueWeek, ...]:
        """Order value per ISO week of club time, the current week last."""

        current_monday = today - timedelta(days=today.weekday())
        mondays = [
            current_monday - timedelta(weeks=offset)
            for offset in range(ORDER_VALUE_WEEKS - 1, -1, -1)
        ]
        # Week starts in UTC, plus the end of the current week.
        bounds = [local_day_bounds(monday)[0] for monday in mondays]
        bounds.append(local_day_bounds(current_monday + timedelta(days=7))[0])
        rows = await connection.fetch(
            """
            SELECT
                week.index,
                coalesce(sum(commitment.total_minor), 0) AS total_minor
            FROM generate_series(1, $2::int) AS week(index)
            LEFT JOIN commitment
              ON commitment.action_id = $1
             AND commitment.status <> 'cancelled'
             AND commitment.created_at >= ($3::timestamptz[])[week.index]
             AND commitment.created_at < ($3::timestamptz[])[week.index + 1]
            GROUP BY week.index
            ORDER BY week.index
            """,
            action_id,
            ORDER_VALUE_WEEKS,
            bounds,
        )
        totals = {int(row["index"]): int(row["total_minor"]) for row in rows}
        return tuple(
            OrderValueWeek(
                week_start=monday,
                iso_week=monday.isocalendar().week,
                total_minor=totals.get(index, 0),
            )
            for index, monday in enumerate(mondays, start=1)
        )

    @staticmethod
    async def _delivery(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
        *,
        evaluated_at: datetime,
    ) -> DeliveryOverview:
        """Windows that have not ended before today, with booked orders.

        "Today" is the day in the zone of the action's delivery configuration,
        the zone its windows are planned in (calendar module).
        """

        configuration = await connection.fetchrow(
            """
            SELECT enabled, timezone
            FROM action_delivery_configuration
            WHERE action_id = $1
            """,
            action_id,
        )
        zone = (
            ZoneInfo(str(configuration["timezone"]))
            if configuration is not None
            else INSTALLATION_TIME_ZONE
        )
        enabled = bool(configuration["enabled"]) if configuration else False
        window_day_start = local_day_bounds(local_day(evaluated_at, zone), zone)[0]
        rows = await connection.fetch(
            """
            SELECT
                window_row.id,
                window_row.starts_at,
                window_row.ends_at,
                count(commitment.id) AS commitments,
                (
                    SELECT coalesce(
                        jsonb_object_agg(unit_totals.unit, unit_totals.quantity),
                        '{}'::jsonb
                    )::text
                    FROM (
                        SELECT line.unit_snapshot AS unit,
                               sum(line.quantity) AS quantity
                        FROM commitment AS booked
                        JOIN commitment_line AS line
                          ON line.commitment_id = booked.id
                        WHERE booked.delivery_window_id = window_row.id
                          AND booked.status <> 'cancelled'
                        GROUP BY line.unit_snapshot
                    ) AS unit_totals
                ) AS quantities_by_unit
            FROM action_delivery_window AS window_row
            LEFT JOIN commitment
              ON commitment.delivery_window_id = window_row.id
             AND commitment.action_id = window_row.action_id
             AND commitment.status <> 'cancelled'
            WHERE window_row.action_id = $1
              AND NOT window_row.retired
              AND window_row.ends_at >= $2
            GROUP BY window_row.id
            ORDER BY window_row.starts_at, window_row.id
            LIMIT $3
            """,
            action_id,
            window_day_start,
            DELIVERY_WINDOW_LIMIT,
        )
        return DeliveryOverview(
            enabled=enabled,
            windows=tuple(
                DeliveryWindowLoad(
                    id=UUID(str(row["id"])),
                    starts_at=row["starts_at"],
                    ends_at=row["ends_at"],
                    commitments=_integer(row, "commitments"),
                    quantities=UnitQuantity.summarize(
                        (OfferingUnit(str(unit)), int(quantity))
                        for unit, quantity in json.loads(
                            str(row["quantities_by_unit"] or "{}")
                        ).items()
                    ),
                )
                for row in rows
            ),
        )
