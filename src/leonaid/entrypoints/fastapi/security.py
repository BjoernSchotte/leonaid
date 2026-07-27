"""Browser-origin, proxy and abuse controls at the HTTP trust boundary."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from typing import Final

from fastapi import Request

from leonaid.adapters.postgres.security import (
    AsyncpgSecurityRateLimitRepository,
)
from leonaid.domain.sessions import SESSION_COOKIE_NAME

UNSAFE_METHODS: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    scope: str
    limit: int
    window: timedelta


RATE_LIMITS: Final = {
    ("POST", "/api/v1/auth/login"): RateLimitPolicy(
        "auth.login.request",
        5,
        timedelta(minutes=10),
    ),
    ("POST", "/api/v1/auth/login/complete"): RateLimitPolicy(
        "auth.login.complete",
        10,
        timedelta(minutes=10),
    ),
    ("POST", "/api/v1/auth/fresh"): RateLimitPolicy(
        "auth.fresh.request",
        5,
        timedelta(minutes=10),
    ),
    ("POST", "/api/v1/auth/fresh/complete"): RateLimitPolicy(
        "auth.fresh.complete",
        10,
        timedelta(minutes=10),
    ),
    ("POST", "/api/v1/invitations"): RateLimitPolicy(
        "invitation.create",
        10,
        timedelta(hours=1),
    ),
    ("POST", "/api/v1/invitations/accept"): RateLimitPolicy(
        "invitation.accept",
        10,
        timedelta(minutes=10),
    ),
}


def client_address(request: Request, *, trust_proxy_headers: bool) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    candidates = (
        tuple(part.strip() for part in forwarded.split(",") if part.strip())
        if trust_proxy_headers
        else ()
    )
    raw = (
        candidates[-1]
        if candidates
        else (request.client.host if request.client is not None else "unknown")
    )
    try:
        return str(ip_address(raw))
    except ValueError:
        return "unknown"


def request_fingerprint(
    request: Request,
    *,
    secret: str,
    trust_proxy_headers: bool,
) -> str:
    session = request.cookies.get(SESSION_COOKIE_NAME, "")
    address = client_address(
        request,
        trust_proxy_headers=trust_proxy_headers,
    )
    user_agent = request.headers.get("user-agent", "unknown")[:320]
    material = f"{address}|{user_agent}|{session[:256]}".encode()
    return hmac.new(
        secret.encode(),
        b"leonaid-security-rate:v1:" + material,
        hashlib.sha256,
    ).hexdigest()


def csrf_violation(
    request: Request,
    *,
    allowed_origins: tuple[str, ...],
) -> str | None:
    if request.method not in UNSAFE_METHODS:
        return None
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in allowed_origins:
        return "origin_not_allowed"
    fetch_site = request.headers.get("sec-fetch-site", "").lower()
    if fetch_site == "cross-site":
        return "cross_site_request"
    browser_request = bool(
        request.headers.get("sec-fetch-mode") or request.headers.get("sec-fetch-dest")
    )
    if browser_request and request.cookies.get(SESSION_COOKIE_NAME) and origin is None:
        return "origin_required"
    return None


async def rate_limit_violation(
    request: Request,
    *,
    repository: AsyncpgSecurityRateLimitRepository,
    secret: str,
    trust_proxy_headers: bool,
) -> RateLimitPolicy | None:
    policy = RATE_LIMITS.get((request.method, request.url.path))
    if policy is None:
        return None
    allowed = await repository.consume(
        scope=policy.scope,
        fingerprint_hash=request_fingerprint(
            request,
            secret=secret,
            trust_proxy_headers=trust_proxy_headers,
        ),
        attempted_at=datetime.now(timezone.utc),
        window=policy.window,
        limit=policy.limit,
    )
    return None if allowed else policy
