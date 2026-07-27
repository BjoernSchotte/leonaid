from leonaid.adapters.operations import ApiMetrics, structured_event


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
