# EmDash authorization surface

Status: bounded Charity editorial and private media HTTP admission implemented; full campaign isolation remains incomplete.

Baseline: EmDash 0.36.0 at `603062902369d9695608e85c2d034d4f66f7a1f1`.
`route-inventory.json` records each route's actual exported HTTP methods, package
module and SHA-256. The offline inventory command evaluates the upstream route
injector, not a filename-derived approximation. It includes 165 core routes and
20 built-in auth routes and one MCP route that are deliberately not enabled in
this installation (186 routes total).

All actors below are resolved through current Core sessions. The bounded
editorial routes admit current campaign-scoped Charity Admins after completed
bootstrap; disabled routes remain closed. The shared `authorization-surface`
test uses real HTTPS requests with System Admin, Charity Admin and anonymous
credentials, each declared method plus HEAD/OPTIONS. Own identity and manifest
GETs return 200 for both admin roles and 401 anonymously. The global dashboard
remains System-Admin-only (200/403/401). Other disabled operations remain 503.
The setup grant is already consumed in this proof. Root routes not owned by the
CMS are tracked by the separate proxy-routing/build route contract.

The `campaign-runtime` proof additionally exercises admitted GETs for the exact
`campaign_pages` collection and canonical ULID content/revision IDs. These need
completed bootstrap, valid HTTPS origin and a current authorized Core session.
Request-local handlers enforce the campaign-read primitives before upstream
data access. Unknown item IDs prove the wrapper's static `NOT_FOUND` response.
The separate `campaign-editorial-isolation` prerequisite exercises both Charity
actors with real Core memberships and disjoint campaign sets. A canonical item
PUT permits authorized System Admin or campaign-member editorial-draft edits
with a revision token, valid Origin and `X-EmDash-Request: 1`. It rejects binding
changes, metadata and direct publication. The versioned editorial contract allows
title, hero heading/introduction, bounded Portable Text, FAQ, partners, a fixed
theme enum and SEO description. Unknown fields and nested properties, executable
blocks/custom marks and unsafe links are rejected. Version 2 adds strict local
hero/social image and partner-logo references; ownership and cached file facts
must match ready media bound to this exact action. Aggregate
editorial JSON is limited to 60 KiB; raw create requests are limited to 64 KiB.
Core pricing, orders, lifecycle and legal configuration are never CMS fields.
Public safe rendering and full native rich-field UX remain separate gates.
The separate `campaign-media-http` proof admits only
scoped reservation, PUT, confirmation, listing, item reads and private file reads.
It uses real Core sessions and immutable campaign ownership; the upstream public
file route is explicitly reprotected rather than relying on upstream locals.
Confirmation verifies actual stored bytes and server-derived dimensions. Three
real logout races prove fresh Core checks after database waits at upload start,
object linking and confirmation. A ready media row is not public publication.
Version-2 references are verified before native normalization and mutations,
including locked stored revisions on restore/publication, and before returning
read or mutation results. Actual same-user cross-action creation and poisoned
stored-revision tests reject foreign references for both Charity and System
Admins with unchanged SQL/media. Native picker context and browser image-field
workflows remain incomplete; HTTP field acceptance is not a browser UX proof.

Actual HTTP/1 slow-body tests exposed proxy request-body draining before error
delivery. Both Caddy variants intercept only CMS 408/413 responses, set connection
closure and copy the upstream response. Other services and successful responses
retain their existing behavior. This uses the documented
[response interception contract](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#intercepting-responses)
and avoids enabling experimental
[HTTP/1 full duplex](https://caddyserver.com/docs/caddyfile/options#enable-full-duplex)
globally. The live TLS proof includes actual five-second body timeout, chunked
oversize denial, database failure/retry, storage outage/corruption, private reads,
two-actor isolation and Core revocation. Browser image-field UX and anonymous
publication-gated media remain unproven.

The native editor may echo the exact stored slug and locale, but cannot change
either. Its `skipRevision` hint is validated as a boolean and normalized to
`false`: every accepted autosave retains a new attributed draft revision.
The published 0.36 admin client drops `_rev` when reading and does not send it
when saving. The isolated, SHA-256-pinned `emdash-editor-patch.mjs` restores token
transport for native manual/autosaves; the backend still rejects missing/stale
tokens. This is not a replacement editor or a client-side authorization check.
The original runtime updater remains responsible for schema validation and
revision storage. The original runtime getter is retained after the scoped
parent check so current draft data and published `liveData` are both preserved.
The inventory surface probe uses non-admitted
placeholder collections/IDs, so it complements rather than replaces this test.

## Authorization after write-lock waits

The new `campaign-editorial-isolation` prerequisite passed in isolated project
`leonaid-emdash-tmp-muon2a5fkj`. Two actual Core Charity identities prove scoped
lists/counts/cursors/search, hostile filter override, own/foreign content and
revision operations, attributed update/restore/discard/publish/unpublish and
draft-only creation. Forbidden writes preserve independent System Admin
snapshots. Both actors' native lists and foreign editor URLs are checked in
Chromium, Firefox and WebKit; native save/conflict/reload/publish/private-follow-up
is additionally exercised as Charity A. With A's memberships removed in Core,
all previously admitted operations deny A without changing content/history;
B retains access. This is not the full `campaign-isolation` gate: media, preview,
complete rich-field UX, hostile dependencies and the
remaining complete operation matrix still require evidence.

The expanded prerequisite also passed in `leonaid-emdash-tmp-hlryd3d3rt` with
actual Charity email-code login, fresh-login confirmation/session rotation,
native editing and logout, followed by native creation through a separate real
login in each of Chromium, Firefox and WebKit. Three assigned Core campaigns
receive draft-only CMS records through the editor's Save action. Duplicate,
foreign-read/claim and subsequent membership-withdrawal checks pass. Positive
browser sessions are not injected; codes come from the actual isolated worker
and SMTP delivery. This supersedes the initial prepared-session limitation for
Charity A's login/edit/create journey, not the remaining broad acceptance gates.

The Charity manifest is generated only from `campaignCollection`, including its
source-derived hash. It contains no global database metadata. The native shell
uses a configured public favicon instead of resolving CMS settings/media. The
global dashboard endpoint remains forbidden, including on SPA navigation; the
CMS root redirects Charity users to their scoped list. This changes no Caddy
framing policy and adds no alternate authentication mechanism.

The initial request profile is not sufficient authority for a mutation that has
waited for a PostgreSQL lock. `requireCurrentCampaignActor` now performs fresh,
bounded Core action and identity reads after content/revision locks, immediately
before the original mutator runs. It requires the same Core subject and role,
and current System Admin or matching Charity membership authority. Creation uses
the same check after its per-action advisory lock. Charity admission also
requires completed setup, identity mapping and the scoped outer/runtime guards.

`campaign-auth-race` reproduces actual blocked HTTP operations, rather than
sleeping before the request or substituting Core responses. Its isolated operator
holds a shared content-row lock (or the actual creation advisory lock), observes
the requesting CMS backend in PostgreSQL's blocking graph, logs that request's
synthetic session out through Core HTTPS, confirms Core identity returns 401,
and releases the lock. Update, revision restore, discard, publish, unpublish and
creation must then return 401 with identical content/revision/list snapshots.
An independent valid Core session reads those snapshots. The unfixed updater
was observed returning 200 after this exact logout sequence.

The dedicated test operator has only the isolated Edge and CMS data networks,
the CMS database role, and transient synthetic sessions. Ordinary HTTP probes
remain Edge-only; no host ports or production services are involved. The same
race proof runs within `campaign-runtime` before its happy-path regressions.

A second fresh authority check also runs after successful native
writes, result-media validation, attribution/effect checks and deferred work,
immediately before the transaction callback completes. Creation has the same
final check after native creation and result validation. The media HTTP proof
holds real INSERTs with fixture-only PostgreSQL triggers (content for creation,
revisions for updates), logs each separate Charity session out through real Core
HTTPS, then requires 401 and identical content/revision/media snapshots after
releasing the lock. This closes revocation during those later write waits.

These checks are not a distributed transaction between
Core and CMS: they do not promise atomic cancellation of a write when revocation
occurs after the final Core authorization read. The editorial-isolation
prerequisite tests withdrawal before the next request; Charity-specific lock-wait
revocation, role/suspension changes, dependency failures and full isolation remain
separate acceptance requirements.

## Admitted editor operations

The pinned native editor passes its campaign through a React context into media
listing and reservation requests. Existing entries use their loaded immutable
action binding; new forms use their selected action. Picker query keys include
that action and the picker subtree resets when it changes. This is request
context, not authorization: Core membership and stored media/content bindings
remain mandatory at the HTTP boundary. The Charity manifest exports the source
image fields' exact PNG/JPEG/WebP validation. List MIME filters are bounded,
distinct exact raster types and apply inside the same scoped SQL query as
counting and pagination; wildcard/provider/folder alternatives remain closed.

Native local thumbnails use the authenticated file endpoint directly, not the
anonymous Astro optimizer. Private file paths accept the raw canonical key or
its exact single `encodeURIComponent` representation. Mixed, lowercase,
double-encoded and malformed forms are not alternate keys; query strings remain
denied. Normal Core, ready-state and byte/hash checks apply to both accepted
representations. The native picker exposes local storage only, no URL/provider
selection. Existing field widgets, upload feedback and persistence flows remain
EmDash's own; no fetch interception or substitute editor was introduced.

Canonical authorized admin editor/list HTML routes under
`/_emdash/admin/content/campaign_pages` now use the same completed-bootstrap,
fixed-origin and current Core session checks. Anonymous navigation returns to
Core login with that validated local path. APIs remain the data-access boundary.
The same boundary now admits the native `campaign_pages/new` page; no other
collection is opened. Creation accepts empty `bylines` and an optional slug only
when it exactly equals `data.action_id`, then drops those immutable echoes before
the guarded creator. A `?campaign=<Core UUID>` handoff on the native new page
prefills the action binding and internal slug. The server validates a single
canonical UUID and rechecks access through Core before rendering; invalid or
unavailable targets fail closed. Anonymous login preserves only this validated
parameter, never arbitrary query parameters. The client prefill conveys no
authority: the creation POST still validates the complete body and current Core
access. Without a handoff, the manual System Admin flow remains available.
Charity navigation to the CMS root redirects to the scoped campaign list.
Charity creation requires an authorized `?campaign=<Core UUID>` handoff.
Campaign-aware navigation in LeonAid itself remains pending.
The narrow `auth/me` POST admits
only upstream's own-user `dismissWelcome` action, with Origin and request-marker
checks. This changes neither identity nor permissions and creates no session.
The surface test expects HTTP 400 for either admin role's empty preference body
and 401 for anonymous callers; other disabled POSTs
remain closed. The native editor browser proof runs separately from the route
inventory matrix and does not claim complete Charity editor admission.

Canonical revision-restore POSTs now use the same bootstrap, current Core authority,
Origin and request-marker checks. The scoped revision reader resolves the stored
campaign parent before the original runtime restore runs under that parent's
row lock and transaction. A restore creates an actor-attributed draft revision;
it does not publish, change content authorship, or rewrite the source revision.
The real `campaign-runtime` proof checks these properties and late-write rollback,
as well as denied actors, missing guards and revoked sessions. This uses EmDash's
explicit restore semantics (no `_rev` precondition on its native restore route),
not an autosave operation. Charity access requires membership of the stored parent.

Canonical `campaign_pages` compare GETs and discard-draft POSTs are also admitted
for System Admins and the campaign's Charity Admins. Comparison holds the scoped content row and both revision
references through upstream reading, requiring each referenced revision to belong
to that exact parent. The real PostgreSQL proof denies foreign policy actors and
corrupted cross-entry pointers even for System Admins. Discard uses the original
runtime handler inside the shared locked transaction and checks that the pointer
was cleared; it neither inserts nor deletes history. HTTPS tests cover unchanged
live data, repeat discard, restoring discarded history, denied actors and rollback
when a fixture-only deferred PostgreSQL trigger rejects the final commit.

Canonical campaign publish POSTs are admitted for authorized admins only after a
fresh, bounded call to the existing authenticated Core action endpoint. Its new
`isPublished` response field evaluates the existing `is_published_at` domain
method with Core's clock; it is not persisted and does not duplicate lifecycle
logic in EmDash. Only a currently active Core publication window permits this
CMS promotion. Backdating and scheduling options are refused. The original
runtime publisher executes under the content lock and transaction; stored live
and draft pointers must resolve to revisions of that exact content item.

`campaign-runtime` proves future, expired and absent-window denial, denial for
draft/scheduled/completed/archived actions, promotion without history changes,
a subsequent private draft, withdrawal on the next publish attempt and rollback
on deferred commit failure. Synthetic fixtures preserve Core lifecycle triggers
and required beneficiaries. This is a CMS mutation gate, NOT an anonymous
delivery proof or a lasting public-access grant: EMS-050 must recheck Core on
every public page request, including withdrawal after a successful CMS publish.

Canonical unpublish POSTs require the same current authorized Core session,
scope, Origin and request marker, but deliberately do not require an active Core
publication window. An authorized operator must still be able to withdraw a CMS
publication after Core closure. The original unpublisher runs atomically: an
existing draft keeps its ID, data and author; without a draft, the live revision
is copied to a new actor-attributed draft. Live pointer and publication timestamp
must be cleared, and the response is hydrated from the preserved draft rather
than echoing old live columns. The real HTTP proof covers both cases, repeat
withdrawal, denied actors, missing guards, revoked sessions and rollback of a
deferred commit error including removal of the provisional draft revision.

The admitted read routes additionally require exact, enabled PostgreSQL binding
guards. Their operator installation refuses inconsistent existing rows. Content
IDs and action bindings cannot change, and campaign revision snapshots must
match their stored parent's action. The live proof disables a real guard and
observes HTTP 503 until explicit restoration. This is defense in depth against
application write paths, not protection against the trusted DB owner executing
arbitrary DDL; caller authorization and the currently closed write routes still
need their own complete proof.

The table describes current deny/allow decisions and the data needed before a
campaign-scoped implementation may replace them. It does not turn closed routes
into completed positive authorization tests. Every enabled content operation
will also need two-campaign positive/negative data assertions, including result
counts, drafts, revisions and media. Caller-provided action IDs are never proof
of authority. Membership must come from Core; existing and proposed bindings
must both be checked and the binding must remain immutable.

## Route matrix

| Route | Methods | Registration | Current rule | Required campaign lookup |
| --- | --- | --- | --- | --- |
| `/_emdash/.well-known/auth` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/admin/[...path]` | GET | core | System Admin root; scoped campaign editor for both admin roles; designated setup | Data APIs independently enforce campaign authority |
| `/_emdash/api/admin/allowed-domains` | GET, POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/allowed-domains/[domain]` | DELETE, PATCH | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/api-tokens` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/api-tokens/[id]` | DELETE | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/byline-fields` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/byline-fields/[slug]` | DELETE, GET, PATCH | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/byline-fields/[slug]/usage` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/byline-fields/reorder` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/bylines` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/bylines/[id]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/bylines/[id]/translations` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/comments` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/comments/[id]` | DELETE, GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/comments/[id]/status` | PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/comments/bulk` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/comments/counts` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/hooks/exclusive` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/hooks/exclusive/[hookName]` | PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/media-usage/activation` | GET, POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/admin/media-usage/collection-deletions` | GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/admin/media-usage/collection-deletions/retry` | POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/admin/media-usage/progress` | GET, POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/admin/media-usage/repair` | POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/admin/media-usage/work` | GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/admin/media-usage/work/retry` | POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/admin/oauth-clients` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/oauth-clients/[id]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/[id]` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/[id]/disable` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/[id]/enable` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/[id]/mcp` | PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/[id]/settings` | GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/[id]/uninstall` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/[id]/update` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/marketplace` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/marketplace/[id]` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/marketplace/[id]/icon` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/marketplace/[id]/install` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/registry/artifact` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/registry/install` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/plugins/updates` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/themes/marketplace` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/themes/marketplace/[id]` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/themes/marketplace/[id]/thumbnail` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/users` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/users/[id]` | GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/users/[id]/disable` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/users/[id]/enable` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/admin/users/[id]/send-recovery` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/dev-bypass` | GET, POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/invite` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/invite/accept` | GET | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/invite/complete` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/invite/register-options` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/logout` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/magic-link/send` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/magic-link/verify` | GET | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/me` | GET, POST | core | Current admin identity GET and own welcome dismissal only | No other user, identity or role mutation |
| `/_emdash/api/auth/mode` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/oauth/[provider]` | GET | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/oauth/[provider]/callback` | GET | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/passkey` | GET | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/passkey/[id]` | DELETE, PATCH | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/passkey/options` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/passkey/register/options` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/passkey/register/verify` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/passkey/verify` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/signup/complete` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/signup/request` | POST | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/auth/signup/verify` | GET | builtin-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/comments/[collection]/[contentId]` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/comments/[collection]/[contentId]/reactions` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/content/[collection]` | GET, POST | core | campaign_pages: scoped admin GET and bounded draft-only POST; otherwise denied | Current Core action, mapped author, serialized create and list/count filters |
| `/_emdash/api/content/[collection]/[id]` | DELETE, GET, PUT | core | campaign_pages canonical ULID: scoped admin GET and revision-checked bounded editorial-draft PUT only | Stored action_id; immutable proposed binding; strict editorial field policy |
| `/_emdash/api/content/[collection]/[id]/compare` | GET | core | campaign_pages canonical ULID: scoped admin only | Stored parent action_id and exact live/draft revision parent bindings |
| `/_emdash/api/content/[collection]/[id]/discard-draft` | POST | core | campaign_pages canonical ULID: scoped admin only; atomic pointer clear | Stored parent action_id; unchanged live content and history |
| `/_emdash/api/content/[collection]/[id]/duplicate` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/permanent` | DELETE | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/preview-url` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/publish` | POST | core | campaign_pages canonical ULID: scoped admin plus fresh Core publication approval; no backdating | Stored action_id, exact revision parents, Core-evaluated current publication window |
| `/_emdash/api/content/[collection]/[id]/restore` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/revisions` | GET | core | campaign_pages canonical ULID: scoped admin only; otherwise denied | Stored parent content action_id |
| `/_emdash/api/content/[collection]/[id]/schedule` | DELETE, POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/terms/[taxonomy]` | GET, POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/translations` | GET | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/unpublish` | POST | core | campaign_pages canonical ULID: scoped admin only; allowed after Core publication closure | Stored action_id and exact revision parents; atomic withdrawal preserving draft/history |
| `/_emdash/api/content/[collection]/authors` | GET | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/trash` | GET | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/dashboard` | GET | core | Core System Admin GET only | Global/identity surface; no campaign authority implied |
| `/_emdash/api/dev/emails` | DELETE, GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/probe` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/wordpress-plugin/analyze` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/wordpress-plugin/callback` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/wordpress-plugin/execute` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/wordpress/analyze` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/wordpress/execute` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/wordpress/media` | POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/import/wordpress/prepare` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/import/wordpress/rewrite-urls` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/manifest` | GET | core | System Admin runtime manifest; Charity source-only campaign manifest | No global settings, other schemas, media, taxonomy or plugin metadata for Charity |
| `/_emdash/api/mcp` | DELETE, GET, POST | mcp-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/media` | GET, POST | core | Core-authorized GET for one explicit campaign; multipart POST denied | Installed media guards, current action authority, scoped list/count/search/cursor; no usage hydration |
| `/_emdash/api/media/[id]` | DELETE, GET, PUT | core | Core-authorized scoped GET; DELETE/PUT denied | Immutable media binding; foreign and missing IDs both 404 |
| `/_emdash/api/media/[id]/confirm` | POST | core | Core-authorized confirmation of an owned staged image | Actual stored hash/type/decoded dimensions; fresh Core check after row lock; atomic ready transition |
| `/_emdash/api/media/[id]/upload` | PUT | core | Core-authorized bounded private image staging | Pending media binding; actual raster bytes; Core rechecks before attempt insertion and final linking |
| `/_emdash/api/media/[id]/usage` | GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/file/[...key]` | GET | core | Authenticated private image preview only; anonymous access denied | Canonical generated key to owned ready media; fresh Core authority and stored hash; no-store |
| `/_emdash/api/media/folders` | GET, POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/folders/[id]` | DELETE, GET, PUT | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/providers` | GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/providers/[providerId]` | GET, POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/providers/[providerId]/[itemId]` | DELETE, GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/upload-url` | POST | core | Core-authorized reservation for one explicit campaign; same-origin PUT URL only | Installed binding guards, current Core action and mapped author; no global deduplication or S3 bearer URL |
| `/_emdash/api/menus` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/menus/[name]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/menus/[name]/items` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/menus/[name]/items/[id]` | DELETE, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/menus/[name]/reorder` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/menus/[name]/translations` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/oauth/device/authorize` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/oauth/device/code` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/oauth/device/token` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/oauth/register` | OPTIONS, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/oauth/token` | OPTIONS, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/oauth/token/refresh` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/oauth/token/revoke` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/plugins/[pluginId]/[...path]` | DELETE, GET, PATCH, POST, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/redirects` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/redirects/[id]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/redirects/404s` | DELETE, GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/redirects/404s/summary` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/revisions/[revisionId]` | GET | core | Canonical ULID: scoped admin, campaign_pages parent required | Revision to owning content action_id |
| `/_emdash/api/revisions/[revisionId]/restore` | POST | core | Canonical ULID: scoped admin, campaign_pages parent required; new draft only | Stored revision parent to owning content action_id; locked atomic restore |
| `/_emdash/api/schema` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/collections` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/collections/[slug]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/collections/[slug]/fields` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/collections/[slug]/fields/[fieldSlug]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/collections/[slug]/fields/reorder` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/collections/reorder` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/orphans` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/schema/orphans/[slug]` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/search` | GET | core | Denied for all actors | Every result/target to owning action_id |
| `/_emdash/api/search/enable` | POST | core | Denied for all actors | Every result/target to owning action_id |
| `/_emdash/api/search/rebuild` | POST | core | Denied for all actors | Every result/target to owning action_id |
| `/_emdash/api/search/stats` | GET | core | Denied for all actors | Every result/target to owning action_id |
| `/_emdash/api/search/suggest` | GET | core | Denied for all actors | Every result/target to owning action_id |
| `/_emdash/api/sections` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/sections/[slug]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/settings` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/settings/backups` | GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/settings/backups/archives` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/settings/backups/archives/[name]` | DELETE, GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/settings/backups/export` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/settings/email` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/setup` | POST | core | Designated one-shot setup only | Global/identity surface; no campaign authority implied |
| `/_emdash/api/setup/admin` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/setup/admin/verify` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/setup/dev-bypass` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/setup/dev-reset` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/setup/status` | GET | core | Designated one-shot setup only | Global/identity surface; no campaign authority implied |
| `/_emdash/api/snapshot` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/taxonomies` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/taxonomies/[name]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/taxonomies/[name]/reorder` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/taxonomies/[name]/terms` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/taxonomies/[name]/terms/[slug]` | DELETE, GET, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/taxonomies/[name]/terms/[slug]/translations` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/taxonomies/[name]/translations` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/themes/preview` | POST | core | Denied for all actors | Every result/target to owning action_id |
| `/_emdash/api/typegen` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/widget-areas` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/widget-areas/[name]` | DELETE, GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/widget-areas/[name]/reorder` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/widget-areas/[name]/widgets` | POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/widget-areas/[name]/widgets/[id]` | DELETE, PUT | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/widget-components` | GET | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/oauth/authorize` | GET, POST | core | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/.well-known/oauth-authorization-server/_emdash` | GET | core | Not routed to CMS | Global/identity surface; no campaign authority implied |
| `/.well-known/oauth-protected-resource` | GET | core | Not routed to CMS | Global/identity surface; no campaign authority implied |
| `/robots.txt` | GET | core | Not routed to CMS | Global/identity surface; no campaign authority implied |
| `/sitemap-[collection].xml` | GET | core | Not routed to CMS | Global/identity surface; no campaign authority implied |
| `/sitemap.xml` | GET | core | Not routed to CMS | Global/identity surface; no campaign authority implied |

## Non-route surfaces and candidate enforcement seam

- Native CLI and direct runtime calls require operator access; they are not a
  Charity-user entrypoint. Device authorization, API-token issuance and MCP HTTP
  paths remain closed. No distributed user CLI credentials are introduced.
- Native and sandboxed plugins are empty in the pinned application configuration.
  Plugin/import/theme mutation routes remain closed even to the current dashboard
  System Admin. There is no plugin-based alternative publishing path enabled.
- Scheduled publication and internal handlers are not safe merely because their
  initiating HTTP route is protected. Core publication/lifecycle checks are still
  required before enabling scheduling and public delivery.
- The per-request `locals.emdash` object is freshly constructed in upstream
  `src/astro/middleware.ts`; its methods are bound to the shared runtime. The
  implemented wrappers modify only this request-local object, never the shared
  runtime across requests.
- `handleContentList` supports server-injected indexed `fieldFilters`, including
  membership (`in`) filters. This can constrain list/count queries, but does not
  automatically protect item lookups, revisions, references, media or publication.
- Astro middleware after EmDash authentication now enforces the bounded
  editorial operations. Each additional operation still needs its own real
  positive/negative campaign-data proof before admission. No broad fork is
  approved by the existing prerequisite evidence.

## Remaining proof obligations

Implement the complete campaign policy and bind every admitted operation to a
specific positive/negative data test. Include alternative IDs/slugs, bulk inputs,
reference targets, media keys, revisions, previews and concurrent binding changes.
The route inventory is a drift alarm and a coverage checklist, not a substitute
for these tests. An upstream-compatible extension proposal is still pending.
