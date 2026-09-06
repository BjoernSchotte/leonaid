# Same-origin route ownership

Scope: EmDash 0.36.0, Astro 7.1.3 and the current two-application spike.
This inventory distinguishes proxy assignment from completed feature proof.

| Path | Owner at the edge | Contract |
| --- | --- | --- |
| `/api/*` | Core API | Existing session, domain and order API; unchanged |
| `/admin/*`, `/app/*` | Existing web/PWA services | Existing navigation remains |
| `/_emdash`, `/_emdash/*` | campaign-site | Preserve prefix; includes editor, setup, API, media, preview and image transforms; currently default-denied |
| `/campaigns`, `/campaigns/*` | campaign-site | Canonical microsites and future scoped form transport; renderer still pending |
| `/_campaign-assets/*` | campaign-site | Built JS, CSS, images and local fonts; byte-verified by the proxy test |
| `/_astro/*` | apps/public | Existing public assets; never globally assigned to CMS |
| `/_image` | apps/public | Existing public image optimization |
| `/_actions/*` | apps/public | Existing Astro Actions; no CMS action namespace is implicitly shared |
| `/_server-islands/*` | apps/public | CMS deferred server islands are not supported in the spike |
| `/robots.txt`, `/sitemap.xml`, `/sitemap-*.xml` | apps/public | Do not expose EmDash's competing root SEO endpoints; campaign-aware public SEO remains part of EMS-050 |
| `/.well-known/*` | Existing public handling | No EmDash OAuth discovery or identity provider; do not redirect all well-known paths to CMS |
| Login, aliases, archives and other paths | apps/public | Core remains authoritative; canonical migration follows EMS-082/085 |
| CMS `/health/live`, `/health/ready` | Internal only | Never expose CMS health via the public catch-all |

Both Caddy files contain the same explicit CMS path matcher. Absence of the
optional service affects only those assigned paths; Caddy has no CMS startup
dependency. Existing CSP remains unchanged. HTTPS, trusted forwarded headers,
pilot runtime and authenticated editor behaviour still require EMS-070 proof.

## Build inventory and drift protection

`apps/campaign-site/route-contract.mjs` checks the actual Astro resolved route
list during sync/build and writes a sanitized `dist/route-inventory.json` into
the image, outside its public client directory. Unknown root routes fail the
build. The CMS image endpoint is explicitly `/_emdash/image`; EmDash's wrapped
image entrypoint retains that configured route. Fonts follow `build.assets`.
The upstream font provider downloads at build time, not in visitors' browsers;
a transient download failure was observed and the subsequent build succeeded.
Do not use `fonts: false` without also resolving upstream's unconditional Astro
`Font` component: an absent registered CSS variable would break editor rendering.

Upstream injects root OAuth discovery routes even with `mcp: false`, plus root
SEO routes. Astro also injects a server-island endpoint without a deferred island
being used. These are inventoried but not exposed by the CMS proxy matcher.
Do not use `server:defer` or add CMS Astro Actions without assigning and proving
their distinct endpoint ownership first. Route assignment does not authorize
an operation: the default-deny/authentication/authorization layer must still
cover every exposed CMS handler.

## Form transport decision for the new renderer

Keep the existing `apps/public` Astro Actions intact. The campaign renderer will
use Core's existing order API through a campaign-scoped server form handler
under `/campaigns/<slug>/`; do not forward CMS forms to an action handler that
can only render the old application's page. Extract/reuse validation and order
submission logic instead of maintaining divergent price or permission rules.
The form handler must support no-JavaScript POST, retain entered values on
validation failure, and preserve idempotency, Core pricing and privacy checks.
This transport is a selected implementation contract, not yet implemented or
proven. EMS-050/085 must verify the real completed order journey.

## Verification scope

`./leonaid test-emdash-spike --case proxy-routing` starts real production Astro
images and the actual local Caddy configuration in a collision-checked unique
Compose project, with no published host ports. It checks generated asset bytes,
public login assets, closed CMS routes and continued public login rendering
after stopping the CMS. It does not substitute for authenticated login,
ordering, browser interaction, draft-media isolation or the pilot HTTPS gate.
