"""Operational visibility without exposing business payloads or secrets."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx

from leonaid.application.operations import (
    ApiMetricSnapshot,
    DependencySignal,
    FailedJob,
    OperationsSnapshot,
)


class ApiMetrics:
    """Process-local request counters; durable business metrics stay in SQL."""

    def __init__(self) -> None:
        self._requests = 0
        self._errors = 0
        self._total_latency_ms = 0.0

    def record(self, *, status_code: int, latency_ms: float) -> None:
        self._requests += 1
        if status_code >= 500:
            self._errors += 1
        self._total_latency_ms += max(0.0, latency_ms)

    def snapshot(self) -> ApiMetricSnapshot:
        average = self._total_latency_ms / self._requests if self._requests > 0 else 0.0
        return ApiMetricSnapshot(
            requests=self._requests,
            errors=self._errors,
            average_latency_ms=round(average, 2),
        )


def structured_event(event: str, **fields: str | int | float | bool | None) -> str:
    """Serialize only explicitly selected, payload-free operational fields."""

    return json.dumps(
        {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **fields,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


class OperationsService:
    def __init__(
        self,
        pool: asyncpg.Pool[Any],
        *,
        api_metrics: ApiMetrics,
        dependency_urls: dict[str, str],
    ) -> None:
        if set(dependency_urls) != {"twenty", "rustfs", "mail"}:
            raise ValueError("Twenty, RustFS und Mail müssen konfiguriert sein.")
        self._pool = pool
        self._api_metrics = api_metrics
        self._dependency_urls = dict(dependency_urls)

    async def snapshot(self, *, request_id: str) -> OperationsSnapshot:
        dependencies = await asyncio.gather(
            *(
                self._probe(name, url, request_id=request_id)
                for name, url in self._dependency_urls.items()
            )
        )
        async with self._pool.acquire() as connection:
            outbox_rows = await connection.fetch(
                "SELECT status, count(*) AS count "
                "FROM outbox_event GROUP BY status ORDER BY status"
            )
            mail_rows = await connection.fetch(
                """
                SELECT status, count(*) AS count
                FROM outbox_event
                WHERE event_type IN (
                    'mail.send.v1',
                    'invoice.mail.send.requested.v1'
                )
                GROUP BY status
                ORDER BY status
                """
            )
            login_row = await connection.fetchrow(
                """
                SELECT
                    count(*) FILTER (
                        WHERE event_type = 'identity.login_challenge.created'
                    ) AS challenges,
                    count(*) FILTER (
                        WHERE event_type = 'identity.login_challenge.consumed'
                    ) AS completions,
                    count(*) FILTER (
                        WHERE event_type IN (
                            'identity.login_challenge.code_locked',
                            'identity.login_challenge.expired'
                        )
                    ) AS failures
                FROM audit_event
                WHERE occurred_at >= now() - interval '24 hours'
                """
            )
            failed_rows = await connection.fetch(
                """
                SELECT
                    id, event_type, aggregate_type, aggregate_id, attempts,
                    last_error_code, dead_lettered_at, manual_retry_count
                FROM outbox_event
                WHERE status = 'dead_letter'
                ORDER BY dead_lettered_at DESC, id
                LIMIT 50
                """
            )
        return OperationsSnapshot(
            generated_at=datetime.now(timezone.utc),
            request_id=request_id,
            api=self._api_metrics.snapshot(),
            dependencies=tuple(dependencies),
            outbox=self._status_counts(outbox_rows),
            mail=self._status_counts(mail_rows),
            login={
                "challengesLast24h": int(login_row["challenges"] if login_row else 0),
                "completionsLast24h": int(login_row["completions"] if login_row else 0),
                "failuresLast24h": int(login_row["failures"] if login_row else 0),
            },
            failed_jobs=tuple(
                FailedJob(
                    id=row["id"],
                    event_type=str(row["event_type"]),
                    aggregate_type=str(row["aggregate_type"]),
                    aggregate_id=row["aggregate_id"],
                    attempts=int(row["attempts"]),
                    last_error_code=str(row["last_error_code"] or "unknown_failure"),
                    failed_at=row["dead_lettered_at"],
                    manual_retry_count=int(row["manual_retry_count"]),
                )
                for row in failed_rows
            ),
        )

    async def retry(
        self,
        *,
        event_id: UUID,
        operator_user_id: UUID,
        request_id: str,
    ) -> FailedJob:
        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    UPDATE outbox_event
                    SET status = 'pending',
                        available_at = $2,
                        dead_lettered_at = NULL,
                        claim_token = NULL,
                        claimed_by = NULL,
                        completed_at = NULL,
                        manual_retry_count = manual_retry_count + 1,
                        last_manual_retry_at = $2,
                        last_manual_retry_by = $3
                    WHERE id = $1 AND status = 'dead_letter'
                    RETURNING
                        id, event_type, aggregate_type, aggregate_id, attempts,
                        last_error_code, manual_retry_count
                    """,
                    event_id,
                    now,
                    str(operator_user_id),
                )
                if row is None:
                    raise ValueError(
                        "Nur ein aktuell fehlgeschlagener Job kann erneut gestartet werden."
                    )
                await connection.execute(
                    """
                    INSERT INTO audit_event (
                        id, actor_user_id, event_type, entity_type, entity_id,
                        request_id, payload, occurred_at
                    )
                    VALUES (
                        $1, $2, 'system.outbox.manual_retry',
                        'outbox_event', $3, $4, $5::jsonb, $6
                    )
                    """,
                    uuid4(),
                    operator_user_id,
                    event_id,
                    request_id,
                    json.dumps(
                        {
                            "eventType": str(row["event_type"]),
                            "previousErrorCode": str(
                                row["last_error_code"] or "unknown_failure"
                            ),
                        },
                        separators=(",", ":"),
                    ),
                    now,
                )
        return FailedJob(
            id=row["id"],
            event_type=str(row["event_type"]),
            aggregate_type=str(row["aggregate_type"]),
            aggregate_id=row["aggregate_id"],
            attempts=int(row["attempts"]),
            last_error_code=str(row["last_error_code"] or "unknown_failure"),
            failed_at=now,
            manual_retry_count=int(row["manual_retry_count"]),
        )

    async def _probe(
        self,
        dependency: str,
        url: str,
        *,
        request_id: str,
    ) -> DependencySignal:
        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(
                    url,
                    headers={"X-Request-ID": request_id},
                )
            response.raise_for_status()
            status = "ready"
            error_code = None
        except Exception:
            status = "unavailable"
            error_code = f"{dependency}_unavailable"
        signal = DependencySignal(
            dependency=dependency,
            status=status,
            latency_ms=round((perf_counter() - started) * 1000, 2),
            request_id=request_id,
            error_code=error_code,
        )
        print(
            structured_event(
                "dependency.probed",
                requestId=request_id,
                dependency=dependency,
                status=status,
                latencyMs=signal.latency_ms,
                errorCode=error_code,
            ),
            flush=True,
        )
        return signal

    @staticmethod
    def _status_counts(rows: list[asyncpg.Record]) -> dict[str, int]:
        counts = {
            "pending": 0,
            "processing": 0,
            "completed": 0,
            "deadLetter": 0,
        }
        for row in rows:
            key = "deadLetter" if row["status"] == "dead_letter" else str(row["status"])
            counts[key] = int(row["count"])
        return counts
