# Neutral surveys package

Implementation in progress; the public package name and own OSS license remain
UNDEFINED. The private package manifest uses UNLICENSED until that decision.
The package now exposes initial contracts, a React respondent runner and scoped
styles, an initial independent visual editor and aggregate charts/tables. The remaining
authoring capabilities are still pending; this is not the accepted full spike.

## Host adapter protocol v1

Every method returns the discriminated Result type. Network failures are mapped
to temporarily_unavailable; aborting a request does not imply server rollback.
The host handles credentials, HTTP transport and authorization. Callers must
never infer permission from hidden UI controls. Unauthorized resource identifiers
return not_found where necessary to avoid leaking resource existence.

All writes are server transactions. A stable operationId identifies one logical
operation scoped to the authenticated actor or participation and route. The
server stores its canonical request digest and committed response atomically
with the mutation. Repeating that operation with the same payload returns its
original response; a different payload yields idempotency_conflict. Authorization
is rechecked before returning a stored result. Failed validation commits nothing.

Revisioned writes require expectedRevision. After the idempotency check, a stale
revision yields revision_conflict and currentRevision; the client must resolve
rather than silently overwrite. A successful state change increments revision.
Full answer snapshots replace the accepted snapshot; omitted keys remove answers.
The server validates against the participation's immutable published definition,
clears hidden answers and treats required-field omissions as permissible for
partial saves. Invalid supplied types or values reject the write with diagnostics.
Only changes to accepted answers refresh the server inactivity timestamp. Page
navigation alone does not extend it. The acknowledgement is the only saved-state
signal; optimistic UI must retain pending edits until acknowledged.

Completion is a distinct revisioned transaction validating all relevant required
answers on the server. It cannot race survey closure into accepting an answer
after the transaction cutoff. Completed responses cannot be changed. Lost
acknowledgements can be retried using the same operationId without duplicate
participations or completion side effects. Restoration never emits a save.

Draft publication checks structural schema, the supported capability profile
and server semantic support. It produces a new immutable version and does not
rewrite existing participations. Unsupported definitions yield diagnostics and
cannot be published. Start binds the current published version and effective
inactivity timeout; its operationId prevents duplicate creation on retry.

Analysis requires a specific version and explicit response statuses. Its
immutable snapshot is permission-scoped and binds every requested export to
identical data. Raw exports require export_raw and report exports require
export_reports; neither is implied by view_aggregates. Export requests use
operationId for deduplication. Status reads and downloads recheck current
permissions and survey deletion; a completed job does not grant lasting access.

## Verification status

These are contracts to implement and prove through SURV-000/010 and subsequent
work packages. Type checking alone is not persistence, authorization or E2E
proof. No plan checkbox is completed by introducing these declarations.

## Respondent runner

Import `SurveyRunner` from `@leonaid/surveys/runner` and styles from
`@leonaid/surveys/styles`. Supply a server-restored Participation and a host
ParticipationAdapter. The package does not import LeonAid transport or identity
code. The public LeonAid host supplies the generated-client adapter and keeps
resume access in HttpOnly cookies. The URL contains the participation ID, never
the access secret or answer data.

The runner uses SurveyJS 3's onTyping updates and asynchronous onCompleting hook.
Text saves debounce for 400 milliseconds, page changes flush immediately, and
completion awaits the last acknowledged save before the server completion call.
Uncertain network writes retain their operation ID and payload. New edits queue
behind them. A known invalid-response rejection permits a corrected snapshot.
Restoration applies initial answers before attaching save listeners.

The current baseline uses browser rendering in Astro; it does not claim SSR
support or hydration parity across additional hosts yet. The runner defaults to German and now accepts host locale/messages; see the
packed-consumer section below. Editor-wide translation remains open.
The host can set `--survey-accent` and `--survey-font`; the stylesheet maps these
to SurveyJS 3's actual `--sjs2-*` tokens on its theme root. It imports the fontless
upstream stylesheet and uses host-provided fonts.

Tests live in `tools/surveys/saves.test.ts` and
`tests/e2e/surveys-runner.spec.mjs`. `./leonaid test-surveys-runner` builds a fresh
isolated stack and exercises actual services before the browser scenarios.


The runner model maps the profile's minimum text length to a native SurveyJS
TextValidator. Text limits use UTF-16 code units, consistent with JavaScript and
browser inputs (an emoji outside the BMP counts as two units). The backend uses
the same measure. Guided string conditions follow SurveyJS's case-insensitive
default; answer data itself keeps its original case. `./leonaid test-surveys-core`
compares these semantics in the actual pinned runtimes.


## Initial visual editor

Import SurveyEditor from `@leonaid/surveys/editor` and its separate stylesheet
from `@leonaid/surveys/editor-styles`. Supply a Draft and an AuthoringAdapter.
The editor has no LeonAid imports. The host currently exposes it at
`/admin/surveys/new` and `/admin/surveys/<id>` after normal member authentication.
These routes do not yet provide the complete survey navigation/list screen.

The initial editor supports page/question creation, movement, duplication and
removal, HTML drag-and-drop with explicit keyboard movement controls, basic
question properties/choices and undo/redo. Stable question/choice IDs survive
wording changes and moves. Page duplication gives its questions new IDs and
remaps internal expression references while preserving quoted literals. Unknown
JSON properties survive edits; unsupported question types are displayed read-only.
Undo/redo keeps a bounded in-memory history of 100 edits; it is not a persisted
edit/audit history. Reordering can invalidate preceding-answer dependencies;
publication validation remains authoritative and must not be bypassed.

Draft autosave debounces at 700ms. The coordinator serializes requests, retries
uncertain writes with identical IDs/payloads and queues newer edits behind them.
Conflicts stop automatic saves. Unacknowledged data remains in memory; reload
is not a recovery mechanism for unsent edits. The host uses the actual generated
LeonAid API client. The current editor UI is German; configurable translations
remain an explicit package follow-up.

The editor now exposes required flags, text/selection limits, number/date bounds,
rating scales, matrix rows/columns and presentation properties. Guided visibility
rules reference preceding questions and combine one level of all/any conditions.
Existing expressions outside that editable shape remain preserved with an explicit
remove action. Reordering can still invalidate a reference; the server rejects an
invalid definition at preview/publication.

Preview flushes the draft and calls `validateDraft(surveyId, expectedRevision)`.
The host must return the exact persisted, authorized and validated draft, or a
revision/validation error. The preview creates a local SurveyJS model without a
ParticipationAdapter; completing it cannot create collected responses. Publication
uses a stable operation ID and revision. After an uncertain acknowledgement,
editing stays locked until the same publication request is resolved.

The advanced JSON section accepts a file or pasted JSON and downloads the current
local definition. Import parses a bounded object with explicit named pages and
questions; malformed structure, non-finite numbers and excessive nesting are
rejected without changing history. Applying a definition is one reversible edit.
Unknown safe properties survive serialization and persistence. Unsupported
question types, options and nested choice content are read-only in the property
panel, with paths listed in compatibility notices. The supported profile remains
explicit: this is not an arbitrary SurveyJS JSON importer. Only the host's
validation endpoint may approve execution in preview or publication.

When another editor wins a save race, automatic writes stop. The user may export
the local definition and explicitly load the server draft, discarding local edit
history. Subsequent saves use the returned revision. Network failures retain the
original operation ID/payload so an uncertain committed save can be resolved
before sending newer edits. The browser gate covers both cases.

Full property/profile compatibility, responsive/accessibility acceptance and
independent packed-consumer proof remain required work. This editor does not claim SurveyJS Creator feature parity.

The web host currently enables TypeScript `skipLibCheck`, matching the neutral
package: SurveyJS 3.0.3's matrix renderer declaration returns `Element | null`
while its declared base method returns `Element` (TS2416). Application source
remains strictly checked; this setting does not establish clean upstream type
declarations. Track removal when the pinned upstream declarations are corrected.

## Packed consumer and host configuration

Host-supplied adapters connect the React questionnaire editor and respondent
runner to persistence. This package does not import LeonAid's API client, UI,
identity or domain modules. Own license decision: **UNDEFINED**; the package is
private and is not being published.

Entrypoints: `editor`, `runner`, `contracts`, `analysis`, `analytics`, `styles`, `editor-styles`, `analytics-styles`. The current
spike distributes TypeScript sources for a TypeScript-capable consumer bundler.
React and React DOM are peer dependencies. Import the runner stylesheet once;
the editor also uses it for preview. Use `--survey-accent` and `--survey-font`
inside the host's survey container to customize the runner theme.

`SurveyRunner` accepts a `Participation`, a `ParticipationAdapter`, optional
`locale` (`de` by default, or `en`) and optional `messages` overriding runner
status, recovery and completion text. The host owns credentials and translates
adapter error messages. Keep adapter and message-object identities stable across
renders, and do not replace a participation while it has unsaved changes.
Questionnaire validation and all authoritative writes remain server concerns.
Provide a secure browser context (HTTPS, or localhost for local development)
for cryptographic operation IDs.

The independent demo installs an actual tarball outside workspace resolution and
saves to SQLite through its own adapter. It is a consumer proof, not a hosted
service or production backend. Editor-wide translation, analytics exports,
compiled distribution and full cross-host theme/hydration acceptance remain
tracked in the spike plan.

## Server aggregate engine (in progress)

The separate `analysis` entrypoint exports `aggregateApprovedSurvey(definition,
responses)`. Use it in a trusted server process after approving a stored
initial-v1 definition. It uses the same SurveyJS model and partial-answer rules
as the respondent/validator. It does not provide authorization, response
selection, immutable snapshot storage, charts or exports. Those host integrations
remain pending. Do not send raw responses to an aggregate-only browser user.

Every question reports relevant, answered, unanswered, hidden and invalid counts.
`answered + unanswered + invalid = relevant`; `relevant + hidden` equals the
selected response count. Missing ratings never become zero. Choice percentages
use valid answered participants, so checkbox totals may exceed 100%. Matrix row
percentages use valid answered cells for that row; an invalid matrix answer is
excluded as a whole and increments each row's invalid count. Text/date values
never become buckets. Numeric fields return sum/mean/minimum/maximum; selection
and rating buckets come only from the approved definition.

The initial NPS convention is the 0–10 rating template with step 1. It computes
`100 * (promoters - detractors) / valid answered`, with 9–10 promoters and 0–6
detractors. Zero answered yields null, not zero. Other scales have no NPS metric.
Sum and bucket counts are retained for future host batch combination; do not
average batch percentages, means or NPS values without their denominators.

## Aggregate result components

Import `SurveyAnalytics` from `@leonaid/surveys/analytics` and its separate
`@leonaid/surveys/analytics-styles` stylesheet. Supply an authorized immutable
`AnalysisSnapshot`; the component never fetches responses or calculates question
aggregates in the browser. `messages` accepts the complete `AnalyticsMessages`
contract (English by default), and `locale` controls numeric formatting.

The view provides choice/rating and matrix bars, numeric/NPS summaries,
per-question denominators, separate scoped status counts, last-page counts and
keyboard-accessible equivalent tables. Host CSS variables `--survey-accent`,
`--survey-border` and `--survey-track` control colors. The host supplies version,
date, status and test-data filters and all authorization. Raw-response views and
exports are separate capabilities and are not provided by this component.

Charts use scoped CSS without another runtime dependency. This entrypoint does
not import the SurveyJS engine or host code and remains outside the respondent
bundle. Own license remains UNDEFINED.
