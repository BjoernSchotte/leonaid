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

Order transport clarification (confirmed by the user): the browser submits to
the same-origin Astro form action, which calls LeonAid Core over the internal
Docker network. Twenty remains the system of record for CRM companies and
contacts; only Core coordinates CRM writes and owns order processing. Neither
EmDash content APIs nor its database store orders or receive CRM credentials.
The Core order endpoint `/api/v1/public/actions/{public_alias}/orders` must NOT
be reachable through public web ingress. The `public` segment is an application
contract name, not permission to expose this endpoint on the internet.

- [x] Deny the Core order route at every public ingress before generic API
      forwarding, independently of request method, including trailing-slash and
      encoded/normalized path variants. Apply the same policy to local and pilot
      routing and the pilot test configuration; preserve unrelated Core API
      routes. Never grant access based on caller-supplied forwarded headers.
- [x] Keep Core free of published host ports and use the internal service URL
      for the Astro order adapter. Document the permitted internal callers:
      the campaign Astro service and the existing public Astro service while
      its shared action/legacy form remains in use. A deny rule at ingress is
      not proof of exclusive service-to-service authorization; inventory and
      enforce that boundary separately if other containers can reach Core.
- [x] Live-prove direct public Core order requests are denied without redirects
      or Core mutations, while real browser submissions through Astro still
      reach Core and complete successfully with Twenty. Include forged internal
      headers, both JS and native form transport, and unrelated API regression
      checks. Retain Core's own token, price, publication, validation and
      idempotency checks; internal reachability never bypasses them.
      Evidence: `campaign-orders` project `leonaid-emdash-tmp-kzgfhdhn3t`
      passed all 18 real browser orders and nine native retries, then denied
      84 direct public requests with a valid, freshly issued order payload:
      HTTP/HTTPS, canonical/trailing-slash paths, seven methods and missing,
      invalid or valid service keys, with forged forwarded/internal headers.
      Every rejection was 404/no-store without redirect or cookie. In-memory
      before/after snapshots of seven complete Core tables (orders, lines,
      consent, audit, submission attempts, command receipts and outbox) and
      actual Twenty companies/people were unchanged. An internal call without
      the key was also rejected without mutation. Exactly the same payload
      succeeded with the authorized internal caller key, returning 201 and
      passing persisted order/line/consent checks. This positive control proves
      the public rejection was not caused by invalid order data. Public platform
      reads, publication withdrawal and Core-outage checks also passed, including
      the existing 364 raw path/method ingress cases. The project published no
      host ports and removed all its owned containers, networks and volumes.
      This closes the isolated order-transport gate, not production activation,
      key rotation/recovery, load limits or the remaining full-spike gates.
      Full `./leonaid check` passed on `c548400`: 249 Python source files,
      210 unit tests, 24 public and 46 campaign Astro files with zero diagnostics,
      and all API/schema, formatting, dependency and privacy/CI gates. The
      working tree remained unchanged; existing upstream warnings remain.

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

| Area                           | Current contract                                                                                                  | Evidence                                                                                 |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Public frontend                | Astro 7.1.3, Node standalone SSR                                                                                  | `apps/public/package.json`, `apps/public/astro.config.mjs`                               |
| Public routing                 | Existing catch-all resolves Core aliases and archives                                                             | `apps/public/src/pages/[...path].astro`                                                  |
| Public data                    | Typed `PublicActionRouteResponse` contains authoritative action, offering, goal, beneficiary, and order-form data | `src/leonaid/entrypoints/fastapi/schemas.py`, `packages/api-client/openapi.json`         |
| Identity                       | `CurrentIdentity` exposes user ID, global roles, active action memberships, and session times                     | `src/leonaid/application/identity.py`                                                    |
| Session                        | Cookie is `__Host-leonaid_session`, Secure, HttpOnly, SameSite=Lax, Path `/`                                      | `src/leonaid/domain/sessions.py`, `src/leonaid/entrypoints/fastapi/routes.py`            |
| Campaign roles                 | `charity_admin` is action-scoped; `system_admin` is global                                                        | `src/leonaid/domain/identity.py`                                                         |
| Deployment                     | Caddy fronts separate `api`, `web`, `pwa`, and `public` containers                                                | `infra/compose/compose.yml`, `infra/proxy/Caddyfile`                                     |
| Production TLS                 | Pilot Caddy owns ports 80/443 and redirects HTTP to HTTPS                                                         | `infra/pilot/compose.yml`, `infra/pilot/Caddyfile`                                       |
| Recovery                       | Current backup contains Core PostgreSQL, Twenty PostgreSQL, Twenty storage, and RustFS                            | `tools/backup/backup.sh`, `tools/backup/restore.sh`                                      |
| EmDash                         | 0.36.0 supports Astro 6+, Node standalone, SQLite/PostgreSQL, S3 storage, and external auth adapters              | upstream checkout at `6030629`                                                           |
| External identity caveats      | Email-based lookup, automatic first-user admin, development auth fallback, local session state                    | upstream `packages/core/src/astro/middleware/auth.ts`, `packages/core/src/auth/types.ts` |
| Existing login return path     | Local `returnTo` is supported                                                                                     | `apps/public/src/components/AuthPage.astro`                                              |
| Strict operational inventories | Backup and release validators require exact file/image sets                                                       | `tools/backup/manifest.py`, `tools/pilot_release/manifest.py`                            |

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

### 4.3 Infrastructure review closure map

Use this map when reviewing the infrastructure changes as a whole. Inclusion in
the plan is not implementation acceptance: the linked tasks and their live
verification gates must still pass before activation.

| Agreed requirement                            | Owning tasks              | Required acceptance outcome                                                                                                                       |
| --------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| One optional Docker service for all campaigns | EMS-000, EMS-010          | Base and pilot configurations work with CMS disabled and enabled; existing services retain their routes and availability.                         |
| Existing PostgreSQL and RustFS                | EMS-000, EMS-040, EMS-080 | Separate database/role and private bucket credentials; no Core database access; SQL and media survive fresh restore.                              |
| Existing Core login and campaign permissions  | EMS-020, EMS-030          | No second login or independent CMS session; foreign campaign reads and writes fail; revocation applies on the next protected request.             |
| Existing navigation and a same-origin editor  | EMS-060                   | Role-aware Edit microsite and Back to LeonAid navigation; top-level editor, not an iframe or duplicated React shell.                              |
| HTTPS and protected first installation        | EMS-010, EMS-070          | Existing Caddy owns TLS; fixed origin and trusted proxy handling; designated operator setup only; restart and recovery never reopen the wizard.   |
| Runtime fit and operational safety            | EMS-010, EMS-070, EMS-080 | Explicit activation, isolated proofs, bounded resources, runtime-only secrets, sanitized monitoring and pinned releases.                          |
| Astro microsites and live Core business data  | EMS-040, EMS-050, EMS-085 | Canonical `/campaigns/<archive_slug>/` pages expose published content only; publishing needs no rebuild; Core remains authoritative for ordering. |
| Editable Krapfentaxi demo                     | EMS-060, EMS-085          | Assigned Charity Admin edits text and media; drafts stay private; published edits appear anonymously and existing orders still work.              |
| Core-managed campaign aliases                 | EMS-082, EMS-085          | Per-campaign backend/UI management, globally unique safe aliases and a single redirect to the canonical page; historical URLs remain stable.      |
| Backup, upgrade and rollback compatibility    | EMS-080, EMS-085          | Versioned manifests cover CMS state, keys and media; fresh restore works; CMS rollback preserves subsequently accepted Core orders.               |

Concrete hosting addresses, production credentials and operating runbooks remain
in `leonaid-internal`. This plan and its PR authorize neither production
activation nor changes to another running stack.

### 4.4 Infrastructure rollout and release approval

Apply the integration in this order; a successful earlier checkpoint does not
authorize skipping a later gate:

1. Verify the CMS-disabled baseline, then provision the dedicated database role,
   private bucket and runtime secrets without changing Core data ownership.
2. Start the optional service without public editor traffic. Complete the
   operator-only bootstrap, install authorization guards and verify that setup
   remains closed after restart and recovery.
3. Prove same-origin TLS, Core authentication, campaign isolation and resource
   limits in an isolated stack before admitting campaign editors.
4. Prove anonymous Astro rendering, publication-gated media and the existing
   Core order journey before importing and switching the Krapfentaxi demo.
   Do not activate redirect aliases while ordering still hands off to an alias
   that would redirect back to the microsite.
5. Require the versioned release inventory, fresh SQL-and-object restore,
   order-preserving rollback and CMS-enabled/disabled regression gates before
   recommending pilot activation. Record remaining failures in `RESULT.md`;
   keep unfinished gates unchecked. Production activation needs separate approval.

### 4.5 Final infrastructure compatibility checklist

The requirements above must also be tested together against the existing
deployment, not only against a standalone CMS fixture. These are remaining
acceptance obligations, not additional infrastructure services:

- [ ] **Activation and readiness (EMS-010/070/080):** verify the base and merged
      pilot stack with the CMS profile both off and on. Keep liveness separate
      from readiness: a running Node process is not proof that bootstrap,
      migrations, authorization guards and required dependencies are ready.
      Public CMS routes stay unavailable until readiness passes; failure must
      not make Caddy or the existing Core services restart in a loop.
- [ ] **Exact storage configuration (EMS-040/080):** prove the selected S3
      client's endpoint, region, path-style addressing and signing against the
      pinned RustFS image. Keep the internal storage hostname out of rendered
      browser URLs. Test upload, read, delete, restart and restore using only
      the scoped CMS credentials; do not substitute root credentials when a
      compatibility test fails.
- [ ] **Shared-server capacity (EMS-010/050):** record the combined PostgreSQL
      connection budget, including Core, worker, CMS and operator headroom.
      Test bounded whole-request latency as well as individual SQL timeouts.
      Exercise CMS publishing, media uploads and dependency failures alongside
      actual Core login and accepted orders with Twenty available. A read-only
      Core health check or an expected CRM-unavailable error is not an order
      availability proof. Run resource-heavy proof stacks serially when Docker
      address pools or host capacity cannot safely accommodate them together.
- [ ] **Route and order compatibility (EMS-050/082/085):** inventory both Astro
      applications' generated assets and action endpoints in the final build.
      Verify native form POST and JavaScript submissions on the canonical
      microsite, validation feedback, retained input and Core idempotency before
      converting the old alias into a redirect. Use the authoritative Core
      order alias, not the canonical archive slug, for the order contract.
- [ ] **Recoverable release boundary (EMS-080):** rehearse the exact pinned
      image, patch, migration, encryption-key and bootstrap-state combination.
      Restore CMS SQL and objects from one consistent recovery point into fresh
      resources. Prove that a CMS-only rollback leaves newer Core orders intact,
      and that missing state never reopens first-run setup. Keep deployment
      disabled if inventory or recovery verification fails.

Record these outcomes under their existing named gates in `RESULT.md`, including
the tested release identity and any remaining STOP condition. Do not mark the
integration complete merely because this checklist has been added to the plan.

## 5. Canonical commands and proof gates

All product and verification work remains Docker-only. Do not require host
Node, Bun, Python, SQLite, or EmDash CLIs.

| Purpose                 | Command                         | Expected success                                        |
| ----------------------- | ------------------------------- | ------------------------------------------------------- |
| Bootstrap               | `./leonaid bootstrap`           | locked Docker toolchains and secrets prepared           |
| Static gates            | `./leonaid check`               | format, types, unit tests, contracts, and policies pass |
| Stack                   | `./leonaid dev`                 | all mandatory services healthy                          |
| Identity                | `./leonaid test-identity`       | real role and session tests pass                        |
| Session lifecycle       | `./leonaid test-sessions`       | login, refresh, and immediate revocation pass           |
| Existing public actions | `./leonaid test-public-actions` | aliases and archives remain green                       |
| Existing public orders  | `./leonaid test-public-orders`  | real ordering journey remains green                     |
| Security                | `./leonaid test-security`       | transport and authorization gates pass                  |
| Backup                  | `./leonaid test-backup`         | fresh-volume restore including the new CMS passes       |
| New spike               | `./leonaid test-emdash-spike`   | all EMS acceptance cases pass                           |

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
- [x] Implement and database-test the UUID-to-EmDash-user persistence primitive:
      unique bidirectional mapping, transactional profile synchronization,
      explicit first-System-Admin requirement, conflict denial and retained
      identity after restart. Connecting this primitive to verified HTTP
      authentication and replacing upstream email lookup remain open below.

- [x] Implement an EmDash `AuthDescriptor` and runtime `authenticate(request,
config)` entrypoint inside `apps/campaign-site` or a narrowly scoped local
      workspace package. Production HTTP identity is proven below; browser
      navigation and broader editor access remain separate open gates.
- [x] Extract the exact `__Host-leonaid_session` cookie from the incoming request
      without forwarding unrelated cookies.
- [x] Prove the System-Admin dashboard entry in Chromium, Firefox and WebKit
      using real Core sessions, including login return navigation and denial
      after revocation. This prerequisite does not close full login-code delivery,
      fresh-login handling or content editing below.
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
- [x] Preserve Core fresh-login confirmation and a canonical CMS item return
      path. Prove actual freshness expiry, continued ordinary CMS access,
      SMTP code confirmation through the Core form, session-token rotation,
      unchanged CMS identity and subsequent native editing/publication.
      Evidence (6 September 2026): `./leonaid test-emdash-spike --case admin-browser`
      passed in Chromium, Firefox and WebKit in isolated no-host-port project
      `leonaid-emdash-tmp-oilupajhcx`. The test-only overlay sets Core's supported
      freshness window to five seconds; no clock or database timestamp is
      replaced. Core returns freshness 401 before confirmation and 200 after
      confirmation. The browser returns to the concrete campaign item rather
      than losing its editor destination. Existing login, edit, logout,
      revocation and TLS restart/database-failure regressions also passed;
      cleanup removed only the proof project's resources. This proves the
      existing Core confirmation flow, not a new blanket fresh-login requirement
      for CMS edits or completion of the broader authentication gate.
      Quality gate: `./leonaid check` passed on `33165e7`, including unit tests,
      Python and frontend/CMS type checks, API parity, formatting and privacy/
      policy checks; the committed working tree remained unchanged.
- [x] Prove System Admin login through the actual Core email-code form from an
      empty browser context, SMTP delivery through the real Core worker, return
      to the native campaign editor, native editing and publication, and Core
      logout followed by CMS API denial and editor login redirection.
      Evidence (6 September 2026): `./leonaid test-emdash-spike --case admin-browser`
      passed in Chromium, Firefox and WebKit in isolated project
      `leonaid-emdash-tmp-d3nso1xqrb`. Login uses no prepared browser session or
      intercepted responses. The proof also repeats native autosave, stale-tab
      conflict, manual save and private follow-up editing, plus previous
      dashboard/revocation and TLS restart/database-failure checks. Mailpit and
      the production worker have explicitly test-only SMTP settings, use only
      this project's networks and publish no host ports; all owned resources
      were removed on successful completion. Logout calls the real Core API
      through the authenticated browser context; navigation/logout UI wiring,
      fresh login, hostile dependency responses and Charity admission remain
      separate open requirements.
      Quality gate: `./leonaid check` passed on `f9d504b`: 208 unit tests,
      242 Python source-file checks, API parity, frontend/CMS type checks,
      formatting and privacy/policy checks; committed tree remained unchanged.
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
`./leonaid check` passed at commit `9274123`: 208 unit tests, 241 Python
type-checked source files, generated API parity, frontend/CMS type and format
checks, privacy/policy checks and an unchanged worktree.

Identity-store checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case identity-map` passed on real PostgreSQL and
the actual EmDash migrations, both from empty storage and after restarting the
database. Twelve concurrent first requests for one Core subject produce exactly
one mapped user. Charity-first bootstrap is denied without creating a user;
email/name/role changes preserve the CMS ID. Cross-subject email collisions
roll back without merging or orphaning identities. Foreign-key deletion,
incompatible mapping constraints and accidental Core-database use are denied.
The operator installs and validates the mapping schema separately from request
processing. Inputs to this internal primitive must come from a currently
validated Core identity; these database tests do not prove that HTTP boundary.
The CMS remains closed and the shared-login gate is not complete.
The `service-runtime` case also passed with the mapping schema installed by the
real pre-HTTP operator job. `./leonaid check` passed at `e0b3b53`, including
208 unit tests, 241 Python source-file type checks, all frontend/CMS checks and
an unchanged worktree. Both proof projects removed their own containers,
networks and volumes after completion; no host ports were published.

Core HTTP boundary checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case core-auth` passed against real Core HTTP and
PostgreSQL in a unique no-host-port project. The client uses the generated API
client with a fixed internal Core origin, no redirect following, a two-second
timeout, a 64 KiB response limit and runtime profile validation. Tests cover
System/Charity identity resolution, denied finance-only access, forged identity
headers, unrelated/local EmDash cookies, duplicate/malformed session cookies,
Core session revocation and removal of the last Charity Admin membership.
A paused API proves timeout denial; a stopped API proves unavailable denial.
The probe has Edge-only access, no database/operator credentials and no mounted
`.env.local` (Bun otherwise loads it automatically). Synthetic session artifacts
and all project resources are removed. The prepared `authenticate()` function
combined this boundary with the UUID mapper and remained System-Admin-only, but
was not yet configured in EmDash at that checkpoint. Upstream stable-ID resolution,
actual middleware/browser integration, hostile-response cases and the complete
shared-login acceptance gate remain open.
`./leonaid check` passed at `e1b8913`: 208 unit tests, 242 Python source-file
type checks, all frontend/CMS checks, generated API parity and an unchanged
worktree. No active CMS authentication route is claimed by this checkpoint.

Production identity seam checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case auth-runtime` now passes against the actual
Node production EmDash middleware, real Core HTTP and PostgreSQL. The external
descriptor is configured with auto-provisioning and upstream role sync disabled.
The narrowly pinned transform documented in `AUTH-PATCH.md` resolves the verified
mapped CMS ID, bypasses email linking and does not create a local CMS session.
Only GET `/_emdash/api/auth/me` is admitted, for a currently verified Core System
Admin. The proof checks stable identity after an email change, repeated requests,
absence of Set-Cookie, anonymous/Charity denial, bearer-header rejection, and
immediate denial after Core session revocation and API shutdown without restarting
the CMS. Setup, editor and passkey routes remain default-denied. Development-mode
access is explicitly refused by source guard; browser/dev runtime proof remains
pending. Real-source integrity tests reject byte drift, semantic drift and double
patch application. A skipped transform fails the production build.

The proof owns fresh project-scoped volumes and three private project networks,
publishes no host ports and gives its HTTP probe only Edge access. Object storage
is intentionally absent from this authentication-only proof. A prior attempt
exhausted Docker's automatic address pool; removing the unused proof-only storage
network allowed the test to run without touching another project's resources.
All owned containers, networks, volumes and synthetic session files were removed.
Full browser SSO, protected TLS setup, hostile-response tests, campaign isolation
and the upstream extension proposal remain open. No full EMS-020 completion is
claimed.

`./leonaid check` passed at `8ac3a04`: 208 unit tests, 242 Python source-file
type checks, all frontend/CMS type and formatting checks, generated API parity,
privacy/policy checks, and an unchanged worktree. The full-spike command still
reports incomplete until the remaining acceptance cases are implemented.

Browser dashboard checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case admin-browser` runs the real bootstrap proof,
then opens the EmDash SPA in Chromium, Firefox and WebKit. All three hydrate the
dashboard with successful manifest/dashboard reads using a genuine Core session.
Anonymous navigation reaches the existing LeonAid login with a fixed local
`returnTo`; revoked sessions redirect there and receive 401 on direct dashboard
API access. Charity access remains 403. Alternative token creation stays closed.
The shared login page now rejects external, backslash, control-character and
nested encoded redirect escapes through a tested pure destination validator.

Only admin-root GET and its manifest/dashboard GET dependencies are opened,
after both the durable bootstrap state and database completion are verified.
Every admitted request rechecks Core and the configured HTTPS origin. During
setup, manifest access is limited to the designated actor. General editor routes
and content mutations remain pending their authorization gates.

The browser proof installs existing synthetic Core session cookies; it does not
claim to prove requesting/delivering a login code or completing fresh login.
Browser contexts bypass trust of the ephemeral test certificate for UI testing;
the accompanying native Node HTTPS proof independently validates the actual
certificate against the project's CA. No production TLS bypass is configured.
All proof services use the unique project and no published host ports; browser
containers have Edge access only. Synthetic sessions and owned resources are
removed after completion. Full EMS-020/030/070 remain open.

`./leonaid check` passed at `c786d7a`: 208 unit tests, 242 Python source-file
type checks, public/CMS and other frontend checks, formatting, API parity and
privacy/policy gates, with an unchanged worktree. `closed-runtime` passed again
against the production image: liveness and all 18 default-deny requests work
without a database or network.

### EMS-030 — Prove campaign-scoped authorization before enabling editors

Dependencies: EMS-020, EMS-070

This is the decisive feasibility task.

Current editorial admission checkpoint (6 September 2026):

- [x] Admit current Charity Admins to the bounded non-media campaign editor
      after completed bootstrap, with server-side membership enforcement for
      list/count/pagination/search, item and revision reads, comparison, draft
      update, restore, discard, publish, unpublish and draft-only creation.
      Require an authorized Core campaign handoff for Charity creation; retain
      immutable bindings and fresh post-lock Core authorization.
- [x] Keep the global dashboard inaccessible to Charity users and redirect their
      CMS home to the scoped campaign list. Return a source-only campaign field
      manifest instead of global database settings/schema/plugin/media metadata.
      Configure a fixed shell favicon so rendering editor HTML does not resolve
      global CMS branding media. Denied Finance-only actors remain denied.
- [x] Prove both Charity actors against actual Core sessions and disjoint action
      memberships, including native browser list isolation and direct foreign
      editor requests. Prove the assigned Charity actor's native autosave/manual
      save, stale-tab conflict, attributed revision, publish and private follow-up
      in Chromium, Firefox and WebKit. Withdraw A's memberships in real Core
      storage and prove every admitted operation denies A without changing its
      content/history, while B remains authorized.

Evidence: `./leonaid test-emdash-spike --case campaign-editorial-isolation`
exited successfully in isolated project `leonaid-emdash-tmp-muon2a5fkj`.
Two real Charity identities operate on three initially seeded campaign records
and independently create two more. Foreign content/revision mutations leave
System-Admin-observed snapshots unchanged. A forged action filter cannot widen
the list; foreign-title search first proves the record is searchable by System
Admin before requiring zero Charity results. All six actor/browser combinations
prove scoped native lists, foreign item API 404 and closed global navigation.
The accompanying HTTPS requests verify the project CA, no-store responses and
absence of independent CMS cookies. Bootstrap remains closed after restart and
database failure. All owned resources were removed; no host ports were published.
The fixture follows Core's actual draft-to-scheduled-to-active lifecycle; no
domain trigger was bypassed. Native list links include locale query parameters,
which the browser proof preserves when matching canonical item destinations.

This is a prerequisite, not success of the broader `campaign-isolation` gate.
Native rich-field UX, membership revocation
during lock waits, remaining account/dependency cases, media, preview and the
complete route/data matrix remain open. Earlier System-Admin-only checkpoints
below describe their historical evidence; this checkpoint supersedes their
blanket Charity-denial status for the bounded admitted operations only.
No production or other-checkout activation is authorized.

Quality and regression evidence for `67d64b1`:

- `./leonaid check` passed with 208 unit tests, 242 Python source-file checks,
  29 CMS files, all frontend/API/type-generation/format/privacy/policy gates and
  an unchanged committed worktree.
- `campaign-runtime` passed in `leonaid-emdash-tmp-swxk9crn6w`, including six
  real PostgreSQL lock-wait/Core-logout races, same-revision concurrency,
  publication lifecycle checks, deferred-commit rollback, missing binding guards,
  uniqueness, creation conflicts, revocation and sanitized failure signals.
- `authorization-surface` passed all 1,866 real HTTPS requests in
  `leonaid-emdash-tmp-qlegeicrvn` under the new identity/manifest policy.
- `admin-browser` passed in `leonaid-emdash-tmp-q4ce7e7udw`: System Admin
  dashboard and native editor, real SMTP login/fresh-login/logout, native creation,
  duplicate and trashed-binding denial, and revoked navigation/API access in
  Chromium, Firefox and WebKit. Finance-only negative actors remain denied;
  positive/foreign Charity checks live in the dedicated prerequisite above.

Every complete live command also passed restart/database-failure bootstrap
closure and removed only its own containers, networks, volumes and transient
synthetic sessions. No proof published host ports. These regressions do not
close the explicitly pending full-spike gates.

Charity login and native creation checkpoint (6 September 2026):

- [x] Prove the assigned Charity Admin signs in through the real Core email-code
      form from an empty browser context, receives the code through the actual
      worker/SMTP delivery, returns to EmDash and receives role 40 rather than
      System Admin privileges. Prove real freshness expiry and confirmation,
      Core session rotation, stable CMS identity, native editing/publication and
      Core logout followed by CMS denial and login redirection.
- [x] Prove native Charity draft creation for an assigned Core campaign from
      the same real login flow, including preserved campaign handoff, title,
      hero and SEO fields, canonical editor return, mapped authorship,
      duplicate conflict, subsequent autosave/reload and Core logout. A second
      Charity actor must neither read nor claim the created campaign binding.

Evidence: the expanded `campaign-editorial-isolation` command exited successfully
in `leonaid-emdash-tmp-hlryd3d3rt`, using Chromium, Firefox and WebKit for both
journeys. Positive login/creation browser contexts do not receive prepared
cookies, intercepted responses or API writes in place of native editing. Three
additional synthetic Core campaigns have actual persisted Charity memberships
and beneficiaries. The native editor creates their CMS records only on Save.
The proof verifies duplicate HTTP 409, foreign HTTP 404/403 and unchanged content
after the foreign actor's denied claim. All original isolation checks pass again;
membership withdrawal now also covers all three browser-created records.
Verified TLS bootstrap remains closed after restart/database failure, all owned
resources and transient sessions were removed, and no host ports were published.
Login challenge codes and cookie values are never logged or committed.

This closes the assigned Charity actor's real-login/native-creation prerequisite,
not the complete identity lifecycle, navigation/logout UI, rich-field editing,
media, public delivery or full campaign-isolation gate. The proof uses Core's
actual logout API through the authenticated browser context; a CMS logout control
is still part of the pending shell/navigation work.

Quality/regression checkpoint for `b45ea36`: `./leonaid check` passed with
208 unit tests, 242 Python source-file checks, 29 CMS files, all frontend/API/
type-generation/format/privacy/policy gates and an unchanged committed worktree.
`admin-browser` passed again in `leonaid-emdash-tmp-boms6sabma`, preserving the
shared helpers' System Admin default: real SMTP login, fresh-login rotation,
native editing/creation, duplicate and trashed-binding checks, logout and
revoked navigation/API denial in all three browsers. Restart/database-failure
bootstrap closure and complete owned-resource cleanup passed; no host ports were
published. The milestone changes tests/fixtures and evidence, not production
authentication semantics or the existing application source.

Campaign-list primitive checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case campaign-content` passed against the pinned
PostgreSQL image and actual EmDash migrations, seed API and content-list handler.
Four real draft records across two synthetic campaigns prove scoped items,
totals, cursor pagination, foreign-title search and hostile action-filter
override. System Admin sees all four; empty and Driver-only memberships deny.
EmDash requires an indexed `string` field for `action_id`; `text` is not
indexable. The proof publishes no ports and removes only its unique project's
resources. Actor profiles here are pure policy inputs, not proof of Core HTTP
authentication. The primitive is not yet wired into the request-local CMS
handlers; full HTTP isolation, immutable bindings and revisions remain pending.
`./leonaid check` passed at `df5040c`: 208 unit tests, 242 Python source-file
type checks, frontend/CMS type and formatting checks, API/privacy/policy gates,
and the 186-route inventory guard; the committed worktree remained unchanged.

Item/revision primitive checkpoint (6 September 2026): the same real
`campaign-content` proof now stages revisions through EmDash's actual
`ContentRepository.updateDraftAware` and verifies own/foreign item reads,
revision lists and direct revision-ID reads for both campaigns. Foreign and
unknown IDs return identical static `NOT_FOUND` envelopes. System Admin can
read both campaigns' revisions. Only canonical ULID item IDs are accepted by
these editor primitives; slug lookup is explicitly denied. Authorization reads
only the stored parent binding before upstream hydration, holding PostgreSQL
shared row locks through the read transaction. Revision authorization joins its
stored collection/entry relationship, never a caller-supplied parent or revision
JSON. HTTP wiring, concurrency fault injection, write authorization, trashed
content and immutable-binding enforcement are still open; this does not admit
Charity users to the runtime.
Quality checkpoint: `./leonaid check` passed at `1766e00`, including 208 unit
tests, 242 Python source-file type checks, all frontend/CMS checks, formatting,
API/privacy/policy gates and route-inventory verification; worktree unchanged.

HTTP read checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case campaign-runtime` passed with the real
production CMS, Core, PostgreSQL and Caddy. After operator-bound setup, four
synthetic entries and real revisions are readable through upstream list/get/
revision-list/revision-get routes using the existing Core System Admin session.
`src/middleware.ts` replaces only the per-request handler object; the shared
EmDash runtime is untouched. The wrapper-specific unknown-ID response proves
middleware ordering and invocation. Anonymous and Charity reads, foreign Origin,
bearer credentials, POST/PUT/DELETE/HEAD/OPTIONS fail closed; Core session
revocation produces 401 on the next read. TLS validates the actual project's CA,
and no independent CMS cookie is issued. This supersedes the pending HTTP wiring
note above for these four System-Admin-only operations, not for Charity access,
write operations, previews or media. Its isolated project has no host ports and
all owned containers, networks, volumes and temporary session files were removed.
Regression/quality checkpoint: `authorization-surface` passed again with 1,866
real HTTPS requests. `./leonaid check` passed at `d0c0cf5`: 208 unit tests,
242 Python source-file type checks, all frontend/CMS checks, formatting,
API/privacy/policy and route-inventory guards; committed worktree unchanged.

Immutable-binding checkpoint (6 September 2026): `campaign-content` now proves
real PostgreSQL rejection of content action/ID changes, invalid content inserts,
revision inserts without matching action data, revision action changes and
revision parent/collection changes. Legitimate EmDash draft revision writes and
all scoped readers still pass. Operator installation is transactional, bounded,
serialized, repeatable and rejects invalid existing bindings; it does not repair
data or guard drift. Check-only validation rejects disabled triggers and changed
function bodies, both tested against actual PostgreSQL objects with rollback.
`campaign-runtime` passes with these guards installed and proves a live HTTP 503
when a guard is deliberately disabled, successful reads after explicit fixture
restoration, and subsequent Core session revocation. Both test projects use no
host ports and clean only their own resources.

These guards enforce application data invariants, not a security boundary against
the trusted database owner issuing arbitrary DDL. They do not authorize creation
for a Core action or substitute for request-scoped membership checks. Normal
schema provisioning must install them after `campaign_pages` exists; so far that
sequence is wired into the isolated fixture operator. Runtime never installs or
repairs them. HTTP writes, creator authorization, the full editorial schema and
restore/upgrade integration remain pending.
Quality checkpoint: `./leonaid check` passed at `e90adda` with 208 unit tests,
242 Python source-file type checks, all frontend/CMS checks, formatting,
API/privacy/policy and route-inventory guards; worktree unchanged.

Revision-attribution and rollback checkpoint (6 September 2026): the admitted
title-draft update now validates the current Core UUID/CMS user mapping inside
the save transaction and attributes only the new draft revision to that actor.
It does not pass an author override to upstream or change the content author.
The real HTTPS proof compares revision attribution with the authenticated
`auth/me` response and verifies unchanged content authorship.

A fixture-only PostgreSQL trigger raises on the attribution update, after the
original updater has inserted the revision and changed the draft pointer.
The HTTP request fails with a sanitized 503; subsequent real reads are identical
to the pre-request content and revision history. Removing the isolated fixture
trigger restores successful saves. Disabled binding guards, concurrent stale
tokens, Core revocation, restart closure and deferred-work log checks remain
part of the same proof. This closes the previously open late-write-failure case
for title saves; richer mutations, full Charity admission and browser editing
remain open. No shared stack, published host port or production data is used.
The repeat proof also rejects a client-supplied author ID. Both clean isolated
runs completed successfully and removed their owned resources. Quality gate:
`./leonaid check` passed at `3fc7a90` with 208 unit tests, 242 Python source-file
type checks, all frontend/CMS checks, formatting, API/privacy/policy and pinned
route-inventory checks; the worktree remained unchanged.

Title-draft editing checkpoint (6 September 2026): the production
`campaign-runtime` proof now seeds published entries with staged drafts and
verifies both representations. Inspection found the previous lower-level content
getter omitted EmDash's runtime draft hydration; the request-local wrapper now
authorizes the stored parent, then calls the original runtime getter, validating
the hydrated action binding before returning it. GET exposes the latest draft
and unchanged `liveData`, rather than silently returning the older live title.

Canonical item PUT currently admits only System Admin title-draft updates with
an opaque `_rev` token. It retains the original EmDash runtime updater, including
schema validation and draft/revision handling. Real HTTPS tests prove one new
revision, save/read consistency, unchanged published title/status, stale-token
409 with no extra revision, and denied anonymous/Charity, bad Origin, missing
request marker, binding changes, metadata and missing-token requests without
mutation. Missing guards and revoked sessions deny PUT as well as GET. The
`campaign-content` proof checks own/foreign update authorization using actual
EmDash records and pure actor-policy inputs. Both isolated projects publish no
ports and clean their owned resources.

This is not general editor completion: rich fields, media, create/publication,
Charity runtime admission and browser editing remain pending. Concurrent title
saves and revision attribution are covered by the subsequent checkpoints.
The title-only mutation policy must be expanded
as the full planned editorial schema and operation-specific proofs land; it is
not a replacement for the required editable Krapfentaxi microsite.
Quality checkpoint: `./leonaid check` passed at `d05378f` with 208 unit tests,
242 Python source-file type checks, all frontend/CMS checks, formatting and
API/privacy/policy gates; worktree unchanged. The separate
`authorization-surface` regression passed all 1,866 real HTTPS requests.

Concurrent-write checkpoint (6 September 2026): the real `campaign-runtime`
proof reproduced two successful PUTs using the same `_rev` token. The upstream
runtime checks `_rev` before later re-reading the entry used for revision staging;
sequential stale-token tests did not cover that interleaving. The application
now locks the content row and invokes the original updater within one PostgreSQL
transaction using EmDash's public `runWithContext` database override. Runtime
getter identity is checked before mutation, so incompatible context resolution
fails closed. Upstream validation, revision staging and pointer changes use the
same transaction; returned failures cause rollback. Deferred revision bookkeeping
is tracked and drained before the transaction closes. Lock and statement timeouts
are explicitly bounded; this adds no database pool or service.

The fixed live proof passes five rounds of four simultaneous same-token PUTs,
repeated after restoring the guard: exactly one success and one new revision per
round, all other responses 409, winner content retained and published values
unchanged. A second clean run also checks sanitized logs for deferred-work and
completed-transaction failures. Core revocation and disabled-guard denial still
pass. The temporary font-download build failure was retried only after its
process terminated and its project was cleaned. Multi-instance/load testing
and other mutation operations remain open; late-write-failure injection is now
covered by the revision-attribution checkpoint. This
closes the demonstrated title-update race, not the whole authorization gate.
Quality checkpoint: `./leonaid check` passed at `9aebff0`: 208 unit tests,
242 Python source-file type checks, all frontend/CMS checks, formatting,
API/privacy/policy and route-inventory guards; worktree unchanged.

- [x] Prove own/foreign item and revision read primitives against real EmDash
      content and revisions, with indistinguishable foreign/unknown responses.
- [x] Wire the four read primitives into request-local EmDash handlers and
      prove the production HTTP path with Core System Admin sessions over
      verified TLS. Charity admission and all write operations remain closed.
- [x] Add and prove operator-installed PostgreSQL invariants for immutable
      content/action IDs and revision-parent bindings, plus check-only runtime
      refusal when their exact definitions are missing, changed or disabled.
- [x] Preserve upstream draft hydration and admit System Admin title-draft PUTs
      through the original runtime updater, with real HTTP save/read/revision
      proof, unchanged published values and stale-revision rejection.
- [x] Prove the native System Admin title editor in Chromium, Firefox and
      WebKit: own welcome dismissal, canonical editor navigation, real autosave
      and explicit save, stale-tab conflict, attributed revision, reload,
      publication and subsequent private draft. Use the exact published admin
      bundle with a small SHA-256-pinned revision-transport backport; require
      unchanged slug/locale echoes and retain revision history on autosave.
      No browser request interception or replacement editor may satisfy this
      gate. The complete editorial model, Charity access, remaining editor
      controls and anonymous edit-to-public delivery remain separate gates.
      Evidence (6 September 2026): `admin-browser` passed all three engines,
      including unchanged identity after welcome dismissal, stale-tab HTTP 409,
      a new actor-attributed revision per autosave, reload persistence, native
      publish, private follow-up/manual save, and revoked-session denial.
      The complete command exited successfully, including setup closure after
      restart/database failure and owned-resource cleanup. Earlier attempts
      exposed missing native revision transport and locale forwarding, then the
      welcome dialog and the need to await the rendered publish transition.
      A launcher edited during one run caused an EOF error after successful
      proofs/cleanup; the complete run was repeated with unchanged scripts.
      `campaign-runtime` passed native slug/locale/autosave payloads, changed
      slug/locale and invalid hint denial, own welcome action/denied actors,
      and the complete prior mutation/publication/rollback regression.
      `authorization-surface` passed 1,866 real HTTPS requests under the updated
      narrow policy. Each run used an independent project, published no host
      ports and removed only its owned resources.
      `./leonaid check` passed at `fa394a7`: 208 unit tests, 242 Python source-file
      type checks, all frontend/CMS checks (19 CMS files), formatting, API parity,
      privacy/policy and inventory guards, with unchanged worktree.
- [x] Reproduce and fix concurrent same-revision title saves; run the original
      runtime updater inside a checked PostgreSQL transaction with a row lock,
      and prove exactly one successful save per concurrent request group.
- [x] Attribute new title-draft revisions to the authenticated mapped actor
      without changing content authorship; prove rollback after an actual late
      PostgreSQL write failure with unchanged content and revision history.
- [x] Admit canonical revision-restore POSTs for System Admins through the
      scoped stored-parent lookup and original runtime handler in a locked
      transaction. Prove a newly attributed draft, unchanged published content
      and source revision, denied actors and late-write rollback over real HTTPS.
      Charity access and the full editor remain pending.
      Evidence (6 September 2026): `campaign-runtime` passed restore success,
      historical snapshot preservation, new revision attribution, anonymous and
      Charity denial, bad Origin/missing marker, unknown IDs, disabled guards,
      revocation and actual late-write rollback. The separate
      `authorization-surface` regression passed all 1,866 HTTPS requests.
      Both unique Docker projects removed their owned resources and published
      no host ports. `./leonaid check` passed at `eb59dde`: 208 unit tests,
      242 Python source-file type checks, all frontend/CMS checks, formatting,
      API/privacy/policy and inventory guards; worktree unchanged.
- [x] Admit System Admin compare GETs and discard-draft POSTs for canonical
      campaign items. Prove scoped comparison, exact revision-parent validation,
      unchanged live content/history, harmless repeated discard, subsequent
      restore, and rollback of a real deferred database commit failure.
      `campaign-content` and `campaign-runtime` passed with real PostgreSQL,
      Core sessions and verified TLS (6 September 2026). Positive Charity HTTP
      access, new-content workflows and the full editor remain pending.
      The `authorization-surface` regression passed all 1,866 HTTPS requests.
      All three isolated proof projects removed their own resources and exposed
      no host ports. `./leonaid check` passed at `e22e918`: 208 unit tests,
      242 Python source-file type checks, all frontend/CMS checks, formatting,
      API/privacy/policy and inventory guards; worktree unchanged.
- [x] Prove the campaign-list query primitive against real EmDash PostgreSQL
      records: both campaigns, total counts, cursor pagination, search and
      overriding hostile caller-supplied action filters. HTTP integration and
      the complete operation policy remain open.
- [x] Capture the pinned core/built-in/MCP HTTP route inventory, including actual
      exported methods and source hashes, and prove the current closed policy
      for every CMS-routed row with System Admin, Charity Admin and anonymous
      real HTTP requests. Full campaign-data isolation remains open below.
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
- [x] Revalidate mutation authority after blocking CMS locks, not only when the
      HTTP request starts. Actual `campaign-auth-race` baseline project
      `leonaid-emdash-tmp-6oczrmd9fy` reproduced a queued update returning 200
      after Core logout and confirmed Core identity 401. The shared mutation
      wrapper now re-reads Core action access and identity after content/revision
      locks, requiring the same subject/role and current campaign authority
      immediately before the original mutator. Creation performs the same check
      after its per-action advisory lock. No actor or membership is taken from
      the submitted content body.
      On `b5fbf38`, `campaign-runtime` passed in isolated project
      `leonaid-emdash-tmp-7h7nf7vhgb`, including all six real lock-wait/logout races
      for update, revision restore, discard, publish, unpublish and creation.
      PostgreSQL's actual blocking graph establishes that each mutation is
      waiting; Core's real HTTPS logout invalidates only that synthetic session;
      release then yields 401 with unchanged content, revisions and listing.
      The complete normal-write/concurrency/publication/rollback/revocation,
      sanitized-error, TLS and bootstrap restart/database-failure regressions
      also passed. Both projects exposed no host ports and removed their owned
      resources. The race operator alone joins isolated CMS data and Edge;
      normal HTTP probes remain Edge-only.
      `./leonaid check` passed on the same commit: 208 unit tests, 242 Python
      source-file checks, API parity, 28 CMS files, frontend/generated-type,
      formatting and privacy/policy gates; unchanged tree.
      This closes the observed pre-lock authorization race, not the full Charity
      gate or a distributed Core/CMS transaction. Revocation after the final
      Core read, positive Charity membership/role changes and hostile Core
      dependency cases are not claimed by this proof; see [AUTHORIZATION.md](AUTHORIZATION.md).
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
- [x] Prove the database creation primitive using the actual EmDash creator:
      require a matching resolved action and current policy actor, persisted
      Core-to-CMS author mapping, bounded title-only input and draft-only output.
      Serialize creation per action; existing and trashed records reserve their
      binding. Evidence (6 September 2026): `campaign-content` passed in isolated
      project `leonaid-emdash-tmp-pseuhkfgqn`, with real PostgreSQL migrations and
      EmDash writes. Four concurrent creates yielded exactly one success and
      three conflicts. Foreign action, missing membership, driver role, wrong
      identity mapping, metadata overrides and malformed fields were denied.
      An actual AFTER INSERT trigger failure left no created record; removing
      the fixture trigger restored successful creation. Owned resources were
      removed. Actor/resolved-action inputs here are pure policy fixtures, not
      proof of Core HTTP authorization. HTTP creation remains closed pending
      live Core resolution, the original runtime hook/validation path and its
      request-context transaction integration. This serialization is not the
      database-wide unique action constraint required in EMS-040.
      The failure proof also exposed upstream error logging of raw database
      exceptions; sanitize that path before HTTP admission (synthetic diagnostic
      data only was used in this proof).
      Quality gate: `./leonaid check` passed on `e0bdb7c`, including the new CMS
      module (20 checked files), unit tests, Python/frontend type checks, API
      parity, formatting and privacy/policy gates; working tree unchanged.
- [ ] Ensure create cannot bind content to an action the actor does not manage,
      and update cannot change `action_id`.
- [x] Admit System Admin HTTP creation through the original EmDash runtime,
      preserving its schema validation and hooks in the guarded transaction.
      Re-read Core campaign access after the per-action lock, bind the author
      from the current persisted identity, and accept only a bounded raw
      `{data: {action_id, title}}` request. New content is always a draft; the
      internal CMS slug is the Core UUID, not a new public URL authority.
      Evidence (6 September 2026): `campaign-runtime` passed in isolated project
      `leonaid-emdash-tmp-hvak5vfdtv`: actual HTTPS/Core/runtime creation and read
      back, one concurrent 201 versus three 409 responses, duplicate rejection,
      oversized/unknown metadata rejection, anonymous/Charity/origin/marker
      denial, absent Core target fail-closed, and revoked-session denial.
      A real AFTER INSERT failure left content unchanged and returned a static
      error. The pinned production log patch retained its fixed failure signal
      without the synthetic database canary in either HTTP or CMS logs. The
      complete prior mutation/publication/rollback suite, TLS restart and
      database-failure checks passed; owned resources were removed. Native
      creation UI, Charity admission, global binding uniqueness and the broader
      creation/duplicate/import contract remain open.
      Quality gate: `./leonaid check` passed on `2cd833c` (208 unit tests,
      242 Python source-file checks, API parity, frontend/CMS checks including
      23 CMS files, formatting and privacy/policy checks; unchanged worktree).
      `authorization-surface` separately passed 1,866 actual HTTPS requests in
      isolated project `leonaid-emdash-tmp-xsy7jksssg`, with restart/database
      failure checks and owned-resource cleanup.
- [ ] Ensure publication cannot make a microsite publicly available unless Core
      reports the referenced action as publishable under existing Core rules.
- [x] Prove the native System Admin campaign creation page in Chromium, Firefox
      and WebKit, including actual form POST, draft author attribution, canonical
      editor navigation, duplicate rejection and subsequent autosave/reload.
      Evidence (6 September 2026): `admin-browser` passed in isolated project
      `leonaid-emdash-tmp-b68pwnyvfw`, using a different real Core campaign per
      browser. Anonymous new-page navigation retained its Core login return
      path; Charity access remained denied. Existing SMTP login/fresh-login,
      editor, revocation and TLS restart/database-failure regressions also
      passed; the no-host-port stack removed only its owned resources.
      The native body may echo only empty bylines and the exact Core UUID slug;
      server-side authorization and draft defaults remain authoritative. This
      is a technical System Admin workflow with manual UUID/slug entry, not
      completion of campaign-aware LeonAid navigation or Charity onboarding.
      Quality gate: `./leonaid check` passed on `5128c1b` with 208 unit tests,
      242 Python source-file checks, API parity, frontend/CMS type checks,
      formatting and privacy/policy checks; the worktree remained unchanged.
      `campaign-runtime` also passed in isolated project
      `leonaid-emdash-tmp-hjgmrlfeon`, including rejection of nonempty bylines
      and a different valid UUID slug, prior mutation/publication/rollback
      regressions, revoked-session denial, sanitized creation-failure logging
      and TLS restart/database-failure checks. Owned resources were removed.
- [x] Gate canonical System Admin CMS publish requests on a fresh authenticated
      Core action read. Expose Core's existing `is_published_at` result as the
      derived `isPublished` response field and regenerate the typed API contract.
      Keep publication logic and its clock in Core; reject CMS backdating and
      scheduling options. Promote the existing draft through the original runtime
      inside a locked transaction with exact revision-parent checks.
      The real `campaign-runtime` proof passed active-window promotion, future/
      expired/absent-window denial, draft/scheduled/completed/archived denial,
      unchanged history, a subsequent private draft, post-publish Core withdrawal,
      denied actors, and deferred-commit rollback (6 September 2026).
      Two fixture errors were corrected without weakening Core guards: an
      archived action cannot reactivate, and new actions need beneficiaries.
      Anonymous rendering, scheduling, Charity publishing and complete operation
      isolation remain pending; this does not close the public-delivery gate.
      Quality evidence: `./leonaid check` passed at `22f76ec`, including 208 unit
      tests, 242 Python source-file type checks, API parity, all frontend/CMS
      checks, formatting and privacy/policy guards, with unchanged worktree.
      `authorization-surface` passed all 1,866 real HTTPS requests. The successful
      publication run and separate surface project both removed their owned
      resources without publishing host ports; failed fixture runs were cleaned
      before replacement runs. No shared Core lifecycle guard was disabled.
- [x] Admit canonical System Admin CMS unpublish requests even after Core's
      publication window closes. Execute the original runtime unpublisher in
      the locked transaction, preserve existing draft data/identity/authorship,
      or create an attributed draft from live when none exists. Return hydrated
      draft data and verify cleared live pointer/publication timestamp.
      `campaign-runtime` passed both paths, unchanged prior history, repeat
      withdrawal, continued republication denial after Core closure, denied
      actors and full deferred-commit rollback (6 September 2026). Anonymous
      page withdrawal and Charity access remain separate, pending gates.
      Quality evidence: `./leonaid check` passed at `2f101b9`, including 208 unit
      tests, 242 Python source-file type checks, API parity, all frontend/CMS
      checks, formatting and privacy/policy guards, with unchanged worktree.
      The separate `authorization-surface` run passed 1,866 actual HTTPS
      requests and confirmed setup remains closed after restart and database
      failure. Both isolated proof projects removed their owned resources and
      published no host ports. These checks do not close the remaining editor,
      Charity authorization, anonymous delivery or recovery gates.

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

Authorization-surface checkpoint (6 September 2026):
`authorization-inventory` evaluates the upstream injectors offline and compares
186 routes (165 core, 20 disabled built-in auth, one disabled MCP), exported HTTP
methods and SHA-256 hashes with the committed `route-inventory.json`. Missing
routes, changed methods and changed source hashes are rejected. This check is
also part of `./leonaid check`. `AUTHORIZATION.md` maps every route to its current
rule and the required campaign binding lookup, and records non-HTTP limitations.

`./leonaid test-emdash-spike --case authorization-surface` passed 1,866 real
HTTPS requests through Caddy/Core/EmDash with synthetic System Admin, Charity
Admin and anonymous actors. It covers each CMS-routed declared operation plus
HEAD/OPTIONS, including disabled built-in auth and MCP paths. After one-time
setup, only the existing System-Admin GETs succeed; other operations stay closed,
with no-store responses and no independent session cookie. The uniquely owned
project, volumes, networks and session artifacts were removed; no host ports
were published. Bootstrap closure still passed after restart/database shutdown.

This is a route-drift/closed-policy checkpoint, not positive campaign isolation.
The proposed request-scoped enforcement seam and indexed field-filter capability
still require real two-campaign data proofs for content, revisions, media and
publication before Charity access may be enabled. No broad fork or client-side
filtering is approved by this result.

`./leonaid check` passed at `d0a6b33`, including the new inventory drift guard,
208 unit tests, 242 Python source-file type checks, all frontend/CMS type and
format checks, API parity and privacy/policy gates, with an unchanged worktree.

### EMS-040 — Define the editorial microsite model

Dependencies: EMS-030 successful

- [x] Connect the pinned native media picker to editor campaign context and
      authenticated private previews. React context carries the action into
      native list/reservation calls; query keys include the action and its
      subtree resets on action changes. Server-side authorization remains
      independent. The source-only Charity manifest includes exact image MIME
      validation; scoped SQL filtering accepts distinct PNG/JPEG/WebP types.
      Raw and exactly once encoded canonical file keys resolve through the same
      Core/ready/hash checks. Native thumbnails bypass the closed anonymous
      optimizer; URL/provider selection stays unavailable.
      `campaign-media-http` passed in `leonaid-emdash-tmp-slqc3u5e31` with actual
      Core/EmDash/PostgreSQL/private RustFS and verified TLS. Chromium, Firefox
      and WebKit each completed actual SMTP Core login, native hero-image
      removal, scoped picker/thumbnail, upload/insert/autosave, persisted preview
      after reload, publication with matching live revision and Core logout;
      private file reads then returned 401. Existing reference isolation,
      five database-wait/logout races, storage failures/retry, membership
      withdrawal and bootstrap restart/database-failure cases passed. All owned
      resources were removed and no host ports were published.
      Initial runs exposed missing image validation in the Charity manifest
      and an incorrect test assumption about `liveData` after publication; both
      were corrected and those isolated stacks were fully cleaned.
      Remaining image UX evidence at this checkpoint included same-SPA campaign
      switching, creation, social/partner-logo selection, search/pagination, upload failure
      recovery, mobile/keyboard/accessibility and comprehensive two-actor browser
      isolation. Public media delivery and fresh restore are still open.
      Post-commit gates at `4106a21`: `./leonaid check` passed all 208 unit tests,
      242 Python source checks, 37 CMS files with no diagnostics and all
      frontend/API/generated-type/format/privacy/policy checks, leaving the
      committed tree unchanged. `authorization-surface` passed all 1,866 real
      HTTPS requests in `leonaid-emdash-tmp-nof8giez6b`, including bootstrap
      closure after restart/database failure and complete owned-resource cleanup;
      no host ports were published.
- [x] Preserve nested partner-logo MIME validation in the pinned native image
      renderer and prove hero, social and partner images through the real editor.
      `campaign-media-http` passed in `leonaid-emdash-tmp-ukugo7kgxq` with real
      Core, EmDash, PostgreSQL, private RustFS and project-CA-verified HTTPS.
      Chromium, Firefox and WebKit each used SMTP Core login, uploaded a hero
      image, removed/reassigned social and partner images, saved/reloaded their
      actual previews and published matching image references. Native list/editor
      links switched between two assigned campaigns without a document reload
      (`performance.timeOrigin` unchanged): each picker showed only its own
      images and a second-campaign save left the first published item unchanged.
      Logout denied subsequent private image reads. The same run passed reference
      isolation, five real database-wait/logout races, storage failure/retry,
      membership withdrawal, Core outage and closed bootstrap after restart and
      database failure. No host ports were published; owned resources were removed.
      The preceding run reached publication but exposed a test selector that
      omitted native locale query parameters; that selector was corrected without
      replacing native navigation or weakening same-document assertions.
      Creation with images, search/pagination, browser upload failure recovery,
      mobile/keyboard/accessibility, full two-actor browser isolation, public
      media and fresh restore remain open. This does not complete EMS-040.
      Post-commit `./leonaid check` passed at `a77a82d`: 208 unit tests, 242
      Python source checks, all frontend/API/generated-type/format/privacy/policy
      gates and 37 CMS files with no diagnostics; the committed tree stayed
      unchanged. The exact-source patch proof also explicitly checks nested
      image validation forwarding and rejects upstream source drift.
- [x] Prove native filename search and recovery after a rejected invalid image
      in Chromium, Firefox and WebKit. The browser proof supplies invalid PNG
      bytes through the actual file input, observes the real upload PUT return
      400, checks the visible error and disabled Insert control, and verifies
      unchanged campaign content and visible ready-media inventory. A valid
      upload succeeds in that same open dialog without reload or injected state;
      the error disappears and the resulting image can be saved and published.
      Native full-filename and partial-name searches send the exact campaign
      context and return the expected media before social/partner selection.
      This proves malformed-image recovery, not browser recovery from dependency
      outages; pagination, no-result/foreign searches, creation with images,
      full two-actor isolation, accessibility and public delivery remain open.
      `campaign-media-http` passed in `leonaid-emdash-tmp-f3whqmamhp`, including
      the existing real TLS, media/reference isolation, five database-wait/logout
      races, storage failure/retry, membership withdrawal, Core outage and
      bootstrap restart/database-failure checks. The project published no host
      ports and removed all of its owned containers, networks and volumes.
      Post-commit `./leonaid check` passed at `66d2c9c`: 208 unit tests, 242
      Python source checks, 37 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
- [x] Prove native Charity creation with images for three separate Core actions
      in Chromium, Firefox and WebKit. Actual SMTP login follows the campaign
      handoff to the prefilled new-page editor. The empty picker is scoped to
      that action; native upload and hero/social selection work before a CMS
      record exists. Uploading alone leaves the content list unchanged. Explicit
      Save creates exactly one actor-attributed draft with both image references
      and no live revision. A reload decodes both private previews; the handoff
      then resolves to the new editor, and logout denies the uploaded file.
      These synthetic Core actions remain drafts: this is creation/private-preview
      evidence, not anonymous rendering or permission to publish an inactive Core
      action. Rich-field editing, complete isolation, public delivery and all
      remaining full-plan gates remain open.
      `campaign-media-http` passed in `leonaid-emdash-tmp-9svli0ygpf` with this
      additional browser proof and all existing native image/search/recovery,
      real TLS/media/reference, five database-wait/logout, storage failure/retry,
      membership withdrawal, Core outage and bootstrap restart/database-failure
      regressions. No host ports were published; all owned test resources were
      removed after successful completion.
      Post-commit `./leonaid check` passed at `214fd73`: 208 unit tests, 242
      Python source checks, 37 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
- [x] Accept native omitted empty Portable Text marks without weakening the
      bounded editorial contract, and prove rich-field Charity creation in the
      real editor. The pinned converter omits empty span `marks` and block
      `markDefs`; treating them as mandatory caused native creation to return 403. Absence now means an empty collection. Null, malformed collections,
      unknown annotations and executable nested properties remain rejected;
      the direct contract proof covers 44 negative cases. No SQL/schema metadata
      migration or new editor patch is required for this compatibility fix.
      `campaign-media-http` passed in `leonaid-emdash-tmp-pwiqfpuqfn`:
      Chromium, Firefox and WebKit each completed actual SMTP Core login,
      heading/bold story input, FAQ, partner name/description/website/logo,
      theme and SEO input, hero/social upload and explicit attributed draft
      creation. Reload retained the actual rich fields and private images.
      Native document-end keyboard navigation then appended text to the last
      paragraph; DOM selection, outgoing PUT, stored fields and another reload
      proved the exact position and preserved heading/bold content. The picker
      proof waits for its visible selected-upload state, not just HTTP completion.
      Existing media/search/recovery, reference isolation, five SQL-wait/logout
      races, storage failure/retry, membership withdrawal, Core outage and
      bootstrap restart/database-failure checks passed. No host ports were
      published and all owned containers, networks and volumes were removed.
      Earlier diagnostic runs exposed timing-dependent empty-paragraph click
      selection and a picker selector missing its native `(selected)` suffix.
      This checkpoint proves the explicit keyboard workflow, not arbitrary
      pointer placement, full rich-editor UX or anonymous rendering.
      Post-commit `./leonaid check` passed at `135031b`: 208 unit tests, 242
      Python source checks, 37 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
- [x] Resolve and prove pointer placement in empty rich-text paragraphs after
      reload, including immediate typing in all three browsers. A real saved
      empty paragraph reproduced Firefox retaining the heading selection even
      though mouse-down/up/click all targeted the paragraph, with unchanged
      geometry. The exact-source editor patch now uses ProseMirror's supported
      `handleClick` seam to select the document position of a directly clicked,
      empty top-level paragraph. It changes no content and declines modified
      clicks, composition, read-only views, nested/nonempty paragraphs and
      non-left buttons. See `DECISIONS.md` for the spike-only maintenance boundary.
      `campaign-media-http` passed in `leonaid-emdash-tmp-3i7dpn2460` with
      Chromium, Firefox and WebKit: native Enter creates the empty paragraph,
      autosave/reload retains it, direct click immediately followed by typing
      updates the correct paragraph, and another reload plus API readback proves
      persistence and unchanged preceding block/span content and formatting.
      No diagnostic listeners, injected selection, delay or keyboard positioning
      occurs between this click and typing. Existing rich-field/image creation,
      media/search/recovery, reference isolation, five SQL-wait/logout races,
      storage failure/retry, revocation, Core outage and bootstrap restart/database
      failure checks passed. No host ports; all owned test resources were removed.
      The focused `campaign-editor-pointer` command retains the real Core login,
      TLS/SQL/storage setup and three-browser creation proof; it explicitly does
      not replace the complete media gate. Its first independent run exposed an
      implicit prior-test dependency on CMS onboarding; the actual Get Started
      dialog is now handled when required. Diagnostic runs with the fix passed
      in `leonaid-emdash-tmp-jpc191kvsj`; earlier failing projects were cleaned.
      Full rich-field reorder/remove/link UX, modifier/drag/mobile accessibility,
      public delivery and recovery remain open.
      Post-commit `./leonaid check` passed at `e000bc6`: 208 unit tests, 242
      Python source checks, 37 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
- [x] Prove native image-picker pagination with more than one full production
      page. The real TLS upload/confirm protocol seeds 101 own raster images and
      a foreign image matching the same search prefix after earlier browser
      fixtures finish. Chromium, Firefox and WebKit use real Core SMTP login,
      search the native picker, load its actual 100+1 pages, compare exact ordered
      IDs and scoped counts, and verify that the foreign item and exhausted
      Load More control are absent. Changing search after loading page two sends
      no stale cursor; selecting the narrowed last-page image saves through the
      native editor and survives reload with a decoded private preview and
      unchanged other editorial fields. No API response or UI-state replacement
      is used. Full `campaign-media-http` passed in
      `leonaid-emdash-tmp-oizz9uzgup`, including prior media/search/editor/repeater,
      reference isolation, five SQL-wait/logout races, dependency-failure/retry,
      revocation and bootstrap restart/database-failure checks. No host ports;
      all owned resources and temporary proof files were removed. The initial
      run `leonaid-emdash-tmp-8wpnxrilmp` passed runtime assertions but exited
      unsuccessfully because its new synthetic metadata file was omitted from
      the explicit cleanup list. That list is corrected; the old file and empty
      directory were removed after inspection. This does not close full
      two-actor browser workflows, accessibility, public delivery or recovery.
      Post-commit `./leonaid check` passed at `d05ebb4`: 208 unit tests, 242
      Python source checks, 38 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
- [x] Prove empty and foreign-only filename searches in the native image picker
      in Chromium, Firefox and WebKit. A separate real Charity B upload supplies
      a unique foreign filename while the existing same-filename/hash isolation
      fixture remains intact. Charity A's native search receives zero items and
      zero count for both the foreign name and a nonexistent name; the dialog
      displays its empty heading, no media list/thumbnails/load-more control and
      a disabled Insert button. Clearing the search restores the own image.
      Complete content snapshots remain unchanged throughout. No responses or
      React state are substituted. Full `campaign-media-http` passed in
      `leonaid-emdash-tmp-y3zh5dgk5n`, including prior media/editor/repeater,
      reference-isolation, five SQL-wait/logout, dependency-failure/retry,
      revocation and bootstrap restart/database-failure checks. No host ports;
      owned resources removed. The initial run `leonaid-emdash-tmp-i7xzuflkg7`
      failed because its search name also existed in Charity A; the corrected
      fixture does not remove that existing positive isolation case. That failed
      stack was also removed. Pagination (native page size 100), full two-actor
      browser workflows, accessibility, public delivery and recovery remain open.
      Post-commit `./leonaid check` passed at `4799abc`: 208 unit tests, 242
      Python source checks, 38 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
- [x] Prove native FAQ and partner add, keyboard reorder and removal with
      autosave/reload persistence in Chromium, Firefox and WebKit. The narrow
      exact-source client patch retains native repeater state and mutations,
      uses real accessible drag/collapse buttons and the existing sortable
      keyboard sensor. The proof reaches the drag handle through Tab navigation,
      verifies picked-up/displaced UI states, then drops with Space. Actual PUT
      responses, API readback and reload prove order; removal restores the whole
      original document, including the partner logo and other editorial fields.
      No injected DnD state or intercepted writes are used. See `DECISIONS.md`.
      Focused `campaign-editor-pointer` passed in `leonaid-emdash-tmp-t9j62pc9hk`.
      Full `campaign-media-http` passed in `leonaid-emdash-tmp-9o6z2vnlxm`,
      including all existing image/search/recovery, reference isolation, five
      SQL-wait/logout races, storage failure/retry, revocation, Core outage and
      bootstrap restart/database-failure checks. No host ports; all owned test
      resources were removed. Earlier failed runs were also fully cleaned:
      production Lingui required an existing compiled interpolated label, and
      keyboard proof needed observable drag-state synchronization before drop.
      A transient external font-fetch build failure passed on retry; this does
      not establish an offline/reproducible build guarantee.
      Pointer/touch sorting, full accessibility and remaining rich-text/link UX,
      public delivery, migration, aliases and recovery/release remain open.
      Post-commit `./leonaid check` passed at `9ff56df`: 208 unit tests, 242
      Python source checks, 38 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
- [x] Revalidate the current Core actor after successful native content writes,
      result-reference checks and deferred tasks, before completing the CMS
      transaction. The same final check covers creation and all shared mutation
      branches. `campaign-media-http` passed in isolated project
      `leonaid-emdash-tmp-onakkpvf9m`: separate actual Charity sessions were
      revoked through Core HTTPS while fixture-only PostgreSQL triggers held
      content INSERT (create) and revision INSERT (update). Both returned 401
      after release with identical complete content/revision/media snapshots;
      independent valid sessions retained access and could create successfully.
      All existing private-media, storage failure/retry, three upload/logout
      races, membership withdrawal and bootstrap restart/database-failure cases
      passed, with no host ports and complete owned-resource cleanup.
      The initial proof targeted a revision INSERT for creation, but native
      EmDash creates the content row directly; the corrected proof targets each
      actual write path. The failed isolated run was also fully cleaned.
      This is not atomic distributed revocation after the final Core read.
      Post-commit verification at `2295b88`: `./leonaid check` passed 208 unit
      tests, 242 Python source checks, 36 CMS files with no diagnostics, all
      frontend/API/generated-type/format/privacy/policy gates and an unchanged
      committed tree. `campaign-runtime` passed in
      `leonaid-emdash-tmp-fw5zdztwwk`: all six earlier lock/logout races,
      content/revision attribution, restore/discard, publication-window denial,
      publish/private follow-up, unpublish/draft preservation, concurrent
      creation and actual late database rollback. Sanitized/deferred-task checks,
      bootstrap restart/database-failure closure and owned-resource cleanup
      passed; no host ports were published.
- [x] Add version-2 local image fields (`hero_image`, `social_image`, partner
      `logo`), strict bounded reference shapes and matching generated types.
      Explicit `upgradeFromVersion1` migration verifies the retained exact v1
      metadata, preserves content/revisions and atomically adds nullable fields;
      regular installation refuses an old version and never repairs drift.
      Actual `schema-runtime` passed in `leonaid-emdash-tmp-yipefbzm44`;
      `schema-migration` in `leonaid-emdash-tmp-t7qtwbj2yh` proved concurrent
      one-winner upgrade, published/draft/revision preservation and complete
      rollback after a real failure during the second new field's DDL.
      The shared image-reference guard locks ready media and immutable bindings,
      checks the exact action and cached file facts, and runs before native
      normalization/create/update/restore/publish and before returning mutations.
      Content, revision and comparison reads reject invalid references as well.
      `campaign-media-http` passed in `leonaid-emdash-tmp-ufbdcww1dt` with actual
      production EmDash/Core/TLS/PostgreSQL/RustFS: own image creation, nested logo,
      save/read/publish/clear/restore/compare, foreign/pending/provider/path/dimension
      injection denial with unchanged content/history, and same-user cross-action
      denial even for System Admin creation. A real poisoned stored revision
      could not be read, compared, restored or published by either admin role;
      full SQL/media snapshots remained unchanged and explicit fixture restoration
      recovered access. Existing storage faults, slow uploads, three real logout
      races, membership withdrawal and bootstrap restart/database-failure cases
      passed. All three successful projects used unique resources, published no
      host ports and cleaned their own resources.
      Initial checks caught a negative compiler-fixture annotation, unvalidated
      upstream result typing and native provider metadata enrichment; these were
      corrected without admitting arbitrary metadata or weakening ownership.
      See [SCHEMA.md](SCHEMA.md). Native picker context, image preview/browser UX,
      public publication-gated delivery, cleanup and fresh restore remain open.
      Follow-up regressions at `bfd7f79` also completed: `schema-runtime`
      (`leonaid-emdash-tmp-ezdb3j5p5b`), `campaign-content`
      (`leonaid-emdash-tmp-8jxw1skhw6`), `campaign-runtime`
      (`leonaid-emdash-tmp-4mzjtdgybr`) and `campaign-editorial-isolation`
      (`leonaid-emdash-tmp-yoy3jev56i`). The browser suite repeated actual SMTP
      login/fresh confirmation/session rotation, native editing/conflicts,
      publishing/private follow-up, creation/logout and both Charity actors'
      scoped-list/foreign-editor checks in Chromium, Firefox and WebKit.
      Membership withdrawal, restart/database failure and complete cleanup
      passed. This covers the existing editorial workflows, not native image
      picker/preview UX, which remains open.
- [x] Admit the campaign-scoped native reservation/PUT/confirmation protocol and
      private file reads through real Core authentication. Global multipart,
      media mutation, folder, usage and image-optimizer alternatives stay closed.
      Reservations require an explicit authorized action; canonical IDs and
      storage keys resolve through immutable ownership before hydration. Neither
      native SHA-1 hints nor same-image uploads expose a global deduplication hit.
      Actual request streams have byte and time limits; S3 transport and object
      reads have bounded deadlines. Confirmation verifies stored MIME/SHA-256,
      derives dimensions by decoding, and changes pending to ready atomically.
      Ready is private upload state, not anonymous publication. Core authority is
      checked after database locks before staging, after object PUT before linking,
      and before confirmation; failed linking safely compensates its own object.
      Evidence (7 September 2026):
      `./leonaid test-emdash-spike --case campaign-media-http` passed in isolated
      project `leonaid-emdash-tmp-vugk541uob` through actual verified Caddy TLS,
      Core sessions, production EmDash/Node, PostgreSQL and private RustFS.
      Two Charity actors proved own uploads/private reads and foreign ID/key/list
      denial, anonymous denial, metadata stripping, server-derived dimensions,
      CSRF rejection, pending/ready conflicts, actual stalled and oversized
      chunked uploads, and closed alternate routes. Real database confirmation
      failure/retry, object corruption, storage outage/restart, membership
      withdrawal and Core outage remained closed without independent CMS cookies.
      Three database-controlled races revoked real Core sessions during upload
      start, linking and confirmation: all returned 401 with unchanged media,
      attempt-ledger and object-key snapshots. CMS restart/database shutdown kept
      bootstrap closed. No host ports were published; all owned resources and
      synthetic session files were removed.
      Earlier runs exposed duplicate nosniff headers, wrong ready-upload conflict
      precedence and HTTP/1 body draining at the proxy. Both Caddy configurations
      now close only CMS 408/413 connections before returning the upstream error;
      no global timeout or experimental full-duplex setting was introduced.
      Both configurations passed offline validation in the pinned Caddy image.
      Native field/picker UX, content/revision media-reference authorization,
      cleanup scheduling, publication-gated delivery and fresh restore remain
      open. This checkpoint does not complete media or campaign isolation.
      Quality/regression checkpoint at `3afaacc`: `./leonaid check` passed with
      208 unit tests, 242 Python source-file checks, 35 CMS files without
      diagnostics, all frontend/API/type-generation/format/privacy/policy gates
      and an unchanged committed tree. `campaign-media-binding` and
      `campaign-media-upload` passed again in projects ending `0on4sgqolo` and
      `yc9aepxs9a`; `authorization-surface` passed 1,866 actual HTTPS requests in
      `vspx2idvue`. `proxy-routing` in `9ffxwicnev` byte-verified 50 CMS assets and
      proved existing public login/assets survive CMS shutdown.
      `campaign-editorial-isolation` in `kcmiw4cria` passed two-actor HTTP and
      Chromium/Firefox/WebKit isolation plus actual Charity SMTP login, fresh
      confirmation/session rotation, native draft editing/conflict/reload,
      publication/private follow-up, creation and logout. Membership withdrawal,
      restart and database-failure bootstrap closure passed. These regression
      projects published no host ports and removed all owned resources.
- [x] Implement and prove private raster-upload staging against actual RustFS,
      independently of HTTP admission. The already locked Sharp 0.35.3 is now an
      explicit CMS dependency; its version/license and frozen install are checked.
      `campaign-image.mjs` accepts only PNG/JPEG/WebP byte signatures with matching
      decoded formats, at most 8 MiB, 16 million pixels and 8192 pixels per axis.
      It rejects animation, truncated images and MIME mismatches, permits one
      decode per process without an unbounded queue, applies a five-second
      processing timeout, honors EXIF orientation, and re-encodes without original
      metadata or appended content. Only normalized bytes are stored; original
      uploads are not retained. SHA-256 identifies the normalized stored bytes.
      `campaign-media-upload.mjs` records an actual upstream upload attempt before
      PUT, writes a fresh private object key and conditionally links it under a
      media-row lock. It does not mark media ready or publish it. Repeated PUTs
      replace only the staged object; cleanup must first prove the old key is
      unreferenced. Failed/ambiguous cleanup remains in the durable attempt ledger.
      Evidence (7 September 2026):
      `./leonaid test-emdash-spike --case campaign-media-upload` passed in project
      `leonaid-emdash-tmp-8ov4zanmbu` with real EmDash repositories/S3 adapter,
      PostgreSQL and scoped private RustFS credentials. It proved byte/hash
      readback, stripped metadata and appended script text, actual two-frame
      WebP rejection, size/pixel/dimension/MIME/truncation denial, foreign-policy
      no-write checks, repeated-upload cleanup, actual PostgreSQL failure after
      object upload with compensation, actual IAM denial with a retained cleanup
      ledger, and retained private bytes/bindings after database/storage restart.
      Anonymous direct S3 reads returned 403 before and after restart. The probe
      had no root credentials or full-workspace/env-file mount; every service had
      no host port, and all owned containers/networks/volumes were removed.
      An earlier failed run exposed identical test animation frames collapsing
      to one frame; two distinct frames were independently verified before rerun.
      This was a lower-level policy-input/storage proof. At that checkpoint HTTP/editor
      upload, bounded request streaming and storage transport timeouts, fresh
      Core checks after upload lock waits, final confirmation, cleanup scheduling,
      preview/public delivery and restore remained open. The HTTP checkpoint
      above supersedes only its explicitly proven requirements; the standalone
      staging proof alone does not authorize HTTP or close campaign isolation.
      Quality checkpoint: `./leonaid check` passed at `02f6159`: 208 unit tests,
      242 Python source-file checks, all frontend/API checks, 32 CMS files without
      diagnostics, generated types, formatting and privacy/policy gates, with an
      unchanged committed tree. The pinned Bun frozen install also passed with
      networking disabled and no dependency changes.
- [x] Implement the campaign-media ownership database prerequisite without
      admitting the global upstream media routes. `auth/campaign-media.mjs`
      installs a separately versioned, immutable media-to-Core-action binding;
      existing unbound media is not automatically assigned by author or hash.
      Pending media and its binding are created in one transaction with a
      server-generated object key, bounded metadata and a raster MIME allowlist.
      Scoped get/list/count/search/pagination and SHA-256 lookup never hydrate
      foreign or unbound media; pending media is excluded from ready lists.
      Ready means upload-ready, not publicly published. Direct ownership changes
      and binding removal are rejected; deleting the actual upstream media row
      cascades its binding. Runtime checks fail on missing/disabled/altered guards
      or schema/version drift; operator installation never silently repairs it.
      Evidence (7 September 2026):
      `./leonaid test-emdash-spike --case campaign-media-binding` passed against
      real EmDash migrations/repositories and PostgreSQL in isolated project
      `leonaid-emdash-tmp-2vinifvut3`. It covered concurrent installation,
      same-author foreign media, different-author own media, global/unbound hash
      denial, literal search, cursor scope, revoked policy inputs, immutable
      ownership, actual PostgreSQL failure after media insertion with complete
      transaction rollback, disabled guard/FK drift and upstream deletion.
      The project published no host ports and removed its own networks/volume.
      Actor profiles are policy inputs in this database proof, not real Core
      authentication evidence. HTTP admission, native upload/selection, actual
      raster-byte validation, RustFS object coordination, media references in
      revisions, private previews, publication-gated delivery and restore remain
      open; this does not close the full media or campaign-isolation gates.
      Quality checkpoint: `./leonaid check` passed on `090460e`: 208 unit tests,
      242 Python source-file checks, frontend/API checks, 30 CMS files with no
      diagnostics, generated-type parity, formatting and privacy/policy gates;
      the committed worktree remained unchanged.
- [x] Implement and admit the bounded non-media editorial contract for the
      currently proven System Admin runtime. `src/campaign-schema.mjs` defines
      version 1 fields for title, hero heading/introduction, Portable Text story,
      FAQ, partners, theme selection and SEO description; runtime fixture setup
      now uses that collection definition. Create/update paths share strict
      nested validation, preserve immutable Core bindings and reject unknown
      fields, media references, executable blocks and unsafe link schemes.
      Limits include 60 KiB aggregate editorial JSON, 64 KiB raw create requests,
      60 story blocks, 20 FAQ entries and 30 partners, plus bounded nested strings.
      Evidence: `campaign-runtime` passed actual authenticated HTTPS writes and
      readback of all seven added fields, invalid/oversized/nested input denial
      with unchanged revision counts, and prior concurrent revision, attribution,
      publication, rollback, revocation, sanitized logging and bootstrap failure
      regressions in project `leonaid-emdash-tmp-bblgojyket`. `admin-browser` passed
      native creation with hero and SEO fields, subsequent edit/reload retention,
      campaign resolver/trash denial, SMTP login/fresh-login and existing editor
      regressions in all three browsers in `leonaid-emdash-tmp-kpiyjjc3zx`.
      `campaign-content` additionally passed the real lower-level database scope,
      create/concurrency and rollback suite in `leonaid-emdash-tmp-grsvc4jeky`.
      All projects exposed no host ports and removed their owned resources.
      `./leonaid check` passed on `be013bf` (208 unit tests, 242 Python source-file
      checks, API parity, frontend/CMS checks including 26 CMS files, formatting
      and privacy/policy gates; unchanged tree). Direct production-policy checks
      accept exact limits and reject 39 unsafe/oversized cases; these are now
      included in the pinned-source proof entry point, which also passed.
      This does not complete the schema migration/export/type-generation gate,
      global action uniqueness, media/social images, complete native rich-field
      UX, safe public rendering, or Charity admission.
- [x] Add a versioned EmDash seed defining a `campaign_pages` collection.
      Version 1 covers the bounded non-media contract above. The operator-only
      installer serializes concurrent installation, preserves matching schema
      and content, and rejects incompatible metadata or version drift without
      repair. This does not install the remaining media fields or global action
      uniqueness constraint. See [schema lifecycle](SCHEMA.md).
- [x] Include an immutable, required, unique `action_id` UUID field and a
      display-only cached action name if needed for editor usability.
      The existing required UUID/immutable content and revision guards are now
      supplemented by the immediate PostgreSQL constraint
      `leonaid_campaign_action_unique UNIQUE (action_id)`, covering all locales
      and soft-deleted rows. Binding operator version 2 is separate from the
      editorial seed version: importing the seed alone does not install the
      physical invariant. Installation is bounded, serialized and transactional;
      invalid/duplicate legacy rows stop installation without automatic deletion
      or reassignment. Repeated versioned installation checks rather than repairs
      drift. Runtime verifies the exact key, backing index and binding version,
      rejecting missing, deferred or composite substitutes. See [SCHEMA.md](SCHEMA.md).
      Evidence on `c5d9515`: `campaign-content` passed in isolated project
      `leonaid-emdash-tmp-k46xqvtqhm`, including direct concurrent SQL inserts
      (one winner, three unique violations), trash/locale reservation, duplicate
      preflight, immutable content/revisions and constraint-drift rejection.
      Pagination/scoping still uses four records, now two distinct actions per
      non-overlapping synthetic Charity profile, rather than duplicate pages.
      `campaign-runtime` passed the full HTTPS regression in
      `leonaid-emdash-tmp-ms23qju8pm`, including actual removal of the constraint,
      503 denial across the admitted operations, explicit fixture restoration,
      publication/unpublication, rollback, concurrent creation and revocation.
      `admin-browser` passed native creation, seeded/new campaign editor routing,
      duplicate rejection, trash reservation, editing/conflicts/publication,
      actual SMTP login/fresh-login and revocation in Chromium, Firefox and WebKit
      in `leonaid-emdash-tmp-hpywrjoqwt`. HTTP/browser fixtures now contain one
      page per action; the earlier deliberately ambiguous binding fixture is
      superseded by database rejection before such a state can be admitted.
      All projects exposed no host ports and removed their owned resources.
      `./leonaid check` passed on the same commit (208 unit tests, 242 Python
      source-file checks, API parity, 28 CMS files, frontend/type generation,
      formatting and privacy/policy gates; unchanged tree).
      This supersedes earlier notes that global action uniqueness was open;
      pilot operator wiring, full model/media and restore/upgrade gates remain open.
- [x] Define typed, bounded fields for hero content, content blocks, FAQ,
      partners, theme choice, SEO description, and social image.
- [ ] Keep Core-owned values out of this schema.
- [ ] Restrict arbitrary HTML, script, iframe, external asset, and unsafe URL
      fields. Render Portable Text through EmDash's supported safe renderer.
- [x] Add a deterministic `schema_version` and an export command that produces a
      reviewable, secret-free seed without live content or personal data.
      `./leonaid export-campaign-schema` passed and emits only version and seed
      metadata from source in a pinned, network-isolated container. Actual
      EmDash seed validation and real PostgreSQL installation passed in
      `schema-runtime`, project `leonaid-emdash-tmp-e7z9sutkyl`: three concurrent
      installers created the collection once; repeated installation preserved
      content, field metadata and version; field-rule/version drift was rejected
      without repair. The complete `campaign-runtime` regression then passed
      using this installer in `leonaid-emdash-tmp-8n6qinvpnb`, including editorial
      writes, concurrency, attribution, publication, rollback, revocation,
      sanitized errors, TLS and closed bootstrap after restart/database failure.
      Both projects exposed no host ports and removed their owned resources.
      `./leonaid check` passed on `9e4d667` (208 unit tests, 242 Python source-file
      checks, API parity, frontend/CMS checks including 27 CMS files, formatting
      and privacy/policy gates; unchanged tree). Pilot operator wiring, physical
      constraint auditing, schema upgrades and restore integration remain open.
- [ ] Add synthetic Golden records for at least two actions and two Charity
      Admins with non-overlapping membership.
- [x] Generate and compile TypeScript field types for the installed version 1
      collection. `./leonaid export-campaign-types` prints deterministic,
      source-derived output; `campaign-fields.generated.ts` is checked in and
      `./leonaid check` rejects drift. The generator preserves optional/null
      fields, required nested properties and the theme union, and explicitly
      rejects unsupported field types. Actual compiler fixtures accept valid
      records and require errors for missing action bindings, invalid themes,
      malformed repeater fields and undeclared Core/media fields. This is a
      field-shape interface, not runtime validation or an authorization grant.
      `schema-runtime` passed on `854fe0e` in isolated project
      `leonaid-emdash-tmp-1rndj92nkv`, proving generated output matches the actual
      installed EmDash/PostgreSQL registry, the source schema and committed
      types, including reordered fields. Compiler and prior concurrent install,
      content preservation and drift-denial proofs passed in the same run.
      No host ports were exposed; owned containers, networks and volume were
      removed. `./leonaid check` passed on the same commit: 208 unit tests,
      242 Python source-file checks, API parity, frontend/CMS checks including
      28 CMS files, generated-type/negative-compiler proofs, formatting and
      privacy/policy gates; unchanged worktree. Full `content-model` acceptance,
      global action uniqueness and media fields remain open.

Verification:

```sh
./leonaid test-emdash-spike --case content-model
```

Expected: schema creation is repeatable from an empty database; duplicate or
mutable `action_id` values are rejected; Core-owned and executable-content
fields are absent; generated TypeScript types compile.

### EMS-050 — Render live campaign microsites from both systems

- [x] Share one unit-aware quantity-preview formatter between SSR and browser
      enhancement. Keep boxes, packages, individual pieces and sponsoring
      separate; show physical contents only when known for boxes/packages.
      Empty and invalid selections have explicit messages. Aggregate only
      matching units and contents; do not count sponsoring as physical pieces.
      `public-order-component` passed in `leonaid-emdash-tmp-i8ts9pl52q` and
      `campaign-public-http` passed in `leonaid-emdash-tmp-3lfbnqg6gw`, serially.
      Both real Astro pages passed Chromium/Firefox/WebKit with and without JS,
      first with the original offering and then with three extra synthetic
      offerings inserted into the isolated Core PostgreSQL database (24 form
      journeys total). The mixed selection retained three boxes, two packages,
      four pieces and one sponsoring after the real Core dependency error;
      its preview stayed unit-specific and its total was 115 EUR. Initial SSR
      and enhanced summaries agree; JS input updates and native error redisplay
      use the same formatter. Focused tests cover ordering, aggregation,
      different/missing package sizes, zero and invalid quantities. Existing
      retained-input, escaped-markup, no-cookie/no-false-success, publication,
      draft/TLS and Core-outage regressions passed. Synthetic full-page mobile
      screenshots were inspected for layout; exact summary text and overflow
      were browser-asserted. No host ports were published; all owned containers,
      networks and volumes were removed. This closes the selection-preview
      issue only: accepted-order confirmation summaries, successful ordering,
      idempotency and the full validation matrix remain open. Core order/CRM
      authority and the existing Astro-to-Core transport are unchanged.
      Quality gate: `./leonaid check` passed at `56e404e`: 208 unit tests,
      244 Python source files, 24 public and 46 CMS Astro files with zero
      diagnostics, frontend/API/schema type checks, formatting and privacy/policy
      checks; the committed worktree stayed unchanged.

- [x] Preserve request-local order inputs on native form errors without cookies,
      CMS storage or another identity. The shared form uses a bounded 64 KiB
      redisplay reader with a two-second read deadline, explicit text-field
      limits, matching Core alias, validated quantities and retained valid
      command ID. Prices, offering metadata and access tokens remain freshly
      supplied by Core. Native error redisplay requires renewed privacy and
      binding confirmation and explains that the current total must be reviewed.
      Separate billing fields are reachable without JavaScript; the existing
      enhancement still hides/disables them when the delivery address is used.
      `public-order-component` passed in `leonaid-emdash-tmp-pukzlsqcjh` and
      `campaign-public-http` passed in `leonaid-emdash-tmp-z3j2pdug9z`, serially:
      both actual Astro pages, Chromium/Firefox/WebKit, with and without JS.
      All 15 contact/address/message fields, separate-billing selection, three
      Krapfentaxi boxes, their 108 EUR total and the command ID survived the real
      Core CRM-unavailable response. Hostile markup remained an escaped input
      value, not an executable element. No cookie or false success appeared.
      The focused redisplay proof covered alias mismatch, duplicate/oversized
      values, invalid quantity/UUID and credential/quote exclusion. An initial
      browser run found textarea formatting whitespace; `set:text` fixed the
      exact round trip before both passing runs. Publication/TLS/Core-outage
      regressions passed; all owned Docker resources were removed, no host ports
      published. This proves error redisplay, not accepted-order idempotency,
      uncertain-outcome retry, mixed-offering summaries or the complete no-JS
      success/validation matrix; those remain required with the Twenty journey.
      Quality gate: `./leonaid check` passed at `5ece946`: 208 unit tests,
      244 Python source files, 24 public and 46 CMS Astro files with zero
      diagnostics, frontend/API/schema type checks, formatting and privacy/policy
      checks; the committed worktree stayed unchanged.

- [x] Embed the shared order form in `/campaigns/<archive_slug>/` using fresh
      Core offerings, form configuration, token and authoritative `orderAlias`.
      The CTA now targets `#bestellen`; it no longer hands off to the legacy
      alias page. Register only the existing `createPublicOrder` action in the
      campaign Astro service for native form POSTs. Browser RPC `/_actions/*`
      remains owned by `apps/public`; direct CMS RPC remains denied and its
      injected route is explicitly classified internal-only in the build
      inventory. No EmDash content API, order schema or order storage is added.
      Native POST admission requires the canonical trailing-slash page, exactly
      one supported action query, trusted HTTPS origin, completed bootstrap and
      currently published Core/CMS content. Core still validates the order.
      `campaign-public-http` passed in `leonaid-emdash-tmp-c2ft1jsnvo`;
      the strengthened `campaign-public-media` passed in
      `leonaid-emdash-tmp-ps5fkwk0hh`. Chromium, Firefox and WebKit submitted the
      actual embedded form with and without JavaScript, stayed on the canonical
      page without POST redirects and displayed the exact Core CRM-unavailable
      error without false success. JavaScript input retention passed. CA-verified
      HTTP probes proved missing/unpublished/future/expired and Core-outage
      native POST denial, wrong-origin/action/noncanonical denial, no cookies
      and no-store. Published HTML comparisons exclude only the two explicitly
      per-request token/command-ID values; all editorial content and private
      draft checks remain compared. Private media delivery, corruption/repair,
      real SQL-lock failures, Core-read availability and recovery regressions
      passed. Both unique stacks removed all owned resources without host ports.
      This supersedes the temporary order handoff, not the remaining accepted
      order gate: Twenty-backed success/idempotency, no-JavaScript input
      retention, final demo import/theme and redirect cutover remain open.
      Quality gate: `./leonaid check` passed at `9248747`: 208 unit tests,
      244 Python source files, 23 public and 46 CMS Astro files with zero
      diagnostics, frontend/API/schema type checks, formatting and privacy/policy
      checks; the committed worktree stayed unchanged.

- [x] Extract the existing public order form into shared `PublicOrder.astro`
      with an explicit Core order-alias prop and shared price/unit formatters.
      Existing alias pages use the same form, Astro action and progressive
      enhancement; no new CMS order endpoint or alternative order storage is
      introduced. `./leonaid test-emdash-spike --case public-order-component`
      passed in isolated project `leonaid-emdash-tmp-hxqkg5saco`: production
      public Astro and Core, Chromium/Firefox/WebKit, desktop with JavaScript
      and mobile without JavaScript. Each actual submission reached the fixed
      Core CRM-unavailable error, kept the form visible, showed no false success
      and caused no horizontal overflow or session cookie. JavaScript error
      handling retained the entered email. All owned containers, networks and
      volumes were removed; no host ports were published. This is a shared-form
      prerequisite only: CMS embedding, accepted orders with Twenty, no-JavaScript
      input retention and final alias cutover remain open. Browser certificate
      validation is not covered by this fixture; TLS has separate gates.
      Quality gate: `./leonaid check` passed at `c8d87d2` with 208 unit tests,
      244 Python source files, public/CMS Astro diagnostics clean, frontend
      type checks, generated API/schema types, formatting and privacy/policy
      checks. The committed worktree remained unchanged.

- [x] Add a five-second server-side statement timeout to the hash-guarded
      runtime PostgreSQL adapter. Existing explicit transaction-local limits
      remain effective; operator migrations remain separate. `postgres-pool`
      passed in `leonaid-emdash-tmp-fg8yredgsm`: PostgreSQL reports `5s`, cancels
      an actual eight-second statement with SQLSTATE `57014` within 4.5–7
      seconds, and successfully reuses that exact connection afterwards.
      Existing pool-saturation, queue cancellation and recovery tests pass.
      Extend `campaign-public-media` with actual HTTP failure isolation:
      lock `options`, then `ec_campaign_pages` in the synthetic CMS database;
      prove the public SQL request is blocked using PostgreSQL's blocking graph.
      Concurrent anonymous page/image requests must return sanitized no-store
      503 responses within six seconds while authenticated Core identity and
      public Core campaign reads still return 200. Unlocking restores both CMS
      responses. This passed in `leonaid-emdash-tmp-o4qnjgiwmf` alongside the
      production build, TLS/bootstrap, publication/media-integrity, all three
      browser engines and service-outage/recovery regressions. The initially
      parallel HTTP run exhausted Docker's default address pools before startup;
      its own partial network was removed, and the serial retry passed without
      touching other stacks. All owned proof resources were removed; no host
      ports were exposed. This proves these specific lock failures and Core
      read availability, not full concurrent order acceptance, total request
      deadlines, peak-load budgets or the complete failure matrix.
      Post-commit `./leonaid check` passed at `5f780a2`: 208 unit tests, 244
      Python source checks, 45 CMS files without diagnostics, frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.

- [x] Bound actual PostgreSQL pool acquisition in the CMS runtime to two
      seconds while retaining the existing five-connection maximum. The pinned
      upstream adapter ignores timeout options, so a hash-guarded build
      transform adds `connectionTimeoutMillis: 2000` to its actual `pg.Pool`.
      Preserve the upstream fail-fast migration dialect and runtime-only
      credentials. Source drift/double patching or a production build that did
      not apply the transform must fail closed. No additional pool or database
      service is introduced; operator migration scripts remain separate.
      `postgres-pool` passed in `leonaid-emdash-tmp-jl3gly3zyd`: load the exact
      production transform with the real installed driver, hold five actual
      PostgreSQL connections, and require further acquisitions to reject in
      1.8–4 seconds. The public reader returns `PublishedCampaignUnavailable`.
      Releasing the connections restores capacity; server activity confirms
      an expired queued query never runs later. Byte/semantic drift and double
      application are rejected. The initial fixture import used pg's CommonJS
      entry; selecting its real ESM export corrected the fixture without
      changing the driver or production patch.
      `campaign-public-media` then passed in `leonaid-emdash-tmp-o02d7pqyzn`:
      production build confirms patch application, and actual Core/CMS/TLS,
      native publish/draft isolation, media corruption/repair, three-browser
      desktop/mobile and service failure/recovery regressions pass. All owned
      resources were removed; no host ports were published. This is a real
      adapter-level saturation proof plus runtime regression, not HTTP-level
      saturation or a whole-request deadline. SQL execution, total request
      budgets and mixed Core/CMS load acceptance remain open.
      Post-commit `./leonaid check` passed at `868cdea`: 208 unit tests, 244
      Python source checks, 45 CMS files without diagnostics, frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.

- [x] Extend the public-media live gate with real RustFS corruption and repair,
      without replacing the storage client or HTTP responses. The isolated
      operator targets only the proof's known synthetic campaign/media ID and
      validates its original hash before changing any object. Independently
      inject same-length byte corruption, incorrect object MIME with intact
      bytes, and object deletion. Anonymous HTTPS must return no-store 503
      rather than damaged bytes or a cached image; restore the original object
      after each fault and require the original hash through anonymous HTTP.
      Before/after SQL snapshots prove unchanged media metadata, campaign
      bindings, content and revision history for every fault/repair operation.
      `campaign-public-media` passed in `leonaid-emdash-tmp-m27lauksr4`, including
      all three fault/repair pairs, real image decoding in Chromium/Firefox/
      WebKit on desktop/mobile with/without JavaScript, and the existing
      publication, private-draft, Core-window, RustFS/Core-outage and restart
      regressions. The probe remains Edge-only; only the isolated operator has
      scoped S3/database access. No host ports were exposed; owned containers,
      networks, volumes and transient proof files were removed. This proves
      individual object repair, not coordinated fresh backup restoration or
      concurrent withdrawal during object I/O; those gates remain open.
      Post-commit `./leonaid check` passed at `0b6e95c`: 208 unit tests, 244
      Python source checks, 44 CMS files without diagnostics, frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.

- [x] Deliver publication-gated public raster images at
      `/campaigns/<archive_slug>/media/<media_id>`, backed by the existing
      private RustFS bucket. Resolve a ready, action-bound media ID referenced
      by live CMS content only; accept no object key from the caller. Check
      stored MIME and SHA-256, then recheck Core availability and the live CMS
      reference after storage I/O. Return no-store responses with nosniff and
      a restrictive image CSP. Use these URLs for responsive hero/partner
      images and accurate social-image metadata in the existing public layout.
      `campaign-public-media` passed in `leonaid-emdash-tmp-nsakvr2urm`:
      actual uploads and native CMS edit/publish over CA-verified HTTPS,
      byte/hash identity, GET/HEAD, method/preview rejection, draft and pending
      concealment, foreign IDs and replaced live URLs denied, unpublish and
      republish without rebuilding, and no leaked private storage URLs.
      Core withdrawal/future/expired windows hide images on the next request;
      stopped RustFS/Core produce 503, and RustFS restart restores identical
      bytes. Chromium/Firefox/WebKit decode hero and partner images on desktop
      with JavaScript and mobile without JavaScript; alt text, dimensions,
      social metadata, repeat visits, keyboard navigation and overflow checks
      pass. Synthetic desktop/mobile screenshots were visually reviewed.
      No host ports were published; all owned resources were removed.
      Initial proof failures identified a missing required title in the test
      update and an overly narrow assertion for Caddy's additional CSP;
      neither required weakening authorization or response security.
      This is not complete public-media acceptance: concurrent withdrawal
      races, tamper/recovery, fresh backup restore and whole-request/resource
      budgets remain open, as do final demo migration and integrated ordering.
      Post-commit `./leonaid check` passed at `1ba5ed0`: 208 unit tests, 244
      Python source checks, 44 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.

- [x] Deliver the first public text-rendering milestone at
      `/campaigns/<archive_slug>/`: fresh bounded/no-redirect Core GET through
      the generated client, then action-bound live-only CMS reading through
      the supported server runtime API. Anonymous EmDash locals deliberately
      omit `db`; the initial live failure identified and corrected this wiring.
      Reuse the existing public LeonAid layout, fonts and tokens. Render CMS
      hero text, validated Portable Text, FAQ and partner text/links alongside
      Core carrier, purpose and offering prices. The temporary order CTA links
      to the existing alias-based order journey; it must be replaced by the
      integrated form BEFORE redirect-alias cutover to avoid a redirect loop.
      This is not final demo migration or complete EMS-050 acceptance.
      `campaign-public-http` passed in `leonaid-emdash-tmp-qy8wgfzker`: actual
      CA-verified HTTPS, GET/HEAD/no-store/no-cookie, canonical slash redirect,
      escaped markup, native API publish/unpublish/recovery without rebuild,
      identical public HTML after a private draft (also with Core login and
      non-native preview parameters), explicit native preview/edit-cookie
      rejection, missing/archive concealment and POST rejection. Committed
      Core withdrawal/future/expired windows hide both content and the order
      CTA on the next HTTP request; stopping Core gives a no-store 503 page.
      Chromium/Firefox/WebKit passed anonymous desktop/mobile, JS/no-JS,
      repeat navigation, native FAQ, no horizontal overflow and keyboard
      skip-link/main-focus tests. Synthetic desktop/mobile screenshots were
      visually reviewed. Renderer tests cover escaping, styles/marks, nested
      lists, prototype-like link keys and unsafe URL/markup rejection.
      All owned Docker resources removed; no host ports exposed. Public media,
      all remaining Core presentation fields, integrated ordering, theme-specific
      Krapfentaxi rendering, authenticated preview, full browser cache/failure
      matrix, whole-request/pool deadlines and historical archives remain open.
      Public pages are still gated by completed bootstrap and secure ingress.
      Post-commit `./leonaid check` passed at `c47240d`: 208 unit tests, 244
      Python source checks, 42 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.

- [x] Add the server-only published-content reader prerequisite, separate from
      the draft-hydrating editor runtime. `readPublishedCampaign` accepts only
      a Core action UUID, checks binding guards, locks a published/non-trashed
      record through live-column hydration and editorial/media-reference
      validation, and returns no author or draft/revision metadata. Callers
      MUST first resolve current Core public availability; this reader does
      not grant public visibility or enable any HTTP route on its own.
      `campaign-public-content` passed against real PostgreSQL in isolated
      project `leonaid-emdash-tmp-ffleaettpc`: private follow-up draft concealment,
      next-read publish/unpublish, two published campaign bindings, missing and
      invalid selectors, scheduled/trashed concealment, malformed editorial
      data and disabled-guard rejection/recovery. An actual second connection
      holding a row write lock proves bounded lock failure and post-release
      recovery. No host ports; all owned resources removed. Per-statement/lock
      limits are implemented, but whole-request/pool acquisition deadlines,
      Core integration, media delivery and public HTTP/browser rendering remain
      open. The command is included in `all`, which still reports incomplete.
      Post-commit `./leonaid check` passed at `f00de47`: 208 unit tests, 244
      Python source checks, 39 CMS files without diagnostics, frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.

- [x] Verify the HTTP-issued campaign token with the real Core codec and make
      the positive form fixture mandatory. The signature binds the expected
      action ID and current order alias, not the stable campaign slug; the
      codec rejects the wrong alias and a corrupted token. In the deliberately
      CRM-unconfigured fixture, the actual order endpoint returns 503 with
      `public_order_crm_unavailable` and leaves commitments unchanged.
      `campaign-core-public` passed in `leonaid-emdash-tmp-wonse17q7r`, including
      existing PostgreSQL/HTTP publication and legacy-route checks; owned Docker
      resources were removed and no host ports exposed. Initial attempts to
      reach the honeypot returned 503 because Core does not construct its order
      service without CRM configuration. This is codec-binding and dependency
      rejection evidence, NOT HTTP token redemption or successful ordering.
      Prove those separately with an actual isolated Twenty-enabled stack;
      do not substitute fake CRM credentials or weaken the service boundary.
      Post-commit `./leonaid check` passed at `c29a1a2`: 208 unit tests, 244
      Python source checks, 38 CMS files without diagnostics, frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.
      The first check identified missing helper annotations, corrected before
      the successful complete rerun.

- [x] Expose the active-campaign Core HTTP prerequisite at
      `/api/v1/public/actions/campaign/{archive_slug}` with a dedicated
      `PublicCampaignRouteResponse` and generated `resolvePublicCampaign` client.
      The stable URL slug is separate from `orderAlias`; existing form/legal
      serialization and alias-bound token issuance are retained. Forms and
      order alias are omitted when Core legal/availability checks disallow
      submission. Success and campaign-path error responses use `no-store`.
      `campaign-core-public` passed in `leonaid-emdash-tmp-gzxxfwoipz`: actual
      anonymous HTTP published response, stable route metadata, no session
      cookie, immediate committed withdrawal/future/expired-window concealment,
      404/405 no-store, and unchanged legacy alias/archive responses. Existing
      PostgreSQL resolver/withdrawal/recovery assertions also passed. All owned
      resources removed; no host ports. This is direct Core HTTP evidence, not
      public TLS/browser cache acceptance, token redemption/order submission,
      dependency-failure deadlines, historical archive policy or Astro delivery.
      Post-commit `./leonaid check` passed at `74f2dd9`: 208 unit tests, 243
      Python source checks, 38 CMS files without diagnostics, all frontend/API/
      generated-type/format/privacy/policy gates and an unchanged committed tree.

- [x] Add and live-prove the internal active-campaign Core resolver prerequisite.
      `resolve_public_campaign` resolves the stable archive slug but applies fresh
      active/publication-window checks, never the legacy archive disclosure rule.
      Its route value and canonical path identify `/campaigns/<slug>/`; a separate
      internal `order_alias` retains the existing Core order-token binding when
      an order form is available. Alias re-resolution must return the same action
      and still be published, otherwise the result is inactive. No new HTTP route
      or transport schema is enabled by this step. `campaign-core-public` passed
      against real PostgreSQL in `leonaid-emdash-tmp-oilpqvfn0n`: active alias-data/
      offering/form parity, canonical path, order-alias binding, before/after-window
      concealment, draft/archive concealment and missing-slug rejection. An actual
      committed publication withdrawal is observed by the next service call;
      restoring the fixture restores the exact result. Owned Docker resources and
      temporary state were removed; no host ports. HTTP/cache contracts, no-alias
      and alias-move race proofs, historical archive policy, public rendering and
      actual order submission remain open. Existing alias/archive endpoints and
      their canonical paths are unchanged at this prerequisite milestone.
      The legacy HTTP serializer explicitly rejects the new internal route kind
      until its transport contract is implemented. The extended live run in
      `leonaid-emdash-tmp-7zvnlhvvbl` also passed actual HTTP GETs to both existing
      alias/archive endpoints with unchanged route kinds and archive canonical
      path; all owned resources were removed. `./leonaid check` passed at
      `6f231b7` (208 unit tests, 243 Python source checks, 38 CMS files without
      diagnostics, all frontend/API/typegen/format/privacy/policy gates and an
      unchanged tree); the first check had identified the missing explicit
      transport boundary after extending the internal route enum.
      The final extended proof commit `0d6e3bf` also passed `./leonaid check`
      with the same test/file counts and an unchanged committed tree.

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

- [x] Prove the native new-page campaign handoff prerequisite for System Admins:
      `/_emdash/admin/content/campaign_pages/new?campaign=<Core UUID>` prefills
      the existing editor's action binding and internal slug without manual
      UUID/slug input. Validate the single canonical UUID and current Core access
      on GET; preserve only the validated campaign parameter through anonymous
      login redirection. POST still performs independent Core authorization and
      guarded creation. Evidence: `admin-browser` passed in Chromium, Firefox
      and WebKit in isolated project `leonaid-emdash-tmp-cc9ihf2dyj`, including
      actual creation, duplicate rejection, autosave/reload, malformed/duplicate
      query rejection, missing Core target fail-closed and Charity denial.
      Existing SMTP login/fresh-login, native editing/publication, revocation and
      bootstrap TLS restart/database-failure regressions passed. All owned
      containers, networks and volumes were removed; no host ports were exposed.
      `./leonaid check` passed on `bcad4db`: 208 unit tests, 242 Python source-file
      checks, API parity, frontend/CMS type checks, formatting and privacy/policy
      gates, with unchanged worktree. This does not close the navigation entry,
      existing-microsite resolver, chooser, Back affordance or Charity admission.
- [ ] Add **Edit microsite** to the existing role-aware LeonAid navigation for
      System Admins and Charity Admins only.
- [x] Add the selected-action resolver prerequisite for System Admins:
      `GET /_emdash/admin/campaigns/<Core UUID>` rechecks Core access and returns
      a no-store 303 to the exact native editor or the campaign-prefilled new
      form. GET creates no content. Multiple bindings and a real trashed CMS row
      return a static 409; missing Core targets fail closed. Register the endpoint
      explicitly through Astro and require its presence in the build inventory.
      Evidence: `admin-browser` passed in Chromium, Firefox and WebKit in isolated
      project `leonaid-emdash-tmp-76kqblohiv`, including both redirects, actual
      editor arrival, unchanged content count on lookup, ambiguous/trashed
      binding denial, unsupported POST denial, anonymous login return, Charity
      denial and revoked-session redirection. The trash fixture invokes the real
      EmDash delete handler; no HTTP response is substituted. Previous native
      creation/editing/publication, SMTP login/fresh-login, bootstrap restart and
      database-failure regressions passed. All owned resources were removed and
      no host ports were exposed. `./leonaid check` passed on `2423161` with 208
      unit tests, 242 Python source-file checks, API parity, frontend/CMS checks
      including 24 CMS files, formatting and privacy/policy gates; unchanged tree.
      The initial run on `6b08cd6` correctly failed because an underscored
      filesystem page was absent from the emitted route inventory; explicit
      registration fixed it without weakening the expected 303. This does not
      close the role-aware LeonAid control, chooser, Back navigation or Charity
      admission, nor replace the outstanding global binding-uniqueness migration.
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

- [x] Show mixed-unit accepted-order quantities from persisted Core line
      snapshots in both native SSR and enhanced JavaScript confirmations.
      Verify box, package, piece and sponsoring together, including exact native
      POST retries, against actual Core SQL and isolated Twenty.
      `./leonaid test-emdash-spike --case campaign-orders` passed in isolated
      project `leonaid-emdash-tmp-htjxpzo4bi`: 24 accepted browser orders across
      Chromium, Firefox and WebKit, desktop JS and mobile no-JS, including six
      mixed orders. All twelve native POST retries kept the original reference
      and quantity summary with no extra orders. The additive Core `quantities`
      response uses persisted line snapshots with deterministic ordering; legacy
      totals remain available. Mixed confirmations show three boxes (72 pieces),
      two packages, four pieces and one sponsoring for 115 EUR. Actual Core SQL
      verified line units, contents, prices, consent and audit evidence; actual
      Twenty reads verified company/person records. Chromium and WebKit mobile
      screenshots in `tmp.KOLjkVELx8` were visually inspected. All twelve prior
      failure/redisplay cases, 84 valid-payload public denials, 364 ingress
      method/path denials, publication states and Core outage checks passed.
      All owned containers, volumes and networks were removed; no host ports
      were published. This is paced functional evidence, not burst acceptance.
      Full `./leonaid check` passed at `18c9b82`: 210 unit tests, 249 Python
      source-file type checks, 24 public and 46 campaign Astro files with zero
      diagnostics, API/schema/type generation, formatting and privacy/CI gates.
      The working tree remained unchanged; existing upstream Pydantic/Vite
      deprecation warnings remain.
- [x] Bound Core order processing, including pool/SQL-lock and CRM admission
      waits, below Astro's 12-second transport timeout. An eight-second
      cancellation scope now returns a safe `public_order_processing_timeout`
      503 instead of allowing the service to wait indefinitely. Public-action
      errors are no-store. The message preserves uncertainty about completed CRM
      writes and instructs retry with the same command rather than a fresh page.
      This is a processing budget after body validation, not a body-ingress or
      whole-response deadline; cancellation cleanup and shared-server budgets
      still need the broader checks below.
      `./leonaid test-emdash-spike --case campaign-orders` passed in isolated
      project `leonaid-emdash-tmp-wbg4whzdpl`: 24 paced and 24 unpaced browser
      orders across Chromium/Firefox/WebKit, JS desktop and no-JS mobile. The
      burst's Firefox JS mixed order returned the actual Core timeout after
      8.06 seconds. Inputs and command ID survived; after the CRM window recovered,
      the same command succeeded with all four units and 115 EUR. All 48 orders
      and 24 exact native POST replays passed SQL/consent/audit checks and real
      Twenty person/company uniqueness checks. The timeout screenshot in
      `tmp.XXts2QQEZZ` was visually inspected.
      A separate actual PostgreSQL advisory lock proved that Core was waiting on
      that lock, returned no-store 503 before eleven seconds, stopped waiting,
      and left seven Core tables and real Twenty unchanged. Unlocking allowed
      exactly the same command to succeed; another replay changed no persisted
      state. Valid-payload public ingress, prior error/redisplay, publication and
      Core-outage regressions also passed. All owned containers, networks and
      volumes were removed; no host ports were published.
      Preparatory runs exposed two test defects: enhanced Astro failures use
      HTTP 503 (native HTML redisplay uses 200), and redundant per-record CRM
      verification requests exhausted Twenty's real quota with HTTP 429. The
      verifier now uses its complete in-memory collection reads and waits one
      CRM window after the burst before observation. No product limit was raised
      or disabled. Earlier unbounded failures were observed in projects
      `leonaid-emdash-tmp-iefyq9xuvg` and `leonaid-emdash-tmp-bwmrkpeu7j`; the exact
      historical wait source was not instrumented and is not claimed proven.
      Full `./leonaid check` passed at `bcccf2c`: 210 unit tests, 250 Python
      source-file type checks, 24 public and 46 campaign Astro files with zero
      diagnostics, API/schema/type generation, formatting and privacy/CI gates.
      The working tree remained unchanged; existing upstream Pydantic/Vite
      deprecation warnings remain.
- [ ] Complete burst/uncertain-outcome acceptance beyond the measured cases:
      native-browser timeout recovery, cancellation during partial CRM writes,
      body/whole-response deadlines, and acceptable resource use under combined
      Core/CMS load and multiple runtime workers. Keep command identity and
      prove no duplicate orders or CRM records. The processing budget and one
      sequential browser burst above are not a production capacity/SLO proof.
- [x] Live-prove accepted campaign orders against real isolated Twenty using
      `./leonaid test-emdash-spike --case campaign-orders`. The pinned stack
      provisions its own Twenty database, Redis, worker and schema. A short-lived
      operator verifies a freshly created restricted CRM key and seeds synthetic
      companies/people; only Core receives the runtime CRM credential. No order
      is stored through EmDash content APIs.
      The successful project `leonaid-emdash-tmp-xfg419em1s` completed 18 browser
      orders: Chromium, Firefox and WebKit, each with JavaScript on desktop and
      without JavaScript at mobile width, for new companies, existing companies
      and private persons. All responses returned HTTP 200 from Astro with the
      expected reference and total. Core SQL independently verified each order,
      line pricing, recipient/consent snapshots and audit evidence; real Twenty
      reads verified the associated company/person records. Nine exact native
      POST retries returned the original reference and created no extra orders.
      Replay is explicit browser-native form resubmission, not a claim that all
      browsers repeat POST on reload (Firefox uses GET). Synthetic visitors have
      distinct browser identifiers; Core's existing five-attempt admission limit
      is unchanged. The browser supplies an incorrect internal caller key, which
      cannot override Astro's server-held key. Consent uses normal hit-tested
      clicks after explicit viewport positioning, avoiding smooth-scroll races.
      Twelve failure/redisplay cases, publication-window checks, Core outage and
      364 direct ingress rejection requests also passed. All owned containers,
      volumes and networks were removed; no host ports were published. The CRM
      test network uses an explicit collision-checked subnet because the host's
      automatic address pools were exhausted; Docker rejects concurrent overlap.
      Synthetic screenshots were retained in `tmp.6M8YVy0v80`; the WebKit mobile
      private-order confirmation was visually inspected. This is not production
      activation, a load test, a mixed-unit success-summary proof, or the complete
      migration/recovery and security matrix. Those broader gates remain open.
      Full `./leonaid check` passed on commit `4c5ca9d`: 210 unit tests,
      248 Python files with no typing issues, 24 public and 46 campaign Astro
      files with zero diagnostics, plus API generation, schema/type generation,
      formatting, dependency and privacy/CI gates. The working tree remained
      unchanged. Existing upstream Pydantic/Vite deprecation warnings remain.
- [x] Authenticate internal order callers independently of network location.
      Add a dedicated 32-byte hex `LEONAID_ORDER_SUBMISSION_KEY`, distributed
      only to Core, `public` and `campaign-site` runtime services. The shared
      server-only Astro adapter supplies it explicitly and refuses to send it
      to any URL other than the fixed internal `http://api:8000` destination.
      Caller-provided frontend headers are not copied into that credential.
      Core checks exactly one well-formed header with constant-time comparison
      before body validation/CORS/order processing; absent configuration,
      missing/wrong/malformed/duplicate keys fail closed with no-store 404.
      Normal Core validation, tokens, prices and CRM authority remain unchanged.
      `campaign-public-http` passed in `leonaid-emdash-tmp-tpnqj3cp1c`: real
      internal HTTP rejection across seven methods, valid caller reaching 422
      schema validation, Core restarted without its key (even the valid caller
      denied), then restored. PostgreSQL commitment counts stayed unchanged
      during each boundary probe. The first missing-key proof failed because
      the temporary environment switch also emptied the probe's key; retain
      the independent operator key explicitly and assert its length before
      testing. The complete rerun passed. Runtime Compose validation checks
      exact allowed key recipients without printing values. Twelve actual
      Chromium/Firefox/WebKit form journeys with/without JS and original/mixed
      offerings still reach the expected CRM-unavailable error through both
      Astro transports. Public ingress denial with running/stopped Core,
      publication and draft-isolation regressions passed. All owned Docker
      resources were removed; no host ports were published. Twelve focused
      caller-policy/configuration unit tests passed.
      Local and production env templates document the new independent key;
      the existing secret generator added it to this worktree's private,
      non-symlinked env file while preserving existing values. No other stack
      was restarted. Existing order-contract tools now authenticate their
      explicit internal test submissions. This is shared-secret authentication
      over the existing trusted Docker transport, not mTLS or protection from
      a compromised authorized service/host. Rotation, production preflight and
      recovery evidence remain required under EMS-080, as do successful orders
      with Twenty; the current fixture deliberately has no CRM credentials.
      Quality gate: `./leonaid check` passed at `8c87317`: 210 unit tests,
      246 Python source files, 24 public and 46 CMS Astro files with zero
      diagnostics, frontend/API/schema type checks, formatting and privacy/policy
      checks; the committed worktree stayed unchanged.

- [x] Live-prove both pilot Caddyfiles with the new `order-ingress-pilot` case
      (also included in `all` and CLI help). Each run uses only pinned Caddy and
      Node containers in a fresh, internal-only Docker network, no host ports,
      no operational environment and its own removable certificate volumes.
      The actual pilot source is mounted read-only, not rewritten for the test;
      synthetic `localhost` domains select local CA issuance instead of ACME.
      The first live attempt found that Caddy's automatic host-specific HTTPS
      redirect preceded the prior hostless port-80 denial. Add an explicit HTTP
      site for the public domain, retain the separate hostless health endpoint,
      and preserve the normal 308 redirect for non-order GET/POST requests.
      Final runs passed with `Caddyfile` in `leonaid-emdash-tmp-jopaazc86s` and
      `Caddyfile.test` in `leonaid-emdash-tmp-ey2exx8hli`: 182 raw-path requests
      each across seven methods, HTTP and CA-verified HTTPS; every order path
      was denied without redirect/cookie despite forged internal headers.
      Health requests remained 200, non-order HTTP GET/POST remained 308, and
      unrelated HTTPS API forwarding reached the expected unavailable upstream
      (502). No backend is started in this ingress-only proof. All owned
      networks, containers and volumes were removed, including failed attempts.
      This supersedes the prior pilot-validation-only limitation. It does not
      prove public ACME issuance, production activation, successful orders,
      committed-row invariance or exclusive internal caller authorization.
      Quality gate: `./leonaid check` passed at `0d195cc`: 208 unit tests,
      244 Python source files, 24 public and 46 CMS Astro files with zero
      diagnostics, frontend/API/schema type checks, formatting and privacy/policy
      checks; the committed worktree stayed unchanged.

- [x] Add the public Core-order ingress deny prerequisite. Local, pilot and
      pilot-test Caddy API handlers use an explicit `route` block that returns
      a no-store 404 for the order path before generic Core forwarding. Pilot
      HTTP also denies that path directly rather than redirecting the request.
      The rule has no method restriction or caller-header exception; encoded
      path matching uses Caddy's decoded/normalized path matcher. See the
      [Caddy ordering contract](https://caddyserver.com/docs/caddyfile/directives)
      and [path matcher contract](https://caddyserver.com/docs/caddyfile/matchers).
      `campaign-public-http` passed in isolated project
      `leonaid-emdash-tmp-crvaszuytq`: 182 actual raw-path HTTP/CA-verified HTTPS
      requests across seven methods and 13 path variants returned the fixed
      404, no-store, no Location and no cookie despite forged forwarding and
      CMS headers. Variants include encoded letters/slashes, repeated slashes,
      literal/encoded parent segments and query strings. Repeating all 182
      requests after stopping Core produced identical denials, proving the
      proxy boundary does not depend on Core. Internal direct submission still
      reaches Core schema validation (422); the unrelated public platform GET
      remains 200. Twelve real campaign form journeys across three browsers,
      JS/no-JS and original/mixed offerings still reach the actual Core
      CRM-unavailable response through Astro. Publication and outage regressions
      passed; all owned resources were removed and no host ports published.
      Both pilot files passed offline validation with pinned Caddy 2.11.4.
      This is local live ingress evidence plus pilot configuration validation,
      NOT a pilot live proof, production deployment, successful Twenty-backed
      order, database mutation audit or exclusive internal caller authorization.
      Those broader requirements in section 2.1 remain open.
      Quality gate: `./leonaid check` passed at `d9cce21`: 208 unit tests,
      244 Python source files, 24 public and 46 CMS Astro files with zero
      diagnostics, frontend/API/schema type checks, formatting and privacy/policy
      checks; the committed worktree stayed unchanged.

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
- [x] Permit initial setup only to a currently authenticated LeonAid System
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

Protected bootstrap checkpoint (6 September 2026):
`./leonaid test-emdash-spike --case bootstrap-runtime` passed with real production
EmDash, Core, PostgreSQL and Caddy. The client validates the actual TLS certificate
against this project's CA; it does not disable certificate verification. The
proof covers default denial, explicit 15-minute operator activation bound to one
Core System Admin UUID, anonymous/Charity denial, foreign Origin denial, forged
forwarding-header replacement, wrong HTTP Host rejection with fixed TLS SNI,
HTTP-to-HTTPS redirect, real setup-page delivery and successful setup POST.
Setup cannot be repeated and remains closed after a CMS restart and PostgreSQL
shutdown. No independently usable CMS session cookie is created.

The separate `cms-bootstrap-state` volume is consumed before upstream mutation;
completion additionally requires reading the actual database completion option.
Real-filesystem tests cover twelve concurrent attempts (exactly one consumes),
actor mismatch, expiry, corruption, symlinks and refusal to rearm existing state.
See `BOOTSTRAP.md` for state transitions, crash behavior and recovery obligations.
The proof creates only its own project networks/volumes, publishes no host ports,
and runs activation with no network or application credentials. Owned temporary
resources and synthetic session files were removed after the test.

This is not the full `tls-and-bootstrap` gate: browser wizard interaction,
general editor/login navigation, pilot runtime origin configuration, complete
proxy trust review and fresh-volume recovery remain open. The new durable state
must be included in EMS-080 before any pilot activation.

Regression/quality checkpoint: `./leonaid check` passed at `6325d98` with
208 unit tests, 242 Python source-file type checks, all frontend/CMS checks,
format/API/privacy/policy gates and an unchanged worktree. `auth-runtime` passed
again. `proxy-routing` now uses verified HTTPS, byte-checks 50 CMS assets and
proves public login/assets survive CMS shutdown; its copied public CA certificate
needed readable permissions for the unprivileged Node probe (no CA key is copied).
`closed-runtime` also passed all 18 default-deny requests without a database or
network. The pilot Caddy configuration passed offline adaptation/validation.

### EMS-080 — Extend backup, restore, upgrade, observability, and operator UX

Dependencies: EMS-050, EMS-070

- [ ] Add the EmDash database and its required runtime state to the existing
      consistent backup inventory.
      Include `cms-bootstrap-state`; missing state must remain closed on restore,
      never be reconstructed as an armed grant from an empty CMS database.
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
      Restore and verify the exact enabled campaign binding functions/triggers;
      missing or altered guards must leave campaign HTTP access closed.
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
  - [x] Multi-alias storage and legacy repository compatibility: migration
        `0028_multiple_campaign_aliases` preserves existing aliases as enabled
        primary aliases with unchanged targets/switch timestamps. Every row has
        a stable UUID and positive revision; alias names remain globally unique,
        while a partial unique index permits at most one primary alias per
        action and a separate action index supports additional redirects.
        Redirects have their own enabled flag. Primary aliases are disabled by
        release through existing publication controls, not by that flag.
        Legacy reads/order joins select only the enabled primary; primary
        replacement preserves redirects and cannot consume a redirect name.
        Completion releases all names and audits primary plus sorted redirects.
        The `alias-persistence` case passed in isolated project
        `leonaid-emdash-tmp-ewsjlmlnjd`: preceding-schema data preservation,
        downgrade/re-upgrade, refusal of lossy downgrade with extra rows,
        actual repository publication/order lookup, same-name concurrency with
        one winner, and lifecycle release audit. No new alias HTTP mutation or
        redirect resolution is enabled by this storage-only checkpoint.
        `krapfentaxi-orders` additionally passed against the new schema in
        `leonaid-emdash-tmp-qztj1gmtfp`: all three real Charity editor journeys,
        24 browser orders checked in Core/Twenty, twelve duplicate-free native
        replays and 84 direct public Core ingress denials. Both cases exited 0
        and removed only their own project resources. New API, authority,
        idempotency, UI and public redirect gates below remain open.
        Full `./leonaid check` at source commit `902e692` exited 0: 247 unit
        tests, 254 Python source checks, 24 public and 47 CMS Astro files without
        diagnostics, generated-type/format/privacy/policy gates and an unchanged
        committed tree. Existing dependency deprecation warnings remain.
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
  - [x] Reserve current service namespaces in the shared `PublicActionAlias`
        domain contract and PostgreSQL. Migration
        `0027_campaign_alias_namespaces` adds the missing `campaigns`,
        `email-change` and `health` roots, explicitly inventories the underscore
        asset/action/CMS roots already excluded by the slug grammar, and keeps
        the prior reserved-root constraint intact. Under a bounded table lock,
        collisions fail with a static operator-resolution error; no alias is
        renamed, deleted or retargeted. The `alias-namespaces` case passed in
        isolated project `leonaid-emdash-tmp-eahyubuxz5`: actual preceding-schema
        Golden data, three real collision/transaction rollbacks, domain and SQL
        unsafe-path denial, unchanged complete alias/action rows, downgrade,
        upgrade and repeated upgrade. Exit 0; only the project's own resources
        were removed. This is the namespace foundation, not completion of the
        multiple-alias persistence/API/UI or redirect resolver gates.
        Full `./leonaid check` at source commit `9479888` exited 0: 247 unit
        tests, 252 Python source checks, 24 public and 47 CMS Astro files without
        diagnostics, generated-type/format/privacy/policy gates and an unchanged
        committed tree. Existing dependency deprecation warnings remain.
- [ ] Enforce global uniqueness in the database, optimistic revision checks,
      idempotent mutation handling, and audit events recording actor, action,
      previous target, and new target. Concurrent claims must yield one winner
      and a clear conflict; UI checks alone are insufficient.
  - [x] Server-side redirect mutation core, not yet wired to HTTP: the typed
        `CampaignAliasCommand`/service and PostgreSQL adapter implement create,
        update (including disable/enable and action moves), and remove. Commands
        bind actor, source/target action, alias UUID, payload and revision to a
        durable receipt. Each transaction rechecks active Core account and
        current Charity memberships (both actions for moves), protects the
        legacy primary alias, uses bounded locks and stores mutation, audit and
        receipt atomically. Replays recheck current authority, including a
        subsequently moved alias's current action. `alias-commands` passed in
        isolated project `leonaid-emdash-tmp-mqb3ygudas`: actual role denial,
        own-action create/disable, rejected unauthorized move, System Admin
        move/remove, stale revision/name/payload conflicts, duplicate-free
        retries, withdrawal, one-winner concurrent claims, and real audit-trigger
        failure with full rollback followed by same-command retry. Nine unit
        cases additionally cover normalized paths, command invariants and bound
        fingerprints. Exit 0; the project's database/network/volume were removed.
        The new HTTP API, list contract, fresh-session handling, UI and complete
        request-level authorization/concurrency gates remain open; this test
        exercises the actual database mutation boundary directly.
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
./leonaid test-emdash-spike --case alias-namespaces
./leonaid test-emdash-spike --case alias-persistence
./leonaid test-emdash-spike --case alias-commands
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

- [x] Prepare the generic editorial schema needed to preserve the demo design:
      version 3 adds `brand_logo`, `story_eyebrow`, `story_title` and partner
      `eyebrow`/`link_label`, with bounded validation and generated types. Explicit
      v1/v2 upgrades refuse drift and ambiguous options. `schema-migration`
      passed in `leonaid-emdash-tmp-8y31un7ozp` and
      `leonaid-emdash-tmp-thhhjlz8il`: actual mid-DDL failure rollback,
      concurrent one-winner upgrade, retained published/draft/revision data
      including populated v2 image references, and repeatability.
      `schema-runtime` passed in `leonaid-emdash-tmp-w16y2u2kxw`.
      `campaign-public-media` passed in `leonaid-emdash-tmp-3k5zp4nb3w`:
      logo-only publication, private replacement draft, withdrawal of the old
      published logo, actual private RustFS bytes and HTTP failure recovery.
      `campaign-media-http` passed in `leonaid-emdash-tmp-bt1jlkogzq`:
      cross-action logo denial, actual Core-login editing of the new fields in
      Chromium/Firefox/WebKit, native partner-field reorder/save/reload, and
      existing upload, revocation and bootstrap failure/recovery gates.
      The first media run caught outdated repeater expectations for the new
      empty text fields; the corrected proof enters and verifies actual values.
      Each run used unique Docker resources, no host ports and complete cleanup.
      Post-commit `./leonaid check` at `8b6351d` passed 210 unit tests,
      250 Python source checks, 24 public and 46 CMS Astro files without
      diagnostics, generated-type/format/privacy/policy gates, and unchanged
      committed source. Existing dependency deprecation warnings remain.
      This prepares the schema only: operator migration CLI, demo import,
      renderer integration, cutover and complete recovery remain open below.
- [ ] Import the current demo's Krapfentaxi editorial texts and assets from
      `apps/public/src/components/KrapfentaxiIntro.astro`, the public layout,
      and `apps/public/src/assets/krapfentaxi/` into the campaign's EmDash record
      and dedicated media storage. Preserve asset attribution and existing design.
- [x] Define the versioned import source package from the existing demo rather
      than synthetic replacements. `krapfentaxi-source.mjs` pins the original
      component, three raster files and `SOURCES.md`; its deterministic manifest
      includes original asset provenance, source hashes and the unchanged rights
      notice. It explicitly does not claim production rights clearance.
      Editorial copy is compared against the actual pinned component; no Core
      business snapshots are copied. The payload builder requires ready,
      action-scoped media metadata and emits no storage keys. This is a payload
      shape guard, not a substitute for database ownership verification.
      `./leonaid test-emdash-spike --case krapfentaxi-source` passed offline in
      pinned Docker with the checkout read-only: actual image decode, repeatable
      fingerprints, isolated returned data, malformed/foreign/pending media
      denial, and actual five-file drift plus symlink refusal in temporary copies.
      This gate now runs in `./leonaid check`. It performs no database/storage
      writes; durable import tracking, target resolution, idempotent apply and
      repeat-run preservation of editor changes remain required below.
      Post-commit `./leonaid check` at `7894fd2` passed the offline source gate,
      210 unit tests, 250 Python source checks, 24 public and 47 CMS Astro files
      without diagnostics, generated-type/format/privacy/policy gates and an
      unchanged committed tree. Existing dependency deprecation warnings remain.
- [x] Add the CMS-driven Krapfentaxi renderer without duplicating the existing
      Core-owned offering, order, beneficiary, goal and privacy sections.
      `PublicAction` accepts the typed campaign route and its explicit order
      alias; a named editorial slot uses only validated published CMS fields.
      The shared layout accepts the published campaign logo without falling
      back to a hard-coded logo when the CMS field is intentionally empty.
      `campaign-public-media` passed in `leonaid-emdash-tmp-rcfefp4hao`:
      runtime theme/text/media publication with no rebuild/restart, private
      drafts before and after publication, exact Core-fact comparisons, one
      order form, and unchanged legacy `/krapfentaxi` in Chromium/Firefox/WebKit,
      desktop/mobile and JS/no-JS. Desktop/mobile screenshots were inspected.
      The first renderer test used EmDash's response envelope for Core and
      failed; the corrected test reads Core's direct typed response.
      Existing public media, database/storage recovery and public-order ingress
      denial gates also passed. Unique Docker resources, no host ports, complete
      cleanup. This uses synthetic editorial text/media: actual demo import,
      final visual acceptance with original assets, accepted orders through the
      themed page, alias cutover and restore remain open.
      Post-commit `./leonaid check` at `9cea665` passed 210 unit tests,
      250 Python source checks, 24 public and 47 CMS Astro files without
      diagnostics, generated-type/format/privacy/policy gates and unchanged
      committed source. Existing dependency deprecation warnings remain.
- [x] Implement a Docker-based, idempotent migration with dry-run reporting and
      an explicit apply mode. Resolve the existing action UUID via Core; create
      no duplicate CharityAction. Re-running must neither duplicate media nor
      overwrite subsequent editorial changes. Record migration version and
      source fingerprints without storing Core-owned facts as editable CMS data.
      `krapfentaxi-migration` passed in `leonaid-emdash-tmp-dovt8mdesk` with actual
      Core target/identity resolution and original private RustFS assets. The
      PostgreSQL journal atomically records reservations and final draft creation.
      Verified read-only dry-run, existing-editorial-content refusal, exact schema
      preflight, CLI session-file permissions and apply replay, same-ID resume
      after reserved/ready checkpoints, concurrent importer exclusion, actual
      final-write PostgreSQL failure/rollback, simulated lost success reply,
      later-edit preservation, anonymous S3/page/media denial and actual Core
      logout denial. Core business facts stayed unchanged; the comparison
      deliberately excludes newly issued per-request order capabilities.
      The first proof incorrectly compared those ephemeral capabilities and
      failed; the corrected proof compares all remaining business fields without
      logging token values. The operator uses the EmDash content repository
      directly to avoid raw upstream HTTP-handler exception logging.
      Unique Docker resources, dedicated CMS credentials only, no host ports,
      complete cleanup. See [operator contract](KRAPFENTAXI_IMPORT.md).
      This creates a draft, not a cutover. Process-kill/restart recovery, final
      imported-image visual acceptance, browser publication and backup/restore
      remain unproven and are required before migration acceptance.
      Post-commit `./leonaid check` at `76d25cb` passed the original-source gate,
      210 unit tests, 250 Python source checks, 24 public and 47 CMS Astro files
      without diagnostics, generated-type/format/privacy/policy gates and an
      unchanged committed tree. Existing dependency deprecation warnings remain.
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
  - [x] Canonical-page portion against the actual imported demo: the
        `krapfentaxi-migration` case now continues into native editor/browser
        checks after the importer revokes its operator session. In isolated
        project `leonaid-emdash-tmp-8lzp6htxtv`, Chromium, Firefox and WebKit
        each logged in as the assigned Charity Admin through real Core SMTP,
        edited story text and uploaded a replacement image, kept both private
        until Publish, and observed publication on the next ordinary anonymous
        canonical GET. A later draft remained private. Each engine checked the
        rendered taxi theme, loaded images, a single order form, mobile/no-JS
        and desktop/JS rendering, no horizontal overflow and no visitor cookies.
        The initial imported draft returned 404 before any browser publication.
        Exit 0; the project's own containers, volumes and networks were removed.
        This does not complete the parent gate: short-alias delivery, final
        original-asset visual acceptance and accepted themed-page orders remain
        separate outstanding checks. No deployment or CMS restart occurred
        between editor changes and public reads.
        Full `./leonaid check` at source commit `1de8faf` exited 0: 210 unit
        tests, 250 Python source checks, 24 public and 47 CMS Astro files without
        diagnostics, generated-type/format/privacy/policy gates and an unchanged
        committed tree. Existing dependency deprecation warnings remain.
- [ ] Prove Core changes (such as offering price and order availability) appear
      independently of editorial publishing. Complete an anonymous test order
      through the new page and verify the existing backend effects.
  - [x] Actual imported-page order acceptance: `./leonaid test-emdash-spike
--case krapfentaxi-orders` passed in isolated project
        `leonaid-emdash-tmp-zsjjfx0d9q`. This runs the real original-asset import
        and all three Charity editor/publication journeys, then adds fresh
        Twenty services and a verified restricted integration key. Without
        republishing CMS content, Core gains the mixed-unit offerings used by
        the existing order contract. Every visitor first verifies the taxi
        renderer and the last actually published editor marker, with its later
        draft absent. Chromium, Firefox and WebKit accepted all 24 orders
        (native/mobile and JS/desktop; new company, existing company, person,
        mixed units). Core SQL and real Twenty proved exact records, totals,
        line snapshots, consent and audit; twelve native POST replays created
        no duplicate orders. All 84 valid-payload public Core ingress probes
        were denied even with a valid service key, with seven Core tables and
        Twenty unchanged; internal unauthorized/authorized controls passed.
        Exit 0 and complete cleanup of only this project's resources. This
        proves normal order completion on the imported canonical page, not
        cutover/alias recovery, additional price/availability transitions, or
        burst/deadline behaviour on this theme.
        Full `./leonaid check` at source commit `6a0cb59` exited 0: 210 unit
        tests, 250 Python source checks, 24 public and 47 CMS Astro files without
        diagnostics, generated-type/format/privacy/policy gates and an unchanged
        committed tree. Existing dependency deprecation warnings remain.
- [ ] Rehearse rollback of renderer selection, aliases, and CMS data together.
      Rollback must preserve orders accepted since cutover: never restore an old
      whole-Core database over newly created transactions to undo a CMS change.
- [ ] Extend backup/restore verification to the final migrated demo and its
      aliases, then repeat the complete browser journey from fresh volumes.

Verification (new case implemented by this task):

```sh
./leonaid test-emdash-spike --case krapfentaxi-migration
./leonaid test-emdash-spike --case krapfentaxi-orders
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

| Actor                  | Campaign A                       | Campaign B                       | Global CMS settings |
| ---------------------- | -------------------------------- | -------------------------------- | ------------------- |
| System Admin           | read/write/publish               | read/write/publish               | allowed             |
| Charity Admin for A    | read/write/publish A             | no draft visibility, no mutation | denied              |
| Charity Admin for B    | no draft visibility, no mutation | read/write/publish B             | denied              |
| Akquisiteur for A      | denied                           | denied                           | denied              |
| Finance Reader         | denied                           | denied                           | denied              |
| Driver for A           | denied                           | denied                           | denied              |
| Suspended former Admin | denied                           | denied                           | denied              |
| Anonymous user         | public published view only       | public published view only       | denied              |

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
