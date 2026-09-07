# Decisions — Surveys spike

Date: 2026-09-06

Status: implementation authorized and in progress; acceptance tracked in PLAN.md

This register separates accepted direction, concrete planning defaults and
technical choices to resolve during the spike. It grants no production, live
email campaign or package publication approval.

## Accepted direction

| ID | Decision |
|---|---|
| D-01 | Dedicated LeonAid Surveys module, German UI label “Umfragen”; standalone or optionally action-linked. |
| D-02 | SurveyJS Form Library renderer, independently implemented drag-and-drop editor and analytics UI. |
| D-03 | Neutral React/TypeScript package; persistence, permissions and exports supplied by LeonAid adapters. |
| D-04 | Own license for the new package and LeonAid: **UNDEFINED**. Decide between MIT and Apache-2.0 later. |
| D-05 | Multi-page questionnaires and server-side autosave during participation. |
| D-06 | Backend-configurable inactivity timeout; partial answers stay analyzable and resumable. |
| D-07 | Survey states: draft, active, ended, archived, deleted; published definitions are versioned. |
| D-08 | CSV/XLSX response data and XLSX/PDF analysis reports; PDF uses Typst. |
| D-09 | Staged capability profile rather than an unsupported promise of full SurveyJS compatibility. |
| D-10 | Separate open anonymous and attributable personal invitation modes. |
| D-11 | Independent package demo; newsletter system is not a prerequisite. |
| D-12 | The initial planning-only boundary was superseded by the user's instruction to implement and prove the plan, with incremental pushes to the draft PR. Own license selection, package publication and production operation remain separate decisions. |
| D-13 | Documents and slug are English: `specs/surveyjs-surveys-spike/`. |
| D-14 | Commercial dependencies are excluded; third-party software added for this module/package must be permissive OSS. OFL-1.1 font assets are allowed with their notices. See [DEPENDENCIES.md](DEPENDENCIES.md). |

## Concrete planning defaults

These make the accepted direction testable. Changes based on spike evidence
must be recorded without silently changing the accepted product direction.

| ID | Default / rule |
|---|---|
| P-01 | 30-minute backend inactivity default, optional survey override, effective value fixed per participation. |
| P-02 | Timeout only classifies responses; access expiry, survey end and retention are independent. |
| P-03 | Resuming updates the same participation when the survey is active and access valid. |
| P-04 | Published definitions are immutable; newly published versions apply to new participations. |
| P-05 | Repeat an ended survey by duplicating it; restoration never reopens access automatically. |
| P-06 | Trash first; permanent deletion includes responses, invitations and exported objects. |
| P-07 | Keep the latest accepted answer snapshot, not a permanent keystroke history. |
| P-08 | Remove hidden follow-up answers from the current analyzable snapshot. |
| P-09 | Atomic, idempotent completion; completed responses are not respondent-editable in the spike. |
| P-10 | Default analysis includes completed and partial responses; in-progress separate; versions not automatically merged. |
| P-11 | No persistent offline answer cache; retry in-memory pending edits while the tab remains open. |
| P-12 | Working package directory `packages/surveys/`; public package name and scope remain undecided. |
| P-13 | Target a verified SurveyJS 3.x patch, including theme and compatibility checks. SSR is evaluated, not mandatory. |

## Technical choices to resolve during the spike

| ID | Question | Stage | Decision criterion |
|---|---|---|---|
| T-01 | Exact SurveyJS 3/React versions and editor, chart and XLSX dependencies | SURV-000 | Compatible with checkout, permissively licensed, pinned and documented; own license remains UNDEFINED. |
| T-02 | Explicit Python rule model or isolated SurveyJS-Core JS validation adapter | SURV-010 | Equivalent client/server semantics for every initial capability; separate definition-schema and answer validation. |
| T-03 | Save debounce, text updates, request ordering and conflict UX | SURV-010/050 | Text saved without blur, no stale overwrite, no false save acknowledgement. |
| T-04 | Timeout, payload, request and export limits | SURV-010/090 | Documented limits and deterministic edge-case evidence. |
| T-05 | Role mapping and protected resume access | SURV-000/060 | Reuse current identity/policies; anonymous mode has no CRM association. |
| T-06 | Server-side chart generation for XLSX and Typst reports | SURV-080 | Shared aggregate data, no private browser screenshots as report pipeline. |
| T-07 | SurveyJS 3 token mapping and SSR/hydration behavior in Astro/React | SURV-000/020 | Isolated styling, no duplicate autosave on hydration, no public caching of private participation content. |

### Public survey request quotas

The spike uses the existing PostgreSQL transport rate limiter with separate
rolling 60-second quotas: 30 participation starts / invitation redemptions,
300 response writes / completions, and 600 public reads per client address.
Each quota spans all survey and participation IDs. A keyed address digest is
stored; client-selected cookies and User-Agent values do not reset it. Existing
identity-route fingerprint behavior is unchanged. Alternate UUID spellings use
the same route quotas. Address selection follows the
existing trusted-proxy configuration; public deployments must keep the API
behind the configured proxy, which supplies the authoritative forwarding header.

The limiter runs before survey handlers, including validation and idempotent
replay. Exhaustion returns HTTP 429 with `request_rate_limited` and a conservative
`Retry-After: 60`; rejected requests never invoke survey writes. A rolling window
may admit a retry earlier, but the full delay is safe. Concurrent requests share
the repository's transaction advisory lock. Member administration uses its
existing policies and is independent of these public quotas.

These are fixed spike defaults, not backend-adjustable inactivity settings.
Users behind one NAT share a quota; tune the defaults against expected event
traffic before production. This is bounded per-address abuse protection, not a
distributed-denial-of-service defense or a load benchmark. Payload byte limits,
export limits and sensitive-log acceptance remain separate parts of 090.A4.

### T-07 respondent rendering disposition

The spike uses browser mounting in both the Astro public host and the packed
independent consumer. Astro returns a loading shell with `Cache-Control: no-store`;
authorized response data is fetched after browser startup. The independent host
also returns an empty mount point and loads private response data from its
`no-store` API. Restoration initializes the model before autosave subscriptions.
The host owns its token overrides and runner locale/messages.

`tools/surveys/rendering-probe.ts` evaluates `SurveyRunner` with React
`renderToString` and synthetic data under pinned Bun, React and SurveyJS versions.
It produces question markup without calling persistence, but the saved synthetic
answer marker is absent from that markup. This is a bounded compatibility probe,
not proof of SSR answer fidelity or Astro hydration. No production SSR path is
selected; future SSR adoption requires a separate answer-fidelity/hydration test.
The browser fallback is explicitly allowed by the plan and retains the same
authoritative persistence/validation adapter. Host browser evidence is recorded
in [SURV-020](proofs/SURV-020.md#browser-rendering-and-restoration-disposition).

### Timeout settings and effective status contract

The planned `survey_partial_timeout_seconds` backend setting is persisted as
`survey_settings.inactivity_timeout_seconds` and exposed as
`inactivityTimeoutSeconds` through GET/PUT `/api/v1/survey-settings`. The initial
value is 1800 seconds; only an active system administrator can read/change this
global setting. PUT requires an operation ID and expected settings revision.
The same operation and payload replay the original response; a changed payload
or stale revision conflicts without changing state.

PUT `/api/v1/surveys/{id}/settings` requires the survey's design capability and
its summary revision (not its draft revision). A null timeout removes the
override. Both settings accept integers from 1 through 604800 seconds; null is
allowed only for the survey override. A participation snapshots the resolved
value when created, so later settings changes cannot reinterpret its deadline.
The member UI for these APIs is still tracked under SURV-060.

The platform worker independently sweeps at most 1000 overdue participations
every five seconds, or after 250ms when a full batch suggests more backlog.
`FOR UPDATE SKIP LOCKED` leaves concurrent writes for a later sweep. A sweep
changes only `in_progress` to `partial`, never answers, revisions, deadlines or
completed state. Database/startup failures retry; the next successful sweep
catches up from durable rows without a per-participation timer in memory.

The PostgreSQL `survey_participation_effective` view supplies `effective_status`
using statement time and the same persisted deadline as the worker. SURV-070
must use this effective status for filters/denominators and prove it through the
actual analysis endpoints while the worker lags. Reading the raw persisted
`status` alone is not an acceptable analysis implementation. The current public
response reader already evaluates this rule independently of worker progress.

## T-02 implementation selection — shared SurveyJS-Core adapter

Select the isolated JavaScript adapter using the same `createSurveyModel`,
restoration and profile answer checks as the browser. The executable comparison
now covers 192 host-approved cases, including 24 explicit condition scenarios.
The Python candidate disagrees on 27 mode/snapshot results: among these are nine
missing required follow-ups that Python incorrectly considers complete because
its relevance evaluation hides the question. See [SURV-010 evidence](proofs/SURV-010.md#isolated-validation-candidate-selection).

Retain Python for the definition capability allowlist, authorization, selecting
the stored published version, revision checks and transaction ownership. Do not
weaken those controls or accept a respondent-supplied definition. The JS
candidate evaluates answers and relevance only after host definition approval.
The shared-Core service is now called by the actual save/completion write path;
the original isolated comparison remains a reproducible diagnostic of the
superseded Python answer-semantics candidate.

The operational cost is an additional pinned Bun service and a bounded HTTP
validation call at the backend adapter boundary. The benefit is eliminating a
second implementation of SurveyJS condition coercion, emptiness and ordering.
The candidate introduces no third-party dependency beyond existing MIT core;
it does not import React, editor code or LeonAid modules. Sustained throughput
and peak memory remain to be measured. The integrated service now has
a 600,000-byte request limit, 256 MiB memory / one CPU limits and private
core-data networking without host ports. The host uses a three-second HTTP I/O
timeout. Stop/pause/recovery and failure atomicity passed the actual API/database
gate. A single observed memory sample was 28.56 MiB; it is not a benchmark.

SURV-010.3 now integrates the adapter with partial saves and completion and
fails closed on adapter failure without advancing revision, answers or completion.
See [integrated live proof](proofs/SURV-010.md#shared-core-backend-integration)
for 192 API/database cases and seven browser scenarios. This accepts the bounded
initial-profile validation gate; full product and production readiness remain
subject to the other work packages.

## Deliberately deferred decisions

- Own OSS license for LeonAid and editor: **UNDEFINED**. No choice between MIT
  and Apache-2.0. Existing `UNLICENSED`/`private` metadata remains unchanged.
  UNDEFINED is a planning marker, not a new SPDX identifier for package manifests.
- Final package name, branding and actual publication.
- Live retention/trash periods, respondent notices and operational approval;
  synthetic fixtures permit technical work independently of those decisions.
- Automatic action audiences, newsletter integration and reminders.
- Advanced capabilities described in [CAPABILITIES.md](CAPABILITIES.md).
- A separately reusable backend product in addition to the frontend package.

## SurveyJS 3 research disposition

The user supplied the official [2025–2026 overview](https://surveyjs.io/stay-updated/major-updates/2025-2026).
[PLAN.md section 2](PLAN.md#2-surveyjs-3-baseline-and-research-findings) records
its implementation implications. Separate upstream product features and
announced roadmap work do not silently expand our custom package scope.

## Retention scheduling semantics

The implementation uses two independent installation-wide settings, configurable
by system administrators: `endedRetentionSeconds` and `trashRetentionSeconds`.
Both default to `null` (automatic action disabled). Positive periods are bounded
at 315,360,000 seconds; the member backend accepts days and converts them to
seconds. Short second-based values are reserved for explicit synthetic proofs;
no real operational period has been selected.

The first stage moves ended/archived surveys to trash, measured from a dedicated
lifecycle clock. Archiving/unarchiving preserves that clock; restoring a trashed
published survey starts a new period in the ended state. Existing closed rows
receive the migration time as their initial clock, rather than assuming that an
unrelated last edit was their closure. The second stage measures from entry into
trash and commits the existing irreversible erasure job. Draft and active surveys
are never selected by retention, regardless of respondent inactivity.

Policy changes apply to already existing surveys. An omitted policy field in an
older timeout-settings request preserves its current value; explicit `null`
disables that stage. Changes use the existing revision and operation replay
contract. Disabling a stage prevents new requests but cannot cancel an erasure
intent already committed. The UI states this consequence before saving.

The worker checks up to 100 candidates per sweep, rechecks eligibility under the
survey locks, skips busy rows, and catches up after restart. The existing sweep
cadence is five seconds (shortened while draining full batches). Backup lifecycle
and restoration of deletion records remain separate work under SURV-090.
