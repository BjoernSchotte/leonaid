# EmDash Campaign Microsite Spike — Implementation and Verification Plan

Status: implementation in progress; dependency checkpoint verified, live gates pending

Plan basis: LeonAid commit `5f5f52c`, 6 September 2026

EmDash source reviewed: `emdash` 0.36.0 at commit
`603062902369d9695608e85c2d034d4f66f7a1f1`

Primary product references:

- [`../produkt-und-architekturvorschlag.md`](../produkt-und-architekturvorschlag.md)
- [`../leonaid-poc/ARCHITECTURE.md`](../leonaid-poc/ARCHITECTURE.md)
- [`../leonaid-pilot/PLAN.md`](../leonaid-pilot/PLAN.md)
- [`../../PERSONAS.md`](../../PERSONAS.md)

> **Execution rule:** This is a bounded feasibility spike, not authorization to
> deploy to production. It includes migrating the Krapfentaxi demo and switching
> its entry route in the isolated worktree/demo environment. Implement each task in dependency
> order, run every named verification gate, and record evidence before checking
> a task off. Stop at any STOP condition instead of weakening authentication,
> campaign isolation, recovery, or the existing public-order journey.

## 1. Objective

Prove whether EmDash can provide editable campaign microsites inside the
existing LeonAid product without introducing a second user account or weakening
LeonAid's campaign-scoped authorization.

The spike succeeds when:

1. an active LeonAid user signs in once through the existing LeonAid login;
2. a `system_admin` or a user with an active `charity_admin` membership can open
   the EmDash admin on the same public origin without another login;
3. a Charity Admin can read and mutate microsite content only for campaigns for
   which that user has an active `charity_admin` membership;
4. suspended, archived, signed-out, unrelated, and non-admin users are denied
   immediately and fail closed;
5. public microsites combine editorial EmDash content with authoritative live
   data from LeonAid Core;
6. all campaign microsites are served below the same LeonAid domain;
7. HTTPS, first-run setup, backup, restore, upgrade, and failure behaviour are
   demonstrated with the real Docker Compose stack and real browser sessions;
8. the existing LeonAid admin shell, public aliases, order forms, and canonical
   archive routes continue to work.
9. the existing Krapfentaxi demo's editorial content is editable in EmDash;
   publishing an edit changes the anonymous Astro page without rebuilding;
10. authorized operators manage campaign redirect aliases in LeonAid Core and
    its existing admin UI, including `/krapfentaxi`.

The spike may also conclude that EmDash 0.36 is unsuitable. That is a valid and
useful result if the evidence shows that campaign-scoped authorization requires
a maintained EmDash fork, unsafe request interception, duplicated identities,
or another disproportionate mechanism.

## 2. Decisions fixed for the spike

### 2.1 LeonAid Core remains authoritative

LeonAid Core continues to own:

- `CharityAction` identity, lifecycle, publication window, alias, and archive
  slug;
- action memberships and the `charity_admin` role;
- carrier, dates, beneficiaries, goals, offerings, prices, order availability,
  order-form configuration, privacy text, and submissions;
- account status, login challenges, sessions, revocation, and audit decisions.

EmDash owns editorial presentation only:

- hero copy and media;
- structured content sections;
- campaign-specific visual choices selected from an allowlisted theme contract;
- partner presentation, FAQ, and editorial updates;
- SEO copy and social media images where those do not contradict Core state.

Do not duplicate prices, offerings, order availability, legal text, action
status, or action-role assignments in EmDash. Every EmDash microsite record must
contain an immutable LeonAid `action_id` reference. Public rendering must resolve
that reference through the existing typed LeonAid API.

### 2.2 Preserve the LeonAid frontend shell; do not embed EmDash in an iframe

The existing React admin application remains the primary LeonAid management
surface under `/admin/`. Add a role-aware navigation entry named **Edit
microsite** that opens the EmDash admin as a top-level same-origin route.

Target routes for the spike:

```text
https://<LEONAID_PUBLIC_DOMAIN>/admin/                 LeonAid admin shell
https://<LEONAID_PUBLIC_DOMAIN>/_emdash/admin/         EmDash editor
https://<LEONAID_PUBLIC_DOMAIN>/campaigns/<slug>/      public microsite
```

Do not use an iframe. The current Caddy policy sets `frame-ancestors 'none'`,
and iframe embedding would add nested routing, focus, responsive-height, error,
and accessibility problems without improving authentication. A top-level link
on the same origin preserves the existing shell and permits the existing
`__Host-leonaid_session` cookie to be presented to both routed applications.

The EmDash admin may receive LeonAid branding and a clear **Back to LeonAid**
link, but reproducing the complete React shell inside EmDash is out of scope.

### 2.3 Use the existing LeonAid session; do not add Passkeys or a second login

LeonAid Core is not currently an OpenID Connect provider. Do not build a partial
OIDC provider merely for this spike. Implement a small EmDash external-auth
adapter that validates each protected EmDash request against LeonAid Core using
the existing `__Host-leonaid_session` cookie and
`GET /api/v1/identity/me`.

The adapter must:

- forward only the LeonAid session cookie to the internal Core URL;
- never accept identity, email, role, or campaign membership from client-set
  forwarding headers;
- use a strict timeout and return authentication failure on timeout, malformed
  responses, Core unavailability, or any non-2xx response;
- derive the stable EmDash subject from LeonAid `userId`, not email;
- map `system_admin` to the EmDash administrator role;
- admit a Charity Admin only when at least one active `charity_admin`
  membership is returned;
- deny all other users rather than auto-provisioning them with a low role;
- synchronize name, disabled state, and effective CMS role on every request;
- avoid logging cookies, tokens, email addresses, or full identity responses.

EmDash's built-in Passkey login must be disabled when this external adapter is
enabled. A user signed out of LeonAid must not retain an independently usable
EmDash login.

In the reviewed version, `packages/core/src/astro/middleware/auth.ts` resolves
external users with `getUserByEmail(authResult.email)` and grants the first local
user Administrator. Returning `subject` alone does not implement stable identity.
Persist a unique Core UUID to EmDash user-ID mapping and resolve accounts through
that mapping, using a supported extension or a narrowly reviewed, pinned patch.
Email is mutable profile data, never an account-linking or account-merging key.
The original Core identity response did not supply email. The minimal extension
implemented in EMS-020 returns the authenticated user's own email through the
existing identity service; no new profile directory or unauthenticated endpoint
is introduced. Do not invent an email or obtain it directly from the Core
database to satisfy EmDash's adapter.
Concurrent provisioning must produce one mapping and no privilege escalation.

Unauthenticated editor navigation returns to the existing LeonAid login with a
validated local `returnTo`; API requests return structured 401/403 responses,
not login HTML. Preserve Core's fresh-login flow where required and reject
external or encoded redirect escapes. Core outages produce a bounded unavailable
response, not a redirect loop. Logout, expiration, and membership withdrawal must
invalidate the next protected request even if EmDash retains a local session.
The reviewed middleware falls back to built-in authentication in development;
all authentication acceptance gates must run the production Docker build, and
any development fallback must be disabled or explicitly refused.

### 2.4 Campaign authorization is a hard gate, not a documented limitation

EmDash 0.36 exposes global CMS roles and author ownership. Its external-auth
result carries one global numeric role. Its standard content routes do not
natively enforce LeonAid `action_id` membership, and its `content:beforeSave`
hook does not receive the authenticated request actor. Therefore mapping every
Charity Admin to EmDash Editor would allow that user to edit every campaign and
is explicitly forbidden.

Before exposing the editor to Charity Admins, the implementation must prove a
maintainable server-side authorization seam covering all of the following:

- content list, get, create, update, duplicate, publish, unpublish, schedule,
  restore, trash, and permanent delete;
- revision reads and restores;
- media attachment and removal when media is assigned to a campaign;
- previews and inline visual editing;
- bulk actions, imports, CLI, REST, MCP, plugin routes, and any alternative
  mutation path enabled in the spike;
- schema, plugin, user, settings, menu, taxonomy, and global media management,
  which must remain System-Admin-only.

The preferred result is an upstream-compatible EmDash authorization extension
that receives the authenticated subject, operation, collection, current item,
and proposed item and can fail closed before data access or mutation. A small,
version-pinned patch may be used only inside the spike to prove this contract.
It must be isolated, documented, covered by negative tests, and proposed
upstream. Do not ship a production pilot that relies on an unreviewed fork or on
client-side filtering.

If no complete server-side seam can be established without a broad fork, stop
the spike after the System-Admin-only proof and write the decision record
described in Task EMS-090.

### 2.5 Same domain and route ownership

Initially, keep `apps/public` authoritative for existing routes. Route these
prefixes to the new EmDash service:

```text
/_emdash/*
/campaigns/*
```

These are page/editor prefixes, not the complete proxy contract. Both Astro
applications can emit root-level assets and action endpoints. EMS-010 must
inventory built JavaScript/CSS, media delivery, image optimization, Astro Actions,
preview, and editor routes. Assign a dedicated campaign asset namespace (for
example `/_campaign-assets/`, subject to build verification), preserve the
existing public application's asset paths, and explicitly assign every other
endpoint to one application. Do not send all `/_astro/*` or `/_actions/*` traffic
to the CMS. Configure both Caddy variants from this route inventory, preserving
paths expected by EmDash rather than stripping its prefix. Reserve every chosen
namespace against campaign aliases. Order-form transport must be resolved here,
not first discovered during the demo cutover.

After the authentication, isolation, rendering, and recovery gates pass,
EMS-085 migrates the demo and activates `/krapfentaxi` as a Core-managed redirect
to `/campaigns/<archive_slug>/`. Use the existing immutable `archive_slug` as the
campaign slug; do not introduce an independently editable EmDash URL identity.
The target remains stable across campaign completion and yearly alias changes.

Core owns a single route-resolution contract for canonical campaign paths,
legacy archive paths, and redirect aliases. Extend the existing `PublicActionAlias`
and publication services instead of building a second competing alias registry.
Support multiple aliases per campaign, globally unique within this installation.
The existing `apps/public` catch-all asks Core to resolve an alias and emits the
redirect. Caddy requires no per-campaign configuration and EmDash redirects are
not the authoritative registry.

Use temporary 302 redirects with `Cache-Control: no-store` for reassignable
aliases such as `/krapfentaxi`. Historical `/archive/<archive_slug>` GET/HEAD
routes may use permanent 308 redirects to the corresponding canonical campaign
URL after migration. Preserve existing API/order POST routes; never redirect
an in-flight order POST as part of the migration. Normalize trailing slashes
and canonical metadata to `/campaigns/<archive_slug>/` without redirect chains.

An inactive alias or unavailable action must retain Core's existing inactive/
not-found semantics. A redirect must not reveal an unpublished target. Completed
campaigns retain their public archive content and reject new orders. Reassigning
a yearly alias must never retarget an old campaign's canonical or archive URL.

## 3. Current verified baseline

| Area | Current contract | Evidence |
| --- | --- | --- |
| Public frontend | Astro 7.1.3, Node standalone SSR | `apps/public/package.json`, `apps/public/astro.config.mjs` |
| Public routing | Existing catch-all resolves Core aliases and archives | `apps/public/src/pages/[...path].astro` |
| Public data | Typed `PublicActionRouteResponse` contains authoritative action, offering, goal, beneficiary, and order-form data | `src/leonaid/entrypoints/fastapi/schemas.py`, `packages/api-client/openapi.json` |
| Identity | `CurrentIdentity` exposes user ID, global roles, active action memberships, and session times | `src/leonaid/application/identity.py` |
| Session | Cookie is `__Host-leonaid_session`, Secure, HttpOnly, SameSite=Lax, Path `/` | `src/leonaid/domain/sessions.py`, `src/leonaid/entrypoints/fastapi/routes.py` |
| Campaign roles | `charity_admin` is action-scoped; `system_admin` is global | `src/leonaid/domain/identity.py` |
| Deployment | Caddy fronts separate `api`, `web`, `pwa`, and `public` containers | `infra/compose/compose.yml`, `infra/proxy/Caddyfile` |
| Production TLS | Pilot Caddy owns ports 80/443 and redirects HTTP to HTTPS | `infra/pilot/compose.yml`, `infra/pilot/Caddyfile` |
| Recovery | Current backup contains Core PostgreSQL, Twenty PostgreSQL, Twenty storage, and RustFS | `tools/backup/backup.sh`, `tools/backup/restore.sh` |
| EmDash | 0.36.0 supports Astro 6+, Node standalone, SQLite/PostgreSQL, S3 storage, and external auth adapters | upstream checkout at `6030629` |
| External identity caveats | Email-based lookup, automatic first-user admin, development auth fallback, local session state | upstream `packages/core/src/astro/middleware/auth.ts`, `packages/core/src/auth/types.ts` |
| Existing login return path | Local `returnTo` is supported | `apps/public/src/components/AuthPage.astro` |
| Strict operational inventories | Backup and release validators require exact file/image sets | `tools/backup/manifest.py`, `tools/pilot_release/manifest.py` |

### 3.1 Drift check

The executor must run this before implementation:

```sh
git diff --stat 5f5f52c..HEAD -- \
  apps/public apps/web packages/api-client packages/features \
  src/leonaid/domain/identity.py \
  src/leonaid/application/identity.py \
  src/leonaid/entrypoints/fastapi \
  infra/compose infra/proxy infra/pilot infra/backup \
  tools leonaid .env.example package.json bun.lock
```

Expected result: either no output, or every changed in-scope contract is read
and reconciled into this plan before work begins. If session, role, public-route,
proxy, or backup contracts have changed incompatibly, stop and report.

## 4. Planned code shape

The expected implementation should remain within these boundaries. Exact test
filenames may follow the nearest existing repository convention.

```text
apps/campaign-site/
  package.json
  astro.config.mjs
  tsconfig.json
  Dockerfile or repository-standard build inputs
  seed/seed.json
  src/
    auth/leonaid-auth.ts
    live.config.ts
    middleware.ts
    lib/core-client.ts
    lib/campaign-authorization.ts
    pages/health/ready.ts
    pages/campaigns/[slug].astro
    components/
    styles/

packages/api-client/
  generated Core types/client, changed only if a new endpoint is proven necessary

infra/compose/
  compose.yml
  Dockerfile.campaign-site

infra/proxy/Caddyfile
infra/pilot/compose.yml
infra/pilot/Caddyfile
infra/backup/
tools/emdash_spike/
tools/backup/
tools/pilot_release/
tools/public_actions/
tools/public_orders/
src/leonaid/application/identity.py
src/leonaid/domain/actions.py
src/leonaid/application/actions.py
src/leonaid/adapters/postgres/actions.py
src/leonaid/entrypoints/fastapi/routes.py
src/leonaid/entrypoints/fastapi/schemas.py
migrations/
packages/features/src/action-admin/
apps/public/src/
tests/fixtures/golden/v1/
leonaid
.env.example
external-systems.lock
infra/locks/images.env
```

Prefer the existing `GET /api/v1/identity/me` contract. Add a dedicated Core
endpoint only if the existing response cannot safely support server-to-server
session validation. Any new endpoint must still call the existing
`IdentityQueryService`; it must not duplicate session lookup or role logic.

Use one EmDash database and one service for all campaigns. Do not create one
container, database, user identity, or hostname per campaign.

### 4.1 PostgreSQL and RustFS are the selected persistence stack

Use the existing `core-postgres` PostgreSQL server with a separate `emdash`
database and a dedicated login role. EmDash must have no access to the LeonAid
Core database, Twenty database, or their credentials. The shared server is an
operational resource, not a shared application schema. SQLite is not a spike or
production fallback.

Provision the database and role idempotently through a Docker operator task,
including on existing PostgreSQL volumes; init scripts alone are insufficient.
Use a non-superuser role with no role/database creation privileges and ownership
only of the EmDash database/schema for its migrations. Audit effective CONNECT
and PUBLIC grants on the shared server and prove denial of Core database access
without breaking existing Core clients. Keep provisioning credentials out of
the CMS container. Expose the PostgreSQL service to `campaign-site` through a
dedicated `cms-data` network, without joining the CMS to `core-data`.

Use the existing RustFS service with a separate media bucket and bucket-scoped
credentials. Include the EmDash SQL dump and RustFS objects in the same recovery
workflow. Record the shared PostgreSQL server's availability/resource coupling;
application ownership and authorization remain separate.

### 4.2 Existing-infrastructure integration contract

The following requirements complement the task checklist; they are acceptance
criteria, not claims that the integration has already been implemented.

- **Explicit activation:** keep the CMS opt-in while the spike is incomplete.
  Define how the existing `./leonaid` commands select the Compose profile for
  development, tests, backup and release. An inactive profile must neither break
  proxy startup nor silently disappear from a CMS-enabled backup. Validate both
  the base Compose configuration and the merged pilot configuration. The pilot
  must use a digest-pinned image, not a host source build, and must override the
  development origin with the configured public HTTPS origin.
- **Safe parallel execution:** every proof command must select a unique Compose
  project explicitly, check container/network/volume and host-port collisions,
  and scope cleanup to resources created by that invocation. Do not reuse the
  default `leonaid` project, shared volume names or another checkout's stack.
  Publish no ports for internal proofs; reserve separate loopback ports for
  browser/TLS proofs. Apply this rule to existing regression commands as well.
- **Bounded shared resources:** define and measure a CMS connection-pool limit,
  database/query timeouts, CPU/memory limits, upload size limits and graceful
  shutdown. Measure representative rendering and publishing alongside Core
  requests. CMS load, a failed migration or storage exhaustion must not exhaust
  Core's connection budget; record thresholds and fail the acceptance test when
  Core login or ordering becomes unavailable.
- **Runtime secrets:** extend the existing bootstrap and environment validation
  rather than introducing a second secret manager. Keep the CMS database login,
  scoped S3 key and EmDash encryption key distinct from Core and RustFS operator
  credentials. Validate the pinned EmDash version's exact encryption-key format
  without printing values. Preserve keys across restart/redeploy, document
  supported rotation and recovery, and never bake secrets into images or build
  arguments. Operator credentials belong only in short-lived provisioning jobs.
- **Private storage, deliberate public delivery:** the RustFS bucket stays
  private. Resolve published media through a controlled application endpoint or
  a proven short-lived delivery mechanism; never expose the RustFS console or
  root credentials. Authorize draft/preview media separately, prevent cross-action
  attachment and path traversal, and test MIME handling, upload limits and
  unsafe SVG/HTML. Avoid a reusable public URL that accidentally reveals a draft.
- **Existing operational boundaries:** add sanitized CMS health/failure signals
  to the current monitoring and release workflow. Keep concrete VPS addresses,
  real domains, credentials, backup destinations and private runbooks exclusively
  in `leonaid-internal`; this public specification contains generic contracts and
  synthetic test evidence only. Do not add a second reverse proxy, PostgreSQL
  server, object store or identity provider for the spike.

Track closure in the existing tasks: activation, isolation and resource limits
in EMS-010; media delivery in EMS-040/050; origin and proxy configuration in
EMS-070; secret lifecycle, monitoring, recovery and release compatibility in
EMS-080. Record the exact test commands and sanitized outcomes in `RESULT.md`.
Unverified requirements remain open even when a standalone provisioning test
passes.

## 5. Canonical commands and proof gates

All product and verification work remains Docker-only. Do not require host
Node, Bun, Python, SQLite, or EmDash CLIs.

| Purpose | Command | Expected success |
| --- | --- | --- |
| Bootstrap | `./leonaid bootstrap` | locked Docker toolchains and secrets prepared |
| Static gates | `./leonaid check` | format, types, unit tests, contracts, and policies pass |
| Stack | `./leonaid dev` | all mandatory services healthy |
| Identity | `./leonaid test-identity` | real role and session tests pass |
| Session lifecycle | `./leonaid test-sessions` | login, refresh, and immediate revocation pass |
| Existing public actions | `./leonaid test-public-actions` | aliases and archives remain green |
| Existing public orders | `./leonaid test-public-orders` | real ordering journey remains green |
| Security | `./leonaid test-security` | transport and authorization gates pass |
| Backup | `./leonaid test-backup` | fresh-volume restore including the new CMS passes |
| New spike | `./leonaid test-emdash-spike` | all EMS acceptance cases pass |

The implementation must add `test-emdash-spike` to `./leonaid help`. It must
start an isolated Compose project with empty volumes, use only synthetic Golden
Dataset identities, and leave the normal development stack untouched.

## 6. Implementation tasks

Execution order is dependency-driven, not numeric: EMS-000 → EMS-010 (private,
setup denied) → EMS-020 (System-Admin-only) → EMS-070 (TLS/bootstrap proof) →
EMS-030 (campaign-isolation proof) → EMS-040 → EMS-050. Continue with EMS-060,
EMS-080, and EMS-082 before EMS-085 and EMS-090. Synthetic Charity Admin tests
may run in the isolated harness; real Charity Admin access stays disabled until
EMS-030 passes. Never expose an unguarded wizard while implementing later tasks.

### EMS-000 — Freeze the spike contract and dependencies

Dependencies: none

- [x] Add EmDash as an exact version, not a caret or floating range.
- [x] Record the resolved package tarball integrity and license in the existing
      dependency-lock mechanism.
- [x] Confirm compatibility with Astro 7.1.3 and the pinned Node 22 runtime.
- [x] Configure EmDash's PostgreSQL adapter and pin its required driver.
      Provision a dedicated database and role on the existing `core-postgres`
      server according to section 4.1, including existing-volume upgrades.
- [x] Use a dedicated RustFS bucket and least-privilege credentials for EmDash
      media. Do not expose the bucket publicly.
- [x] Disable marketplace plugins and sandboxed third-party plugins unless the
      spike explicitly tests and pins `workerd`.
- [x] Add a short `DECISIONS.md` beside this plan recording the selected EmDash
      version, database, storage, plugin policy, and the accepted spike-only
      limitations.

Verification:

```sh
./leonaid check
```

Expected: dependency parity, licenses, formatting, type checks, and existing
tests pass; no floating EmDash or container version exists.

Partial evidence (6 September 2026): Docker Node execution of
`tools/emdash_spike/dependencies.mjs`, frozen Bun installation, and the existing
`tools/pins/check.py` all passed. Exact EmDash version, MIT license, tarball
integrity and Docker workspace-manifest parity are checked. EMS-000 as a whole
remains incomplete until provisioning and storage-permission proofs pass. The
later build and quality-gate evidence below supersedes the initial pending
build/plugin/check status, not the outstanding database and storage work.

Production-build checkpoint: `./leonaid test-emdash-spike --case closed-runtime`
passes with Astro 7.1.3/Node 22.23.0, zero type diagnostics, no marketplace or
sandbox runner, and explicit empty plugin lists. This proves build/basic runtime
compatibility only, not database/editor workflows. The S3 adapter additionally
requires explicitly pinned AWS client and presigner packages (see DECISIONS.md).

Quality-gate checkpoint: `./leonaid check` passed at implementation commit
`6d881f9` on 6 September 2026: 206 unit tests, Python and all frontend type
checks, formatting, dependency/API/privacy/policy checks, and an unchanged
working tree. Linked-worktree Git metadata is mounted read-only into the two
Git-based test containers. This is not a substitute for any live integration
gate in the remaining tasks.

PostgreSQL checkpoint: `./leonaid test-emdash-spike --case postgres` passed on
6 September 2026 against the pinned PostgreSQL image in a fresh uniquely named
Compose project with no host ports. The operator module provisions the dedicated
database/role, preserves initialized Core data, refuses unexpected ownership and
privileged preexisting roles, and proves denied Core connections and role/database
creation. The actual EmDash adapter runs all migrations idempotently. After a
database restart the test verifies existing Core/CMS rows and migration state
before reapplying provisioning. CMS service wiring and RustFS proofs remain open.

RustFS checkpoint: `./leonaid test-emdash-spike --case rustfs` passed against the
pinned beta.11 image in a unique internal Docker network with no host ports.
The real operator creates a private `emdash-media` bucket and a scoped
`leonaid-emdash` IAM user, refuses unexpected existing bindings/policies, and is
repeatable from both an empty volume and retained state after restart. Tests
prove own-bucket object/list/delete access, denied foreign-bucket read/write/list,
denied IAM and bucket deletion, and denied anonymous object downloads. The Core
test object and CMS retained object survive restart. This closes the standalone
storage provisioning proof, not the remaining HTTP-service/media UI wiring.
`./leonaid check` also passed at commit `97b6d83`, including 206 unit tests,
240 Python source-file type checks, CMS/frontend type checks and formatting;
the worktree was unchanged. EMS-000's dependency/provisioning gates are complete.
Continue with the still-open EMS-010 service-integration requirements.

### EMS-010 — Create the isolated EmDash Astro service

Dependencies: EMS-000

- [x] Create `apps/campaign-site` as a private Astro server application using
      the repository's existing workspace conventions.
- [x] Configure `@astrojs/node` in standalone server mode.
- [ ] Configure EmDash with a persistent database, RustFS S3 storage, a fixed
      `EMDASH_SITE_URL`, and the public origin's Astro `security.allowedDomains`.
- [x] Bind the runtime to `0.0.0.0` only inside the container; do not publish a
      host port from Compose.
- [x] Add `/health/ready` that checks process readiness and database access but
      does not expose setup status, versions, paths, or credentials.
- [ ] Separate process liveness from readiness and bootstrap completion. Caddy
      and existing Core services must start and remain usable when the CMS is
      absent, unhealthy, uninitialized, or undergoing a failed migration. Do not
      make global proxy startup depend on CMS health or create an HTTPS/setup
      readiness cycle. Apply readiness gates only to CMS traffic activation.
- [x] Add a digest-pinned, non-root, multi-stage Docker image following
      `infra/compose/Dockerfile.public` conventions.
- [ ] Add `campaign-site` to `edge`, storage, and the dedicated `cms-data`
      network; attach `core-postgres` to `cms-data` as well. The CMS must not
      join `core-data`, `crm-data`, or `mail-data`. Grant SQL access only to its
      own database and object-storage access only to its own bucket.
- [ ] Add a service health check and a default-deny bootstrap policy before
      the first start; no setup UI or API is reachable until EMS-070 authorizes
      it. Keep the service private while authentication is being implemented.
- [ ] Record and implement the complete route/asset ownership inventory from
      section 2.5. Inspect a production build and test both Astro applications
      through Caddy, including generated chunks, images, and form transport.

Verification:

```sh
./leonaid test-emdash-spike --case service-isolation
./leonaid test-emdash-spike --case route-ownership
```

Expected: the container becomes healthy, has no published host port, can
connect to its EmDash PostgreSQL database but cannot connect to the Core or
Twenty databases with its credentials. Its RustFS credentials cannot read or
write other buckets. Content survives container recreation. Verify provisioning
both from empty volumes and against an already initialized Core database.
Both frontends' assets load without cross-routing or 404s; setup is denied from
first boot; Core login/API and existing order routes work with the CMS stopped.

Partial service checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case service-runtime` passed using the actual base
Compose service and production image in a unique project with no published
ports. Separate operator jobs provision PostgreSQL/RustFS and run real EmDash
migrations before HTTP startup. The runtime runs non-root with only CMS-scoped
credentials; its actual EmDash S3 adapter reads retained media. SQL and media
survive CMS recreation. Stopping PostgreSQL leaves `/health/live` at 200 and
changes `/health/ready` to a bounded, sanitized 503; restarting it restores 200.
Setup UI/API remain denied throughout. The harness cleans up only its own
project resources. Bootstrap produces the versioned EmDash encryption-key
format and preserves existing key bytes when converting the initial hex format.
This is not the full `service-isolation` or `route-ownership` gate: pilot wiring,
cross-Twenty denial, proxy/browser routing, resource limits and Core login/order
availability during CMS failure remain unverified and open.

Quality checkpoint: `./leonaid check` passed at commit `52fd7d5`: 208 unit
tests, 240 Python source-file type checks, all frontend/CMS type and format
checks, dependency/API/privacy/policy gates, and an unchanged worktree. The
updated `closed-runtime` test also passed with 18 denied GET/POST requests in
the production image without network/database access. No editor, authentication
or full proxy acceptance is implied by these results.

Proxy checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case proxy-routing` passed with both production
Astro images and the actual local Caddyfile. Fifty CMS assets, including bundled
fonts, match their image bytes through Caddy; public login assets remain served
by `apps/public`. CMS setup and campaign requests stay denied. Public login HTML
and assets remain available after the CMS is stopped. The pilot Caddyfile passes
offline validation with synthetic domains. See `ROUTES.md` and the image's
generated route inventory for exact endpoint ownership. The proof uses one
unique Edge network, no published ports and no unrelated service dependencies;
all test containers and that network were removed. This does not close the
full route-ownership task: real CMS image transformation, form transport,
authenticated browser flows and pilot HTTPS still need their later gates.
`./leonaid check` subsequently passed at `34ae0a7`, including 208 unit tests,
240 Python type-checked files, all frontend/CMS checks and an unchanged worktree.

### EMS-020 — Implement same-origin LeonAid authentication

Dependencies: EMS-010

- [x] Extend the existing authenticated Core profile with the current user's
      own email, regenerate OpenAPI/TypeScript, and prove that email remains
      mutable profile data while `userId` stays stable. Never expose this field
      on anonymous or suspended-session responses.

- [ ] Implement an EmDash `AuthDescriptor` and runtime `authenticate(request,
      config)` entrypoint inside `apps/campaign-site` or a narrowly scoped local
      workspace package.
- [ ] Extract the exact `__Host-leonaid_session` cookie from the incoming request
      without forwarding unrelated cookies.
- [ ] Call `http://api:8000/api/v1/identity/me` with the cookie and a bounded
      timeout. Deny access on DNS errors, timeout, 401, 403, 5xx, invalid JSON,
      and schema drift. Distinguish an invalid session from dependency failure
      for the HTTP response; outages must not trigger login redirect loops.
- [ ] Validate the response with an explicit runtime schema before using it.
- [ ] Return a stable EmDash subject based on Core `userId` and the minimum
      effective EmDash role. Return no valid identity for users without
      `system_admin` or an active `charity_admin` membership.
- [ ] Configure EmDash external auth as the exclusive authentication method;
      ensure its Passkey, OAuth, magic-link, signup, and invitation login paths
      cannot create an alternate session.
- [ ] Ensure EmDash does not grant the first authenticated user Administrator
      merely because its local users table is empty. Initial setup must be
      completed only by a currently authenticated LeonAid `system_admin`.
- [ ] Synchronize changes on every protected request so Core suspension,
      archival, session revocation, or role removal takes effect immediately.
- [ ] Implement the unique persisted Core UUID → EmDash user-ID mapping from
      section 2.3; do not rely on subject metadata that upstream ignores during
      lookup. Document any minimal Core profile contract extension and regenerate
      its client. Prevent automatic linking/merging by matching email.
- [ ] Test email changes, two different Core subjects with matching email,
      concurrent first logins, and an empty CMS user table. Identity must remain
      stable and collisions fail closed; only a Core System Admin can bootstrap.
- [ ] Implement browser login/validated-return navigation, fresh-login handling,
      structured API failures, and bounded outage handling from section 2.3.
- [ ] Prove logout and revocation with a retained EmDash session cookie; disable
      the upstream development fallback and run tests against the production
      Docker build, not `astro dev`.
- [ ] Keep operator-facing CMS access System-Admin-only until EMS-030 passes.

Verification:

```sh
./leonaid test-emdash-spike --case authentication
./leonaid test-sessions
```

Expected cases:

- active System Admin receives EmDash admin access;
- a synthetic Charity Admin's identity/role mapping passes in the isolated
  harness; operator access remains denied until EMS-030 proves isolation;
- Akquisiteur, Finance Reader, Driver, anonymous user, malformed cookie, expired
  session, revoked session, suspended account, and archived account receive
  401/403 as appropriate;
- removing the last relevant membership invalidates the next EmDash request;
- no second login, Passkey, or EmDash-only session remains usable.

Profile prerequisite checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case identity-profile` passed against the actual
Core production image, migrations and a fresh Golden Dataset PostgreSQL volume
in a unique Compose project without host ports. Two authenticated users receive
only their respective profile; changing one synthetic account's email changes
its next `/me` response without changing its UUID or the other user's profile.
Suspension denies the next request. Both successful profile responses and
401/403 authentication/authorization errors are explicitly `no-store`; the
401 header gap found by this proof was fixed in the common error response.
All temporary resources were removed. This closes only the minimal Core profile
extension, not the CMS adapter, stable account mapping or shared-login gate.

### EMS-030 — Prove campaign-scoped authorization before enabling editors

Dependencies: EMS-020, EMS-070

This is the decisive feasibility task.

- [ ] Inventory every EmDash 0.36 route and operation capable of reading drafts
      or mutating content, revisions, publication state, media, menus, settings,
      users, schemas, plugins, REST tokens, CLI access, or MCP access.
- [ ] Build a table in `specs/emdash-campaign-microsite-spike/AUTHORIZATION.md`
      mapping each operation to its actor, `action_id` source, allow rule, deny
      rule, and automated test.
- [ ] Implement or minimally patch a server-side authorization seam that runs
      before each protected read or mutation and receives the authenticated
      LeonAid `userId`.
- [ ] Query Core for the actor's current active memberships; do not trust an
      EmDash field, cached browser value, author ID, or client header as proof of
      `charity_admin` membership.
- [ ] Permit a System Admin across campaigns.
- [ ] Permit a Charity Admin only when the current/proposed microsite's immutable
      `action_id` is present with active `charity_admin` membership.
- [ ] Return 404, rather than revealing content existence, for cross-campaign
      item reads where practical; return 403 for clearly global CMS surfaces.
- [ ] Disable every unproven alternative path. At minimum keep schema, plugin,
      user, global settings, API-token creation, CLI mutation, MCP mutation,
      imports, menus, taxonomies, and global media management System-Admin-only
      during the spike.
- [ ] Ensure list/search counts and draft previews cannot disclose another
      campaign's content.
- [ ] Ensure create cannot bind content to an action the actor does not manage,
      and update cannot change `action_id`.
- [ ] Ensure publication cannot make a microsite publicly available unless Core
      reports the referenced action as publishable under existing Core rules.

Verification:

```sh
./leonaid test-emdash-spike --case campaign-isolation
```

Expected: a two-user, two-campaign matrix proves both positive and negative
access for every row in `AUTHORIZATION.md`, including direct HTTP calls that
bypass the admin UI. Zero unauthorized response may contain the other
campaign's title, slug, body, revision, media metadata, ID, or existence signal.

STOP if the only available implementation is any of the following:

- client-side filtering or hidden navigation;
- a Caddy rule based on caller-supplied identity headers;
- EmDash global Editor access for all Charity Admins;
- author ownership used as a substitute for action membership;
- incomplete interception of EmDash's REST, preview, revision, or publication
  paths;
- a broad fork whose security-relevant diff cannot be isolated and tested.

On STOP, keep EmDash access System-Admin-only and proceed directly to EMS-090.

### EMS-040 — Define the editorial microsite model

Dependencies: EMS-030 successful

- [ ] Add a versioned EmDash seed defining a `campaign_pages` collection.
- [ ] Include an immutable, required, unique `action_id` UUID field and a
      display-only cached action name if needed for editor usability.
- [ ] Define typed, bounded fields for hero content, content blocks, FAQ,
      partners, theme choice, SEO description, and social image.
- [ ] Keep Core-owned values out of this schema.
- [ ] Restrict arbitrary HTML, script, iframe, external asset, and unsafe URL
      fields. Render Portable Text through EmDash's supported safe renderer.
- [ ] Add a deterministic `schema_version` and an export command that produces a
      reviewable, secret-free seed without live content or personal data.
- [ ] Add synthetic Golden records for at least two actions and two Charity
      Admins with non-overlapping membership.

Verification:

```sh
./leonaid test-emdash-spike --case content-model
```

Expected: schema creation is repeatable from an empty database; duplicate or
mutable `action_id` values are rejected; Core-owned and executable-content
fields are absent; generated TypeScript types compile.

### EMS-050 — Render live campaign microsites from both systems

Dependencies: EMS-040

- [ ] Implement `/campaigns/[slug]` in `apps/campaign-site`.
- [ ] Normalize public URLs to `/campaigns/<archive_slug>/`. Extend Core's
      resolver to distinguish canonical rendering from legacy redirects; do not
      reuse archive-only availability rules for an active campaign page.
- [ ] Resolve the slug through the existing LeonAid public action route, not by
      trusting the EmDash slug alone.
- [ ] Load the matching published `campaign_pages` record by Core `action_id`.
- [ ] Render authoritative Core data with existing public components or
      extracted shared presentation components where practical.
- [ ] Keep order submission on the current LeonAid Core contract. Do not proxy
      order writes through EmDash and do not persist order or sponsor data in
      EmDash.
- [ ] Define explicit states for missing editorial content, unpublished action,
      inactive action, archived action, Core unavailable, EmDash unavailable,
      and stale/mismatched references.
- [ ] Make Core publication state dominant: published EmDash content must never
      expose an unpublished Core action or enable submissions outside Core's
      availability rules.
- [ ] Preserve canonical URLs, no-index rules for previews, German locale,
      accessibility, and the existing independent order journey.
- [ ] Serve public campaign HTML with `Cache-Control: no-store` for the spike;
      do not inherit the existing public frontend's archive/stale HTML caches.
      Disable application-level caching of publication and Core availability
      decisions. Preview/editor/API responses are private and no-store; public
      queries never load drafts. Cache only immutable, safely public assets.
- [ ] Publishing, unpublishing, and Core visibility withdrawal must take effect
      on the next request without deployment, restart, or stale-cache fallback.
      Use versioned media URLs when replacing images. Test normal repeat browser
      visits without manually disabling cache, including redirects and previews.
- [ ] Use bounded dependency timeouts and explicit unavailable responses when
      Core or CMS cannot be read; never substitute stale drafts or availability.
      Stop the CMS during integration tests and prove login, Core API, admin,
      and independent existing order endpoints remain available. The new
      campaign page itself may be unavailable; do not promise CMS-free rendering.

Verification:

```sh
./leonaid test-emdash-spike --case public-rendering
./leonaid test-emdash-spike --case cache-and-failure-isolation
./leonaid test-public-actions
./leonaid test-public-orders
```

Expected: two microsites render below the same domain with different editorial
content and correct live Core data; draft changes remain private; Core state
wins every conflict. Update route expectations only for the explicit canonical
URL migration; preserve all publication, archive, authorization, and ordering
assertions in the existing tests.

### EMS-060 — Keep the LeonAid shell and add seamless navigation

Dependencies: EMS-030, EMS-050

- [ ] Add **Edit microsite** to the existing role-aware LeonAid navigation for
      System Admins and Charity Admins only.
- [ ] Where an action is already selected, link to the campaign-scoped EmDash
      editing route for that `action_id`. Otherwise link to an authorized
      campaign chooser that reveals only manageable campaigns.
- [ ] Open EmDash as a normal top-level navigation on the same origin; do not
      use `target=_blank` by default and do not add an iframe.
- [ ] Add a visible **Back to LeonAid** affordance in the EmDash admin branding
      or supported extension point.
- [ ] Preserve keyboard focus, browser Back behaviour, mobile navigation, and
      unsaved-change warnings across the transition.
- [ ] Do not copy operational LeonAid forms or domain mutations into EmDash.

Verification:

```sh
./leonaid test-emdash-spike --case shell-navigation
```

Expected: eligible personas reach the correct editor without another login;
ineligible personas do not see the entry and are still denied on a direct URL;
Back returns to the correct LeonAid action; Chromium, Firefox, and WebKit pass
keyboard and 200% zoom checks.

### EMS-070 — Add same-domain TLS routing and secure first-run setup

Dependencies: EMS-010, EMS-020

- [ ] Route `/_emdash/*` and `/campaigns/*` to `campaign-site` in local and pilot
      Caddy configuration, plus the verified asset/endpoint inventory from
      EMS-010, without changing unrelated route ownership.
- [ ] Set the canonical public HTTPS origin through `EMDASH_SITE_URL`; configure
      Astro allowed domains and trusted proxy headers explicitly.
- [ ] Trust forwarded client-IP headers only from the controlled Caddy hop.
- [ ] Keep the EmDash container private to Compose with no host port.
- [ ] Extend the default-deny policy already present in EMS-010 with a
      temporary, fail-closed bootstrap gate covering every
      `/_emdash/admin/setup*` and `/_emdash/api/setup*` route. Protect both UI and
      API; protecting the visible wizard alone is insufficient.
- [ ] Permit initial setup only to a currently authenticated LeonAid System
      Admin. Do not store temporary bootstrap credentials in Git.
- [ ] Verify setup completion from inside the trusted network, then permanently
      close setup routes (do not remove protection). The gate must not reopen
      because the database is unavailable or empty after recovery; reopening
      requires an explicit authorized bootstrap operation.
- [ ] Add HSTS and compatible CSP/security headers. Do not weaken the existing
      LeonAid policy globally to accommodate EmDash; scope any required admin
      directives narrowly to `/_emdash/*`.

Verification:

```sh
./leonaid test-emdash-spike --case tls-and-bootstrap
```

Expected: HTTP redirects to HTTPS; wrong Host and forwarded headers fail;
setup UI and API cannot be claimed anonymously; only the designated System
Admin completes setup; setup cannot be repeated; all normal EmDash auth uses
the LeonAid session and no Passkey prompt appears.

### EMS-080 — Extend backup, restore, upgrade, observability, and operator UX

Dependencies: EMS-050, EMS-070

- [ ] Add the EmDash database and its required runtime state to the existing
      consistent backup inventory.
- [ ] Ensure RustFS backup includes the dedicated media bucket and verify media
      object restoration, not just metadata.
- [ ] Preserve the EmDash encryption key outside its database and include only
      a presence/fingerprint check in committed evidence.
- [ ] Add a separate `emdash.dump` using PostgreSQL `pg_dump` to backup manifests,
      inventory validation, and restore tooling. Stop EmDash HTTP and scheduled
      writers while taking the coordinated SQL/media recovery point. Restore
      into a freshly provisioned EmDash database owned by its dedicated role;
      never restore EmDash tables into the Core database. Verify role grants and
      cross-database denial again after recovery.
- [ ] Version the backup manifest inventory: `tools/backup/manifest.py` currently
      requires schema version 1 and an exact four-file set. Define an explicit
      legacy restore path for pre-CMS backups without silently treating a missing
      CMS dump as valid for the new format. Restore legacy backups only into the
      matching pre-CMS topology or require explicit CMS initialization with
      setup locked. Test old, new, missing-dump, and unknown-version fixtures.
- [ ] Restore into a fresh Compose project and prove users still authenticate
      through Core, campaign authorization remains correct, drafts/revisions
      exist, and media renders.
- [ ] Add an upgrade rehearsal from the pinned EmDash version to an explicitly
      selected successor only after backup. EmDash migrations have no automatic
      downgrade; rollback must restore the pre-upgrade database.
- [ ] Add health and sanitized operational signals without logging identities,
      cookies, editorial drafts, internal paths, or media URLs containing
      credentials.
- [ ] Add the service to `doctor`, deployment validation, SBOM/vulnerability
      scanning, and `./leonaid` help.
- [ ] Extend `tools/pilot_release/manifest.py` and its strict image inventory
      with a digest-pinned campaign-site image and the corresponding image-lock
      variable. Version the release contract and record EmDash package, patch,
      and schema/migration identity alongside existing Core migration metadata.
      Define explicit handling of pre-CMS release manifests; never silently
      relax exact inventory checks to permit missing images or migrations.
- [ ] Run a single controlled CMS migration step before enabling CMS traffic,
      not lazily on the first public request. If upstream startup migrates
      automatically, contain it in an exclusive no-traffic maintenance phase.
      Migration failure leaves existing Core services available and CMS traffic
      disabled. Tie restore-based rollback to the matching prior CMS image,
      encryption key, SQL and media recovery point; preserve later Core orders.

Verification:

```sh
./leonaid test-backup
./leonaid test-emdash-spike --case recovery
./leonaid test-emdash-spike --case upgrade-rollback
./leonaid test-emdash-spike --case release-manifest-compatibility
./leonaid test-security
```

Expected: encrypted off-host backup and byte-/logic-verified fresh restore pass;
failed migration restores the previous state; no secret or personal data enters
committed logs or CI artifacts.

### EMS-082 — Manage redirect aliases per campaign in LeonAid

Dependencies: EMS-030, EMS-050, EMS-070

- [ ] Extend existing Core alias persistence and application services to support
      multiple aliases per action. Migrate existing assignments without changing
      their targets or publication windows. Retain backward compatibility for
      existing clients until they use the new contract.
- [ ] Add list/create/update/disable/remove operations to the existing action
      management API and regenerate OpenAPI and the TypeScript client.
- [ ] Authorize every operation through Core: System Admins manage all aliases;
      Charity Admins manage aliases of their own actions. Moving an alias to
      another action requires authority over both actions or System Admin status.
- [ ] Add an "Addresses and redirects" section to the existing campaign admin
      screen. Show the canonical URL, aliases, effective target and availability;
      provide create, edit, disable, and remove controls with conflict feedback.
- [ ] Store the target as an action ID, deriving its URL server-side. Accept
      normalized single-segment local aliases only for this spike. Reject
      absolute URLs, external hosts, query/fragment targets, encoded separators,
      dot segments, and reserved roots including `api`, `admin`, `app`,
      `_emdash`, `_astro`, `campaigns`, `archive`, and authentication routes.
      Include all additional asset/image/action namespaces selected in EMS-010.
- [ ] Enforce global uniqueness in the database, optimistic revision checks,
      idempotent mutation handling, and audit events recording actor, action,
      previous target, and new target. Concurrent claims must yield one winner
      and a clear conflict; UI checks alone are insufficient.
- [ ] Render redirects through the Core resolver and `apps/public` catch-all
      according to section 2.5. No alias-to-alias or arbitrary URL targets exist,
      so cycles and external redirects are impossible by construction.
- [ ] Include alias state in backup, restore, and synthetic fixtures. Test
      membership withdrawal, disabled aliases, collisions, reserved paths,
      simultaneous claims, and unauthorized cross-campaign reassignment.

Verification (new case implemented by this task):

```sh
./leonaid generate-api-client
./leonaid test-emdash-spike --case redirect-aliases
./leonaid test-public-actions
```

Expected: a Charity Admin configures two aliases for their campaign through the
real UI; anonymous GET/HEAD requests receive a single same-origin 302 to its
canonical URL. Moving the yearly alias preserves historical canonical URLs.
Unauthorized changes, collisions, and unsafe paths fail without mutations;
disabled/unpublished targets expose no private campaign data.

### EMS-085 — Migrate the Krapfentaxi demo and prove edit-to-public delivery

Dependencies: EMS-060, EMS-080, EMS-082

This task runs in the isolated worktree/demo Compose project. It does not change
another running checkout or authorize production deployment.

- [ ] Import the current demo's Krapfentaxi editorial texts and assets from
      `apps/public/src/components/KrapfentaxiIntro.astro`, the public layout,
      and `apps/public/src/assets/krapfentaxi/` into the campaign's EmDash record
      and dedicated media storage. Preserve asset attribution and existing design.
- [ ] Implement a Docker-based, idempotent migration with dry-run reporting and
      an explicit apply mode. Resolve the existing action UUID via Core; create
      no duplicate CharityAction. Re-running must neither duplicate media nor
      overwrite subsequent editorial changes. Record migration version and
      source fingerprints without storing Core-owned facts as editable CMS data.
- [ ] Render the migrated demo at `/campaigns/<archive_slug>/` with the existing
      offerings and working order form. Port the editorial sections sufficiently
      to remove their dependency on hard-coded copy in the new renderer.
- [ ] Take a recovery point, then activate the Core-managed `/krapfentaxi` alias
      and historical archive compatibility from section 2.5. Keep `apps/public`
      for login, legacy handling, and unrelated routes.
- [ ] Verify the actual form transport: existing Astro Actions are tied to their
      serving application. Either reuse their implementation in the new app or
      use the existing Core order API with equivalent validation and progressive
      enhancement. Reverify the EMS-010 action-route ownership contract; do not
      assume copying the form component is sufficient. Preserve no-JavaScript
      submission, idempotency, server pricing, and error/success feedback.
- [ ] Log in as the assigned Charity Admin, edit a text and image in EmDash,
      save a draft, and verify an anonymous browser still sees the published
      version. Publish and verify the anonymous canonical page and short alias
      display the changes on the next normal request without manual cache bypass,
      image rebuild, process restart, or deployment. A subsequent draft must
      remain private.
- [ ] Prove Core changes (such as offering price and order availability) appear
      independently of editorial publishing. Complete an anonymous test order
      through the new page and verify the existing backend effects.
- [ ] Rehearse rollback of renderer selection, aliases, and CMS data together.
      Rollback must preserve orders accepted since cutover: never restore an old
      whole-Core database over newly created transactions to undo a CMS change.
- [ ] Extend backup/restore verification to the final migrated demo and its
      aliases, then repeat the complete browser journey from fresh volumes.

Verification (new case implemented by this task):

```sh
./leonaid test-emdash-spike --case krapfentaxi-migration
./leonaid test-emdash-spike --case edit-publish-delivery
./leonaid test-emdash-spike --case recovery
./leonaid test-public-actions
./leonaid test-public-orders
```

Expected: the existing demo is editable, anonymous visitors see published edits
through Astro without a deployment, `/krapfentaxi` resolves to the canonical
microsite, and real orders work in Chromium, Firefox, WebKit, and without client
JavaScript. Rollback restores the previous presentation without losing orders.

### EMS-090 — Produce the go/no-go decision

Dependencies: EMS-020 and either EMS-085 or the EMS-030 STOP path

- [ ] Write `specs/emdash-campaign-microsite-spike/RESULT.md` with the exact
      LeonAid and EmDash commits, executed commands, evidence IDs, limitations,
      operational cost, and recommendation.
- [ ] Record one of these outcomes:
  - `GO`: same login, complete campaign isolation, same-domain rendering,
    recovery, Krapfentaxi migration, alias administration, edit-to-public
    delivery, and regressions are proven;
  - `SYSTEM_ADMIN_ONLY`: editorial functionality works, but safe campaign-scoped
    Charity Admin access is not maintainable;
  - `NO_GO`: authentication, authorization, runtime, upgrade, recovery, or UX
    fails a hard requirement.
- [ ] If a small EmDash authorization patch was necessary, link the isolated
      patch, tests, and upstream proposal and state the exact maintenance burden.
- [ ] Keep operational domains, credentials, real user data, and private setup
      evidence out of the public repository.
- [ ] Record the demo cutover and rollback evidence from EMS-085. Do not remove
      `apps/public` or claim production approval from a local demo result.

Verification:

```sh
./leonaid test-emdash-spike
git diff --check
git status --short
```

Expected: the full spike returns success only for `GO`; limited/no-go outcomes
return a clearly classified non-zero result or explicit report status without
claiming completion. The working tree contains only planned source, tests, and
sanitized evidence.

## 7. Required authorization test matrix

The new real integration test must cover at least this matrix:

| Actor | Campaign A | Campaign B | Global CMS settings |
| --- | --- | --- | --- |
| System Admin | read/write/publish | read/write/publish | allowed |
| Charity Admin for A | read/write/publish A | no draft visibility, no mutation | denied |
| Charity Admin for B | no draft visibility, no mutation | read/write/publish B | denied |
| Akquisiteur for A | denied | denied | denied |
| Finance Reader | denied | denied | denied |
| Driver for A | denied | denied | denied |
| Suspended former Admin | denied | denied | denied |
| Anonymous user | public published view only | public published view only | denied |

For every denied cell, test the browser route and direct HTTP/API request. UI
hiding is not proof of authorization.

## 8. Security and privacy acceptance criteria

- [ ] One LeonAid login is the only interactive login for both admin surfaces.
- [ ] Core remains the sole session and membership authority.
- [ ] EmDash receives no Core database credentials.
- [ ] Session cookies and identity responses never appear in logs or error pages.
- [ ] Session revocation and account suspension deny the next EmDash request.
- [ ] Cross-campaign list, search, preview, revision, media, and mutation paths
      fail closed.
- [ ] EmDash setup cannot be claimed from the public internet.
- [ ] Production EmDash routes require HTTPS and a fixed public origin.
- [ ] CMS content cannot inject executable HTML, scripts, unsafe iframes, or
      unrestricted remote assets.
- [ ] Public rendering never exposes drafts or overrides Core availability.
- [ ] Backup and restore include database, revisions, auth mapping, media, and
      required encryption-key continuity.
- [ ] Only synthetic identities/content are used in CI and committed evidence.

## 9. Out of scope

- Replacing the existing LeonAid login with EmDash auth.
- Turning LeonAid Core into a general OIDC identity provider.
- iframe embedding of the EmDash admin.
- Switching another running checkout or a production deployment as part of the
  worktree/demo migration.
- Arbitrary external redirects, nested alias paths, and cross-domain campaigns.
- Letting EmDash own prices, orders, invoices, action status, memberships, legal
  configuration, or submission availability.
- Arbitrary theme/plugin installation by Charity Admins.
- Public EmDash API tokens, MCP mutation, marketplace plugins, or agent-driven
  publishing.
- Multi-club tenancy, multiple EmDash instances, high availability, Kubernetes,
  or Cloudflare deployment.
- Production approval based only on build/type checks without real browser,
  authorization, backup, and restore proof.

## 10. STOP conditions

Stop and report instead of improvising if:

1. EmDash cannot consume the existing Same-Origin LeonAid session without
   copying or weakening the cookie.
2. EmDash creates an independently usable session after Core revocation.
3. The first externally authenticated user is elevated to Administrator without
   a prior Core System-Admin check.
4. Any EmDash read or mutation path bypasses campaign membership enforcement.
5. Campaign isolation requires global Editor access, client filtering, or author
   ownership as a proxy for action membership.
6. A broad maintained fork of EmDash is required.
7. EmDash requires direct access to Core or Twenty databases.
8. Existing public action/order tests regress or public availability semantics
   become ambiguous.
9. Backup cannot restore database, revisions, media, and encryption continuity
   into a fresh project.
10. The implementation would commit real domains, credentials, user data,
    session material, drafts, or private operational evidence.

## 11. Completion definition

The spike is complete only when every applicable task is checked, every command
has recorded sanitized evidence, and `RESULT.md` contains an explicit outcome.
A successful build or a visually working EmDash editor is not sufficient.

For `GO`, all of the following must be green:

```sh
./leonaid check
./leonaid test-identity
./leonaid test-sessions
./leonaid test-public-actions
./leonaid test-public-orders
./leonaid test-security
./leonaid test-backup
./leonaid test-emdash-spike
git diff --check
```

For `GO`, the current Krapfentaxi demo must already be editable in EmDash and
served by Astro at `/campaigns/<archive_slug>/`, with `/krapfentaxi` managed as a
redirect in LeonAid. Draft/public isolation, publication without deployment,
alias administration, and end-to-end ordering are required evidence.

After `GO`, production rollout and possible retirement or consolidation of
`apps/public` remain separate decisions. Canonical demo migration and backend
alias administration are included in this plan.
