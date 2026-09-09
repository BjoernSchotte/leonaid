"""Internal caller authentication; never replaces Core order-domain validation."""

from __future__ import annotations

import hmac
import re

from starlette.requests import Request

ORDER_PATH = re.compile(r"^/api/v1/public/actions/[^/]+/orders/*$")


def order_proxy_denied(request: Request, *, key: str | None) -> bool:
    if ORDER_PATH.fullmatch(request.url.path) is None:
        return False
    supplied = request.headers.getlist("x-leonaid-order-key")
    if key is None or len(supplied) != 1:
        return True
    candidate = supplied[0]
    if re.fullmatch(r"[0-9a-f]{64}", candidate) is None:
        return True
    return not hmac.compare_digest(candidate, key)
