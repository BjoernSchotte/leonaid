#!/usr/bin/env python3
"""Test-only probe of the installed Twenty's e-mail verification.

Run by tools/pilot_install/test.sh inside the isolated test project, never
against a real installation.

- `verified`: the bootstrap admin is verified and signs in under the
  production setting, and public sign-up of new addresses is closed.
- `refused`: the bootstrap admin, after the test reset its verification flag,
  cannot obtain a login token. This is what blocks a naive first-admin
  bootstrap and why pilot-install verifies the address.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from typing import Any

import httpx

LOGIN = (
    "mutation L($email: String!, $password: String!, $origin: String!) "
    "{ getLoginTokenFromCredentials(email: $email, password: $password, "
    "origin: $origin) { loginToken { token } } }"
)


def graphql(
    client: httpx.Client, query: str, variables: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(
        "/metadata",
        json={"query": query, "variables": variables},
        headers={"Origin": os.environ["TWENTY_ORIGIN"]},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Twenty returned no JSON object")
    return payload


def admin_login(client: httpx.Client) -> dict[str, Any]:
    return graphql(
        client,
        LOGIN,
        {
            "email": os.environ["TWENTY_BOOTSTRAP_EMAIL"],
            "password": os.environ["TWENTY_BOOTSTRAP_PASSWORD"],
            "origin": os.environ["TWENTY_ORIGIN"],
        },
    )


def verified(client: httpx.Client) -> str:
    state = graphql(
        client,
        "query C($email: String!) "
        "{ checkUserExists(email: $email) { exists isEmailVerified } }",
        {"email": os.environ["TWENTY_BOOTSTRAP_EMAIL"]},
    )
    user = (state.get("data") or {}).get("checkUserExists") or {}
    if user != {"exists": True, "isEmailVerified": True}:
        raise AssertionError(f"bootstrap admin state is {user!r}")
    if admin_login(client).get("errors"):
        raise AssertionError("the verified bootstrap admin cannot sign in")
    signup = graphql(
        client,
        "mutation S($email: String!, $password: String!) "
        "{ signUp(email: $email, password: $password) "
        "{ tokens { accessOrWorkspaceAgnosticToken { token } } } }",
        {
            "email": f"stranger-{secrets.token_hex(6)}@leonaid.org",
            "password": secrets.token_hex(16),
        },
    )
    if "SIGNUP_DISABLED" not in json.dumps(signup.get("errors") or []):
        raise AssertionError("public sign-up is open after the installation")
    return "verified bootstrap admin signs in; public sign-up is closed"


def refused(client: httpx.Client) -> str:
    errors = json.dumps(admin_login(client).get("errors") or [])
    if "EMAIL_NOT_VERIFIED" not in errors and "not verified" not in errors:
        raise AssertionError(
            "an unverified admin was not refused for missing verification: "
            + errors[:400]
        )
    return "an unverified admin is refused with EMAIL_NOT_VERIFIED"


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    probes = {"verified": verified, "refused": refused}
    if mode not in probes:
        raise SystemExit("usage: verification_probe.py verified|refused")
    with httpx.Client(base_url=os.environ["TWENTY_BASE_URL"], timeout=60) as client:
        print(f"pilot-install-probe: OK: {probes[mode](client)}")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, httpx.HTTPError, KeyError) as error:
        print(f"pilot-install-probe: FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
