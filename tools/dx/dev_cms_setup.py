#!/usr/bin/env python3
"""Complete the EmDash setup of the local dev CMS (./leonaid dev-cms).

The pilot leaves this step to the designated System Admin in the browser.
The dev stack signs that seed account in the real way (sign-in mail, code
from the local Mailpit) and posts the setup with its session.

Only for the dev stack: the script connects to the loopback address and
trusts exactly the root certificate of that stack's own Caddy CA. The session
token stays in memory and is never printed.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import ssl
import sys
import time
import urllib.parse
from typing import Any

LOGIN_SUBJECT = "LeonAid-Login"
CODE = re.compile(r"den Code ([0-9]{6}) verwenden")


class Failure(Exception):
    pass


class Edge:
    """The dev proxy on 127.0.0.1, addressed with the admin origin's name."""

    def __init__(self, origin: str, port: int, ca_file: str) -> None:
        parsed = urllib.parse.urlsplit(origin)
        if parsed.scheme != "https" or not parsed.hostname:
            raise Failure(f"the admin origin {origin!r} is no https URL")
        self.origin = f"https://{parsed.netloc}"
        self.host = parsed.netloc
        self.server_name = parsed.hostname
        self.port = port
        self.context = ssl.create_default_context(cafile=ca_file)

    def call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        session: str | None = None,
    ) -> tuple[int, list[str], str]:
        raw = socket.create_connection(("127.0.0.1", self.port), timeout=20)
        connection = http.client.HTTPSConnection(self.host, timeout=20)
        connection.sock = self.context.wrap_socket(
            raw, server_hostname=self.server_name
        )
        headers = {"Host": self.host, "Origin": self.origin}
        if session is not None:
            headers["Cookie"] = "__Host-leonaid_session=" + session
            headers["X-EmDash-Request"] = "1"
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            text = response.read().decode("utf-8", "replace")
            return response.status, response.headers.get_all("Set-Cookie") or [], text
        finally:
            connection.close()

    def expect(self, status: int, method: str, path: str, **options: Any) -> str:
        actual, _, text = self.call(method, path, **options)
        if actual != status:
            raise Failure(f"{method} {path} answered {actual}, expected {status}")
        return text


def login_mails(edge: Edge, email: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"query": f"to:{email} subject:{LOGIN_SUBJECT}"})
    status, _, text = edge.call("GET", f"/mail/api/v1/search?{query}")
    if status != 200:
        raise Failure(
            f"Mailpit answered {status} at /mail/; the dev-mail profile must run"
        )
    return json.loads(text).get("messages") or []


def sign_in(edge: Edge, email: str) -> str:
    before = {message["ID"] for message in login_mails(edge, email)}
    edge.expect(202, "POST", "/api/v1/auth/login", body={"email": email})
    deadline = time.monotonic() + 90
    while True:
        fresh = [m for m in login_mails(edge, email) if m["ID"] not in before]
        if fresh:
            break
        if time.monotonic() > deadline:
            raise Failure(
                f"no sign-in mail for {email}; is the account seeded "
                "('./leonaid seed') and the worker running?"
            )
        time.sleep(1)
    newest = max(fresh, key=lambda message: message.get("Created") or "")
    detail = edge.expect(200, "GET", f"/mail/api/v1/message/{newest['ID']}")
    match = CODE.search(json.loads(detail).get("Text") or "")
    if match is None:
        raise Failure("the sign-in mail carries no code")
    status, cookies, _ = edge.call(
        "POST",
        "/api/v1/auth/login/complete",
        body={"email": email, "code": match.group(1)},
    )
    tokens = [
        cookie.split(";", 1)[0].split("=", 1)[1]
        for cookie in cookies
        if cookie.startswith("__Host-leonaid_session=")
    ]
    if status != 200 or len(tokens) != 1:
        raise Failure(f"the code sign-in answered {status}")
    return tokens[0]


def main() -> int:
    origin, port, ca_file, email = sys.argv[1:5]
    try:
        edge = Edge(origin, int(port), ca_file)
        session = sign_in(edge, email)
        try:
            status, _, _ = edge.call(
                "GET", "/_emdash/api/setup/status", session=session
            )
            if status != 200:
                raise Failure(
                    f"the setup is not open for {email} (status {status}); "
                    "the setup grant must be armed for this System Admin"
                )
            edge.expect(
                200,
                "POST",
                "/_emdash/api/setup",
                session=session,
                body={
                    "title": "LeonAid Dev CMS",
                    "tagline": "",
                    "includeContent": False,
                },
            )
        finally:
            # The session existed for the setup alone.
            edge.call("POST", "/api/v1/auth/logout", session=session)
    except (Failure, OSError, ValueError) as error:
        print(f"dev-cms: ERROR: {error}", file=sys.stderr)
        return 1
    print(f"dev-cms: {email} completed the EmDash setup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
