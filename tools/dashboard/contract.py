#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL aggregate contract for POC-101."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4, uuid5

import asyncpg
import httpx

from leonaid.adapters.postgres.dashboard import AsyncpgDashboardRepository
from leonaid.domain.calendar import local_day, local_day_bounds
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
EMPTY_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
FELIX_ID = UUID("10000000-0000-4000-8000-000000000003")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
# Signed in by the command palette browser test (system admin, no membership).
SIMONE_ID = UUID("10000000-0000-4000-8000-000000000001")
SESSION_NAMESPACE = UUID("fc6f4986-ff43-4fd3-b4aa-92a6cead8141")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc101-{user_id}-server-session-token-value"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> None:
    now = datetime.now(timezone.utc)
    users = (KLARA_ID, FELIX_ID, ANNA_ID, SIMONE_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    for user_id in users:
        await connection.execute(
            """
            INSERT INTO user_session (
                id, user_id, token_digest, expires_at,
                last_seen_at, fresh_login_at, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(token_for(user_id)),
            now + SESSION_LIFETIME,
            now,
        )


async def dashboard(
    api: httpx.AsyncClient,
    *,
    action_id: UUID,
    user_id: UUID,
    label: str,
) -> httpx.Response:
    return await api.get(
        f"/api/v1/actions/{action_id}/dashboard",
        headers={
            "Cookie": f"{SESSION_COOKIE_NAME}={token_for(user_id)}",
            "X-Request-ID": f"poc101:{label}",
        },
    )


def as_object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractFailure(f"{label} is not an object")
    return value


def integer(row: asyncpg.Record, key: str) -> int:
    return int(row[key] or 0)


async def assert_acquirer_aggregate(
    connection: asyncpg.Connection[Any],
    payload: dict[str, Any],
) -> None:
    acquirer = as_object(payload.get("acquirer"), "Acquirer dashboard")
    if payload.get("charityAdmin") is not None:
        raise ContractFailure("Acquirer receives action-wide admin metrics")
    pipeline = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'open') AS open,
            count(*) FILTER (WHERE status = 'contacted') AS contacted,
            count(*) FILTER (WHERE status = 'committed') AS committed,
            count(*) FILTER (WHERE status = 'declined') AS declined,
            count(*) FILTER (WHERE status = 'handed_over') AS handed_over,
            count(*) AS total
        FROM acquisition_assignment
        WHERE action_id = $1 AND acquirer_user_id = $2
        """,
        ACTION_ID,
        ANNA_ID,
    )
    api_pipeline = as_object(acquirer.get("pipeline"), "Personal pipeline")
    pipeline_mapping = {
        "open": "open",
        "contacted": "contacted",
        "committed": "committed",
        "declined": "declined",
        "handedOver": "handed_over",
        "total": "total",
    }
    if pipeline is None or any(
        int(api_pipeline[api_key]) != integer(pipeline, sql_key)
        for api_key, sql_key in pipeline_mapping.items()
    ):
        raise ContractFailure("Personal API pipeline differs from SQL")

    activity_count = await connection.fetchval(
        """
        SELECT count(*) FROM acquisition_activity
        WHERE action_id = $1 AND actor_user_id = $2
        """,
        ACTION_ID,
        ANNA_ID,
    )
    if int(acquirer["activityCount"]) != int(activity_count or 0):
        raise ContractFailure("Personal activity count differs from SQL")
    reminders = as_object(acquirer.get("reminders"), "Follow-ups")
    if (
        int(reminders["unscheduled"]) != 2
        or int(reminders["overdue"]) != 0
        or int(reminders["today"]) != 0
        or int(reminders["upcoming"]) != 0
        or int(reminders["total"]) != 2
    ):
        raise ContractFailure("Personal follow-ups are not exact")


async def assert_admin_aggregate(
    connection: asyncpg.Connection[Any],
    payload: dict[str, Any],
) -> None:
    admin = as_object(payload.get("charityAdmin"), "Charity admin dashboard")
    if payload.get("acquirer") is not None:
        raise ContractFailure("Charity admin receives other users' personal metrics")
    pipeline = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'open') AS open,
            count(*) FILTER (WHERE status = 'contacted') AS contacted,
            count(*) FILTER (WHERE status = 'committed') AS committed,
            count(*) FILTER (WHERE status = 'declined') AS declined,
            count(*) FILTER (WHERE status = 'handed_over') AS handed_over,
            count(*) AS total
        FROM acquisition_assignment
        WHERE action_id = $1
        """,
        ACTION_ID,
    )
    api_pipeline = as_object(admin.get("pipeline"), "Action-wide pipeline")
    pipeline_mapping = {
        "open": "open",
        "contacted": "contacted",
        "committed": "committed",
        "declined": "declined",
        "handedOver": "handed_over",
        "total": "total",
    }
    if pipeline is None or any(
        int(api_pipeline[api_key]) != integer(pipeline, sql_key)
        for api_key, sql_key in pipeline_mapping.items()
    ):
        raise ContractFailure("Action-wide API pipeline differs from SQL")

    commitment_sql = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'draft') AS draft,
            count(*) FILTER (WHERE status = 'review_ready') AS review_ready,
            count(*) FILTER (WHERE status = 'confirmed') AS confirmed,
            count(*) FILTER (WHERE status = 'invoiced') AS invoiced,
            count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
            count(*) AS total,
            count(*) FILTER (WHERE status <> 'cancelled') AS active_total,
            coalesce(sum(total_minor) FILTER (
                WHERE status <> 'cancelled'
            ), 0) AS active_total_minor
        FROM commitment
        WHERE action_id = $1
        """,
        ACTION_ID,
    )
    line_sql = await connection.fetchrow(
        """
        SELECT
            coalesce(sum(line.quantity) FILTER (
                WHERE commitment.status <> 'cancelled'
                  AND line.unit_snapshot = 'box'
            ), 0) AS total_boxes,
            coalesce(sum(
                CASE
                    WHEN commitment.status <> 'cancelled'
                    THEN line.quantity * coalesce(
                        line.pieces_per_unit_snapshot,
                        CASE WHEN line.unit_snapshot = 'piece' THEN 1 ELSE 0 END
                    )
                    ELSE 0
                END
            ), 0) AS total_pieces
        FROM commitment
        JOIN commitment_line AS line ON line.commitment_id = commitment.id
        WHERE commitment.action_id = $1
        """,
        ACTION_ID,
    )
    api_commitments = as_object(admin.get("commitments"), "Orders")
    if commitment_sql is None or line_sql is None:
        raise ContractFailure("SQL order aggregates are missing")
    commitment_mapping = {
        "draft": "draft",
        "reviewReady": "review_ready",
        "confirmed": "confirmed",
        "invoiced": "invoiced",
        "cancelled": "cancelled",
        "total": "total",
        "activeTotal": "active_total",
        "activeTotalMinor": "active_total_minor",
    }
    if any(
        int(api_commitments[api_key]) != integer(commitment_sql, sql_key)
        for api_key, sql_key in commitment_mapping.items()
    ) or any(
        int(api_commitments[api_key]) != integer(line_sql, sql_key)
        for api_key, sql_key in (
            ("totalBoxes", "total_boxes"),
            ("totalPieces", "total_pieces"),
        )
    ):
        raise ContractFailure("API order aggregates differ from SQL")

    invoice_sql = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (WHERE status = 'issued') AS issued,
            count(*) FILTER (WHERE status = 'sent') AS sent,
            count(*) FILTER (
                WHERE status IN ('issued', 'sent')
            ) AS open,
            count(*) FILTER (WHERE status = 'paid') AS paid,
            count(*) FILTER (WHERE status = 'cancelled') AS cancelled,
            count(*) AS total,
            coalesce(sum(gross_minor) FILTER (
                WHERE status IN ('issued', 'sent', 'paid')
            ), 0) AS invoiced_amount_minor,
            -- Open receivables are remainders: gross minus active entries.
            coalesce(sum(
                greatest(gross_minor - (
                    SELECT coalesce(sum(payment.amount_minor), 0)
                    FROM payment_record AS payment
                    WHERE payment.invoice_id = invoice.id
                      AND NOT EXISTS (
                          SELECT 1 FROM payment_reversal AS reversal
                          WHERE reversal.payment_id = payment.id
                      )
                ), 0)
            ) FILTER (WHERE status <> 'cancelled'), 0) AS open_amount_minor
        FROM invoice
        WHERE action_id = $1
        """,
        ACTION_ID,
    )
    api_invoices = as_object(admin.get("invoices"), "Invoices")
    if invoice_sql is None:
        raise ContractFailure("SQL invoice aggregates are missing")
    invoice_mapping = {
        "issued": "issued",
        "sent": "sent",
        "open": "open",
        "paid": "paid",
        "cancelled": "cancelled",
        "total": "total",
        "invoicedAmountMinor": "invoiced_amount_minor",
        "openAmountMinor": "open_amount_minor",
    }
    if any(
        int(api_invoices[api_key]) != integer(invoice_sql, sql_key)
        for api_key, sql_key in invoice_mapping.items()
    ):
        raise ContractFailure("API invoice aggregates differ from SQL")

    # Overdue and failed dispatch, independently of the repository's SQL.
    today = local_day(datetime.now(timezone.utc))
    attention_sql = await connection.fetchrow(
        """
        SELECT
            count(*) FILTER (
                WHERE remainder.minor > 0 AND invoice.due_on < $2
            ) AS overdue,
            coalesce(sum(remainder.minor) FILTER (
                WHERE invoice.due_on < $2
            ), 0) AS overdue_amount_minor,
            count(*) FILTER (
                WHERE invoice.status <> 'cancelled'
                  AND (
                    SELECT event.status = 'dead_letter' AND mail.sent_at IS NULL
                    FROM invoice_delivery AS delivery
                    JOIN outbox_event AS event ON event.id = delivery.outbox_event_id
                    LEFT JOIN mail_delivery AS mail ON mail.outbox_event_id = event.id
                    WHERE delivery.invoice_id = invoice.id
                    ORDER BY delivery.requested_at DESC, delivery.created_at DESC,
                             delivery.id DESC
                    LIMIT 1
                  )
            ) AS delivery_failed
        FROM invoice
        CROSS JOIN LATERAL (
            SELECT CASE
                WHEN invoice.status = 'cancelled' THEN 0
                ELSE greatest(invoice.gross_minor - coalesce(sum(payment.amount_minor), 0), 0)
            END AS minor
            FROM payment_record AS payment
            WHERE payment.invoice_id = invoice.id
              AND NOT EXISTS (
                  SELECT 1 FROM payment_reversal AS reversal
                  WHERE reversal.payment_id = payment.id
              )
        ) AS remainder
        WHERE invoice.action_id = $1
        """,
        ACTION_ID,
        today,
    )
    if attention_sql is None or any(
        int(api_invoices[api_key]) != integer(attention_sql, sql_key)
        for api_key, sql_key in (
            ("overdue", "overdue"),
            ("overdueAmountMinor", "overdue_amount_minor"),
            ("deliveryFailed", "delivery_failed"),
        )
    ):
        raise ContractFailure("API overdue or failed-dispatch counts differ from SQL")

    weeks = admin.get("orderValueWeeks")
    if not isinstance(weeks, list) or len(weeks) != 8:
        raise ContractFailure("Order value needs exactly eight weeks")
    monday = today - timedelta(days=today.weekday())
    first_monday = monday - timedelta(weeks=7)
    if [week.get("weekStart") for week in weeks] != [
        (first_monday + timedelta(weeks=index)).isoformat() for index in range(8)
    ]:
        raise ContractFailure("Order value weeks are not the last eight Mondays")
    weekly_sql = await connection.fetchval(
        """
        SELECT coalesce(sum(total_minor), 0)
        FROM commitment
        WHERE action_id = $1
          AND status <> 'cancelled'
          AND created_at >= $2
          AND created_at < $3
        """,
        ACTION_ID,
        local_day_bounds(first_monday)[0],
        local_day_bounds(monday + timedelta(days=7))[0],
    )
    if sum(int(week["totalMinor"]) for week in weeks) != int(weekly_sql or 0):
        raise ContractFailure("Weekly order value differs from SQL")

    delivery = as_object(admin.get("delivery"), "Delivery overview")
    windows_sql = await connection.fetch(
        """
        SELECT
            window_row.id,
            count(commitment.id) FILTER (
                WHERE commitment.status IN ('review_ready', 'confirmed', 'invoiced')
            ) AS commitments
        FROM action_delivery_window AS window_row
        LEFT JOIN commitment ON commitment.delivery_window_id = window_row.id
        WHERE window_row.action_id = $1
          AND NOT window_row.retired
          AND window_row.ends_at >= $2
        GROUP BY window_row.id, window_row.starts_at
        ORDER BY window_row.starts_at, window_row.id
        LIMIT 8
        """,
        ACTION_ID,
        local_day_bounds(today)[0],
    )
    api_windows = delivery.get("windows")
    if not isinstance(api_windows, list) or [
        (str(item["id"]), int(item["commitments"])) for item in api_windows
    ] != [(str(row["id"]), integer(row, "commitments")) for row in windows_sql]:
        raise ContractFailure("Delivery windows differ from SQL")


def assert_definitions(payload: dict[str, Any], expected_keys: set[str]) -> None:
    definitions = payload.get("metricDefinitions")
    if not isinstance(definitions, list):
        raise ContractFailure("Metric definitions are missing")
    actual_keys = {
        str(item.get("key"))
        for item in definitions
        if isinstance(item, dict)
        and str(item.get("label", "")).strip()
        and str(item.get("description", "")).strip()
        and str(item.get("href", "")).startswith("/")
    }
    if actual_keys != expected_keys:
        raise ContractFailure("Metric definitions are incomplete")


async def assert_reminder_buckets_use_the_berlin_day() -> None:
    """Follow-up buckets follow the club's day at a pinned night-hour clock.

    Evaluated at 23:45 UTC on 14 January (00:45 on the 15th in Berlin). A
    follow-up due 22:30 UTC on the 14th is overdue in Berlin (23:30 on the
    14th) although UTC still calls it today; one due 22:30 UTC on the 15th
    is today in Berlin although UTC calls it upcoming.
    """

    evaluated_at = datetime(2026, 1, 14, 23, 45, tzinfo=timezone.utc)
    pool = await asyncpg.create_pool(require_env("CORE_DATABASE_URL"))
    try:
        ids = [
            row["id"]
            for row in await pool.fetch(
                """
                SELECT id FROM acquisition_assignment
                WHERE action_id = $1 AND acquirer_user_id = $2
                  AND status <> 'handed_over' AND due_at IS NULL
                ORDER BY id
                """,
                ACTION_ID,
                ANNA_ID,
            )
        ]
        if len(ids) != 2:
            raise ContractFailure("Golden follow-up fixture changed")
        repository = AsyncpgDashboardRepository(pool)
        cases = (
            (
                datetime(2026, 1, 14, 23, 30, tzinfo=timezone.utc),
                datetime(2026, 1, 14, 22, 30, tzinfo=timezone.utc),
                {"overdue": 1, "today": 1, "upcoming": 0},
            ),
            (
                datetime(2026, 1, 14, 23, 30, tzinfo=timezone.utc),
                datetime(2026, 1, 15, 22, 30, tzinfo=timezone.utc),
                {"overdue": 0, "today": 2, "upcoming": 0},
            ),
        )
        try:
            for first, second, expected in cases:
                await pool.executemany(
                    "UPDATE acquisition_assignment SET due_at = $2 WHERE id = $1",
                    [(ids[0], first), (ids[1], second)],
                )
                snapshot = await repository.snapshot(
                    action_id=ACTION_ID,
                    actor_user_id=ANNA_ID,
                    include_acquirer=True,
                    include_charity_admin=False,
                    evaluated_at=evaluated_at,
                )
                if snapshot is None or snapshot.acquirer is None:
                    raise ContractFailure("Acquirer dashboard missing")
                reminders = snapshot.acquirer.reminders
                actual = {
                    "overdue": reminders.overdue,
                    "today": reminders.today,
                    "upcoming": reminders.upcoming,
                }
                if actual != expected:
                    raise ContractFailure(
                        f"Follow-ups ignore the Berlin day: {actual} != {expected}"
                    )
        finally:
            await pool.execute(
                "UPDATE acquisition_assignment SET due_at = NULL WHERE id = ANY($1)",
                ids,
            )
    finally:
        await pool.close()


class _Rollback(Exception):
    """Ends a contract transaction without keeping its fixture."""


async def assert_window_load_counts_only_booked_orders() -> None:
    """The dashboard window load matches the delivery board.

    Three golden orders are booked into a fresh window: one stays binding,
    one becomes a draft and one is cancelled. Only the binding one counts,
    in the order count and in the quantities. Everything is rolled back.
    """

    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        try:
            async with connection.transaction():
                orders = await connection.fetch(
                    """
                    SELECT commitment.id,
                           (SELECT sum(line.quantity) FROM commitment_line AS line
                            WHERE line.commitment_id = commitment.id) AS quantity
                    FROM commitment
                    WHERE action_id = $1
                      AND status <> 'cancelled'
                      AND EXISTS (
                          SELECT 1 FROM commitment_line AS line
                          WHERE line.commitment_id = commitment.id
                      )
                    ORDER BY id
                    LIMIT 3
                    """,
                    ACTION_ID,
                )
                if len(orders) != 3:
                    raise ContractFailure("Golden order fixture changed")
                await connection.execute(
                    """
                    INSERT INTO action_delivery_configuration(action_id, enabled)
                    VALUES ($1, true)
                    ON CONFLICT (action_id) DO UPDATE SET enabled = true
                    """,
                    ACTION_ID,
                )
                window_id = uuid4()
                starts_at = datetime.now(timezone.utc) + timedelta(days=1)
                await connection.execute(
                    """
                    INSERT INTO action_delivery_window(id, action_id, starts_at, ends_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    window_id,
                    ACTION_ID,
                    starts_at,
                    starts_at + timedelta(hours=2),
                )
                booked, draft, cancelled = (row["id"] for row in orders)
                for order_id, status in (
                    (booked, "confirmed"),
                    (draft, "draft"),
                    (cancelled, "cancelled"),
                ):
                    await connection.execute(
                        """
                        UPDATE commitment
                        SET delivery_window_id = $2,
                            delivery_window_snapshot = '{}'::jsonb,
                            status = $3
                        WHERE id = $1
                        """,
                        order_id,
                        window_id,
                        status,
                    )
                overview = await AsyncpgDashboardRepository._delivery(
                    connection,
                    ACTION_ID,
                    evaluated_at=datetime.now(timezone.utc),
                )
                load = next(
                    (item for item in overview.windows if item.id == window_id),
                    None,
                )
                if load is None:
                    raise ContractFailure("Fresh delivery window is missing")
                if load.commitments != 1:
                    raise ContractFailure(
                        f"Window counts drafts or cancellations: {load.commitments}"
                    )
                total = sum(item.quantity for item in load.quantities)
                if total != int(orders[0]["quantity"]):
                    raise ContractFailure(
                        f"Window quantities count drafts or cancellations: {total}"
                    )
                raise _Rollback
        except _Rollback:
            pass
    finally:
        await connection.close()


async def run() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        await seed_sessions(connection)
        await connection.execute(
            """
            UPDATE charity_action
            SET goal_value = NULL,
                goal_unit = NULL,
                actual_value = 125,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
            """,
            EMPTY_ACTION_ID,
        )

        async with httpx.AsyncClient(
            base_url=require_env("API_BASE_URL"),
            timeout=30,
        ) as api:
            anna_response = await dashboard(
                api,
                action_id=ACTION_ID,
                user_id=ANNA_ID,
                label="anna",
            )
            anna_response.raise_for_status()
            if anna_response.headers.get("cache-control") != "private, no-store":
                raise ContractFailure("Dashboard response is cacheable")
            anna = as_object(anna_response.json(), "Anna dashboard")
            goal = as_object(anna.get("goal"), "Action goal")
            if (
                goal.get("actualValue") != "900"
                or goal.get("targetValue") != "1000"
                or goal.get("unit") != "EUR"
                or goal.get("progressBasisPoints") != 9000
                or goal.get("configured") is not True
            ):
                raise ContractFailure("Golden action goal is not exact")
            await assert_acquirer_aggregate(connection, anna)
            assert_definitions(
                anna,
                {
                    "acquirer.pipeline",
                    "acquirer.reminders",
                    "acquirer.activities",
                },
            )

            klara_response = await dashboard(
                api,
                action_id=ACTION_ID,
                user_id=KLARA_ID,
                label="klara",
            )
            klara_response.raise_for_status()
            klara = as_object(klara_response.json(), "Klara dashboard")
            await assert_admin_aggregate(connection, klara)
            assert_definitions(
                klara,
                {
                    "admin.pipeline",
                    "admin.commitments",
                    "admin.invoiced",
                    "admin.open_receivables",
                    "admin.overdue",
                    "admin.delivery_failed",
                    "admin.to_invoice",
                    "admin.order_value_weeks",
                    "admin.delivery",
                },
            )
            delivery_definition = next(
                item
                for item in klara["metricDefinitions"]
                if item.get("key") == "admin.delivery"
            )
            if delivery_definition.get("href") != f"/admin/delivery?action={ACTION_ID}":
                raise ContractFailure("Delivery windows do not open the delivery board")

            concealed = await dashboard(
                api,
                action_id=ACTION_ID,
                user_id=FELIX_ID,
                label="concealed",
            )
            if concealed.status_code != 404:
                raise ContractFailure("Unrelated dashboard is not hidden")

            empty_response = await dashboard(
                api,
                action_id=EMPTY_ACTION_ID,
                user_id=FELIX_ID,
                label="partial-empty",
            )
            empty_response.raise_for_status()
            empty = as_object(empty_response.json(), "Empty dashboard")
            empty_goal = as_object(empty.get("goal"), "Partly configured goal")
            empty_admin = as_object(empty.get("charityAdmin"), "Empty admin view")
            if (
                empty_goal.get("configured") is not False
                or empty_goal.get("targetValue") is not None
                or empty_goal.get("progressBasisPoints") is not None
                or empty_goal.get("actualValue") != "125"
                or as_object(empty_admin["pipeline"], "Empty pipeline").get("total")
                != 0
                or as_object(empty_admin["commitments"], "Empty orders").get("total")
                != 0
                or as_object(empty_admin["invoices"], "Empty invoices").get("total")
                != 0
            ):
                raise ContractFailure("Empty or partly configured action is not stable")
    finally:
        await connection.close()
    await assert_reminder_buckets_use_the_berlin_day()
    await assert_window_load_counts_only_booked_orders()

    print("dashboard-contract: OK: roles, golden metrics, real SQL aggregates,")
    print(
        "dashboard-contract:     definitions, empty view and row-level protection proven"
    )


if __name__ == "__main__":
    asyncio.run(run())
