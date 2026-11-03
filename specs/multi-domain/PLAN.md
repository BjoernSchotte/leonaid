# Multiple domains — admin host, public host, campaign hosts

Status: 2026-11-03. Specification and feasibility spike. Nothing in this
document is implemented. Implementation needs Björn's answers to
[§13](#13-open-questions-for-björn) and a separate go.

## 1. Context

Today one installation serves everything under one host,
`LEONAID_PUBLIC_DOMAIN` (`infra/proxy/Caddyfile`, `infra/pilot/Caddyfile`):

| Path                               | Upstream                        | Audience               |
| ---------------------------------- | ------------------------------- | ---------------------- |
| `/admin/*`                         | `web` (admin SPA)               | members                |
| `/app/*`                           | `pwa` (acquisition PWA)         | members                |
| `/api/*`                           | `api` (Core, FastAPI)           | members and public     |
| `/_emdash/*`                       | `campaign-site` (EmDash admin)  | campaign editors       |
| `/campaigns/*`, `/_campaign-assets/*` | `campaign-site` (microsites) | public                 |
| `/login`, `/invite`, `/email-change`, `/fresh-login` | `public` (Astro) | members        |
| `/surveys/*`                       | `public`                        | survey respondents     |
| `/<alias>`, `/archive/<slug>`, `/` | `public`                        | public                 |

Campaign aliases are paths (`public_action_alias`, migrations 0027–0029;
`src/leonaid/application/campaign_aliases.py`; `PublicActionAlias` in
`src/leonaid/domain/actions.py`). A published CMS campaign has the canonical
path `/campaigns/<archive-slug>/`; aliases redirect there
(`apps/public/src/lib/campaign-redirect.ts`). `LEONAID_REMOTE_HOST` and
`LEONAID_LAN_HOST` are development-only second names for the same site.

The club wants, later:

- **A** — `backend.domain.org` for administration (`/admin`, `/app`, full
  `/api`, CMS admin) and `domain.org` for all public campaign pages, path-based
  as today.
- **B** — `backend.domain.org` plus one host per campaign:
  `weihnachtsmarkt.domain.org` (subdomain), `krapfentaxi.org` and
  `lions-open.de` (own registered domains).

## 2. Goals

1. G1: Separate the member/administration surface from the public surface by
   host (stage 1, target A).
2. G2: Serve a campaign at the root of its own host, subdomain or own domain
   (stage 2, target B), managed in the admin UI like aliases, without editing
   Caddy files or restarting containers for each new host.
3. G3: Keep one installation, one Caddy, one release image per service, one
   8 GB VPS. Hosts are configuration and data, not builds.
4. G4: Keep today's single-host installation working unchanged when no extra
   host is configured.
5. G5: Correct absolute URLs per host: canonical, Open Graph, sitemap, mail
   links.
6. G6: No new attack surface on the administration host from public hosts:
   sessions, CSRF and CORS stay bound to the admin origin.

## 3. Non-goals

- Several clubs (tenants) in one installation. One club per install stays.
- Different legal entities per domain. All hosts belong to the same club;
  one Impressum and one privacy notice per installation (see Q4).
- DNS management by LeonAid (no registrar or DNS provider API). The club
  points DNS records itself.
- Wildcard certificates or DNS-01 challenges. HTTP-01/TLS-ALPN-01 only.
- Per-host EmDash admin. The CMS editor stays on the admin host.
- Per-campaign mail sender domains (SPF/DKIM per domain). Mail keeps the
  existing sender identity (`infra/pilot/MAIL-RUNBOOK.md`).
- A CDN or a second VPS.

## 4. Terms

| Term          | Meaning                                                                                       |
| ------------- | --------------------------------------------------------------------------------------------- |
| admin host    | Host for members and editors. Today's only host when nothing else is configured.            |
| public host   | Host for the club's public pages and path-based campaigns (`domain.org`). Optional.         |
| campaign host | A host bound to exactly one action; the campaign page is served at `/`. Optional, stage 2.  |
| site host     | Public host or campaign host (any host that serves public pages).                            |

## 5. Summary of the decision

- **Spike verdict: EmDash 1.4 multi-host works with listed patches** (§12).
  EmDash itself is not the obstacle: LeonAid renders campaign pages in its
  own Astro route and uses EmDash only as content store and editor. The
  blockers are four LeonAid-owned single-host assumptions, each a small,
  local change. With a 73-line throwaway patch, one unchanged EmDash 1.4.0
  build served the published Krapfentaxi campaign at `https://krapfentaxi.test/`
  and path-based at `https://club.test/campaigns/krapfentaxi-2026/`, with
  per-host canonical and Open Graph URLs, a real browser order POST with and
  without JavaScript, no CSP violations, and the EmDash admin still bound
  to the admin host.
- Stage 1 (admin host + public host) is configuration plus small code
  changes. Stage 2 (campaign hosts) adds a `site_host` table, an admin UI,
  host resolution in the campaign site, Caddy on-demand TLS with a LeonAid
  `ask` endpoint, and per-host SEO.
- The host → campaign mapping lives in Core. Caddy holds no per-campaign
  configuration; it never needs a reload for a new host.

## 6. Stage 1 — admin host and public host (target A)

### 6.1 Configuration

| Variable                  | Today                                 | Stage 1                                                                                                                               |
| ------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `LEONAID_PUBLIC_DOMAIN`   | the only host                         | unchanged meaning when `LEONAID_ADMIN_DOMAIN` is empty (single-host mode, G4)                                                          |
| `LEONAID_ADMIN_DOMAIN`    | —                                     | new, optional. When set, admin surface moves here and `LEONAID_PUBLIC_DOMAIN` becomes the public host                                 |
| `LEONAID_PUBLIC_BASE_URL` | mail links (login, invite, surveys)   | renamed in meaning to the **admin** base URL for member mails; a new `LEONAID_SITE_BASE_URL` for public links (survey invitations)    |
| `LEONAID_ALLOWED_ORIGINS` | credentialed CORS/CSRF origins        | admin origin only. New `LEONAID_PUBLIC_ORIGINS`: origins allowed for `/api/v1/public/*` without credentials                           |
| `EMDASH_SITE_URL`         | site origin, pinned by `hasSecurePublicOrigin` | admin origin (CMS editor, sign-in links). Public campaign routes accept the site hosts instead (§6.4)                        |

The installer (`infra/pilot/production.env.example`, `tools/pilot_install`)
derives all of these from two inputs, admin domain and public domain.

### 6.2 Routing

| Path                                                                        | Admin host                          | Public host                                  |
| --------------------------------------------------------------------------- | ----------------------------------- | -------------------------------------------- |
| `/admin/*`, `/app/*`                                                        | `web`, `pwa`                        | 308 → admin host                             |
| `/api/*`                                                                    | `api` (internal orders path 404 as today) | only `/api/v1/public/*` and `/api/health/*`; everything else 404 |
| `/_emdash/*`                                                                | `campaign-site`                     | 404                                          |
| `/login`, `/invite`, `/email-change`, `/fresh-login`                        | `public`                            | 308 → admin host                             |
| `/campaigns/*`, `/_campaign-assets/*`                                       | `/campaigns/*` 308 → public host; assets served | `campaign-site`                   |
| `/_actions/createPublicOrder`                                               | 404                                 | `public`                                     |
| `/surveys/*`                                                                | 308 → public host                   | `public`                                     |
| `/`, `/<alias>`, `/archive/<slug>`, `/_astro/*`, `/_image`, static files    | `/` → 302 `/admin/`; rest 308 → public host | `public`                             |

The redirects keep every old link working: bookmarks, printed QR codes and
mails sent before the switch point at the old single host, which becomes the
admin host or the public host (Q1).

### 6.3 Sessions, CSRF, CORS

- The session cookie is `__Host-leonaid_session` (`src/leonaid/domain/sessions.py`):
  host-only, `Secure`, `Path=/`, no `Domain`. It is never sent to the public
  host or any campaign host, also not to a sibling subdomain. No change.
- Core CSRF (`csrf_violation` in `src/leonaid/entrypoints/fastapi/security.py`)
  rejects an unsafe request whose `Origin` is not in `allowed_origins`. The
  spike shows the public inbox form posting from a second host fails today
  (`403 csrf_rejected`, §12.3). Change: a second, credential-free allowlist
  for the `/api/v1/public/*` prefix only. CORS for those origins sends
  `Access-Control-Allow-Origin` **without** `Access-Control-Allow-Credentials`.
  Admin endpoints keep the admin-only allowlist, so a compromised campaign
  page can never make a credentialed call to the admin API.
- All public forms stay **same-origin**: the edge proxies
  `/api/v1/public/*` and `/_actions/createPublicOrder` on every site host.
  No browser cross-host call is needed.
- Astro `checkOrigin` stays on in both Astro apps. It compares `Origin` with
  `Astro.url`, so every site host must be in `security.allowedDomains`
  (§6.4).
- Survey participation cookies (`src/leonaid/modules/surveys/routes.py`) are
  set by the API on the host that serves the survey. Surveys move to the
  public host with their links; the cookies follow.

### 6.4 Code changes (stage 1)

1. **`apps/campaign-site/src/auth/public-origin.ts`**: split into
   `hasSecureAdminOrigin` (unchanged logic, pinned to `EMDASH_SITE_URL`) and
   `hasSecureSiteOrigin` (Host, `X-Forwarded-Host` and `Origin` must equal one
   configured site host, `X-Forwarded-Proto` must be `https`). The public
   campaign branch of `closed-bootstrap.ts` uses the site variant; setup and
   admin branches keep the admin variant.
2. **`apps/public/runtime-allowed-domains.mjs`**: accept a comma-separated
   list (both Astro apps). Spike patch: 3 lines.
3. **`apps/campaign-site/src/pages/campaigns/[slug].astro`**: canonical and
   Open Graph origin from the request's validated site host, not from
   `EMDASH_SITE_URL`.
4. **EmDash editor "Live View"** (`emdash-editor-patch.mjs`,
   `leonaidLivePath` in `src/middleware.ts`): today a relative path,
   validated by regex. It must become an absolute `https://` URL on the
   public host (a relative link would open the admin host; the 308 in §6.2
   is the safety net, not the design).
5. **Core**: second origin allowlist (§6.3); `public_base_url` split into
   admin and site base URLs for mail links (§9).
6. **Caddy**: two site blocks in `infra/pilot/Caddyfile` and
   `infra/proxy/Caddyfile` generated from one route table (sketch in §8).
   The `body_read_timeouts` and `order_declared_body_limit` snippets move
   unchanged into both blocks.
7. **Pilot**: the pilot compose has no `emdash` profile and no
   `EMDASH_SITE_URL` override today (`infra/pilot/compose.yml`); the base
   value `https://localhost:8443` would be wrong in production. Enabling the
   CMS in the pilot is a prerequisite of either stage.

## 7. Stage 2 — campaign hosts (target B)

### 7.1 Behaviour

- An action manager adds a host to an action in the admin UI ("Domains" next
  to "Aliase"): `weihnachtsmarkt.domain.org`, `krapfentaxi.org`,
  `www.krapfentaxi.org`.
- LeonAid shows the DNS records to create (A/AAAA to the server, or CNAME to
  the public host for subdomains) and a **Prüfen** button.
- The check (§7.4) proves the host points to this server. Only then the host
  becomes `verified`; Caddy may then obtain a certificate on the first
  request.
- One host per action is **primary**. Its root `/` serves the campaign. Other
  hosts of the same action (`www.`, alternative spellings) 308 to the primary
  host root.
- The old path `https://domain.org/campaigns/<slug>/` and every alias of the
  action 308 to `https://<primary-host>/` once the primary host is `active`.
  The spike shows the page also renders under the old path on the campaign
  host (duplicate content); that path must 308 to `/` (§12.4).
- A campaign host serves only its own campaign. Any other campaign path, any
  alias of another action, `/_emdash/*`, `/admin`, `/app` and non-public
  `/api/*` return 404 (spike: other campaign → 404, `/_emdash` → 404).
- Archive: when the action ends, the host keeps serving the archived page.
  Removing the host (or the domain lapsing) falls back to the public host
  path, which stays valid as redirect target in reverse.

### 7.2 Request flow

```
Browser ──TLS (SNI krapfentaxi.org)──▶ Caddy
  known site block?  admin / public host ─▶ as stage 1
  otherwise          on-demand TLS: ask http://api:8000/internal/tls/ask?domain=krapfentaxi.org
                     ├─ 2xx: certificate (ACME HTTP-01/TLS-ALPN-01), then proxy
                     └─ else: TLS handshake fails (spike: "tlsv1 alert internal error")
  /_actions/createPublicOrder, /api/v1/public/*, static public files ─▶ public / api
  everything else ─▶ campaign-site:3000 (Host, X-Forwarded-Host/Proto set)
campaign-site middleware (first in the sequence, before the closed guard):
  site = Core GET /api/v1/public/sites/{host}   (cached 30 s, negative cache 30 s)
  unknown → 404; campaign host + "/" → next("/campaigns/<slug>/?query")
  campaign host + "/campaigns/<slug>/" → 308 "/"
closed guard → [slug].astro: canonical https://<host>/, og:* on <host>
```

The spike implemented exactly this rewrite with Astro `next(url)` inside a
`sequence()` placed before the existing closed guard
(`apps/campaign-site/src/closed-bootstrap.ts`). The guard then sees the
mapped path, so its rules (method allow-list, preview refusal, order POST
admission) apply unchanged. Astro 7.4.4 `sequence` carries the rewrite to
the following handlers and the page (`node_modules/astro/dist/core/middleware/sequence.js`).

### 7.3 Data model (migration sketch)

```python
# migrations/versions/00xx_site_hosts.py
op.create_table(
    "site_host",
    sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    # Lowercase IDNA A-label, no port, no trailing dot, <= 253 chars.
    sa.Column("hostname", sa.Text(), nullable=False),
    sa.Column("action_id", sa.UUID(), sa.ForeignKey("action.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    # pending -> verified -> active ; any -> disabled
    sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
    sa.Column("verification_token", sa.Text(), nullable=False),
    sa.Column("verified_at", sa.DateTime(timezone=True)),
    sa.Column("last_checked_at", sa.DateTime(timezone=True)),
    sa.Column("last_check_result", sa.Text()),
    sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("created_by", sa.UUID(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint("status IN ('pending','verified','active','disabled')", name="ck_site_host_status"),
    sa.CheckConstraint(r"hostname ~ '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$' AND length(hostname) <= 253",
                       name="ck_site_host_hostname"),
    sa.CheckConstraint("revision > 0", name="ck_site_host_revision"),
)
op.create_index("uq_site_host_hostname", "site_host", ["hostname"], unique=True)
op.create_index("uq_site_host_primary_action", "site_host", ["action_id"], unique=True,
                postgresql_where=sa.text("is_primary AND status <> 'disabled'"))
```

- The admin host and the public host stay in environment variables, not in
  the table: they must work before the database exists, and Caddy needs them
  as static site blocks.
- A hostname equal to the admin or public host, or below the admin host
  (`*.backend.domain.org`), is refused by the domain layer.
- Commands follow `campaign_aliases.py`: idempotent command id, revision
  check, `require_action_manager`, audit entry. Downgrade refuses existing
  rows, like 0028.
- Public read endpoint `GET /api/v1/public/sites/{hostname}` returns
  `{kind, actionId, archiveSlug, primaryHost, status}` for `active` hosts only.
- Internal endpoint `GET /internal/tls/ask?domain=` (§10.1), not routed by
  Caddy to the internet.

### 7.4 Host verification

LeonAid checks the host itself, without DNS provider APIs:

1. Caddy's `:80` block routes `/.well-known/leonaid-host-check/*` on any
   host to the API (HTTP only, before the HTTPS redirect).
2. **Prüfen** makes the API fetch
   `http://<host>/.well-known/leonaid-host-check/<token>` (timeout 5 s, no
   redirects, response ≤ 1 KiB, egress only to the resolved public
   addresses — never private/loopback ranges, the same SSRF rule as
   `_is_forbidden_public_host` in `configuration.py`).
3. A matching token proves DNS points here and port 80 is reachable, which is
   also what ACME HTTP-01 needs. Status → `verified`; the first HTTPS
   request then obtains the certificate; a successful TLS self-check sets
   `active`.
4. A nightly job re-checks active hosts. Failures are shown in operations
   (existing operations view), never silently disabled; three consecutive
   failures over 72 h set `disabled` and stop `ask` approval, so a lapsed
   domain re-registered by someone else cannot keep a certificate path.

### 7.5 SEO and legal pages per host

- Canonical and `og:url` = `https://<primary-host>/` (spike: works).
- `og:image` absolute on the same host. Campaign media stays at
  `/campaigns/<slug>/media/<id>` on the campaign host (served by the same
  route, now allowed on that host) — no `/_emdash/image` is used by public
  pages (spike resource list, §12.3).
- `robots.txt` and `sitemap.xml` per host: today they are internal-only CMS
  routes (`apps/campaign-site/route-contract.mjs`). New small endpoints:
  campaign host → one URL; public host → home, aliases' canonical targets
  that are not on own hosts, archives.
- Impressum and Datenschutz: no such page exists yet in `apps/public`. Add
  `/impressum` and `/datenschutz` to `apps/public`, linked in the footer of
  `PublicLayout.astro`, rendered from the active legal configuration
  (migration 0023) on every site host. One content per installation
  (non-goal: per-domain legal entities). Q4.

### 7.6 Mail links

| Mail                                   | Link host                                                     |
| -------------------------------------- | ------------------------------------------------------------- |
| Magic login, invitation, e-mail change | admin host (`sessions.py`, `invitations.py`, `email_changes.py`) |
| Invoice delivery                       | admin host if it links at all; the PDF is attached             |
| Survey invitation                      | public host (`surveys.py` line 908)                            |
| Order confirmation (customer)          | the action's primary campaign host, else public host path     |

A small `LinkBuilder` in Core (`admin_url(path)`, `site_url(action_id, path)`)
replaces the string concatenations; it reads the primary host from
`site_host` at send time.

## 8. Proxy configuration sketch

Pinned image: `caddy:2.11.7-alpine` (`infra/locks/images.env`).

```caddyfile
{
	email {$CADDY_ACME_EMAIL}
	admin off
	servers {
		strict_sni_host on
		timeouts {
			read_body_idle -1s
		}
	}
	# Stage 2 only. Approval is LeonAid's decision; Caddy 2.11 has no own
	# rate limit for on-demand issuance (interval/burst were removed).
	on_demand_tls {
		ask http://api:8000/internal/tls/ask
	}
}

(site_common) {
	import body_read_timeouts
	import common_headers
	@internal_orders path /api/v1/public/actions/*/orders /api/v1/public/actions/*/orders/*
	respond @internal_orders 404
	handle /api/v1/public/* {
		import leonaid_headers
		reverse_proxy api:8000
	}
	handle /api/health/* { … as today … }
	handle /api/* {
		respond 404
	}
	handle /_emdash* {
		respond 404
	}
	@login path /login /invite /email-change /fresh-login /admin /admin/* /app /app/*
	redir @login https://{$LEONAID_ADMIN_DOMAIN}{uri} 308
	@public_order path /_actions/createPublicOrder /_actions/createPublicOrder/
	handle @public_order {
		import astro_headers
		import order_declared_body_limit
		reverse_proxy public:3000
	}
}

http:// {
	handle /.well-known/leonaid-host-check/* {
		reverse_proxy api:8000
	}
	handle {
		redir https://{host}{uri} 308
	}
}

{$LEONAID_ADMIN_DOMAIN} {
	import body_read_timeouts
	import common_headers
	# /api/*, /_emdash/*, /admin/*, /app/*, login pages: today's routes.
	# /campaigns/* and public paths: 308 to the public host.
}

{$LEONAID_PUBLIC_DOMAIN} {
	import site_common
	@campaign_routes path /campaigns /campaigns/* /_campaign-assets/*
	handle @campaign_routes { import cms_proxy }
	handle { import astro_headers; import order_declared_body_limit; reverse_proxy public:3000 }
}

# Stage 2: every other host that LeonAid approved.
https:// {
	tls {
		on_demand
	}
	import site_common
	@public_static path /favicon.svg /community-routes.png /community-routes.webp /impressum /datenschutz
	handle @public_static { reverse_proxy public:3000 }
	handle { import cms_proxy }
}
```

`cms_proxy` is today's `reverse_proxy campaign-site:3000 { … header_up X-Forwarded-Host {hostport} … }`
block unchanged. In the dev stack (`infra/proxy/Caddyfile`) the same blocks
use `tls internal`, as the spike did.

## 9. Security

### 9.1 On-demand TLS abuse

- Risk: an attacker points arbitrary names at the server and makes Caddy
  request certificates, burning Let's Encrypt limits (300 new orders per
  account per 3 h; 5 failed validations per host per hour) and disk.
- Control: `ask` approves only hostnames with `site_host.status IN
  ('verified','active')`. Spike (§12.2): unregistered SNI fails the
  handshake; an unreachable `ask` endpoint fails closed
  (`failed to get permission for on-demand certificate`).
- Caddy 2.11.7 rejects `interval`/`burst` in `on_demand_tls`
  ("no longer supported", §12.2). Rate limiting is therefore in LeonAid:
  `ask` allows at most 10 distinct new approvals per hour per installation
  (existing `security_rate_limit` repository) and answers in < 50 ms from
  an indexed lookup. Approved hosts are few and bounded by admin action.
- `ask` is reachable only on the internal network; the edge returns 404 for
  `/internal/*` and `/api/internal/*` on every host.

### 9.2 Host header injection

- `strict_sni_host on` already rejects a Host that differs from the TLS SNI
  (spike: `421`). Caddy sets `X-Forwarded-Host`; the CMS also requires Host
  = `X-Forwarded-Host` (`hasSecure…Origin`).
- Astro trusts Host only when it matches `allowedDomains`; otherwise
  `Astro.url` falls back to `localhost` (spike: the public app rendered
  canonical `https://localhost:3000/archive/…` for the unlisted
  `club.test`). For stage 2 the list is dynamic, so Astro gets a
  catch-all pattern `{ protocol: "https" }` (an empty hostname matches every
  host in `@astrojs/internal-helpers` `matchHostname`) **and** the campaign
  site's first middleware rejects every host that Core does not return as
  `active`. Host validity is therefore decided by Core, not by Astro.
  Alternative if review rejects the catch-all: restart `public` and
  `campaign-site` on host activation with the explicit list (seconds of
  downtime per new host).
- Absolute URLs are built only from the validated host, never from
  `X-Forwarded-Host` directly.

### 9.3 Cookies

- No `Domain=` cookie anywhere. Admin session is `__Host-` prefixed and
  stays on the admin host. Campaign hosts set no cookies (spike: browser
  context had 0 cookies after order submission on `krapfentaxi.test`).
- A campaign host under the club's domain (`weihnachtsmarkt.domain.org`) is a
  sibling of the admin host. With host-only cookies, siblings cannot read or
  set the admin session. They could set a `Domain=domain.org` cookie, which
  the `__Host-` prefix ignores. CSRF tokens are not cookie-based.
- EmDash's own cookies (`emdash-edit-mode`, auth) exist only on the admin
  host; the public route refuses `emdash-edit-mode=true` as today.

### 9.4 CSRF and Origin

- Native order POST on a campaign host: the CMS guard requires `Origin` =
  the request's own site host. Spike: `https://krapfentaxi.test` → 200;
  `https://evil.test` and the sibling `https://club.test` → 403.
- JavaScript order RPC (`/_actions/createPublicOrder` in `apps/public`):
  Astro `checkOrigin`. Spike: same host passes, foreign origins → 403.
- Core public endpoints: §6.3 (credential-free public allowlist).

### 9.5 Open redirects

- All redirects target either a configured host (env) or a hostname read
  from `site_host` for the requested action; never a host from the request
  or a query parameter. The existing `campaignRedirect` invariants
  (`apps/public/src/lib/campaign-redirect.ts`) extend to "target host is the
  action's primary active host".
- `return_to` handling after login stays path-only on the admin host.

### 9.6 Content Security Policy

`'self'` is per host, so nothing changes. Cross-host resources are not used
(spike: 0 CSP violations on both hosts, JS on and off).

## 10. Operations

### 10.1 DNS, ports, ACME

- Admin and public host: A/AAAA records to the VPS, as today for the one host.
- Campaign subdomain: CNAME to the public host, or A/AAAA.
- Own domain: A/AAAA at the apex (`krapfentaxi.org`) and for `www`. Registrar
  "web forwarding" products do not work (they terminate HTTP elsewhere).
- Ports 80 and 443 must stay open to the internet (already published,
  `infra/pilot/compose.yml`). Port 80 serves the host check and HTTP-01;
  TLS-ALPN-01 runs on 443.
- CAA records, if the domain has any, must allow `letsencrypt.org`.
- Certificates live in the Caddy data volume (already persistent and in
  backups). Each host costs ~10 KB and one renewal every ~60 days.

### 10.2 Pilot install

- `production.env.example`: `LEONAID_ADMIN_DOMAIN`, public domain, derived
  base URLs and origin lists. The installer refuses an admin domain equal to
  the public domain.
- The pilot readiness check (`tools/pilot_readiness`) gains: both hosts
  resolve to this server; port 80 reachable for each.
- Runbook (`infra/pilot/LIVE-PILOT-RUNBOOK.md`): "Domain hinzufügen" steps,
  what the club does at its registrar, how long ACME takes, how to read the
  check result.

### 10.3 Resource cost

No new container. One indexed lookup per new TLS handshake for an unknown
SNI and one cached Core lookup per 30 s per host in the campaign site. No
measurable memory impact on the 8 GB VPS.

## 11. Migration of existing aliases and links

- Stage 1 switch: the existing single host becomes the public host (Q1);
  all existing alias and `/campaigns/` URLs keep working unchanged. Admin
  paths on the old host 308 to the new admin host. Members get one notice;
  sessions start fresh on the admin host (host-only cookie).
- Stage 2 per action: aliases stay in `public_action_alias`, unchanged.
  When a primary host becomes `active`, the resolver returns the host URL
  as `redirectPath`/canonical, so `/krapfentaxi` and
  `/campaigns/krapfentaxi-2026/` on the public host 308 to
  `https://krapfentaxi.org/`. Disabling the host reverts automatically.
- Printed QR codes keep pointing at the public host alias; the redirect chain
  is at most two hops (alias → host root).
- The primary order alias (`orderAlias`, order token binding) is not
  changed: the order form on the campaign host still submits the alias
  `krapfentaxi` with its token (spike: the real form did so).

## 12. Spike result

Date 2026-11-03. Throwaway code in a session scratch directory outside the
repository (not committed): Caddyfile,
probe scripts, 73-line patch, a driver derived from
`tools/emdash_spike/auth-runtime-test.sh` mode `public-http`.

### 12.1 Method

1. `./leonaid bootstrap` in the worktree; isolated stack started through
   `run-in-slot.sh` with the existing `public-http` flow: Core, PostgreSQL,
   campaign-site (EmDash 1.4.0, Astro 7.4.4), public, product proxy; golden
   seed; designated-operator setup; Krapfentaxi campaign published by the
   existing `public-campaign-http-proof.mjs`.
2. A throwaway Caddy 2.11.7 on the project's `edge` network with network
   aliases `club.test` (stage 1 public host, path-based) and
   `krapfentaxi.test` (stage 2 campaign host, whole host to the CMS), `tls
   internal`, `strict_sni_host on`.
3. HTTP probe (Node, in `bootstrap-probe`) and a Chromium order submission
   (Playwright, in `admin-browser`, JS off and on) against the product
   proxy, both throwaway hosts and the CMS directly.
4. **V0**: unchanged images. **V1**: images built from a scratch copy with
   the patch below (`astro check` and `astro build` passed in the image
   build). Stack torn down by the driver's owned teardown; no leftover
   containers, networks, volumes or images.

V1 patch (environment-driven stand-in for `site_host`):

| File                                   | Change                                                                                                   |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `src/auth/public-origin.ts`            | `hasSecurePublicOrigin(request, allowCampaignHosts)`: public routes accept hosts from `LEONAID_SPIKE_CAMPAIGN_HOSTS` |
| `src/closed-bootstrap.ts`              | `onRequest = sequence(campaignHostRewrite, closedBootstrap)`; `/` on a campaign host → `next("/campaigns/<slug>/")`; `/_emdash*` on a campaign host → 404 |
| `src/pages/campaigns/[slug].astro`     | canonical/OG origin = validated request host; canonical path `/` on the campaign host                     |
| `apps/public/runtime-allowed-domains.mjs` | comma-separated host list                                                                              |

### 12.2 Caddy on-demand TLS (pinned 2.11.7)

Standalone container, `on_demand_tls { ask http://127.0.0.1:9123/check }`, a
stand-in `ask` site approving two names, `https:// { tls internal { on_demand } }`.

| Probe                                                     | Result                                                                                      |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| SNI `krapfentaxi.test`, `weihnachtsmarkt.club.test` (approved) | certificate issued on first request, `200`                                             |
| SNI `evil.test` (not approved)                            | handshake refused: `tlsv1 alert internal error`                                             |
| `ask` endpoint down                                       | refused; log `failed to get permission for on-demand certificate` (fail closed)             |
| SNI `krapfentaxi.test`, `Host: evil.test`                 | `421` (`strict_sni_host`)                                                                   |
| `interval 2m` / `burst 5` in `on_demand_tls`              | config error: "the on_demand_tls 'interval' option is no longer supported"                  |

Not testable locally: real ACME issuance (needs public DNS and port 80).

### 12.3 Campaign site under several hosts

| Probe                                                     | V0 (as is)                                    | V1 (patched)                                         |
| --------------------------------------------------------- | --------------------------------------------- | ---------------------------------------------------- |
| `https://proxy:8443/campaigns/krapfentaxi-2026/` (baseline) | 200, canonical `https://proxy:8443/campaigns/…` | 200, unchanged                                      |
| `https://club.test/campaigns/krapfentaxi-2026/`           | **403 Invalid CMS origin**                    | 200, canonical/og:url `https://club.test/campaigns/krapfentaxi-2026/`, og:image on `club.test` |
| `https://krapfentaxi.test/`                               | **503 CMS access is not enabled** (`/` is not a public CMS route) | 200, canonical/og:url `https://krapfentaxi.test/`, og:image on `krapfentaxi.test` |
| all page resources on that host (favicon, `/_campaign-assets/*.css/js`) | —                               | all 200 (root-relative, host-neutral)                |
| `https://krapfentaxi.test/campaigns/krapfentaxi-2026/`    | 403                                           | 200 with canonical `/` → needs a 308 in the product   |
| `https://krapfentaxi.test/campaigns/krapfentaxi-2025/` (other campaign) | 403                             | 404 (inactive)                                       |
| CMS direct, `Host: unregistered.test`                     | 403                                           | 403                                                  |
| CMS direct `/_emdash/api/manifest` with admin session, `Host: krapfentaxi.test` | 403                     | 404                                                  |
| same with `Host: proxy:8443` (admin host)                 | 200                                           | 200 (admin unaffected)                               |
| `https://club.test/krapfentaxi` (apps/public alias page)  | 200, canonical **`https://localhost:3000/…`** (host not in `allowedDomains`) | 200, canonical `https://club.test/archive/…` |
| native order POST `/?_action=createPublicOrder`, Origin same host | 503 (route closed)                    | 200 (rendered form result)                           |
| same, Origin `https://evil.test` / `https://club.test`    | 503                                           | 403 / 403                                            |
| JS order RPC `/_actions/createPublicOrder/`, Origin same host | **403 Cross-site POST form submissions are forbidden** | 400 input validation (= origin accepted)  |
| same, foreign Origin                                      | 403                                           | 403                                                  |
| Core `POST /api/v1/public/inbox-cases` on `club.test`, Origin `https://club.test` | **403 csrf_rejected**     | 403 (Core not patched in the spike; §6.3)            |
| same, Origin = configured origin                          | 422 (reaches validation)                      | 422                                                  |

Browser (Chromium, real form, synthetic data; the stack has no CRM, so the
expected Core outcome is "Das Bestellformular ist vorübergehend nicht
verfügbar." — identical to the single-host baseline):

| Page                                           | JS off                                       | JS on                                              |
| ---------------------------------------------- | -------------------------------------------- | -------------------------------------------------- |
| `proxy:8443/campaigns/krapfentaxi-2026/` (baseline) | POST page → Core → expected message      | POST `/_actions/createPublicOrder/` → expected message |
| V0 `krapfentaxi.test/`, `club.test/campaigns/…` | page 503 / 403, no form                     | same                                               |
| V1 `krapfentaxi.test/`                         | POST `/?_action=createPublicOrder` → expected message | POST `/_actions/createPublicOrder/` → expected message |
| V1 `club.test/campaigns/krapfentaxi-2026/`     | expected message                             | expected message                                   |

All V1 runs: 0 CSP violations, 0 cookies set.

### 12.4 Findings

1. EmDash 1.4 has one `siteUrl`/`EMDASH_SITE_URL`
   (`emdash/dist/public-url-*.mjs`, `site-url-*.mjs`). It is used for the
   admin, sign-in links and EmDash's own outbound URLs. LeonAid never lets
   EmDash render public pages, so this single origin is correct as the
   **admin** origin and needs no patch. `EMDASH_ALLOWED_ORIGINS` exists but
   is for passkeys and only accepts subdomains of `siteUrl`; it is not
   needed (LeonAid auth, no passkeys).
2. The blockers are LeonAid's: `hasSecurePublicOrigin` pins public routes to
   `EMDASH_SITE_URL`; `runtime-allowed-domains.mjs` admits one domain;
   `[slug].astro` builds canonical/OG from `EMDASH_SITE_URL`; the closed
   guard only knows `/campaigns/<slug>/` paths. All four were fixed in the
   spike in 73 changed lines.
3. Asset and media URLs are root-relative (`/_campaign-assets/*`,
   `/campaigns/<slug>/media/<id>`) and work on every host. Astro `site` and
   `base` are unset and must stay unset; `build.assets` and the
   `/_emdash/image` endpoint (admin only) need no change.
4. Astro middleware rewrite via `next(url)` in a `sequence` works before the
   closed guard, including POST with query string. No route-contract
   change: the root path is never an Astro route of the campaign site.
5. The old campaign path on a campaign host renders a duplicate page; the
   product must 308 it to `/`.
6. The JS order path is served by `apps/public` on every site host; both
   Astro apps need the host list.
7. Core's public inbox endpoint needs the public origin allowlist (§6.3).
8. Not covered: real ACME, EmDash admin "Live View" link rewriting
   (code read only), sitemap/robots, survey pages on a second host.

**Verdict: works with listed patches.** No EmDash patch is needed for
multi-host public pages; the CMS admin stays single-host by design.

## 13. Open questions for Björn

1. Q1: Stage 1 switch: does today's host become the **public** host (all
   printed links stay valid, admin moves) or the **admin** host? Recommended:
   public.
2. Q2: Admin host name: `backend.domain.org`, `verwaltung.…`, `intern.…`?
   It appears in every member mail.
3. Q3: Should the public host keep a home page listing all campaigns, or
   redirect `/` to the current campaign?
4. Q4: One Impressum/Datenschutz for all domains (same club as provider) —
   or does any campaign domain need a different responsible party (e.g. a
   partner club or Förderverein)? The latter is a non-goal today.
5. Q5: Who may add a domain: action manager or system admin only?
   Recommended: system admin, because DNS and costs are club-level.
6. Q6: When an action ends, keep the campaign domain serving the archive,
   or redirect it to the public host? Domain renewal is a club cost.
7. Q7: Is the catch-all Astro host pattern guarded by Core (§9.2) acceptable,
   or prefer restarts on host activation?
8. Q8: Order confirmation mails: link to the campaign domain (recommended)
   or always to the public host?

## 14. Test plan

| Level        | Tests                                                                                                                                                       |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit (Python) | hostname normalization/IDNA/rejections (port, trailing dot, IP literal, admin/public host, subdomain of admin host); command revisions; `ask` decisions and rate limit; LinkBuilder per mail type; CSRF two allowlists |
| Unit (TS)    | `hasSecureAdminOrigin`/`hasSecureSiteOrigin`; host rewrite (root, query, old path → 308, other campaign → 404, `/_emdash` → 404); runtime allowed-domains list patch; canonical builder |
| Contract     | OpenAPI for `site_host` commands and `/api/v1/public/sites/{host}`; migration up/down with refusal                                                          |
| Integration  | new `test-emdash-spike --case multi-host` derived from this spike: V1 probe table §12.3 as assertions, plus redirects of aliases to the primary host       |
| Caddy        | `tools/proxy/validate-caddyfiles.sh` for both site-block variants; on-demand probe of §12.2 (approved, unknown, `ask` down, SNI/Host mismatch)              |
| Browser      | existing `public-order-component-proof.mjs` parametrized by base URL (campaign host root, public host path), three engines, JS on/off, CSP guard            |
| E2E          | admin: add host → check → active; Live View opens the campaign host; login on admin host only                                                              |
| Pilot        | readiness check resolves hosts and port 80; manual ACME acceptance on a real test subdomain before the first own domain                                   |

## 15. Effort estimate

Developer days, including tests and docs, excluding Björn's review time.

| Stage | Scope                                                                                                     | Estimate   |
| ----- | --------------------------------------------------------------------------------------------------------- | ---------- |
| 0     | Enable the CMS in the pilot (`emdash` profile, `EMDASH_SITE_URL`) — prerequisite                           | 1–2 d      |
| 1     | env + installer, two Caddy site blocks (prod + dev), origin split CMS, allowed-domains list, canonical, Core public allowlist, mail link builder, Live View link, redirects, tests, runbook | 5–7 d |
| 2     | `site_host` migration/domain/commands/API, admin UI "Domains", host check + nightly job, `ask` endpoint + rate limit, Caddy on-demand block, CMS host middleware + 308s, sitemap/robots, Impressum/Datenschutz pages, alias redirect to primary host, multi-host spike case, browser tests, ops docs | 12–16 d |

Stage 2 depends on stage 1. Real-ACME acceptance needs one real test
subdomain and one test domain owned by the club.
