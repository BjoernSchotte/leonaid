# EmDash authorization surface

Status: route inventory and closed-policy verification; campaign isolation is NOT proven.

Baseline: EmDash 0.36.0 at `603062902369d9695608e85c2d034d4f66f7a1f1`.
`route-inventory.json` records each route's actual exported HTTP methods, package
module and SHA-256. The offline inventory command evaluates the upstream route
injector, not a filename-derived approximation. It includes 165 core routes and
20 built-in auth routes and one MCP route that are deliberately not enabled in
this installation (186 routes total).

All actors below are resolved through current Core sessions. Charity users have
no admitted CMS operation yet. The shared test for every CMS-routed row is
`authorization-surface`: real HTTPS requests with System Admin, Charity Admin and
anonymous credentials, each declared method plus HEAD/OPTIONS. An admitted GET
is expected to return 200/403/401 respectively; other operations remain 503.
The setup grant is already consumed in this proof. Root routes not owned by the
CMS are tracked by the separate proxy-routing/build route contract.

The `campaign-runtime` proof additionally exercises admitted GETs for the exact
`campaign_pages` collection and canonical ULID content/revision IDs. These need
completed bootstrap, valid HTTPS origin and a current Core System Admin session.
Request-local handlers enforce the campaign-read primitives before upstream
data access. Unknown item IDs prove the wrapper's static `NOT_FOUND` response.
All Charity users remain denied; positive Charity HTTP isolation is not yet
claimed. A canonical item PUT now permits only System Admin title-draft edits
with a revision token, valid Origin and `X-EmDash-Request: 1`. It rejects binding
changes, metadata, publication and other editorial fields pending their proofs.
The original runtime updater remains responsible for schema validation and
revision storage. The original runtime getter is retained after the scoped
parent check so current draft data and published `liveData` are both preserved.
The inventory surface probe uses non-admitted
placeholder collections/IDs, so it complements rather than replaces this test.

Canonical revision-restore POSTs now use the same bootstrap, Core System Admin,
Origin and request-marker checks. The scoped revision reader resolves the stored
campaign parent before the original runtime restore runs under that parent's
row lock and transaction. A restore creates an actor-attributed draft revision;
it does not publish, change content authorship, or rewrite the source revision.
The real `campaign-runtime` proof checks these properties and late-write rollback,
as well as denied actors, missing guards and revoked sessions. This uses EmDash's
explicit restore semantics (no `_rev` precondition on its native restore route),
not an autosave operation. Charity admission remains closed.

Canonical `campaign_pages` compare GETs and discard-draft POSTs are also admitted
for System Admins. Comparison holds the scoped content row and both revision
references through upstream reading, requiring each referenced revision to belong
to that exact parent. The real PostgreSQL proof denies foreign policy actors and
corrupted cross-entry pointers even for System Admins. Discard uses the original
runtime handler inside the shared locked transaction and checks that the pointer
was cleared; it neither inserts nor deletes history. HTTPS tests cover unchanged
live data, repeat discard, restoring discarded history, denied actors and rollback
when a fixture-only deferred PostgreSQL trigger rejects the final commit.

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
| `/_emdash/admin/[...path]` | GET | core | Root/one-shot setup only | Global/identity surface; no campaign authority implied |
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
| `/_emdash/api/auth/me` | GET, POST | core | Core System Admin GET only | Global/identity surface; no campaign authority implied |
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
| `/_emdash/api/content/[collection]` | GET, POST | core | GET campaign_pages: System Admin only; otherwise denied | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]` | DELETE, GET, PUT | core | campaign_pages canonical ULID: System Admin GET and revision-checked title-draft PUT only | Stored action_id; immutable proposed binding; narrow draft field policy |
| `/_emdash/api/content/[collection]/[id]/compare` | GET | core | campaign_pages canonical ULID: System Admin only | Stored parent action_id and exact live/draft revision parent bindings |
| `/_emdash/api/content/[collection]/[id]/discard-draft` | POST | core | campaign_pages canonical ULID: System Admin only; atomic pointer clear | Stored parent action_id; unchanged live content and history |
| `/_emdash/api/content/[collection]/[id]/duplicate` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/permanent` | DELETE | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/preview-url` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/publish` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/restore` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/revisions` | GET | core | campaign_pages canonical ULID: System Admin only; otherwise denied | Stored parent content action_id |
| `/_emdash/api/content/[collection]/[id]/schedule` | DELETE, POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/terms/[taxonomy]` | GET, POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/translations` | GET | core | Denied for all actors | Current/proposed content action_id; list/count filters |
| `/_emdash/api/content/[collection]/[id]/unpublish` | POST | core | Denied for all actors | Current/proposed content action_id; list/count filters |
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
| `/_emdash/api/manifest` | GET | core | Core System Admin GET only | Global/identity surface; no campaign authority implied |
| `/_emdash/api/mcp` | DELETE, GET, POST | mcp-disabled | Denied for all actors | Global/identity surface; no campaign authority implied |
| `/_emdash/api/media` | GET, POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/[id]` | DELETE, GET, PUT | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/[id]/confirm` | POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/[id]/upload` | PUT | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/[id]/usage` | GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/file/[...key]` | GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/folders` | GET, POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/folders/[id]` | DELETE, GET, PUT | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/providers` | GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/providers/[providerId]` | GET, POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/providers/[providerId]/[itemId]` | DELETE, GET | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
| `/_emdash/api/media/upload-url` | POST | core | Denied for all actors | Media-to-campaign binding (not global ownership) |
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
| `/_emdash/api/revisions/[revisionId]` | GET | core | Canonical ULID: System Admin only, campaign_pages parent required | Revision to owning content action_id |
| `/_emdash/api/revisions/[revisionId]/restore` | POST | core | Canonical ULID: System Admin only, campaign_pages parent required; new draft only | Stored revision parent to owning content action_id; locked atomic restore |
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
  `src/astro/middleware.ts`; its methods are bound to the shared runtime. A future
  enforcement layer must never mutate that shared runtime across requests.
- `handleContentList` supports server-injected indexed `fieldFilters`, including
  membership (`in`) filters. This can constrain list/count queries, but does not
  automatically protect item lookups, revisions, references, media or publication.
- A standard Astro middleware after EmDash authentication is a candidate for
  request-scoped enforcement. Its ordering and complete operation coverage need
  real tests before any Charity access is enabled. No broad fork is approved.

## Remaining proof obligations

Implement the complete campaign policy and bind every admitted operation to a
specific positive/negative data test. Include alternative IDs/slugs, bulk inputs,
reference targets, media keys, revisions, previews and concurrent binding changes.
The route inventory is a drift alarm and a coverage checklist, not a substitute
for these tests. An upstream-compatible extension proposal is still pending.
