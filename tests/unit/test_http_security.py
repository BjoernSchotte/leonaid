from __future__ import annotations

from starlette.requests import Request

from leonaid.entrypoints.fastapi.security import (
    client_address,
    csrf_violation,
    request_fingerprint,
)

SECRET = "http-security-unit-secret-with-at-least-32-characters"
ORIGINS = ("https://portal.leonaid.invalid",)


def request(
    *,
    method: str = "POST",
    headers: tuple[tuple[bytes, bytes], ...] = (),
    client: tuple[str, int] = ("10.0.0.5", 50000),
) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": "/api/v1/invitations",
            "raw_path": b"/api/v1/invitations",
            "query_string": b"",
            "headers": list(headers),
            "client": client,
            "server": ("api", 8000),
        }
    )


def test_csrf_rejects_foreign_and_cross_site_browser_requests() -> None:
    foreign = request(
        headers=(
            (b"origin", b"https://attacker.invalid"),
            (b"sec-fetch-site", b"cross-site"),
            (b"cookie", b"__Host-leonaid_session=secret-session-token"),
        )
    )
    missing_origin = request(
        headers=(
            (b"sec-fetch-mode", b"cors"),
            (b"cookie", b"__Host-leonaid_session=secret-session-token"),
        )
    )

    assert csrf_violation(foreign, allowed_origins=ORIGINS) == "origin_not_allowed"
    assert csrf_violation(missing_origin, allowed_origins=ORIGINS) == "origin_required"


def test_csrf_allows_same_origin_and_non_browser_service_calls() -> None:
    same_origin = request(
        headers=(
            (b"origin", b"https://portal.leonaid.invalid"),
            (b"sec-fetch-site", b"same-origin"),
            (b"sec-fetch-mode", b"cors"),
            (b"cookie", b"__Host-leonaid_session=secret-session-token"),
        )
    )

    assert csrf_violation(same_origin, allowed_origins=ORIGINS) is None
    assert csrf_violation(request(), allowed_origins=ORIGINS) is None


def test_proxy_address_is_used_only_when_explicitly_trusted() -> None:
    proxied = request(
        headers=((b"x-forwarded-for", b"203.0.113.10, 192.0.2.4"),),
    )

    assert client_address(proxied, trust_proxy_headers=True) == "192.0.2.4"
    assert client_address(proxied, trust_proxy_headers=False) == "10.0.0.5"
    assert request_fingerprint(
        proxied,
        secret=SECRET,
        trust_proxy_headers=True,
    ) != request_fingerprint(
        proxied,
        secret=SECRET,
        trust_proxy_headers=False,
    )
