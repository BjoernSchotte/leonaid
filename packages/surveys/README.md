# Neutral surveys package

Implementation in progress; the public package name and own OSS license remain
UNDEFINED. The private package manifest uses UNLICENSED until that decision.
The package now exposes initial contracts, a React respondent runner and scoped
styles, an initial independent visual editor, aggregate charts/tables and an
adapter-driven export panel. The remaining
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
packed-consumer section below. The editor also accepts host translation and preview locale; see below.
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
LeonAid API client. The editor defaults to German and accepts host translations and preview locale
through the optional props documented below.

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

Entrypoints: `editor`, `runner`, `contracts`, `analysis`, `analytics`, `exports`,
`styles`, `editor-styles`, `analytics-styles`, `export-styles`. The current
spike distributes TypeScript sources for a TypeScript-capable consumer bundler.
React and React DOM are peer dependencies (`^19.2.8`). The independently packed
consumer and LeonAid currently verify exactly `19.2.8`; the compatibility range
does not claim that future releases have already been tested. Runtime hosts keep
exact dependency versions and frozen lockfiles. Import the runner stylesheet once;
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
service or production backend. The independent export page uses a separate
bundle and the host's own SQLite-backed CSV adapter. Additional host language catalogues,
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

## Export panel

Import `SurveyExports` from `@leonaid/surveys/exports` and the separate
`@leonaid/surveys/export-styles` stylesheet. Supply the selected immutable
`snapshotId`, a stable `ExportAdapter`, allowed `products`, and optionally a
complete `ExportMessages` translation object. Supported product identifiers are
`responses_csv`, `responses_xlsx`, `analysis_xlsx`, and `analysis_pdf`; the host
chooses which it implements and permits. The component generates no files and
imports no host transport, SurveyJS renderer, editor or analysis engine.

The adapter implements `requestExport`, `exportStatus` and `download` from the
neutral analysis contract. Return `Result<ExportJob>` for creation/status and
`Result<Blob>` for download. Jobs use queued, running, retrying, completed,
failed or revoked states and may supply a filename. The host must freeze the
selected data and recheck access on each operation. `temporarily_unavailable`
preserves the original creation operation ID for an explicit retry. Authorization
or missing-resource errors clear the affected job's download action.

Pending jobs are polled; status errors stop polling until the user retries.
Changing snapshots resets the displayed jobs, and unmounting aborts observation
without implying cancellation of a server operation. This initial component
keeps its job list in memory; restoring a job list after navigation is a separate
host concern. Completed downloads use temporary object URLs that are revoked
after triggering the download; the component does not persist response blobs.
Import this entrypoint only in an authorized result/export view to keep it out
of the respondent bundle. The independent demo demonstrates this separation
with an actual packed installation and its own persisted CSV export adapter.


### Editor host translation

`SurveyEditor` accepts optional `translate: EditorTranslator` and `locale`
(default `de`). The gettext-style callback receives the German source message
and optional named text/number placeholders. It covers toolbar/property/condition
controls, accessible names, local validation/conflict/save messages and newly
created page/question/choice defaults. Author-supplied titles, choices, IDs and
condition expressions are preserved. Adapter messages pass through the callback
at display time; hosts should supply localized adapter diagnostics or a fallback.

```tsx
import { SurveyEditor, formatEditorMessage, type EditorTranslator } from "@leonaid/surveys/editor";
const catalogue: Record<string, string> = {
  "Frage hinzufügen": "Add question",
  "Regel {number} entfernen": "Remove rule {number}",
};
const translate: EditorTranslator = (message, values) =>
  formatEditorMessage(catalogue[message] ?? message, values);
<SurveyEditor draft={draft} adapter={adapter} translate={translate} locale="en" />;
```

Return plain strings; React renders them as text. `formatEditorMessage` substitutes
only supplied own keys once, preserving unknown placeholders. A new translation
callback identity does not replace unsaved editor history or its save coordinator.
Existing authored content is not retranslated when the host changes language;
new defaults use the latest callback. Notices already emitted retain their
rendered wording. `locale` is applied when opening the SurveyJS preview; English
and German are available in the current bundle. Hosts using another SurveyJS
locale must register its corresponding SurveyJS translation and set their page
language. The editor does not provide a catalogue for every language.

The packed independent `/editor` demo proves translated controls, reordered
numbered labels, generated defaults, JSON errors, English preview and actual
SQLite draft persistence across backend restart. Its deliberately small synthetic
adapter supports load/save/validation and disables publication. It is not a
production authentication or arbitrary-questionnaire validation service.

### Host logo

`SurveyRunner` accepts an optional `logo={{ src: "/brand/logo.svg", alt: "Your organization" }}`.
This is host configuration, not a property accepted in questionnaire JSON. The
same logo appears during participation and on the completion page. Changing it
does not recreate the SurveyJS model or reset answers, current page or saving.

Only root-relative static image paths are accepted: alphanumeric, underscore or
hyphen directory/file names ending in svg, png, webp, jpg, jpeg or avif. The path
is limited to 512 characters and the alt text to 160. External/protocol-relative
URLs, query strings, fragments, percent encoding and traversal are omitted without
an image request. An omitted logo renders no image. Hosts own the asset and its
serving policy: use a static route that does not redirect off-origin and do not
put participant data in a filename. The image sends no referrer and fits a
160-by-64 CSS box constrained to the available width. No image upload or remote
asset fetching service is added. LeonAid supplies its existing local brand mark;
the independent demo supplies its own mark and an interactive configuration field.

### Narrow progress navigation

The progress region is an inline-size CSS container. At widths up to 32rem, the SurveyJS
page-step grid wraps within the host container and uses at least 44px step
controls. Connecting lines are omitted in the wrapped layout; desktop layout
remains the SurveyJS default. This applies to narrow embedded hosts as well as
mobile viewports. SurveyJS may independently render rating questions as dropdowns
when there is insufficient width for their radio choices.
