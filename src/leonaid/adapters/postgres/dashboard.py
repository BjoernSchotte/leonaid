"""Real PostgreSQL aggregates for role-aware dashboards."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import asyncpg

from leonaid.application.dashboard import (
    AcquirerDashboard,
    CharityAdminDashboard,
    CommitmentCounts,
    DashboardRepository,
    DashboardSnapshot,
    GoalProgress,
    InvoiceCounts,
    PipelineCounts,
    ReminderCounts,
    progress_basis_points,
)

BERLIN = ZoneInfo("Europe/Berlin")


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
                                  AND (due_at AT TIME ZONE 'Europe/Berlin')::date < $3
                            ) AS overdue,
                            count(*) FILTER (
                                WHERE due_at IS NOT NULL
                                  AND (due_at AT TIME ZONE 'Europe/Berlin')::date = $3
                            ) AS today,
                            count(*) FILTER (
                                WHERE due_at IS NOT NULL
                                  AND (due_at AT TIME ZONE 'Europe/Berlin')::date > $3
                            ) AS upcoming,
                            count(*) FILTER (WHERE due_at IS NULL) AS unscheduled
                        FROM acquisition_assignment
                        WHERE action_id = $1
                          AND acquirer_user_id = $2
                          AND status <> 'handed_over'
                        """,
                        action_id,
                        actor_user_id,
                        evaluated_at.astimezone(BERLIN).date(),
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
                    commitments = await self._commitments(connection, action_id)
                    invoices = await self._invoices(connection, action_id)
                    charity_admin = CharityAdminDashboard(
                        pipeline=pipeline,
                        commitments=commitments,
                        invoices=invoices,
                    )

        actual_value = Decimal(action["actual_value"])
        target_value = (
            Decimal(action["goal_value"]) if action["goal_value"] is not None else None
        )
        currency = str(action["currency"])
        return DashboardSnapshot(
            action_id=UUID(str(action["id"])),
            action_name=str(action["name"]),
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
                line_summary.total_pieces
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
        )

    @staticmethod
    async def _invoices(
        connection: asyncpg.Connection[Any],
        action_id: UUID,
    ) -> InvoiceCounts:
        row = await connection.fetchrow(
            """
            SELECT
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
            WHERE action_id = $1
            """,
            action_id,
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
        )
