from datetime import datetime, timezone

from leonaid.adapters.operations import ApiMetrics, structured_event
from leonaid.application.operations import (
    ApiMetricSnapshot,
    DependencySignal,
    MonitoringSnapshot,
    OperationsSnapshot,
)
from leonaid.entrypoints.fastapi.prometheus import render_operations_metrics


def test_api_metrics_count_server_errors_and_average_real_values() -> None:
    metrics = ApiMetrics()
    metrics.record(status_code=200, latency_ms=10.0)
    metrics.record(status_code=503, latency_ms=30.0)

    snapshot = metrics.snapshot()

    assert snapshot.requests == 2
    assert snapshot.errors == 1
    assert snapshot.average_latency_ms == 20.0


def test_structured_event_contains_only_explicit_safe_fields() -> None:
    rendered = structured_event(
        "http.request.completed",
        requestId="poc114-browser-correlation",
        method="GET",
        path="/api/v1/admin/operations",
        statusCode=200,
    )

    assert '"requestId":"poc114-browser-correlation"' in rendered
    assert '"path":"/api/v1/admin/operations"' in rendered
    assert "token" not in rendered.casefold()
    assert "document" not in rendered.casefold()


def test_prometheus_metrics_are_bounded_and_payload_free() -> None:
    snapshot = OperationsSnapshot(
        generated_at=datetime.now(timezone.utc),
        request_id="pilot-alerting-request-id",
        api=ApiMetricSnapshot(
            requests=21,
            errors=2,
            average_latency_ms=12.5,
        ),
        dependencies=(
            DependencySignal(
                dependency="worker",
                status="ready",
                latency_ms=2.0,
                request_id="pilot-alerting-request-id",
                error_code=None,
            ),
            DependencySignal(
                dependency="mail",
                status="unavailable",
                latency_ms=3.0,
                request_id="pilot-alerting-request-id",
                error_code="mail_unavailable",
            ),
        ),
        outbox={
            "pending": 3,
            "processing": 1,
            "completed": 8,
            "deadLetter": 2,
        },
        mail={
            "pending": 1,
            "processing": 0,
            "completed": 5,
            "deadLetter": 1,
        },
        login={
            "challengesLast24h": 7,
            "completionsLast24h": 6,
            "failuresLast24h": 1,
        },
        failed_jobs=(),
        monitoring=MonitoringSnapshot(
            status="inactive",
            checks=(),
            active_alerts=(),
        ),
    )

    rendered = render_operations_metrics(snapshot, maintenance_mode=True)

    assert 'leonaid_dependency_up{dependency="mail"} 0' in rendered
    assert 'leonaid_dependency_up{dependency="worker"} 1' in rendered
    assert 'leonaid_outbox_jobs{status="deadLetter"} 2' in rendered
    assert "leonaid_login_failures_24h 1" in rendered
    assert "leonaid_maintenance_mode 1" in rendered
    assert "pilot-alerting-request-id" not in rendered
    assert "mail_unavailable" not in rendered
