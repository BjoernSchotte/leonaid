"""Probe the generated Caddyfiles against the host routing table.

Runs inside the proxy test network (tools/proxy/routing-test.sh). Every
upstream answers with its own service name, so each probe proves which
service received a request, with which path, and whether the edge redirected
instead. The expected rows are specs/multi-domain §6.2.
"""

from __future__ import annotations

import http.client
import os
import socket
import ssl
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    host: str
    path: str
    status: int
    # Upstream service and the path it received, or the redirect target.
    expect: str
    method: str = "GET"
    # Response headers that must contain the given text.
    headers: tuple[tuple[str, str], ...] = ()
    # Matched as a substring of the body instead of the exact echo.
    contains: bool = False


PROXY = os.environ.get("ROUTING_PROXY", "proxy")
ADMIN = "app.leonaid.test"
PUBLIC = "leonaid.test"
ALIAS = "www.leonaid.test"
SINGLE = "single.leonaid.test"
PORT = int(os.environ.get("ROUTING_PORT", "443"))
# Redirect targets and Host headers name the port unless it is 443.
S = "" if PORT == 443 else f":{PORT}"

SPLIT: tuple[Probe, ...] = (
    # Admin host: member apps, full API, CMS editor, sign-in pages.
    Probe(ADMIN, "/admin/orders?commitment=1", 200, "web /orders?commitment=1"),
    Probe(ADMIN, "/app/activities", 200, "pwa /activities"),
    Probe(ADMIN, "/admin", 308, "/admin/"),
    Probe(ADMIN, "/app", 308, "/app/"),
    Probe(ADMIN, "/api/v1/me", 200, "api /api/v1/me"),
    Probe(ADMIN, "/api/health/live", 200, "api /health/live"),
    Probe(ADMIN, "/api/v1/public/actions/a/orders", 404, ""),
    Probe(
        ADMIN, "/_emdash/admin/", 200, f"campaign-site /_emdash/admin/ xfh={ADMIN}{S}"
    ),
    Probe(
        ADMIN,
        "/_campaign-assets/a.js",
        200,
        f"campaign-site /_campaign-assets/a.js xfh={ADMIN}{S}",
    ),
    Probe(
        ADMIN, "/login?returnTo=%2Fadmin%2F", 200, "public /login?returnTo=%2Fadmin%2F"
    ),
    Probe(ADMIN, "/invite?token=x", 200, "public /invite?token=x"),
    Probe(ADMIN, "/email-change", 200, "public /email-change"),
    Probe(ADMIN, "/fresh-login", 200, "public /fresh-login"),
    Probe(ADMIN, "/impressum", 200, "public /impressum"),
    Probe(ADMIN, "/datenschutz", 200, "public /datenschutz"),
    Probe(ADMIN, "/_astro/login.css", 200, "public /_astro/login.css"),
    Probe(ADMIN, "/favicon.svg", 200, "public /favicon.svg"),
    Probe(ADMIN, "/favicon.ico", 200, "public /favicon.ico"),
    Probe(ADMIN, "/_actions/createPublicOrder/", 404, "", "POST"),
    Probe(ADMIN, "/", 200, "public /login/start"),
    # Astro form actions run on any page; the admin host refuses them all.
    Probe(ADMIN, "/impressum?_action=createPublicOrder", 404, "", "POST"),
    Probe(ADMIN, "/login?_action=createPublicOrder", 404, "", "POST"),
    Probe(
        ADMIN,
        "/_health",
        200,
        "ready",
        headers=(("Strict-Transport-Security", "includeSubDomains"),),
    ),
    Probe(
        ADMIN,
        "/campaigns/krapfentaxi-2026/",
        308,
        f"https://{PUBLIC}{S}/campaigns/krapfentaxi-2026/",
    ),
    Probe(ADMIN, "/surveys/7?x=1", 308, f"https://{PUBLIC}{S}/surveys/7?x=1"),
    Probe(ADMIN, "/krapfentaxi", 308, f"https://{PUBLIC}{S}/krapfentaxi"),
    Probe(
        ADMIN,
        "/archive/krapfentaxi-2026",
        308,
        f"https://{PUBLIC}{S}/archive/krapfentaxi-2026",
    ),
    # Public host: public pages, campaign pages, public API only.
    Probe(PUBLIC, "/", 200, "public /"),
    Probe(PUBLIC, "/krapfentaxi", 200, "public /krapfentaxi"),
    Probe(PUBLIC, "/surveys/7", 200, "public /surveys/7"),
    Probe(PUBLIC, "/impressum", 200, "public /impressum"),
    Probe(PUBLIC, "/datenschutz", 200, "public /datenschutz"),
    Probe(
        PUBLIC,
        "/_actions/createPublicOrder/",
        200,
        "public /_actions/createPublicOrder/",
        "POST",
    ),
    Probe(
        PUBLIC,
        "/campaigns/krapfentaxi-2026/",
        200,
        f"campaign-site /campaigns/krapfentaxi-2026/ xfh={PUBLIC}{S}",
    ),
    Probe(
        PUBLIC,
        "/_campaign-assets/a.css",
        200,
        f"campaign-site /_campaign-assets/a.css xfh={PUBLIC}{S}",
    ),
    Probe(
        PUBLIC, "/api/v1/public/legal-notice", 200, "api /api/v1/public/legal-notice"
    ),
    Probe(PUBLIC, "/api/health/ready", 200, "api /health/ready"),
    Probe(PUBLIC, "/api/v1/me", 404, ""),
    Probe(PUBLIC, "/api/v1/auth/login-challenges", 404, "", "POST"),
    Probe(PUBLIC, "/api/v1/public/actions/a/orders", 404, "", "POST"),
    Probe(PUBLIC, "/_emdash/admin/", 404, ""),
    Probe(PUBLIC, "/_emdash", 404, ""),
    Probe(PUBLIC, "/admin/orders?x=1", 308, f"https://{ADMIN}{S}/admin/orders?x=1"),
    Probe(PUBLIC, "/admin", 308, f"https://{ADMIN}{S}/admin"),
    Probe(PUBLIC, "/app/", 308, f"https://{ADMIN}{S}/app/"),
    Probe(
        PUBLIC,
        "/login?returnTo=%2Fapp%2F",
        308,
        f"https://{ADMIN}{S}/login?returnTo=%2Fapp%2F",
    ),
    Probe(PUBLIC, "/invite?token=t", 308, f"https://{ADMIN}{S}/invite?token=t"),
    Probe(
        PUBLIC, "/email-change?token=t", 308, f"https://{ADMIN}{S}/email-change?token=t"
    ),
    Probe(PUBLIC, "/fresh-login", 308, f"https://{ADMIN}{S}/fresh-login"),
    Probe(PUBLIC, "/login/start", 308, f"https://{ADMIN}{S}/login/start"),
    # The old PWA worker is replaced, never redirected (§6.7).
    Probe(
        PUBLIC,
        "/app/sw.js",
        200,
        "self.registration.unregister()",
        headers=(("Content-Type", "text/javascript"), ("Cache-Control", "no-store")),
        contains=True,
    ),
    Probe(PUBLIC, "/app/sw.js?v=2", 200, "client.navigate(client.url)", contains=True),
)

# HSTS on the public apex must not cover the club's other subdomains.
NO_SUBDOMAIN_HSTS = ((PUBLIC, "/_health"),)
# Aliases of the public host redirect as a whole, path and query kept. The
# dev split proxy has no aliases.
ALIASES: tuple[Probe, ...] = (
    Probe(ALIAS, "/krapfentaxi?x=1", 308, f"https://{PUBLIC}/krapfentaxi?x=1"),
    Probe(ALIAS, "/campaigns/a/", 308, f"https://{PUBLIC}/campaigns/a/"),
    Probe(ALIAS, "/admin/", 308, f"https://{PUBLIC}/admin/"),
)

# An admin host without a general public host (§6.6, stage 2 needs it).
ADMIN_ONLY: tuple[Probe, ...] = (
    Probe(ADMIN, "/admin/x", 200, "web /x"),
    Probe(ADMIN, "/app/x", 200, "pwa /x"),
    Probe(ADMIN, "/api/v1/me", 200, "api /api/v1/me"),
    Probe(ADMIN, "/_emdash/admin/", 200, f"campaign-site /_emdash/admin/ xfh={ADMIN}"),
    Probe(ADMIN, "/surveys/7", 200, "public /surveys/7"),
    Probe(ADMIN, "/impressum", 200, "public /impressum"),
    Probe(ADMIN, "/krapfentaxi", 200, "public /krapfentaxi"),
    Probe(ADMIN, "/campaigns/a/", 200, "public /campaigns/a/"),
    Probe(ADMIN, "/archive/a", 200, "public /archive/a"),
    Probe(ADMIN, "/_actions/createPublicOrder/", 404, "", "POST"),
    Probe(ADMIN, "/surveys/7?_action=createPublicOrder", 404, "", "POST"),
    Probe(ADMIN, "/", 200, "public /login/start"),
)

SINGLE_HOST: tuple[Probe, ...] = (
    Probe(SINGLE, "/", 200, "public /"),
    Probe(SINGLE, "/login", 200, "public /login"),
    Probe(SINGLE, "/krapfentaxi", 200, "public /krapfentaxi"),
    Probe(SINGLE, "/admin/x", 200, "web /x"),
    Probe(SINGLE, "/app/x", 200, "pwa /x"),
    Probe(SINGLE, "/admin", 308, "/admin/"),
    Probe(SINGLE, "/api/v1/me", 200, "api /api/v1/me"),
    Probe(SINGLE, "/api/v1/public/actions/a/orders", 404, ""),
    Probe(
        SINGLE, "/_emdash/admin/", 200, f"campaign-site /_emdash/admin/ xfh={SINGLE}"
    ),
    Probe(SINGLE, "/campaigns/a/", 200, f"campaign-site /campaigns/a/ xfh={SINGLE}"),
    Probe(
        SINGLE,
        "/_actions/createPublicOrder/",
        200,
        "public /_actions/createPublicOrder/",
        "POST",
    ),
)


def request(probe: Probe) -> tuple[int, str, dict[str, str]]:
    address = socket.gethostbyname(PROXY)
    # Caddy's internal CA of this test proxy (tls internal), never a bypass.
    context = ssl.create_default_context(cafile=os.environ["ROUTING_CA_FILE"])
    connection = http.client.HTTPSConnection(address, PORT, context=context, timeout=10)
    # SNI and Host must name the probed site (strict_sni_host).
    connection.sock = context.wrap_socket(
        socket.create_connection((address, PORT), timeout=10),
        server_hostname=probe.host,
    )
    headers = {"Host": probe.host + S}
    body = b"{}" if probe.method == "POST" else None
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    connection.request(probe.method, probe.path, body=body, headers=headers)
    response = connection.getresponse()
    text = response.read().decode("utf-8", "replace").strip()
    location = response.getheader("Location") or ""
    received = {name.casefold(): value for name, value in response.getheaders()}
    connection.close()
    if 300 <= response.status < 400:
        return response.status, location, received
    return response.status, text if response.status == 200 else "", received


def main() -> int:
    mode = sys.argv[1]
    probes = {
        "split": SPLIT + (ALIASES if PORT == 443 else ()),
        "admin-only": ADMIN_ONLY,
        "single": SINGLE_HOST,
    }[mode]
    failures = []
    for probe in probes:
        status, result, received = request(probe)
        matched = probe.expect in result if probe.contains else result == probe.expect
        if status != probe.status or not matched:
            failures.append(
                f"{probe.method} https://{probe.host}{probe.path}: "
                f"got {status} {result[:200]!r}, want {probe.status} {probe.expect!r}"
            )
        for name, text in probe.headers:
            if text not in received.get(name.casefold(), ""):
                failures.append(
                    f"{probe.method} https://{probe.host}{probe.path}: header "
                    f"{name} lacks {text!r}: {received.get(name.casefold())!r}"
                )
    if mode == "split":
        for host, path in NO_SUBDOMAIN_HSTS + (((ALIAS, "/x"),) if PORT == 443 else ()):
            _, _, received = request(Probe(host, path, 0, ""))
            hsts = received.get("strict-transport-security", "")
            if "max-age=" not in hsts or "includesubdomains" in hsts.casefold():
                failures.append(f"https://{host}{path}: HSTS {hsts!r}")
    for failure in failures:
        print(f"proxy-routing: ERROR: {failure}", file=sys.stderr)
    if failures:
        return 1
    print(
        f"proxy-routing: OK: {len(probes)} {mode} routes match specs/multi-domain §6.2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
