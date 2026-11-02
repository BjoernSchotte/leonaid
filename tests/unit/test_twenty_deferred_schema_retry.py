import httpx
import pytest

from tools.seed.golden import SeedError, TwentyClient

DEFERRED = {
    "errors": [
        {
            "message": "2 deferred schema action(s) are still running on workspace w",
        }
    ]
}


def client(monkeypatch: pytest.MonkeyPatch, responses: list[dict]) -> TwentyClient:
    for key, value in {
        "TWENTY_BASE_URL": "http://twenty-server:3000",
        "TWENTY_ORIGIN": "http://localhost:3020",
        "TWENTY_BOOTSTRAP_EMAIL": "admin@leonaid.org",
        "TWENTY_BOOTSTRAP_PASSWORD": "0123456789abcdef",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("tools.seed.golden.time.sleep", lambda _: None)
    remaining = list(responses)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Origin"])
        return httpx.Response(200, json=remaining.pop(0))

    result = TwentyClient()
    result.client = httpx.Client(transport=httpx.MockTransport(handler))
    result.seen = seen  # type: ignore[attr-defined]
    return result


def test_graphql_repeats_a_mutation_refused_for_running_deferred_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twenty = client(
        monkeypatch,
        [DEFERRED, DEFERRED, {"data": {"createOneField": {"id": "f"}}}],
    )

    data = twenty.graphql("mutation { createOneField }", {})

    assert data == {"createOneField": {"id": "f"}}
    assert twenty.seen == ["http://localhost:3020"] * 3  # type: ignore[attr-defined]


def test_graphql_stops_repeating_after_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twenty = client(monkeypatch, [DEFERRED, DEFERRED])
    clock = iter([0.0, 0.0, 1000.0])
    monkeypatch.setattr("tools.seed.golden.time.monotonic", lambda: next(clock))

    with pytest.raises(SeedError, match="deferred schema action"):
        twenty.graphql("mutation { createOneField }", {})


def test_graphql_does_not_repeat_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    twenty = client(monkeypatch, [{"errors": [{"message": "Forbidden"}]}])

    with pytest.raises(SeedError, match="Forbidden"):
        twenty.graphql("query { getRoles }", {})
    assert len(twenty.seen) == 1  # type: ignore[attr-defined]
