# Multiple domains — admin host, public host, campaign hosts

Status: 2026-11-07. Björn answered the open questions on 2026-11-03
([§13](#13-decisions-björn-2026-11-03)). Implementation started on
2026-11-07: stages 0 and 1 are built ([§16](#16-implementation-status-and-rulings));
1a and 1b follow, 1c is dropped, stage 2 comes after 1b.

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

- **A** — `app.domain.org` for administration (`/admin`, `/app`, full
  `/api`, CMS admin) and `domain.org` for all public campaign pages, path-based
  as today.
- **B** — `app.domain.org` plus one host per campaign:
  `weihnachtsmarkt.domain.org` (subdomain), `krapfentaxi.org` and
  `lionsopen.de` (own registered domains), with or without a general public
  host `domain.org`.
- **C** — recurring campaigns on one domain: `lionsopen.de/` shows the current
  edition (Lions Open 2026), `lionsopen.de/2025/` the archived 2025 edition
  (§7.7).

## 2. Goals

1. G1: Separate the member/administration surface from the public surface by
   host (stage 1, target A).
2. G2: Serve a campaign at the root of its own host, subdomain or own domain
   (stage 2, target B), and older editions of a recurring campaign under a
   path segment of the same host (target C). Managed by the system admin in
   the admin UI, without editing Caddy files or restarting containers for
   each new host.
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
  one Impressum and one privacy notice per installation (decision D4).
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
| admin host    | Host for members and editors (`app.domain.org`). New in stage 1; today's only host keeps this role only in single-host mode. |
| public host   | General host for the club's public pages and path-based campaigns (`domain.org`, `www.domain.org`). Optional (§6.6). |
| campaign host | A host that serves the editions of one campaign (series): the current edition at `/`, older editions at `/<segment>/`. Optional, stage 2. |
| site host     | Public host or campaign host (any host that serves public pages).                            |
| edition       | One action bound to a campaign host, for example Lions Open 2025. Each edition has a fixed path segment on that host (`2025`). |
| binding       | The row that maps (campaign host, edition segment) to an action (§7.3).                     |
| canonical URL | The one public URL of an action: campaign host root, campaign host segment, or public host path (§7.7.3). |

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
- Stage 1 (new admin host `app.<domain>`; today's host becomes the public
  host) is configuration plus small code changes. Stage 2 (campaign hosts)
  adds the `site_host` and `site_binding` tables, a system-admin UI, host
  resolution in the campaign site, Caddy on-demand TLS with a LeonAid `ask`
  endpoint, and per-host SEO.
- An installation does not need a general public host. Without one, the
  admin host plus campaign hosts carry everything (§6.6); this mode needs
  stage 2.
- Recurring campaigns reuse their domain: host + edition segment → action,
  with a root flag for the current edition and a binding history, so every
  old URL keeps working (§7.7).
- The host → campaign mapping lives in Core. Caddy holds no per-campaign
  configuration; it never needs a reload for a new host.

## 6. Stage 1 — admin host and public host (target A)

### 6.1 Configuration

| Variable                  | Today                                 | Stage 1                                                                                                                               |
| ------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `LEONAID_PUBLIC_DOMAIN`   | the only host                         | unchanged meaning when `LEONAID_ADMIN_DOMAIN` is empty (single-host mode, G4). With an admin domain: the general public host, or **empty** for an installation without one (§6.6) |
| `LEONAID_ADMIN_DOMAIN`    | —                                     | new, optional, convention `app.<domain>` (example `app.example.org`). When set, the admin surface moves here                         |
| `LEONAID_PUBLIC_DOMAIN_ALIASES` | —                               | new, optional, comma-separated. Extra names of the public host (`www.example.org` next to `example.org`); each 308s to `LEONAID_PUBLIC_DOMAIN` with the path kept |
| `LEONAID_PUBLIC_BASE_URL` | mail links (login, invite, surveys)   | renamed in meaning to the **admin** base URL for member mails; a new `LEONAID_SITE_BASE_URL` for public links (survey invitations). Without a public host, `LEONAID_SITE_BASE_URL` equals the admin base URL (§6.6) |
| `LEONAID_ALLOWED_ORIGINS` | credentialed CORS/CSRF origins        | admin origin only. New `LEONAID_PUBLIC_ORIGINS`: static origins allowed for `/api/v1/public/*` without credentials (public host and its aliases). Stage 2 adds the active campaign hosts from `site_host` at request time (§6.3) |
| `EMDASH_SITE_URL`         | site origin, pinned by `hasSecurePublicOrigin` | admin origin (CMS editor, sign-in links). Public campaign routes accept the site hosts instead (§6.4)                        |

The installer (`infra/pilot/production.env.example`, `tools/pilot_install`)
derives all of these from two inputs, admin domain (proposed default
`app.<public domain>`) and public domain (may be left empty, §6.6).

### 6.2 Routing

| Path                                                                        | Admin host                          | Public host                                  |
| --------------------------------------------------------------------------- | ----------------------------------- | -------------------------------------------- |
| `/admin/*`, `/app/*` (base paths: §6.7)                                     | `web`, `pwa`                        | 308 → admin host                             |
| `/api/*`                                                                    | `api` (internal orders path 404 as today) | only `/api/v1/public/*` and `/api/health/*`; everything else 404 |
| `/_emdash/*`                                                                | `campaign-site`                     | 404                                          |
| `/login`, `/invite`, `/email-change`, `/fresh-login`                        | `public`                            | 308 → admin host                             |
| `/campaigns/*`, `/_campaign-assets/*`                                       | `/campaigns/*` 308 → public host; assets served | `campaign-site`                   |
| `/_actions/createPublicOrder`                                               | 404                                 | `public`                                     |
| `/surveys/*`                                                                | 308 → public host                   | `public`                                     |
| `/impressum`, `/datenschutz`                                                | `public`                            | `public`                                     |
| `/`                                                                         | role-based entry: login, then the view for the user's role (§6.7) | `public`: list of active campaigns (§6.5) |
| `/<alias>`, `/archive/<slug>`, `/_astro/*`, `/_image`, static files         | 308 → public host                   | `public`                                     |

Without a public host the admin host column changes as described in §6.6.

The redirects keep every old link working: bookmarks, printed QR codes and
mails sent before the switch point at the old single host, which becomes the
public host (decision D1). Only member links (`/admin`, `/app`, login pages)
move, and they 308 to the admin host.

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
- The public allowlist is not only static. For `/api/v1/public/*` Core accepts
  `Origin` when it equals the request's own host **and** that host is the
  public host, one of its aliases, or an `active` row in `site_host` (cached
  lookup, same source as the `ask` endpoint). This keeps forms working on a
  campaign host that was added a minute ago, without a restart (decision D7),
  and in installations without a public host.
- All public forms stay **same-origin**: the edge proxies
  `/api/v1/public/*` and `/_actions/createPublicOrder` on every site host.
  No browser cross-host call is needed.
- Astro `checkOrigin` stays on in both Astro apps. It compares `Origin` with
  `Astro.url`, so every site host must be in `security.allowedDomains`
  (§6.4).
- Survey participation cookies (`src/leonaid/modules/surveys/routes.py`) are
  set by the API on the host that serves the survey. Surveys move to the
  public host with their links; the cookies follow. Without a public host,
  surveys stay on the admin host (§6.6).

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
   validated by regex. It must become the action's absolute canonical URL
   (§7.7.3; public host path in stage 1, campaign host in stage 2). A
   relative link would open the admin host; the 308 in §6.2 is the safety
   net, not the design.
5. **Core**: second origin allowlist (§6.3); `public_base_url` split into
   admin and site base URLs for mail links (§7.6).
6. **Caddy**: site blocks for the admin host, the public host (if
   configured) and its aliases in `infra/pilot/Caddyfile` and
   `infra/proxy/Caddyfile`, generated from one route table (sketch in §8).
   The `body_read_timeouts` and `order_declared_body_limit` snippets move
   unchanged into each block.
7. **Pilot**: the pilot compose has no `emdash` profile and no
   `EMDASH_SITE_URL` override today (`infra/pilot/compose.yml`); the base
   value `https://localhost:8443` would be wrong in production. Enabling the
   CMS in the pilot is a prerequisite of either stage.
8. **Public home page** (§6.5): `apps/public` home state lists active
   campaigns from a new Core read endpoint.
9. **Role-based entry on the admin host** (§6.7): `/` on the admin host,
   `landingPath` in the identity response, one source for the `/admin` and
   `/app` base paths.
10. **No-public-host mode** (§6.6): Caddy generator and installer accept an
    empty public domain; the admin host serves surveys and legal pages and
    answers alias paths with redirects.

### 6.5 Home page of the public host (decision D3)

- `/` on the public host lists all **active** campaigns: actions whose public
  availability is `active` (status `active`, inside the publication window,
  published). Ended, draft and scheduled actions are not listed.
- Each entry links to the action's canonical URL (§7.7.3): a campaign host
  root or edition segment, or `/campaigns/<archive-slug>/` on the public
  host. The list therefore also links to campaigns on own domains.
- Data: new `GET /api/v1/public/campaigns?availability=active` in Core
  (title, short text, theme image, canonical URL; no internal ids beyond the
  archive slug). Cached like the other public reads (`max-age=60`).
- No active campaign: today's home text ("Engagement, das ankommt.") stays as
  empty state. The existing inbox form (`PublicInbox`) stays on the home page.
- The public host's sitemap contains the home page and the canonical URLs
  that live on the public host.

### 6.6 Installations without a general public host (decision D3)

A club may have no `domain.org` site at all, only campaign hosts such as
`lionsopen.domain.org` and `krapfentaxi.domain.org`. Then
`LEONAID_PUBLIC_DOMAIN` is empty and `LEONAID_ADMIN_DOMAIN` is set.

- **Requires stage 2.** Without a public host, a campaign is public only
  through a campaign host binding. Stage 1 alone in this mode would publish
  nothing, so the installer refuses an empty public domain unless the
  stage-2 feature is enabled. For such a club, "stage 1" is: admin host plus
  campaign hosts, rolled out together.
- **Every site host is self-sufficient.** Legal pages (`/impressum`,
  `/datenschutz`), the public API (`/api/v1/public/*`), the JS order action
  and static public files are served on each campaign host (the `https://`
  catch-all block in §8 already does this). Core accepts the request's own
  campaign host as public origin (§6.3).
- **The admin host takes the public leftovers, as redirects or token pages
  only:**
  - `/surveys/*` is served on the admin host (survey links in mails use
    `LEONAID_SITE_BASE_URL` = admin base URL). Survey pages do not depend on
    the admin session; their participation cookies are host-only and
    separate from `__Host-leonaid_session`.
  - `/<alias>`, `/archive/<slug>` and `/campaigns/<slug>/` on the admin host
    308 to the action's canonical URL on its campaign host, or answer 404
    when the action has no binding. The admin host never renders campaign
    content.
  - `/impressum` and `/datenschutz` are also served on the admin host (the
    login page needs them). This holds in every mode.
- **A campaign without a binding** has no public URL. The action page in the
  admin UI shows "not publicly reachable", and publishing warns. Order
  confirmation mails then contain no campaign link (§7.6).
- The public home page (§6.5) does not exist in this mode. No host lists all
  campaigns; each campaign host lists its own editions (§7.7).
- Caddy: the generator (§6.4 item 6) omits the public host block when the
  public domain is empty.

### 6.7 Admin host: role-based entry and base paths (decision D2)

Host name convention: `app.<domain>` (`app.example.org`). The admin web
(`/admin/`) and the acquisition PWA (`/app/`) both live on this host.
Björn's requirements: `app.domain.org` lands directly in the application,
not in `app.domain.org/app/` by typing; one login for everyone; after login
each user sees the view for their role.

**Root `/` is a role-based entry point, not one fixed app.**

1. `GET /` on the admin host is served by `apps/public` (the Astro app that
   already owns `/login`). Server-side it asks Core for the current identity
   with the forwarded session cookie.
2. No session: 302 to `/login` (no `returnTo`; the post-login step picks the
   destination). Valid session: 302 to the user's `landingPath`. No
   client-side flash, no service worker involved.
3. `landingPath` moves into Core: a new field of the current-identity
   response, computed from global roles, action memberships, enabled modules
   and an optional user preference. It replaces `defaultDestination` in
   `apps/public/src/components/AuthPage.astro` and the fixed target of
   `RedirectToOperationalApp` in `apps/web/src/app.tsx`, so the rule exists
   once. Default order (Björn, 2026-11-03): any `acquirer` role (global or
   through an action membership) → `/app/`, even when the user has other
   roles; otherwise `system_admin` → `/admin/system`; `charity_admin` →
   `/admin/`; finance roles → `/admin/invoices`; otherwise the first `web`
   navigation item. This changes today's rule, where acquisition was the
   default only for acquirer-only users.
4. **Several roles:** the default is the acquisition app whenever the user
   has an acquirer role (order above). Both shells show a switch ("Zur
   Akquise-App" / "Zur Verwaltung"), built from the existing `surface` field
   of `NavigationItem`. A user can choose "Als Startbereich verwenden"; Core
   stores it as `preferred_surface` (`web` | `pwa`, nullable), and
   `landingPath` honours it while the user has a role for that surface.
5. **Deep links survive login:** an unauthenticated request for
   `/admin/orders?commitment=…` or `/app/activities?…` redirects to
   `/login?returnTo=<path+query>`; after login the user lands exactly there,
   not on `landingPath`. `returnTo` stays path-only and must start with the
   admin or PWA base path (today's `safeLocalReturnTo`, §9.5). An acquirer
   who follows an `/admin/*` deep link is sent to the PWA by the web app, as
   today.
6. **PWA installability is unchanged:** manifest `start_url` and `scope` stay
   at the PWA base path. An installed PWA opens the acquisition view directly
   and never passes through `/`. An expired session in the installed PWA
   goes to `/login?returnTo=/app/`, as today. The root entry is for browser
   visits and typed URLs.

**Path names.** After the entry redirect the visible paths are
`app.domain.org/admin/…` and `app.domain.org/app/…`. Recommendation: keep
both names in stage 1, because the root entry already meets "lands directly
in the application". Renaming `/app/` (for example to `/akquise/`) is
cosmetic and a separate later step. Stage 1 must not block it, so stage 1
introduces **one source of truth per base path**:

- A product-wide constant, not a per-installation environment variable: the
  Vite `base` is a build-time value, and G3 requires one image for all
  installations. A small shared module exports `ADMIN_BASE = "/admin/"` and
  `PWA_BASE = "/app/"`; Core has the same two values in one Python module,
  checked equal by a contract test.
- What has to read the constant (hard-coded today; `/app/` appears in about
  86 files, most of them tests):
  - `apps/pwa/vite.config.ts` and `apps/web/vite.config.ts` (`base`)
  - PWA router prefixes (`apps/pwa/src/app.tsx`, `apps/pwa/src/modules.tsx`)
    and the web router prefix strip (`apps/web/src/app.tsx`)
  - service worker `apps/pwa/public/sw.js` (offline URL, precache list,
    scope check, `/app/assets/` cache rule) and its registration
    (`register("/app/sw.js", { scope: "/app/" })`)
  - `apps/pwa/public/manifest.webmanifest` (`start_url`, `scope`) and the
    links in `apps/pwa/index.html`, generated at build from the constant
  - Core `NavigationItem` hrefs in each module's `api.py`/`navigation.py`,
    and deep links in `application/activity_feed.py`
  - `apps/public` auth targets (`AuthPage.astro`, `invite.astro`), replaced
    by `landingPath` or the constants
  - the Caddy route table (`handle_path /app/*`, `/admin/*`, the per-path CSP
    header blocks) and the `@login` redirect matcher in §8
  - mail links into the apps (through the `LinkBuilder`, §7.6)
  - tests and browser proofs that use the literal paths
- Cookie paths are not affected: `__Host-leonaid_session` must have `Path=/`.
- **When the rename happens:** the old path keeps a 308 for its whole tree
  (`/app/*` → `/<new>/*`, query kept) on the admin host, and the public
  host's existing `/app/*` redirect points at the new path. The old service
  worker at scope `/app/` would otherwise keep serving its cached shell
  offline, so the old path's `sw.js` is served as a self-unregistering
  worker (`self.registration.unregister()`, then `client.navigate` to the new
  base) for at least one release. Installed home-screen icons keep their old
  `start_url`; they follow the 308 but open in the browser, so acquirers
  reinstall once.
- **Reinstall at the host switch:** stage 1 itself moves the PWA origin (old
  host → `app.<domain>`). That already forces one reinstall and needs the
  same self-unregistering worker at the old host's `/app/sw.js`. If the club
  wants the rename, doing it in the same release as the stage-1 switch costs
  one reinstall instead of two. Recommendation: fix the final PWA path
  before the stage-1 go; if undecided, keep `/app/`.

## 7. Stage 2 — campaign hosts (target B)

### 7.1 Behaviour

- Only the **system admin** adds, checks, assigns and removes domains
  (decision D5): DNS and domain costs are club-level. The UI lives in the
  system area ("Domains"), not in the action. Action managers see their
  action's public URLs read-only on the action page.
- The system admin adds a host: `weihnachtsmarkt.domain.org`,
  `krapfentaxi.org`, `www.krapfentaxi.org`, `lionsopen.de`.
- LeonAid shows the DNS records to create (A/AAAA to the server, or CNAME to
  the admin or public host for subdomains) and a **Prüfen** button.
- The check (§7.4) proves the host points to this server. Only then the host
  becomes `verified`; Caddy may then obtain a certificate on the first
  request. A verified host works at once, without a restart (decision D7).
- A host is either a **campaign host** (has bindings) or a **redirect host**
  (`www.krapfentaxi.org` → `krapfentaxi.org`, whole host, path kept, 308).
- The system admin **binds** actions to a campaign host. Each binding has an
  edition segment (`2025`); at most one binding per host holds the root `/`.
  The routing rules, the archive behaviour after a campaign ends and domain
  reuse by a follow-up campaign are in §7.7.
- The old path `https://domain.org/campaigns/<slug>/` and every alias of the
  action redirect to the action's canonical URL (§7.7.3, 302 to a host root,
  else 308) once the action has a live binding on an `active` host. The spike shows the page also renders under the old path on the
  campaign host (duplicate content); that path must redirect to the
  canonical URL (§12.4).
- A campaign host serves only the editions bound to it. Any other campaign
  path, any alias of another action, `/_emdash/*`, `/admin`, `/app` and
  non-public `/api/*` return 404 (spike: other campaign → 404, `/_emdash` →
  404).
- Removing a host or a lapsing domain: §7.7.6.

### 7.2 Request flow

```
Browser ──TLS (SNI lionsopen.de)──▶ Caddy
  known site block?  admin / public host ─▶ as stage 1
  otherwise          on-demand TLS: ask http://api:8000/internal/tls/ask?domain=lionsopen.de
                     ├─ 2xx: certificate (ACME HTTP-01/TLS-ALPN-01), then proxy
                     └─ else: TLS handshake fails (spike: "tlsv1 alert internal error")
  /_actions/createPublicOrder, /api/v1/public/*, legal pages, static public files ─▶ public / api
  everything else ─▶ campaign-site:3000 (Host, X-Forwarded-Host/Proto set)
campaign-site middleware (first in the sequence, before the closed guard):
  site = Core GET /api/v1/public/sites/{host}   (cached 30 s, negative cache 30 s)
  unknown → 404; redirect host → 308 https://<target>{path}
  resolve path against the host's bindings (§7.7.2):
    serve edition  → next("/campaigns/<slug>/<rest>?query")
    redirect       → 302/308 to the edition's canonical URL
    no match       → 404
closed guard → [slug].astro: canonical/og:* from the binding, on <host>
```

The spike implemented the root case of this rewrite with Astro `next(url)`
inside a `sequence()` placed before the existing closed guard
(`apps/campaign-site/src/closed-bootstrap.ts`). The guard then sees the
mapped path, so its rules (method allow-list, preview refusal, order POST
admission) apply unchanged. Astro 7.4.4 `sequence` carries the rewrite to
the following handlers and the page (`node_modules/astro/dist/core/middleware/sequence.js`).
A segment path (`/2025/`) uses the same rewrite with a different source
prefix; the native order POST posts to the page's own URL
(`/2025/?_action=createPublicOrder`) and is rewritten the same way.

### 7.3 Data model (migration sketch)

Two tables: `site_host` holds what belongs to a hostname (verification,
certificate approval, redirect host). `site_binding` holds the mapping of
(host, edition segment) to an action, with history.

```python
# migrations/versions/00xx_site_hosts.py
op.create_table(
    "site_host",
    sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    # Lowercase IDNA A-label, no port, no trailing dot, <= 253 chars.
    sa.Column("hostname", sa.Text(), nullable=False),
    # pending -> verified -> active ; any -> disabled ;
    # disabled -> verified (re-check passes, bindings live) | pending (re-add after removal)
    sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
    # Redirect host (www.) -> target host, whole host, path kept. NULL = campaign host.
    sa.Column("redirect_to_host_id", sa.UUID(), sa.ForeignKey("site_host.id", ondelete="RESTRICT")),
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
    sa.CheckConstraint("redirect_to_host_id IS NULL OR redirect_to_host_id <> id", name="ck_site_host_redirect_self"),
    sa.CheckConstraint("revision > 0", name="ck_site_host_revision"),
)
op.create_index("uq_site_host_hostname", "site_host", ["hostname"], unique=True)

op.create_table(
    "site_binding",
    sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
    sa.Column("site_host_id", sa.UUID(), sa.ForeignKey("site_host.id", ondelete="RESTRICT"), nullable=False),
    sa.Column("action_id", sa.UUID(), sa.ForeignKey("action.id", ondelete="RESTRICT"), nullable=False),
    # Path segment of this edition on the host: "2025", "lions-open-2025". Never empty.
    sa.Column("edition_segment", sa.Text(), nullable=False),
    # This edition owns "/" while it is the host's current edition (§7.7.2).
    sa.Column("at_root", sa.Boolean(), nullable=False, server_default=sa.false()),
    # Canonical binding of the action when it has live bindings on several hosts.
    sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    # NULL = live. Set = history row; its path 308s to the action's current canonical URL.
    sa.Column("valid_to", sa.DateTime(timezone=True)),
    sa.Column("ended_reason", sa.Text()),
    sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("created_by", sa.UUID(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.CheckConstraint(r"edition_segment ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND length(edition_segment) <= 63",
                       name="ck_site_binding_segment"),
    sa.CheckConstraint("(valid_to IS NULL) = (ended_reason IS NULL)", name="ck_site_binding_history"),
    sa.CheckConstraint("ended_reason IS NULL OR ended_reason IN "
                       "('segment_changed','unbound','host_removed')",
                       name="ck_site_binding_ended_reason"),
    sa.CheckConstraint("valid_to IS NULL OR NOT at_root", name="ck_site_binding_history_not_root"),
    sa.CheckConstraint("revision > 0", name="ck_site_binding_revision"),
)
live = sa.text("valid_to IS NULL")
# One current edition per host.
op.create_index("uq_site_binding_root", "site_binding", ["site_host_id"], unique=True,
                postgresql_where=sa.text("at_root AND valid_to IS NULL"))
# A segment names one live edition per host.
op.create_index("uq_site_binding_segment", "site_binding", ["site_host_id", "edition_segment"], unique=True,
                postgresql_where=live)
# An action appears at most once per host.
op.create_index("uq_site_binding_host_action", "site_binding", ["site_host_id", "action_id"], unique=True,
                postgresql_where=live)
# One canonical binding per action.
op.create_index("uq_site_binding_primary", "site_binding", ["action_id"], unique=True,
                postgresql_where=sa.text("is_primary AND valid_to IS NULL"))
# History lookup for old paths.
op.create_index("ix_site_binding_history", "site_binding", ["site_host_id", "edition_segment", "valid_to"],
                postgresql_where=sa.text("valid_to IS NOT NULL"))
```

- The admin host and the public host stay in environment variables, not in
  the tables: they must work before the database exists, and Caddy needs them
  as static site blocks. Path-based campaigns on the public host keep using
  `/campaigns/<archive-slug>/` and `public_action_alias`; they need no
  binding row.
- Domain-layer rules, not expressible as SQL constraints: a hostname equal to
  the admin or public host, one of the public host's aliases, or below the
  admin host (`*.app.domain.org`) is refused; a redirect host has no live
  bindings and its target is a campaign host, not another redirect host; an
  edition segment must not be a reserved first path segment on campaign
  hosts (`archive`, `campaigns`, `_campaign-assets`, `_actions`, `_astro`,
  `_image`, `_emdash`, `api`, `impressum`, `datenschutz`, `surveys`,
  `robots.txt`, `sitemap.xml`, plus `RESERVED_PUBLIC_ALIASES` in
  `src/leonaid/domain/actions.py`).
- Bindings are never updated in place for segment or host. A segment change
  retires the row (`valid_to`, `ended_reason='segment_changed'`) and inserts a
  new live row, which takes over `at_root` and `is_primary` (a history row
  never holds the root); only `at_root` and `is_primary` flip in place (with
  `revision` + 1). A second binding of the same action on another host is
  created with `is_primary = false`.
- Commands follow `campaign_aliases.py`: idempotent command id, revision
  check, `require_system_admin` (decision D5), audit entry. Commands:
  `AddSiteHost`, `CheckSiteHost`, `SetRedirectHost`, `BindEdition`,
  `ChangeEditionSegment`, `MoveRootToEdition` (§7.7.4), `UnbindEdition`,
  `RemoveSiteHost`. Downgrade refuses existing rows, like 0028.
- Actions are never deleted today (no delete command; archived actions are
  immutable), and the `RESTRICT` foreign key keeps it so. If deletion of
  drafts is added later, a draft's bindings are deleted with it: a draft was
  never public, so it has no URLs to keep.
- Public read endpoint `GET /api/v1/public/sites/{hostname}` returns, for an
  `active` host only: `{kind: "campaign" | "redirect", redirectTo?,
  editions: [{segment, atRoot, archiveSlug, availability, canonicalUrl,
  title, endedAt?}], history: [{segment, targetUrl}]}`. A host has a handful
  of editions, so the whole list fits one cached response; history rows of
  the same segment collapse to the newest.
- Internal endpoint `GET /internal/tls/ask?domain=` (§9.1), not routed by
  Caddy to the internet. It approves `verified` and `active` campaign and
  redirect hosts.

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

- Canonical and `og:url` = the action's canonical URL (§7.7.3), built from
  the binding, never from the request path (spike: works for the root case).
- `og:image` absolute on the same host. Campaign media stays at
  `/campaigns/<slug>/media/<id>` on the campaign host (served by the same
  route, allowed for every edition bound to that host, live or history) — no
  `/_emdash/image` is used by public pages (spike resource list, §12.3).
- `robots.txt` and `sitemap.xml` per host: today they are internal-only CMS
  routes (`apps/campaign-site/route-contract.mjs`). New small endpoints:
  campaign host → its edition list page and each edition's canonical URL
  (root for the current edition while it runs, `/<segment>/` for the
  others); public host → home and the canonical URLs that live on the public
  host. Redirecting URLs (history, `/campaigns/<slug>/`, aliases) are never
  listed.
- Impressum and Datenschutz (decision D4): one content per installation, for
  all hosts. No such page exists yet in `apps/public`. Add `/impressum` and
  `/datenschutz` to `apps/public`, linked in the footer of
  `PublicLayout.astro` and of the campaign page, rendered from the active
  legal configuration (migration 0023), served on every site host and on
  the admin host.

### 7.6 Mail links

| Mail                                   | Link host                                                     |
| -------------------------------------- | ------------------------------------------------------------- |
| Magic login, invitation, e-mail change | admin host (`sessions.py`, `invitations.py`, `email_changes.py`) |
| Invoice delivery                       | admin host if it links at all; the PDF is attached             |
| Survey invitation                      | public host (`surveys.py` line 908); admin host when there is no public host (§6.6) |
| Order confirmation (customer)          | the action's **edition URL** on its primary campaign host (decision D8), else the public host path, else no link |

The order confirmation links the permanent edition URL
`https://lionsopen.de/2025/`, not the root. While 2025 is the current
edition, `/2025/` 302s to `/` (§7.7.2); after the domain moves to 2026, the
same link still shows 2025.

A small `LinkBuilder` in Core (`admin_url(path)`, `site_url(action_id,
path)`, `edition_url(action_id)`) replaces the string concatenations; it
reads `site_binding` at send time and the base paths from the constants of
§6.7.

### 7.7 Recurring campaigns and domain reuse (decision D6)

Björn's decisions: after a campaign ends, its domain redirects to the
archive page. A recurring campaign reuses the domain: Lions Open 2025 →
Lions Open 2026 on `lionsopen.de`; the new edition gets the domain, and the
old edition must stay reachable, for example at `lionsopen.de/2025/`.

#### 7.7.1 Alternatives

| | Model | Old edition after reuse | Verdict |
| --- | --- | --- | --- |
| **A** | Host + edition segment → action (`site_binding`), one edition holds `/`, history rows | stays on the same host at `/<segment>/`; its URL never changes | **recommended** |
| B | Host → one action; reassignment moves the host, old edition falls back to the public host path | `domain.org/campaigns/lions-open-2025/` | rejected: breaks without a public host (D3), moves old links to another host, loses the domain's history |
| C | New `campaign_series` entity owns the domain; editions are actions linked to the series | `/<segment>/` like A | rejected for now: same URLs as A, plus a new aggregate, admin screens and migrations. The host already identifies the series |

Why A: it handles every case with one table and two flags. The URL of an
ended edition is fixed from the day the campaign ends and never changes
again, also not when the domain moves on. Without a public host (§6.6) it
is the only option that keeps old editions online. Reuse needs no copy or
move of data, only flipping one flag. A series entity (C) can be added later
for "copy last year's campaign" without changing URLs; it is not needed for
routing.

#### 7.7.2 Routing on a campaign host

Each live binding has a fixed `edition_segment`. The default is the year of
the action's publication start (`PublicationWindow.starts_at`), or the
archive slug when that year is already used on the host. The system admin
can change it while binding. "Running" means public availability `active`;
"ended" means availability `archive` (status `completed` or `archived`).
"Not yet public" covers drafts, scheduled actions and an active action
outside its publication window.

| Request | Rule |
| --- | --- |
| `/` | root edition **running** → serve it. Otherwise 302 (temporary, `/` is reusable) to the fallback edition: the running edition on this host, else the most recently ended one. No edition public → 404 page with legal links |
| `/<segment>/…` live, root edition and running | 302 to `/…` (query kept). Temporary on purpose: a cached 308 would later send `/2025/` to the 2026 edition. The segment URL is permanent; `/` is canonical while the edition runs |
| `/<segment>/…` live, any other case | serve the edition (archive page when ended; order form when running) |
| `/<segment>/…` only in history | 308 to that action's current canonical URL (may be another segment, another host, or the public host path) |
| `/archive/` | edition list of this host: all live editions with title, period and link, newest first |
| `/archive/<archive-slug>` | 308 to that edition's canonical URL when it is bound to this host, else 404 |
| `/campaigns/<slug>/` | 308 to the canonical URL of that edition when bound to this host, else 404. Media below `/campaigns/<slug>/media/` is served, not redirected |
| anything else | 404 |

"308" in this table and in every redirect to a canonical URL (aliases,
public host paths, history) becomes **302 when the target is a host root**
(§7.7.3, redirect code rule).

"After the end the domain redirects to the archive page" (D6) falls out of
these rules without a data change: when Lions Open 2025 completes, `/` 302s
to `/2025/`, which renders the archived campaign. Every edition page shows a
"Frühere Ausgaben" link to `/archive/` when the host has more than one
edition. A one-off campaign (`krapfentaxi.org`) behaves the same: after the
end `/` 302s to `/2026/`, and the domain is ready for reuse.

#### 7.7.3 Canonical URL of an action

1. Live primary binding on an `active` host, `at_root`, running →
   `https://<host>/`.
2. Live primary binding on an `active` host otherwise →
   `https://<host>/<segment>/`.
3. No live binding, public host configured → `https://<public host>/campaigns/<archive-slug>/`
   (or the alias page for non-CMS actions, as today).
4. None of these → no public URL (§6.6).

**Redirect code rule.** A host root is reused by the next edition, so a
redirect to `https://<host>/` is always 302; browsers must not cache it.
Redirects to a segment URL or a public host path are 308: those URLs never
change their meaning. Example: while 2025 runs, `/campaigns/lions-open-2025/`
302s to `lionsopen.de/`; after the end it 308s to `lionsopen.de/2025/`.

The alias resolver (`apps/public/src/lib/campaign-redirect.ts`), the public
home list (§6.5), sitemaps, mails and the history redirects all use this one
function in Core. It is returned in `canonicalUrl` by the public endpoints.

#### 7.7.4 Moving the domain to the follow-up campaign

Admin UI, system area → Domains → `lionsopen.de`:

- Shows the editions: `2026 — Lions Open 2026 — geplant`,
  `2025 — Lions Open 2025 — beendet — aktuell auf /`.
- Action **"Domain an Folgeaktion übergeben"**: pick the follow-up action
  (any non-ended action; it is bound now if it is not yet), confirm or edit
  its segment, and see a preview before confirming:
  - `lionsopen.de/` → Lions Open 2026 (from its publication start; until
    then `/` keeps pointing to the newest public edition)
  - Lions Open 2025 → `lionsopen.de/2025/` (unchanged if already ended)
  - aliases and `/campaigns/lions-open-2025/` → `lionsopen.de/2025/`
  - order confirmations already sent link `/2025/` and stay valid
- One command `MoveRootToEdition(host, action, segment)`: in one
  transaction, bind the action if needed, clear `at_root` on the old
  binding, set it on the new one (the partial unique index forbids two
  roots), audit both. Idempotent by command id; revision-checked on the host.
- The follow-up can be prepared early: binding a scheduled action at root
  is allowed, and `/` keeps its 302 fallback until the new edition is public
  (§7.7.2). Nothing changes publicly on the day of the switch except
  through the publication window.

#### 7.7.5 Edge cases

- **Two editions running at once** (2026 already open while 2025 still
  takes late orders): allowed with a warning in the preview. 2025 is served
  at `/2025/` and still accepts orders; order tokens bind to the alias, not
  the URL. `/` shows 2026.
- **Segment change** (`2025` → `lions-open-2025`): history row; `/2025/…`
  308s to the new segment. A retired segment can be reused by another
  edition later; the live binding then wins over history. The UI warns,
  because old links would then show the other edition.
- **Unbinding one edition** (`UnbindEdition`): history row; its paths 308 to
  the action's next canonical URL (public host path or nothing → 404). An
  action at root cannot be unbound while it is the only edition of a host
  unless the admin confirms that `/` then 404s.
- **Same campaign on two hosts** (`krapfentaxi.org` and
  `krapfentaxi.domain.org`): prefer a redirect host. If both must serve,
  both get bindings and `is_primary` picks the canonical one; the other
  serves the same page with the canonical link pointing to the primary.
- **Deleting a campaign:** not possible today (§7.3). Archived actions stay,
  so their URLs stay.
- **Old path campaigns on the public host:** `/campaigns/<slug>/` and
  aliases follow §7.7.3; when the action has a live binding they redirect
  to the campaign host (302 to a root, else 308).

#### 7.7.6 Removing a domain, lapsed domains

- **Remove** (`RemoveSiteHost`, system admin): the preview lists every live
  edition and its new canonical URL (public host path, or "not publicly
  reachable" without a public host). On confirm, all live bindings become
  history (`ended_reason='host_removed'`), the host becomes `disabled`, and
  `ask` stops approving it. The row stays for audit and so the hostname can
  be re-added later (`disabled` → `pending`, new token). Old links on that
  host cannot be served anymore; that is the price of dropping the domain.
  Aliases and public host paths keep working.
- **Lapsed or moved DNS** (nightly check, §7.4): the host becomes
  `disabled`, bindings stay live but are not served, and canonical URLs fall
  back to rule 3 of §7.7.3. The nightly job keeps checking a disabled host
  that still has live bindings; a successful check sets it `verified` again
  and the TLS self-check `active`. The operations view shows the failure.

#### 7.7.7 Migration from today's aliases

- No data migration. `public_action_alias` stays the path namespace of the
  public host; `site_host` and `site_binding` start empty.
- Every existing alias and `/campaigns/<slug>/` URL keeps resolving; once an
  action gets a live binding, it redirects to the canonical URL (redirect
  code rule of §7.7.3; at most two hops: alias → canonical, plus the root
  fallback 302 of §7.7.2 when the target is a root without a running
  edition).
- For a club that already ran a campaign twice under two archive slugs
  (`lions-open-2025`, `lions-open-2026`), the system admin binds both to the
  new host, the older one with segment `2025`, the newer one at root.

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
	# Browsers do not follow a redirect for a service worker script, so the
	# old PWA worker is replaced by a self-unregistering one served here (§6.7).
	handle /app/sw.js {
		import retired_service_worker
	}
	# Paths come from the base-path constants (§6.7) via the route table.
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
	# / : role-based entry, served by public:3000 (§6.7).
	# /impressum, /datenschutz: public:3000.
	# With a public host: /campaigns/*, /surveys/* and other public paths
	# 308 to the public host.
	# Without a public host (§6.6): /surveys/* served by public:3000;
	# /<alias>, /archive/<slug>, /campaigns/<slug>/ go to public:3000, which
	# only answers 308 to the canonical URL or 404.
}

# Omitted by the generator when LEONAID_PUBLIC_DOMAIN is empty (§6.6).
# LEONAID_PUBLIC_DOMAIN_ALIASES (www.) get a block that 308s to it.
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
	# Host lookup, redirect hosts, root / segment / history / archive rules: §7.7.2.
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
  (`apps/public/src/lib/campaign-redirect.ts`) extend to "target is the
  action's canonical URL from Core" (§7.7.3); history redirects take their
  target from the same function, never from the stored row alone.
- `returnTo` handling after login stays path-only on the admin host and must
  start with the admin or PWA base path (§6.7).
- The role-based entry `/` redirects only to `landingPath`, a server-computed
  path from the constants of §6.7.

### 9.6 Content Security Policy

`'self'` is per host, so nothing changes. Cross-host resources are not used
(spike: 0 CSP violations on both hosts, JS on and off).

## 10. Operations

### 10.1 DNS, ports, ACME

- Admin host (`app.<domain>`) and public host (if any, plus `www.`): A/AAAA
  records to the VPS, as today for the one host.
- Campaign subdomain: CNAME to the admin or public host, or A/AAAA.
- Own domain: A/AAAA at the apex (`krapfentaxi.org`) and for `www`. Registrar
  "web forwarding" products do not work (they terminate HTTP elsewhere).
- Ports 80 and 443 must stay open to the internet (already published,
  `infra/pilot/compose.yml`). Port 80 serves the host check and HTTP-01;
  TLS-ALPN-01 runs on 443.
- CAA records, if the domain has any, must allow `letsencrypt.org`.
- Certificates live in the Caddy data volume. It is persistent and, since
  stage 1, part of every pilot backup (`caddy-data.tar`, restored into the
  target's volume), so a restore needs no new issuance and does not hit the
  stage-2 `ask` limit. Each host costs ~10 KB and one renewal every ~60 days.

### 10.2 Pilot install

- `production.env.example`: `LEONAID_ADMIN_DOMAIN=app.example.org`,
  `LEONAID_PUBLIC_DOMAIN=example.org`, optional
  `LEONAID_PUBLIC_DOMAIN_ALIASES=www.example.org`, derived base URLs and
  origin lists. The installer refuses an admin domain equal to the public
  domain or one of its aliases, and refuses an empty public domain unless
  stage 2 is enabled (§6.6).
- The pilot readiness check (`tools/pilot_readiness`) gains: every configured
  host resolves to this server; port 80 reachable for each.
- Runbook (`infra/pilot/LIVE-PILOT-RUNBOOK.md`): "Domain hinzufügen" steps,
  what the club does at its registrar, how long ACME takes, how to read the
  check result.

### 10.3 Resource cost

No new container. One indexed lookup per new TLS handshake for an unknown
SNI and one cached Core lookup per 30 s per host in the campaign site. No
measurable memory impact on the 8 GB VPS.

## 11. Migration of existing aliases and links

- Stage 1 switch (decision D1): the existing single host becomes the public
  host; all existing alias and `/campaigns/` URLs keep working unchanged. The
  new admin host is `app.<domain>`. Admin paths on the old host 308 to the
  new admin host. Members get one notice; sessions start fresh on the admin
  host (host-only cookie); acquirers reinstall the PWA once (§6.7).
- Stage 2 per action: aliases stay in `public_action_alias`, unchanged.
  When an action gets a live binding on an `active` host, the resolver returns the canonical URL
  (§7.7.3) as `redirectPath`/canonical, so `/krapfentaxi` and
  `/campaigns/krapfentaxi-2026/` on the public host redirect to
  `https://krapfentaxi.org/` (302, while it runs) or `/2026/` (308, after the
  end). Disabling the host
  reverts automatically. Details and recurring campaigns: §7.7.7.
- Printed QR codes keep pointing at the public host alias; the redirect chain
  is at most two hops (alias → canonical URL).
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

## 13. Decisions (Björn, 2026-11-03)

| # | Question | Decision | Where |
| --- | --- | --- | --- |
| D1 | Does today's host become the public or the admin host? | **Public host.** The admin host is new; all printed and mailed public links stay valid. | §6.2, §11 |
| D2 | Admin host name? | **`app.<domain>`** (`app.example.org`). `/` on it is a role-based entry: one login for everyone, then the view for the user's role; deep links survive login; several roles get a default plus a switch; with an acquirer role the default is the acquisition app. Base paths `/admin/` and `/app/` stay in stage 1 but come from one constant each, so `/app/` can be renamed later with 308s. | §6.1, §6.7 |
| D3 | Home page of the public host? | **Lists all active campaigns.** A club may have **no** general public host, only campaign hosts; then legal pages and the public API work per campaign host, and the admin host takes surveys and alias redirects. | §6.5, §6.6 |
| D4 | One Impressum/Datenschutz for all domains? | **Yes**, one club, one content. | §3, §7.5 |
| D5 | Who may add domains? | **System admin only.** | §7.1, §7.3 |
| D6 | Campaign domain after the end; recurring campaigns? | After the end the domain **redirects to the archive page**. A follow-up campaign can **take over the domain**; old editions stay reachable on the same host at `/<segment>/`. | §7.7 |
| D7 | Catch-all Astro host pattern guarded by Core? | **Accepted.** New domains take effect immediately. | §6.3, §9.2 |
| D8 | Order confirmation link? | **Campaign domain** (the permanent edition URL). | §7.6 |

Follow-up decision needed before the stage-1 go: the final PWA path
(`/app/` or a new name), so acquirers reinstall only once (§6.7).
**Ruled 2026-11-07 (lead, for Björn): keep `/app/`.** Nobody has installed
the PWA yet, so the host switch costs no reinstall and stage 1c is dropped.

## 14. Test plan

| Level        | Tests                                                                                                                                                       |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unit (Python) | hostname normalization/IDNA/rejections (port, trailing dot, IP literal, admin/public host, public host alias, subdomain of admin host); edition segment validation and reserved segments; command revisions and system-admin requirement; `MoveRootToEdition` atomicity; canonical URL function (§7.7.3) for every rule; `landingPath` per role combination and `preferred_surface`; `ask` decisions and rate limit; LinkBuilder per mail type (edition URL for order confirmations); CSRF two allowlists incl. dynamic campaign hosts |
| Unit (TS)    | `hasSecureAdminOrigin`/`hasSecureSiteOrigin`; host resolution table of §7.7.2 (root running/ended/not yet public, live segment at root → 308, live segment, history → 308, `/archive/`, `/campaigns/<slug>/` → 308, media served, other campaign → 404, `/_emdash` → 404, redirect host); runtime allowed-domains list patch; canonical builder; base-path constants used by router, SW and manifest |
| Contract     | OpenAPI for `site_host`/`site_binding` commands, `/api/v1/public/sites/{host}`, `/api/v1/public/campaigns`, `landingPath`; migration up/down with refusal; partial unique indexes (two roots, duplicate live segment, two primaries) rejected by PostgreSQL; TS and Python base-path constants equal |
| Integration  | new `test-emdash-spike --case multi-host` derived from this spike: V1 probe table §12.3 as assertions, plus redirects of aliases to the canonical URL, plus a two-edition scenario (2025 ended at `/2025/`, 2026 at `/`, move root, segment change) and a no-public-host scenario |
| Caddy        | `tools/proxy/validate-caddyfiles.sh` for single-host, admin + public, and admin-only (no public host) variants; on-demand probe of §12.2 (approved, unknown, `ask` down, SNI/Host mismatch); retired `/app/sw.js` served, not redirected |
| Browser      | existing `public-order-component-proof.mjs` parametrized by base URL (campaign host root, campaign host segment, public host path), three engines, JS on/off, CSP guard; public home list |
| E2E          | admin: add host → check → active → bind → move root to follow-up; Live View opens the campaign host; `/` on the admin host: logged out → login, acquirer → PWA, admin → admin web, deep link through login; PWA install and old-worker unregistration |
| Pilot        | readiness check resolves hosts and port 80; manual ACME acceptance on a real test subdomain before the first own domain                                   |

## 15. Effort estimate

Developer days, including tests and docs, excluding Björn's review time.
Updated 2026-11-03 for decisions D1–D8.

| Stage | Scope                                                                                                     | Before | Now        |
| ----- | --------------------------------------------------------------------------------------------------------- | ------ | ---------- |
| 0     | Enable the CMS in the pilot (`emdash` profile, `EMDASH_SITE_URL`) — prerequisite                           | 1–2 d  | 1–2 d      |
| 1     | env + installer, Caddy site blocks generated from one route table (prod + dev, with and without public host), origin split CMS, allowed-domains list, canonical, Core public allowlist, mail link builder, Live View link, redirects, tests, runbook | 5–7 d | 5–7 d |
| 1a    | Public home page with active campaigns (§6.5)                                                              | —      | 1 d        |
| 1b    | Role-based entry on `app.<domain>`: `landingPath` in Core, entry route, switch + `preferred_surface`, deep-link tests; base-path constants wired through PWA, web, Core navigation, Caddy table; retired service worker (§6.7) | — | 3–4 d |
| 1c    | Optional, later or with the stage-1 switch: rename `/app/` (≈86 files, mostly tests) with 308s             | —      | 1–2 d      |
| 2     | `site_host` + `site_binding` migration/domain/commands/API, system-admin UI "Domains" with editions and move-to-follow-up preview, host check + nightly job, `ask` endpoint + rate limit, Caddy on-demand block, CMS host middleware with segment/history/archive rules + 308s, canonical URL function, per-host edition list, sitemap/robots, Impressum/Datenschutz pages, alias redirect to canonical URL, no-public-host mode (admin host surveys and redirects, dynamic public origins), multi-host spike case incl. two editions, browser tests, ops docs | 12–16 d | 17–22 d |

Total without 1c: 27–36 d (was 18–25 d). The increase comes from the
role-based entry (D2), recurring campaigns with domain reuse (D6, about
+4 d) and installations without a public host (D3, about +1–2 d). D5
(system admin only) and D7/D8 change nothing.

Stage 2 depends on stage 1. A club without a public host needs stages 1 and
2 together (§6.6). Real-ACME acceptance needs one real test subdomain and
one test domain owned by the club.

## 16. Implementation status and rulings

### 16.1 Stages 0 and 1 (PR `md/stage0-1`)

| Item (§6.4) | Where |
| --- | --- |
| Route table, generated Caddyfiles (pilot + dev, one host and split) | `tools/proxy/caddyfiles.py` → `infra/pilot/Caddyfile{,.split}`, `infra/proxy/Caddyfile{,.split}`; `LEONAID_PROXY_CADDYFILE` selects the file |
| Routing proof against a running Caddy | `tools/proxy/routing-test.sh` + `routing_proof.py` (pilot single, pilot split with alias, dev split); `./leonaid check` and the CI lint job |
| Origin split CMS | `apps/campaign-site/src/auth/public-origin.ts`: `hasSecureAdminOrigin`, `hasSecureSiteOrigin`, `siteOriginOf` |
| Allowed domains list | `apps/public/runtime-allowed-domains.mjs` (several variables, comma/space lists, port ignored) |
| Canonical / Open Graph | `[slug].astro` uses the validated site origin |
| Live View | `leonaidLiveUrl` (absolute, public host) in `apps/campaign-site/src/middleware.ts`; patch regex in `emdash-editor-patch.mjs` |
| Core public allowlist | `LEONAID_PUBLIC_ORIGINS`, `StaticPublicOrigins` behind the `PublicOrigins` protocol (`security.py`); CORS without credentials on `/api/v1/public/*` only |
| Mail link builder | `src/leonaid/application/links.py` (`admin_url`, `site_url`); `LEONAID_SITE_BASE_URL` |
| Installer/env | `pilot-secrets --public-domain … [--admin-domain …] [--alias …] [--single-host]`; `production.env.example`; pilot contract (`validate.py`) and doctor checks |
| Stage 0 CMS in the pilot | `campaign-site` release image, pilot compose service (profile `emdash`, `EMDASH_SITE_URL` = admin origin), `LEONAID_CMS_ENABLED`, `release-manifest-cms.json` (schema 2), backup/restore topology `emdash` |

### 16.2 Rulings

- R1: the admin host also serves `/_astro/*`, `/favicon.svg` and the two
  `community-routes` images of `apps/public`. The sign-in pages need them, and
  a cross-host redirect of a stylesheet or script would break `'self'` CSP.
  §6.2 listed them as 308.
- R2: `/` on the admin host 302s to `/admin/` until stage 1b ships the
  role-based entry; the web app already forwards acquirers to the PWA.
- R3: Caddy reads `LEONAID_PUBLIC_DOMAIN_ALIASES` as site addresses, which
  need ", " between names. The env value therefore uses ", "; the pilot
  contract rejects a bare comma, and every LeonAid parser accepts commas
  and spaces.
- R4: the dev split uses `app.localhost` (admin) and `localhost` (public);
  `proxy:8443` stays an admin name for in-network tests and the healthcheck.
  Aliases have no dev equivalent. Plain HTTP in dev split mode only answers
  `/_health`.
- R5: `LEONAID_PUBLIC_BASE_URL` keeps its name and now means the admin base
  URL; the dev compose maps an optional `LEONAID_ADMIN_BASE_URL` to it.
- R6: the derived origin of `LEONAID_PUBLIC_BASE_URL` no longer carries the
  scheme's default port (`https://host:443` never matched a browser Origin).
- R7: production refuses a public origin that is also a credentialed admin
  origin.
- R8: the pilot TLS monitor (`PILOT_TLS_HOST`) checks every host: public,
  admin and aliases; the earliest expiry counts.
- R9: the campaign site adds 384 MiB. To keep the 1.5 GiB host reserve,
  `worker` (512→384), `twenty-worker` (1400→1280) and `survey-validator`
  (128→96) got lower limits, each well above its measured peak (DOC-P027).
- R10: both member pages and editor deep links keep using relative paths;
  admin links to a public campaign path rely on the 308 until stage 2 returns
  absolute canonical URLs.
- R11: the production CMS provisioning (database role, media bucket, editor
  setup) has no `pilot-*` command yet; `LEONAID_CMS_ENABLED` stays `false`
  until it exists. Open point for the launch.

### 16.4 Review of #97 (rv-md1)

- R14 (I1): Core accepts a public origin only when it names the request's own
  host (`same_host` in `security.py`); a page of the public host can never
  write to the admin host's public API with the admin cookies.
- R15 (M3): `LEONAID_PUBLIC_ORIGINS` is exactly the public host origin.
  Aliases 308 at the edge, so no page runs on them.
- R16 (I2): the public host block imports `public_host_headers`: HSTS without
  `includeSubDomains`, because the public host is usually the club's apex.
  Admin and single hosts keep `includeSubDomains`.
- R17 (I3): `caddy-data` is backed up and restored when the volume exists
  (pilot); `caddy-data.tar` is an optional, verified manifest entry.
- R18 (I5): the public host cannot ask who is signed in: the session is
  host-only on the admin host, the public host serves no identity API, and the
  build-time CSP (`connect-src 'self'`) forbids a cross-host request. The
  header shows a static "Anmelden" link to the admin host there and sends no
  identity request; the admin host and single hosts keep the personal links.
- R19 (M1): the admin host refuses every Astro form action
  (`?_action=…`) before any page route (rewrite to a 404 handler).
- R20 (M8): the public host serves a self-unregistering worker at
  `/app/sw.js` (no redirect); stage 1b moves it to the base-path constant.
- R21 (M9): `infra/pilot/Caddyfile.admin-only` is generated and proven; the
  pilot contract refuses it until stage 2 (no campaign hosts yet).
- R22 (M5): `./leonaid pilot-revoke-sessions` signs every member out after
  the switch; the install guide has a "Switch to an admin host" section.
- R23 (M6): `pilot-doctor` probes every alias (certificate, 308 to the public
  host) and port 80 (`/_health`) of every host.
- R24 (M7): the dev compose takes `LEONAID_ALLOWED_ORIGINS` from the
  environment; the dev split sets only the admin origin there.
- Open: the split-mode stack proof (`./leonaid test-multi-host`) runs public
  app, Core and web/PWA behind `Caddyfile.split`, without the CMS. The CMS
  part (native order POST on the public host, Live View in the editor) needs
  the EmDash spike harness and follows with stage 2's `multi-host` case.

