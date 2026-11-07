#!/usr/bin/env python3
"""Generate every product Caddyfile from one route table.

One installation serves its routes under one host (single-host mode) or
splits them across an admin host and a public host (specs/multi-domain,
stage 1). Both modes, in production (infra/pilot) and in the dev stack
(infra/proxy), are rendered from ROUTES below, so a path can never be routed
differently in one file than in another by accident.

    python3 tools/proxy/caddyfiles.py           # rewrite the files
    python3 tools/proxy/caddyfiles.py --check   # fail on drift (./leonaid check)
    python3 tools/proxy/caddyfiles.py --render pilot-split --tls-internal

Each route lists its action per site role:

    single  the only host of a single-host installation (G4: unchanged)
    admin   the admin host app.<domain> (members, editors, full API)
    public  the general public host <domain> and its aliases
    admin_only  the admin host of an installation without a public host
            (§6.6, needs stage 2: the contract refuses it until then)
    site    every campaign host (stage 2, §7): a catch-all site block with
            on-demand TLS; Core's ask endpoint approves the host first

A role without an entry falls through to the role's catch-all route.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _base_paths() -> dict[str, str]:
    """ADMIN_BASE and PWA_BASE from Core's one source (specs/multi-domain §6.7).

    Read as text: the generator runs on the plain runner Python, without the
    Core dependencies.
    """
    source = (ROOT / "src/leonaid/platform/base_paths.py").read_text(encoding="utf-8")
    values = dict(
        re.findall(r'^(ADMIN_BASE|PWA_BASE): Final = "([^"]+)"$', source, re.M)
    )
    if set(values) != {"ADMIN_BASE", "PWA_BASE"}:
        raise SystemExit(
            "caddyfiles: base paths missing in src/leonaid/platform/base_paths.py"
        )
    return values


ADMIN_BASE = _base_paths()["ADMIN_BASE"]
PWA_BASE = _base_paths()["PWA_BASE"]
# The role-based entry page of apps/public; `/` on the admin host serves it.
ENTRY_PAGE = "/login/start"

ADMIN_ORIGIN = {"pilot": "https://{$LEONAID_ADMIN_DOMAIN}", "dev": ""}
PUBLIC_ORIGIN = {"pilot": "https://{$LEONAID_PUBLIC_DOMAIN}", "dev": ""}
# The dev proxy listens on 8443 inside the container; browsers reach it on the
# host port LEONAID_HTTPS_PORT. Redirects must name the host port.
DEV_PORT = ":{$LEONAID_HTTPS_PORT:8443}"
ADMIN_ORIGIN["dev"] = "https://{$LEONAID_ADMIN_DOMAIN:app.localhost}" + DEV_PORT
PUBLIC_ORIGIN["dev"] = "https://{$LEONAID_PUBLIC_DOMAIN:localhost}" + DEV_PORT

# Action names.
HEALTH = "health"
API_HEALTH = "api_health"
API = "api"
API_NOT_FOUND = "api_not_found"
NOT_FOUND = "not_found"
CMS = "cms"
WEB = "web"
PWA = "pwa"
PUBLIC = "public"
SLASH = "slash"
TO_ADMIN = "to_admin"
TO_PUBLIC = "to_public"
ENTRY = "entry"
CRM = "crm"
MAIL = "mail"
MAILING = "mailing"
LOCAL_IMPORT = "local_import"
# Astro form actions run as POST <any page>?_action=…; refused on admin hosts.
REFUSED_ACTIONS = "refused_actions"
# Self-unregistering service worker for the PWA scope of a public host.
RETIRED_WORKER = "retired_worker"
# Core's internal endpoints (the on-demand TLS ask, §9.1) never leave the
# Docker network.
INTERNAL = ("/internal", "/internal/*", "/api/internal", "/api/internal/*")
# The host check of §7.4 runs over plain HTTP on every name.
HOST_CHECK = "/.well-known/leonaid-host-check/*"
# Served below a path prefix that handle_path strips.
STRIPPED = (WEB, PWA, CRM, MAILING)


@dataclass(frozen=True)
class Route:
    name: str
    paths: tuple[str, ...]
    actions: dict[str, str]
    # Adjacent routes of one group with the same action share one matcher.
    group: str = ""
    # Dev-only routes (CRM, Mailpit, Listmonk, local extensions).
    dev_only: bool = False


def _slashless(base: str) -> str:
    return base.rstrip("/")


MEMBER_PAGES = ("/login", "/login/*", "/invite", "/email-change", "/fresh-login")
# One Impressum and one privacy notice per installation, on every host (D4).
LEGAL_PAGES = ("/impressum", "/datenschutz")
# The sign-in pages on the admin host load these files of the public app.
# A cross-host redirect for a stylesheet or script would violate the CSP
# ('self'), so the admin host serves them itself.
# Browsers also fetch /favicon.ico on their own; a redirect to the public
# host would be a cross-host image the admin CSP blocks.
PUBLIC_APP_ASSETS = (
    "/_astro/*",
    "/favicon.ico",
    "/favicon.svg",
    "/community-routes.png",
    "/community-routes.webp",
)
PUBLIC_ORDER = ("/_actions/createPublicOrder", "/_actions/createPublicOrder/")

ROUTES: tuple[Route, ...] = (
    # Before every handle: an order action never runs on the admin host, also
    # not as POST /impressum?_action=createPublicOrder (§6.2).
    Route(
        "admin_actions",
        (),
        {"admin": REFUSED_ACTIONS, "admin_only": REFUSED_ACTIONS},
    ),
    Route(
        "internal",
        INTERNAL,
        {
            "single": NOT_FOUND,
            "admin": NOT_FOUND,
            "public": NOT_FOUND,
            "admin_only": NOT_FOUND,
            "site": NOT_FOUND,
        },
    ),
    Route(
        "health",
        ("/_health",),
        {
            "single": HEALTH,
            "admin": HEALTH,
            "public": HEALTH,
            "admin_only": HEALTH,
            "site": HEALTH,
        },
    ),
    Route(
        "api_health",
        ("/api/health/*",),
        {
            "single": API_HEALTH,
            "admin": API_HEALTH,
            "public": API_HEALTH,
            "admin_only": API_HEALTH,
            "site": API_HEALTH,
        },
    ),
    # The public host exposes only the public API (forms, surveys, legal
    # notice); the internal order path stays closed on every host.
    Route("api_public", ("/api/v1/public/*",), {"public": API, "site": API}),
    Route(
        "api",
        ("/api/*",),
        {
            "single": API,
            "admin": API,
            "public": API_NOT_FOUND,
            "admin_only": API,
            "site": API_NOT_FOUND,
        },
    ),
    # The CMS editor lives on the admin host only.
    Route(
        "emdash",
        ("/_emdash", "/_emdash/*"),
        {
            "single": CMS,
            "admin": CMS,
            "public": NOT_FOUND,
            "admin_only": CMS,
            "site": NOT_FOUND,
        },
        group="campaign_routes",
    ),
    Route(
        "campaigns",
        ("/campaigns", "/campaigns/*"),
        # Without a public host the public app answers 308 to the campaign
        # host or 404 (stage 2); the admin host never renders campaign pages.
        {
            "single": CMS,
            "admin": TO_PUBLIC,
            "public": CMS,
            "admin_only": PUBLIC,
            "site": CMS,
        },
        group="campaign_routes",
    ),
    # Build assets of the campaign site: campaign pages and the EmDash admin.
    Route(
        "campaign_assets",
        ("/_campaign-assets/*",),
        {"single": CMS, "admin": CMS, "public": CMS, "admin_only": CMS, "site": CMS},
        group="campaign_routes",
    ),
    Route(
        "slashless_service_roots",
        (_slashless(PWA_BASE), _slashless(ADMIN_BASE)),
        {
            "single": SLASH,
            "admin": SLASH,
            "public": TO_ADMIN,
            "admin_only": SLASH,
            "site": TO_ADMIN,
        },
        group="slashless_service_roots",
    ),
    Route(
        "slashless_dev_roots",
        ("/crm", "/mail", "/mailing"),
        {"single": SLASH, "admin": SLASH},
        group="slashless_service_roots",
        dev_only=True,
    ),
    # Browsers never follow a redirect for a service worker script. A device
    # that opened the PWA on the old single host keeps that worker; this one
    # replaces it, unregisters itself and reloads the page, which then 308s to
    # the admin host (§6.7).
    Route("retired_worker", (PWA_BASE + "sw.js",), {"public": RETIRED_WORKER}),
    Route(
        "pwa",
        (PWA_BASE + "*",),
        {
            "single": PWA,
            "admin": PWA,
            "public": TO_ADMIN,
            "admin_only": PWA,
            "site": TO_ADMIN,
        },
        group="member_routes",
    ),
    Route(
        "web",
        (ADMIN_BASE + "*",),
        {
            "single": WEB,
            "admin": WEB,
            "public": TO_ADMIN,
            "admin_only": WEB,
            "site": TO_ADMIN,
        },
        group="member_routes",
    ),
    Route(
        "member_pages",
        MEMBER_PAGES,
        {"admin": PUBLIC, "public": TO_ADMIN, "admin_only": PUBLIC, "site": TO_ADMIN},
        group="member_routes",
    ),
    Route(
        "legal_pages",
        LEGAL_PAGES,
        {"admin": PUBLIC, "admin_only": PUBLIC, "site": PUBLIC},
        group="admin_public_pages",
    ),
    Route(
        "public_app_assets",
        PUBLIC_APP_ASSETS,
        {"admin": PUBLIC, "admin_only": PUBLIC, "site": PUBLIC},
        group="admin_public_pages",
    ),
    # Order forms exist only on site hosts.
    Route(
        "public_order",
        PUBLIC_ORDER,
        {"admin": NOT_FOUND, "admin_only": NOT_FOUND, "site": PUBLIC},
    ),
    # Role-based entry: login, then the view for the member's role (§6.7).
    Route("root", ("/",), {"admin": ENTRY, "admin_only": ENTRY}),
    Route("crm", ("/crm/*",), {"single": CRM, "admin": CRM}, dev_only=True),
    Route("mail", ("/mail/*",), {"single": MAIL, "admin": MAIL}, dev_only=True),
    Route(
        "mailing",
        ("/mailing/*",),
        {"single": MAILING, "admin": MAILING},
        dev_only=True,
    ),
    Route(
        "local_extensions",
        (),
        {"single": LOCAL_IMPORT, "admin": LOCAL_IMPORT},
        dev_only=True,
    ),
    # Everything else: aliases, archive pages, surveys, the home page.
    # Without a public host, surveys, aliases and archive paths stay on the
    # admin host; the public app answers them (stage 2: 308 or 404, §6.6).
    Route(
        "catch_all",
        (),
        {
            "single": PUBLIC,
            "admin": TO_PUBLIC,
            "public": PUBLIC,
            "admin_only": PUBLIC,
            # Host lookup, editions, history and archive rules: the campaign
            # site's host middleware (§7.7.2).
            "site": CMS,
        },
    ),
)

PILOT_GLOBAL = """{
	email {$CADDY_ACME_EMAIL}
	admin off
	# Campaign hosts (specs/multi-domain §7): a certificate only for a host
	# Core approves; Caddy 2.11 has no own rate limit, Core has (§9.1).
	on_demand_tls {
		ask http://api:8000/internal/tls/ask
	}
	servers {
		strict_sni_host on
		# Disabled here, applied per request by body_read_timeouts.
		timeouts {
			read_body_idle -1s
		}
	}
}
"""

PILOT_TEST_GLOBAL = """{
	admin off
	# Campaign hosts (specs/multi-domain §7): a certificate only for a host
	# Core approves; Caddy 2.11 has no own rate limit, Core has (§9.1).
	on_demand_tls {
		ask http://api:8000/internal/tls/ask
	}
	servers {
		strict_sni_host on
		# Disabled here, applied per request by body_read_timeouts.
		timeouts {
			read_body_idle -1s
		}
	}
}
"""

DEV_GLOBAL = """{
	# Campaign hosts (specs/multi-domain §7): a certificate only for a host
	# Core approves; Caddy 2.11 has no own rate limit, Core has (§9.1).
	on_demand_tls {
		ask http://api:8000/internal/tls/ask
	}
	servers {
		strict_sni_host on
		# Disabled here, applied per request by body_read_timeouts.
		timeouts {
			read_body_idle -1s
		}
	}
}
"""

SNIPPETS = """
(common_headers) {
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
		Strict-Transport-Security "max-age=31536000; includeSubDomains"
	}
}

# The general public host is usually the club's apex domain (club.org). HSTS
# with includeSubDomains there would force HTTPS on every *.club.org name of
# the club (webmail, intranet, devices) for a year, so this host omits it.
(public_host_headers) {
	header {
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
		Strict-Transport-Security "max-age=31536000"
	}
}

# Strict Content-Security-Policy without 'unsafe-inline'. The admin web app and
# the PWA are static builds whose scripts and styles are all files, so Caddy
# sends the complete policy for them and for the API.
(leonaid_headers) {
	header {
		Content-Security-Policy "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'; frame-src 'self' https://www.google.com https://maps.google.com; img-src 'self' data: blob:; object-src 'none'; script-src 'self'; style-src 'self'"
		X-Frame-Options DENY
	}
}

# The Astro apps (public pages, campaign site, EmDash admin) send their own
# policy with the same directives plus sha256 hashes of the scripts and styles
# Astro inlines (security.csp in apps/public and apps/campaign-site
# astro.config.mjs). A second Caddy policy would intersect with it and block
# those hashed scripts, so Caddy sets the same strict policy only for responses
# without one (endpoints, redirects, errors). The leading "?" does exactly this.
(astro_headers) {
	header {
		?Content-Security-Policy "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'; frame-src 'self' https://www.google.com https://maps.google.com; img-src 'self' data: blob:; object-src 'none'; script-src 'self'; style-src 'self'"
		X-Frame-Options DENY
	}
}

# Compress only static build assets under fixed build prefixes: scripts,
# styles, SVG and the PWA manifest. HTML pages, API responses (including
# /_emdash/api), source maps and every other dynamic route stay uncompressed
# because they can carry session-bound secrets next to reflected input
# (BREACH). woff2 is already compressed. Prefix and response type must both
# match.
# Inside handle_path /admin/* and /app/* (prefix already stripped).
(spa_asset_encoding) {
	@spa_build_asset path /assets/* /manifest.webmanifest
	encode @spa_build_asset zstd gzip {
		match {
			header Content-Type text/javascript*
			header Content-Type application/javascript*
			header Content-Type text/css*
			header Content-Type image/svg+xml*
			header Content-Type application/manifest+json*
		}
	}
}

# Astro build output of the public app and the campaign site.
(astro_asset_encoding) {
	@astro_build_asset path /_astro/* /_campaign-assets/*
	encode @astro_build_asset zstd gzip {
		match {
			header Content-Type text/javascript*
			header Content-Type application/javascript*
			header Content-Type text/css*
			header Content-Type image/svg+xml*
			header Content-Type application/manifest+json*
		}
	}
}

# A public order whose declared body exceeds 64 KiB. Shared by the rejection
# route and the request body read deadlines below.
(oversized_order_match) {
	method POST
	expression `(path('/_actions/createPublicOrder', '/_actions/createPublicOrder/') || query({'_action': 'createPublicOrder'})) && {http.request.header.Content-Length} != '' && int({http.request.header.Content-Length}) > 65536`
}

# Request body read deadlines. Since Caddy 2.11.7 the server wraps every body
# in its own idle read deadline (read_body_idle, default 1m) and re-arms it
# after the handlers return. That outer deadline overrides any shorter
# route-level one, so a rejected oversized order would keep its connection for
# a minute while net/http drains the declared but never sent body. The global
# options therefore disable the server-wide wrapper, and every site imports
# these bounds instead: 1s for an oversized order (bounded post-response
# drain), the upstream 1m idle default for every other request (slowloris
# mitigation). The two matchers are disjoint, so only one deadline applies.
(body_read_timeouts) {
	@oversized_order_body {
		import oversized_order_match
	}
	@regular_body {
		not {
			import oversized_order_match
		}
	}
	timeouts @oversized_order_body {
		read_timeout 1s
	}
	timeouts @regular_body {
		read_timeout 1m
	}
}

(order_declared_body_limit) {
	@oversized_order {
		import oversized_order_match
	}
	route @oversized_order {
		# Reject before a proxy request-body reader is started. body_read_timeouts
		# bounds the HTTP/1 server's post-response drain of this request to 1s.
		header Cache-Control no-store
		respond "Das Bestellformular ist zu groß. Diese Anfrage wurde nicht an die Bestellverarbeitung weitergeleitet." 413 {
			close
		}
	}
}
"""

HEADER = """# GENERATED by tools/proxy/caddyfiles.py from its route table. Do not edit;
# change the table and run `python3 tools/proxy/caddyfiles.py`.
"""


@dataclass
class Target:
    """One rendered Caddyfile."""

    environment: str  # pilot | dev
    mode: str  # single | split
    tls_internal: bool = False
    lines: list[str] = field(default_factory=list)


def _indent(text: str, depth: int) -> list[str]:
    prefix = "\t" * depth
    return [prefix + line if line else "" for line in text.splitlines()]


def _api_proxy(environment: str) -> str:
    if environment == "dev":
        return "reverse_proxy api:8000 {\n\theader_up X-Forwarded-For {remote_host}\n}"
    return "reverse_proxy api:8000"


def _action_body(action: str, environment: str, paths: tuple[str, ...]) -> str:
    admin = ADMIN_ORIGIN[environment]
    public = PUBLIC_ORIGIN[environment]
    if action == HEALTH:
        return 'respond "ready" 200'
    if action == API_HEALTH:
        return "import leonaid_headers\nuri strip_prefix /api\n" + _api_proxy(
            environment
        )
    if action == API:
        comment = (
            "# This Core mutation is internal-only; Astro remains the public transport."
            if environment == "dev"
            else "# Explicit order prevents the generic API proxy from exposing orders."
        )
        inner = (
            "@internal_orders path /api/v1/public/actions/*/orders /api/v1/public/actions/*/orders/*\n"
            "header @internal_orders Cache-Control no-store\n"
            'respond @internal_orders "Not Found" 404\n' + _api_proxy(environment)
        )
        return (
            "import leonaid_headers\n"
            + comment
            + "\nroute {\n"
            + "\n".join(_indent(inner, 1))
            + "\n}"
        )
    if action == API_NOT_FOUND:
        return 'import leonaid_headers\nheader Cache-Control no-store\nrespond "Not Found" 404'
    if action == NOT_FOUND:
        return 'import astro_headers\nheader Cache-Control no-store\nrespond "Not Found" 404'
    if action == CMS:
        return """import astro_headers
import astro_asset_encoding
import order_declared_body_limit
reverse_proxy campaign-site:3000 {
	# Do not drain a stalled/rejected HTTP/1 body before returning its error.
	# This affects only CMS body-limit responses, not other applications.
	@body_rejected status 408 413
	handle_response @body_rejected {
		header Connection close
		copy_response
	}
	# common_headers supplies one unambiguous nosniff value at the edge.
	header_down -X-Content-Type-Options
	header_up -Forwarded
	header_up X-Forwarded-For {remote_host}
	header_up X-Forwarded-Host {hostport}
	header_up X-Forwarded-Proto {scheme}
}"""
    if action in (WEB, PWA):
        upstream = "web:3000" if action == WEB else "pwa:3000"
        return (
            "import leonaid_headers\nimport spa_asset_encoding\nreverse_proxy "
            + upstream
        )
    if action == PUBLIC:
        return """import astro_headers
import astro_asset_encoding
import order_declared_body_limit
reverse_proxy public:3000 {
	@body_rejected status 408 413
	handle_response @body_rejected {
		header Connection close
		copy_response
	}
}"""
    if action == TO_ADMIN:
        return f"redir {admin}{{uri}} 308"
    if action == TO_PUBLIC:
        return f"redir {public}{{uri}} 308"
    if action == ENTRY:
        # Role-based entry (§6.7): the public app asks Core for the session
        # and answers 302 to /login or to the member's landingPath.
        return f"rewrite * {ENTRY_PAGE}\n" + _action_body(PUBLIC, environment, paths)
    if action == RETIRED_WORKER:
        # No braces: Caddy would read them as placeholders. matchAll() lists
        # the window clients by default.
        script = (
            'self.addEventListener("install", () => self.skipWaiting()); '
            'self.addEventListener("activate", (event) => event.waitUntil('
            "self.registration.unregister().then(() => self.clients.matchAll())"
            ".then((clients) => Promise.all("
            "clients.map((client) => client.navigate(client.url))))));"
        )
        return (
            'header Content-Type "text/javascript; charset=utf-8"\n'
            "header Cache-Control no-store\n"
            f"respond `{script}` 200"
        )
    if action == CRM:
        return "reverse_proxy twenty-server:3000"
    if action == MAIL:
        return "reverse_proxy mailpit:8025"
    if action == MAILING:
        return "reverse_proxy listmonk:9000"
    raise ValueError(f"unknown action {action} for {paths}")


def _routes(environment: str) -> list[Route]:
    return [route for route in ROUTES if environment == "dev" or not route.dev_only]


def _site_routes(role: str, environment: str) -> list[str]:
    """The handle blocks of one site role, in table order."""
    out: list[str] = []
    pending: list[Route] = []
    # Matcher names must be unique within a site block.
    used: set[str] = set()

    def flush() -> None:
        if not pending:
            return
        action = pending[0].actions[role]
        paths = tuple(path for route in pending for path in route.paths)
        name = pending[0].group or pending[0].name
        if name in used:
            name = pending[0].name
        if action == SLASH or len(paths) > 1 and action not in STRIPPED:
            used.add(name)
        if action == SLASH:
            out.append(f"\t@{name} path {' '.join(paths)}")
            out.append(f"\tredir @{name} {{path}}/ 308")
        elif action == REFUSED_ACTIONS:
            # rewrite runs before every handle, so no page route can win.
            out.extend(
                [
                    "\t@admin_actions query _action=*",
                    "\trewrite @admin_actions /_leonaid/refused-action",
                    "\thandle /_leonaid/refused-action {",
                    "\t\timport astro_headers",
                    "\t\theader Cache-Control no-store",
                    '\t\trespond "Not Found" 404',
                    "\t}",
                ]
            )
        elif action == LOCAL_IMPORT:
            out.extend(
                _indent(
                    "# Local development extensions (docs: infra/compose/README.md). The dev-local\n"
                    "# overlay mounts .local/dev/caddy.d here read-only; every other stack has no\n"
                    "# such directory, and a glob without matches imports nothing.\n"
                    "import /etc/caddy/local.d/*.caddy",
                    1,
                )
            )
        else:
            body = _indent(_action_body(action, environment, paths), 2)
            if action == CMS and pending[0].group == "campaign_routes":
                out.append(
                    "\t# Preserve CMS paths. The service is optional and cannot block proxy startup."
                )
            if not paths:
                out.append("\thandle {")
            elif action in STRIPPED:
                out.append(f"\thandle_path {paths[0]} {{")
            elif len(paths) == 1:
                out.append(f"\thandle {paths[0]} {{")
            else:
                out.append(f"\t@{name} path {' '.join(paths)}")
                out.append(f"\thandle @{name} {{")
            out.extend(body)
            out.append("\t}")
        out.append("")
        pending.clear()

    for route in _routes(environment):
        action = route.actions.get(role)
        if action is None:
            continue
        mergeable = (
            pending
            and route.group
            and pending[0].group == route.group
            and pending[0].actions[role] == action
            # handle_path strips one prefix; never merge it.
            and action not in STRIPPED
            and route.paths
        )
        if not mergeable:
            flush()
        pending.append(route)
    flush()
    while out and out[-1] == "":
        out.pop()
    return out


def _site(addresses: str, role: str, target: Target, extra: list[str]) -> list[str]:
    lines = [f"{addresses} {{", "\timport body_read_timeouts"]
    if role == "site":
        lines += (
            ["\ttls internal {", "\t\ton_demand", "\t}"]
            if target.tls_internal
            else ["\ttls {", "\t\ton_demand", "\t}"]
        )
    elif target.tls_internal:
        lines.append("\ttls internal")
    lines.append(
        "\timport public_host_headers"
        if role == "public"
        else "\timport common_headers"
    )
    lines.append("")
    lines.extend(extra)
    routes = _site_routes(role, target.environment)
    if role == "site" and target.mode == "single":
        # One host: member pages of a campaign host go to that host.
        admin = ADMIN_ORIGIN[target.environment]
        routes = [
            line.replace(admin, PUBLIC_ORIGIN[target.environment]) for line in routes
        ]
    lines.extend(routes)
    lines.append("}")
    return lines


HTTP_PILOT_BODY = """	import body_read_timeouts
	handle /.well-known/leonaid-host-check/* {
		import leonaid_headers
		reverse_proxy api:8000
	}
	@internal_orders path /api/v1/public/actions/*/orders /api/v1/public/actions/*/orders/*
	handle @internal_orders {
		header Cache-Control no-store
		respond "Not Found" 404
	}
	handle /_health {
		respond "ready" 200
	}
	handle {
		redir https://{host}{uri} 308
	}
}

# Every other name, campaign hosts included: the host check of
# specs/multi-domain §7.4 (Caddy answers ACME HTTP-01 itself), else HTTPS.
:80 {
	import body_read_timeouts
	handle /.well-known/leonaid-host-check/* {
		import leonaid_headers
		reverse_proxy api:8000
	}
	handle /_health {
		respond "ready" 200
	}
	handle {
		redir https://{host}{uri} permanent
	}
}
"""


SITE_COMMENT = [
    "",
    "# Campaign hosts (specs/multi-domain §7): every other name Core approved.",
    "# Unknown names get no certificate; the TLS handshake fails.",
]


def _pilot(target: Target) -> list[str]:
    lines = (PILOT_TEST_GLOBAL if target.tls_internal else PILOT_GLOBAL).splitlines()
    lines += SNIPPETS.splitlines()
    lines.append("")
    lines.append(
        "# A host-specific HTTP route precedes Caddy's automatic HTTPS redirect."
    )
    if target.mode == "single":
        lines.append("http://{$LEONAID_PUBLIC_DOMAIN} {")
        lines += HTTP_PILOT_BODY.splitlines()
        lines.append("")
        lines += _site("{$LEONAID_PUBLIC_DOMAIN}", "single", target, [])
        lines += SITE_COMMENT
        lines += _site("https://", "site", target, [])
        return lines
    if target.mode == "admin-only":
        lines.append("http://{$LEONAID_ADMIN_DOMAIN} {")
        lines += HTTP_PILOT_BODY.splitlines()
        lines.append("")
        lines.append(
            "# Admin host without a general public host (specs/multi-domain §6.6)."
        )
        lines += _site("{$LEONAID_ADMIN_DOMAIN}", "admin_only", target, [])
        lines += SITE_COMMENT
        lines += _site("https://", "site", target, [])
        return lines
    lines.append("http://{$LEONAID_ADMIN_DOMAIN}, http://{$LEONAID_PUBLIC_DOMAIN} {")
    lines += HTTP_PILOT_BODY.splitlines()
    lines.append("")
    lines.append(
        "# Admin host (specs/multi-domain §6.2): members, editors and the full API."
    )
    lines += _site("{$LEONAID_ADMIN_DOMAIN}", "admin", target, [])
    lines.append("")
    lines.append(
        "# Public host plus LEONAID_PUBLIC_DOMAIN_ALIASES (comma-separated, may be"
    )
    lines.append(
        "# empty). Caddy substitutes both before parsing, so the aliases join this"
    )
    lines.append(
        "# address list; each alias answers 308 to the public host, path kept."
    )
    alias = [
        "\t@public_alias not host {$LEONAID_PUBLIC_DOMAIN}",
        "\tredir @public_alias https://{$LEONAID_PUBLIC_DOMAIN}{uri} 308",
        "",
    ]
    lines += _site(
        "{$LEONAID_PUBLIC_DOMAIN} {$LEONAID_PUBLIC_DOMAIN_ALIASES}",
        "public",
        target,
        alias,
    )
    lines += SITE_COMMENT
    lines += _site("https://", "site", target, [])
    return lines


DEV_TWENTY = """http://crm.localhost:8080 {
	import body_read_timeouts
	import common_headers
	reverse_proxy twenty-server:3000
}
"""

DEV_SINGLE_ADDRESSES = (
    "https://proxy:8443, https://localhost:8443, "
    "https://{$LEONAID_LAN_HOST:127.0.0.1}:8443, "
    "https://{$LEONAID_REMOTE_HOST:127.0.0.1}:8443"
)


def _dev(target: Target) -> list[str]:
    lines = DEV_GLOBAL.splitlines() + SNIPPETS.splitlines()
    lines.append("")
    if target.mode == "single":
        # Shared by the HTTP diagnostics listener and the HTTPS names.
        body = _site_routes("single", "dev")
        lines.append("(leonaid_routes) {")
        lines += body
        lines.append("}")
        lines.append("")
        lines += DEV_TWENTY.splitlines()
        lines.append("")
        lines += [
            "http://:8080 {",
            "\timport body_read_timeouts",
            "\timport common_headers",
            "\thandle /.well-known/leonaid-host-check/* {",
            "\t\treverse_proxy api:8000",
            "\t}",
            "\t@cms_https path /_emdash /_emdash/* /campaigns /campaigns/* /_campaign-assets/*",
            "\thandle @cms_https {",
            "\t\tredir https://localhost:{$LEONAID_HTTPS_PORT:8443}{uri} 308",
            "\t}",
            "\timport leonaid_routes",
            "}",
            "",
            f"{DEV_SINGLE_ADDRESSES} {{",
            "\timport body_read_timeouts",
            "\ttls internal",
            "\timport common_headers",
            "\timport leonaid_routes",
            "}",
        ]
        lines += SITE_COMMENT
        lines += _site("https://:8443", "site", Target("dev", "single", True), [])
        return lines
    lines += DEV_TWENTY.splitlines()
    lines.append("")
    lines += [
        "# HTTP serves only the health check; everything else moves to HTTPS on",
        "# the same name, because the hosts are told apart by name.",
        "http://:8080 {",
        "\timport body_read_timeouts",
        "\timport common_headers",
        "\thandle /.well-known/leonaid-host-check/* {",
        "\t\treverse_proxy api:8000",
        "\t}",
        "\thandle /_health {",
        '\t\trespond "ready" 200',
        "\t}",
        "\thandle {",
        "\t\tredir https://{host}" + DEV_PORT + "{uri} 308",
        "\t}",
        "}",
        "",
        "# Admin host. `proxy` stays an admin name for in-network tests and the",
        "# healthcheck.",
    ]
    lines += _site(
        "https://{$LEONAID_ADMIN_DOMAIN:app.localhost}:8443, https://proxy:8443",
        "admin",
        target,
        [],
    )
    lines.append("")
    lines.append("# Public host (aliases are a production feature).")
    lines += _site(
        "https://{$LEONAID_PUBLIC_DOMAIN:localhost}:8443", "public", target, []
    )
    lines += SITE_COMMENT
    lines += _site("https://:8443", "site", target, [])
    return lines


TARGETS = {
    "pilot-single": ("infra/pilot/Caddyfile", Target("pilot", "single")),
    "pilot-split": ("infra/pilot/Caddyfile.split", Target("pilot", "split")),
    "pilot-admin-only": (
        "infra/pilot/Caddyfile.admin-only",
        Target("pilot", "admin-only"),
    ),
    "dev-single": ("infra/proxy/Caddyfile", Target("dev", "single")),
    "dev-split": ("infra/proxy/Caddyfile.split", Target("dev", "split", True)),
}


def render(name: str, *, tls_internal: bool = False) -> str:
    _, template = TARGETS[name]
    target = Target(
        template.environment, template.mode, template.tls_internal or tls_internal
    )
    lines = _pilot(target) if target.environment == "pilot" else _dev(target)
    return HEADER + "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--render", choices=sorted(TARGETS))
    parser.add_argument("--tls-internal", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.render:
        sys.stdout.write(render(arguments.render, tls_internal=arguments.tls_internal))
        return 0
    drift = []
    for name, (relative, _) in TARGETS.items():
        path = arguments.root / relative
        expected = render(name)
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == expected:
            continue
        if arguments.check:
            drift.append(relative)
        else:
            path.write_text(expected, encoding="utf-8")
            print(f"caddyfiles: wrote {relative}")
    if drift:
        for relative in drift:
            print(
                f"caddyfiles: ERROR: {relative} differs from the route table; "
                "run python3 tools/proxy/caddyfiles.py",
                file=sys.stderr,
            )
        return 1
    if arguments.check:
        print(f"caddyfiles: OK: {len(TARGETS)} Caddyfiles match the route table")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
