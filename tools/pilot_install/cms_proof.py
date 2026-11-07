#!/usr/bin/env python3
"""Drive the provisioned pilot CMS through the real edge (pilot-cms-provision proof).

Runs in the network namespace of the isolated pilot proxy and trusts only that
project's own Caddy CA. The Core session token arrives in CMS_PROOF_SESSION,
never on the command line, and is never printed.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import sys
from typing import Any

HOST = os.environ["CMS_PROOF_HOST"]
CA_FILE = os.environ["CMS_PROOF_CA_FILE"]
ORIGIN = f"https://{HOST}"
CONTENT = "/_emdash/api/content/campaign_pages"


class EdgeConnection(http.client.HTTPSConnection):
    """HTTPS to the local proxy with the public host name as SNI and Host."""

    def connect(self) -> None:
        raw = socket.create_connection(("127.0.0.1", 443), timeout=15)
        context = ssl.create_default_context(cafile=CA_FILE)
        self.sock = context.wrap_socket(raw, server_hostname=HOST)


def call(
    method: str,
    path: str,
    *,
    session: bool = True,
    body: dict[str, Any] | None = None,
    raw: bytes | None = None,
) -> tuple[int, dict[str, str], str]:
    headers = {"Host": HOST, "Origin": ORIGIN}
    if session:
        headers["Cookie"] = "__Host-leonaid_session=" + os.environ["CMS_PROOF_SESSION"]
        headers["X-EmDash-Request"] = "1"
    payload = raw
    if body is not None:
        payload = json.dumps(body).encode()
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection = EdgeConnection(HOST, 443, timeout=15)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8", "replace")
        return (
            response.status,
            {key.lower(): value for key, value in response.getheaders()},
            text,
        )
    finally:
        connection.close()


def expect(status: int, method: str, path: str, **options: Any) -> str:
    actual, _, text = call(method, path, **options)
    if actual != status:
        raise SystemExit(
            f"cms-proof: ERROR: {method} {path} answered {actual}, expected {status}"
        )
    return text


def main() -> int:
    mode = sys.argv[1]
    if mode == "setup-closed":
        # Before the grant the setup stays closed, even for a System Admin.
        expect(503, "GET", "/_emdash/api/setup/status")
        print("cms-proof: setup is closed without a grant")
    elif mode == "setup":
        expect(401, "GET", "/_emdash/api/setup/status", session=False)
        expect(200, "GET", "/_emdash/api/setup/status")
        expect(
            200,
            "POST",
            "/_emdash/api/setup",
            body={"title": "Pilot CMS", "tagline": "", "includeContent": False},
        )
        # The grant is consumed: a second setup is refused.
        expect(503, "POST", "/_emdash/api/setup", body={"title": "again"})
        print("cms-proof: the designated System Admin completed the EmDash setup")
    elif mode == "setup-refused":
        # A setup request EmDash rejects (malformed body) must not use up the
        # grant: the status stays reachable for the designated System Admin.
        status, _, _ = call("POST", "/_emdash/api/setup", raw=b"{")
        # 503 is the gate's own denial; any other error is EmDash's refusal.
        if not 400 <= status < 600 or status == 503:
            raise SystemExit(
                f"cms-proof: ERROR: a malformed setup answered {status}"
            )
        expect(200, "GET", "/_emdash/api/setup/status")
        print("cms-proof: a refused setup request kept the grant")
    elif mode == "publish":
        action_id, slug, title = sys.argv[2:5]
        # Before the page exists the public route has nothing to show.
        expect(404, "GET", f"/campaigns/{slug}/", session=False)
        created = json.loads(
            expect(
                201,
                "POST",
                CONTENT,
                body={"data": {"action_id": action_id, "title": title}},
            )
        )["data"]["item"]
        if created["status"] != "draft":
            raise SystemExit("cms-proof: ERROR: a new page is not a draft")
        expect(200, "POST", f"{CONTENT}/{created['id']}/publish")
        item = json.loads(expect(200, "GET", f"{CONTENT}/{created['id']}"))["data"][
            "item"
        ]
        if item["status"] != "published" or not item["liveRevisionId"]:
            raise SystemExit("cms-proof: ERROR: the page was not published")
        print("cms-proof: campaign page created and published in the editor")
    elif mode == "public":
        slug, title = sys.argv[2:4]
        status, headers, text = call("GET", f"/campaigns/{slug}/", session=False)
        if status != 200 or title not in text:
            raise SystemExit(
                f"cms-proof: ERROR: the public campaign page answered {status}"
            )
        if f"{ORIGIN}/campaigns/{slug}/" not in text:
            raise SystemExit("cms-proof: ERROR: the page has no canonical URL")
        if "content-security-policy" not in headers:
            raise SystemExit("cms-proof: ERROR: the public page has no CSP")
        print(f"cms-proof: {ORIGIN}/campaigns/{slug}/ serves the published page")
    else:
        raise SystemExit("cms-proof: ERROR: unknown mode")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
