"""Payload-free Prometheus transport for LeonAid operational signals."""

from __future__ import annotations

from leonaid.application.operations import OperationsSnapshot


def render_operations_metrics(
    snapshot: OperationsSnapshot,
    *,
    maintenance_mode: bool,
) -> str:
    """Render only bounded technical counters and states.

    Request IDs, object IDs, error details and business payloads are
    intentionally excluded from the monitoring contract.
    """

    lines = [
        "# HELP leonaid_api_requests_total Requests handled by this API process.",
        "# TYPE leonaid_api_requests_total counter",
        f"leonaid_api_requests_total {snapshot.api.requests}",
        "# HELP leonaid_api_errors_total HTTP 5xx responses handled by this API process.",
        "# TYPE leonaid_api_errors_total counter",
        f"leonaid_api_errors_total {snapshot.api.errors}",
        "# HELP leonaid_api_average_latency_milliseconds Mean request latency since process start.",
        "# TYPE leonaid_api_average_latency_milliseconds gauge",
        (
            "leonaid_api_average_latency_milliseconds "
            f"{snapshot.api.average_latency_ms:.2f}"
        ),
        "# HELP leonaid_dependency_up Whether a required operational dependency responds.",
        "# TYPE leonaid_dependency_up gauge",
    ]
    for dependency in sorted(snapshot.dependencies, key=lambda item: item.dependency):
        value = 1 if dependency.status == "ready" else 0
        lines.append(
            f'leonaid_dependency_up{{dependency="{dependency.dependency}"}} {value}'
        )

    lines.extend(
        [
            "# HELP leonaid_outbox_jobs Durable jobs by technical state.",
            "# TYPE leonaid_outbox_jobs gauge",
        ]
    )
    for status in ("pending", "processing", "completed", "deadLetter"):
        lines.append(
            f'leonaid_outbox_jobs{{status="{status}"}} {snapshot.outbox[status]}'
        )

    lines.extend(
        [
            "# HELP leonaid_mail_jobs Mail jobs by technical state.",
            "# TYPE leonaid_mail_jobs gauge",
        ]
    )
    for status in ("pending", "processing", "completed", "deadLetter"):
        lines.append(f'leonaid_mail_jobs{{status="{status}"}} {snapshot.mail[status]}')

    lines.extend(
        [
            "# HELP leonaid_login_failures_24h Rejected or expired login challenges in the last 24 hours.",
            "# TYPE leonaid_login_failures_24h gauge",
            (f"leonaid_login_failures_24h {snapshot.login['failuresLast24h']}"),
            "# HELP leonaid_maintenance_mode Whether expected write traffic is paused.",
            "# TYPE leonaid_maintenance_mode gauge",
            f"leonaid_maintenance_mode {1 if maintenance_mode else 0}",
            "",
        ]
    )
    return "\n".join(lines)
