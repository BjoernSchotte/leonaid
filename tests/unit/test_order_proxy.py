from starlette.requests import Request

from leonaid.entrypoints.fastapi.order_proxy import order_proxy_denied

KEY = "a" * 64


def request(path: str, headers: list[tuple[bytes, bytes]]) -> Request:
    return Request(
        {
            "type": "http",
            "scheme": "http",
            "method": "POST",
            "path": path,
            "query_string": b"",
            "headers": headers,
            "server": ("api", 8000),
        }
    )


def test_order_proxy_fails_closed_without_a_single_valid_key() -> None:
    for path in [
        "/api/v1/public/actions/example/orders",
        "/api/v1/public/actions/example/orders/",
    ]:
        for headers in [
            [],
            [(b"x-leonaid-order-key", b"b" * 64)],
            [(b"x-leonaid-order-key", KEY.encode())] * 2,
            [(b"x-leonaid-order-key", b"bad")],
        ]:
            assert order_proxy_denied(request(path, headers), key=KEY)
        valid = request(path, [(b"x-leonaid-order-key", KEY.encode())])
        assert not order_proxy_denied(valid, key=KEY)
        assert order_proxy_denied(valid, key=None)


def test_order_proxy_does_not_intercept_other_core_routes() -> None:
    for path in [
        "/api/v1/platform",
        "/api/v1/public/actions/alias/example",
        "/api/v1/actions/example/commitments",
    ]:
        assert not order_proxy_denied(request(path, []), key=None)
