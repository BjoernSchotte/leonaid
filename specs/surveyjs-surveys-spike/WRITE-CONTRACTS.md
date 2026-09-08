# Survey write contracts

Own license: **UNDEFINED**. Transport version: `/api/v1`. This inventory describes
the implementation. The [consolidated contract review](proofs/SURV-000-CONTRACT-REVIEW.md)
accepts SURV-000.A1 from the current route inventory and recorded live error, role,
concurrency and capability evidence. Final aggregate/CI acceptance remains separate.

## Sources and boundaries

The canonical request and response models and operation IDs are in
`src/leonaid/entrypoints/fastapi/surveys.py`, with analysis and export models in
`src/leonaid/application/surveys/`. The host-neutral TypeScript package exposes
its own adapter contracts; HTTP cookies, SQL and LeonAid identity stay in the host.
The Python `SurveyRepository` port currently dispatches dictionary payloads by
operation name. This is an implementation limitation, not a claim of statically
typed DTOs throughout the application boundary.

All input models reject unknown fields and use strict types. Mutation requests
have `operationId` (1–128 characters) and `expectedRevision` (integer >= 1), unless
the table specifies otherwise. Definitions and answer objects are bounded to
262144 serialized bytes; transport body and rate limits apply independently.
Invalid DTOs return 422 before a survey write. Definition profile and final-answer
validation are separate: saving a draft can preserve unsupported JSON, whereas
publication requires executable profile coverage. The draft-validation POST is
included in the inventory although it has no persistent write.

HTTP errors use `ApiErrorResponse`: `{error: {code, message, requestId}}`.
The central transport handler converts invalid request models to 422
`request_invalid`, without echoing field input. Domain validation also returns
422 with its domain code. The neutral package's `SurveyError` is an adapter
contract, not this HTTP envelope: it includes normalized codes and diagnostics,
and optional revision/retry information. Do not deserialize the HTTP error body
directly as `SurveyError`.

Export job states are also explicitly adapted in `apps/web/src/survey-exports.tsx`:
HTTP `processing`, `available`, `cancelled` become package `running`, `completed`,
`revoked`; `queued`, `retrying`, `failed` keep their names. Products remain
`responses_csv`, `responses_xlsx`, `analysis_xlsx`, `analysis_pdf` on both sides.

Member operations authenticate the current LeonAid session. Missing authentication
returns 401. Resource authorization normally hides an inaccessible survey with 404;
global settings require a system administrator (403 for an ordinary account).
Owner, system administrator, action management roles and explicit survey grants
are resolved by `may_access_survey`; an action-linked grant cannot bypass action
membership. The capability in the table is the operation's required capability,
not a new global role. Public participation uses separate resume credentials.

## Concurrency conventions

**Author replay:** writes lock the survey and serialize creation by survey-ID
advisory lock. A receipt is scoped to survey, actor, operation and operation ID.
An exact normalized request replays its stored result; changed data under the same
key returns 409 `idempotency_conflict`. Current authorization and applicable
lifecycle guards still apply; a receipt is not an authorization bypass.

**Revisions:** draft save/validate/publish compare the draft revision. Lifecycle,
timeout, access and invitation writes compare the survey revision. Global settings
compare their singleton revision. Respondent writes compare the participation
revision. A stale revision returns 409 `revision_conflict`, without overwriting
the newer state. These revision namespaces must not be interchanged.

**Snapshots/jobs:** analysis, raw selections and export selections freeze explicit
version/status/date filters under the survey lock; they do not accept a survey
revision. Export jobs reference an existing frozen snapshot. Their replay key is
survey/requester/operation ID, and their response reflects the job's current state.

## Complete transport inventory

Names below are the stable OpenAPI operation IDs. The executable inventory records
each concrete HTTP method/path and request/response model in its evidence JSON.

| Operation | Authorization / invalid operation | Concurrency and successful persistence |
| --- | --- | --- |
| `createSurvey` | Authenticated account; linking an action requires action management and an existing action; invalid executable definition rejected | Operation ID without expected revision; author replay; conflicting existing ID returns 409; inserts survey and draft at revision 1 atomically |
| `saveSurveyDraft` | `design`; closed surveys cannot be edited; bounded definition object | Author replay + draft revision; replaces draft JSON and increments draft revision, leaving publications unchanged |
| `validateSurveyDraft` | `design`; executable profile validation; closed survey rejected | Expected draft revision only; returns current validated draft; no operation receipt or data mutation |
| `publishSurvey` | `publish`; profile validation and lifecycle/scheduled-end guards | Author replay + draft revision; inserts immutable numbered version with renderer/profile/hash, updates active survey pointer and advances both revisions |
| `updateSurveySettings` | System administrator; timeout 1–604800 seconds; retention null or 1–315360000 seconds | Singleton lock/revision; actor/key receipt; increments settings revision; omitted retention fields preserve policy, explicit null disables it |
| `updateSurveyTimeout` | `design`; deleted survey rejected; nullable timeout override in the same timeout range | Author replay + survey revision; updates override and survey revision; existing participation timeout snapshots remain unchanged |
| `scheduleSurveyEnd` | `publish`; future explicit timezone or null; closed survey rejected | Author replay + survey revision; persists normalized end schedule and increments revision; server enforces due end independently of browser |
| `updateSurveyAccess` | `publish`; anonymous/invitation enum; only draft survey | Author replay + survey revision; persists access mode and advances revision |
| `transitionSurvey` | `publish` for end; `archive` for archive/unarchive; `delete` for trash/restore; illegal transition rejected | Author replay + survey revision; changes lifecycle/deletion timestamps; leaving active marks in-progress participations partial; restore returns to ended if published, otherwise draft |
| `duplicateSurvey` | `design`; deleted source rejected; distinct unused target ID and nonblank bounded title | Author replay + source survey revision; copies published definition if available, otherwise draft; new owner is requester; no answers, grants, invitations or tokens copied |
| `deleteSurveyPermanently` | `delete`; survey must first be trashed | Survey revision; durable content-free deletion intent/outbox before acknowledgement; archive publication failure returns 503 while intent remains retryable; same requester/key/revision replays even after erasure; different request conflicts; see RECOVERY.md |
| `createSurveyInvitation` | `manage_invitations`; valid bounded email/name and 1–90 day expiry; invitation-mode/lifecycle guards | Author replay + survey revision; persists invitation and durable mail outbox transactionally; response never exposes token |
| `revokeSurveyInvitation` | `manage_invitations`; invitation must belong to survey | Author replay + survey revision; revokes invitation/associated access; unknown invitation is hidden; asynchronous mail cannot grant revoked access |
| `createSurveyAnalysis` | `view_aggregates`; explicit existing published version; test-data filter additionally requires design; deleted survey rejected | Operation ID + canonical filter; author replay, no expected revision; freezes aggregate/input snapshot under lock |
| `createSurveyResponseSelection` | `read_responses`; same version/date/status/test constraints | Same snapshot/replay semantics; returns frozen selection metadata, not all response contents |
| `createSurveyExportSelection` | `export_raw` or `export_reports`; same version/date/status/test constraints | Same snapshot/replay semantics; exposes export selection metadata without requiring raw-response or aggregate viewing permission |
| `createSurveyExport` | Product-specific `export_raw` or `export_reports`; authorized snapshot and test-data scope; quota may return 429 | Operation ID + snapshot ID + product, no expected revision; survey lock and requester admission lock; atomically inserts job and empty-payload outbox event; no job on rejected admission |
| `startSurveyParticipation` | Active anonymous survey before scheduled end; invitation mode returns 403; bounded URL-safe client-generated resume secret | Operation ID, no revision; receipt scoped to secret digest; locks survey, snapshots published version and effective timeout; creates one participation for an exact replay; a resume credential already bound to another start/survey returns 409 `idempotency_conflict` without extra writes; sets Secure/HttpOnly/SameSite cookie |
| `redeemSurveyInvitation` | Active invitation survey; valid unexpired/unrevoked token; unknown token hidden | Token only, no operation ID or revision; locked invitation binds to one participation; repeated redemption restores the same participation; timeout/version/expiry snapshotted at first redemption |
| `saveSurveyResponse` | Active survey and valid unrevoked/unexpired participation cookie; completed response rejects new writes; answer types, values and known page required | Participation-scoped replay + revision; authoritative validation removes hidden answers; full snapshot and page saved atomically; revision advances, answer-change clock advances only when cleaned answers change |
| `completeSurveyResponse` | Same respondent access; required/relevant final validation of stored answers | Participation-scoped replay + revision; no submitted answers in this request; atomically marks validated stored snapshot completed and advances revision/time; missing required answers do not complete |

Invitation writes compare but do not increment the survey revision; their own
operation receipts and the survey lock serialize their persistence. A revoke
clears encrypted mail material and is enforced again when respondent access is
used. It does not physically delete previously collected answers.

## Verification scope

`tools/surveys/write_contracts_live.py` compares its explicit operation inventory
with every POST/PUT/PATCH/DELETE route registered by the actual survey router.
It validates every nominal request through its actual model, sends an extra-field
negative request with a real admin session to the live API, and then sends a
syntax-valid unauthenticated request. Public cases address a nonexistent survey;
they prove missing-resource rejection, not valid-cookie authorization behavior.

After each rejected request it compares complete row-content digests for every
survey table and the outbox, not merely row counts. Before the checks it creates
and publishes a survey through HTTP, starts a participation, saves an answer and
verifies that exact answer in PostgreSQL. Digests, credentials and row
contents stay local; committed evidence contains operation metadata and results.
The worker is stopped during this comparison to exclude legitimate background
changes. Identity-session activity and request-rate accounting are intentionally
outside the survey/outbox invariant. A normal real browser foundation journey
and isolated teardown follow the HTTP checks.

This inventory is not a replacement for the success, replay, concurrency, role,
recovery and UI proofs in SURV-010 through SURV-090. In particular, the negative
transport run alone cannot accept **000.A1**, **000.T1** or C-01–C-15 coverage.

The [expanded negative run](proofs/SURV-000.md#http-error-envelope-verification)
also validates every response against ApiErrorResponse, its exact JSON keys,
expected error code, correlated request ID/header and non-echoed invalid input.
The source-reviewed profile/limits and host rendering contract are consolidated
in [PROFILE-CONTRACT.md](PROFILE-CONTRACT.md).


## Concurrent duplicate-operation verification

`tools/surveys/write_replay_live.py` is run by the same `contracts` infrastructure
mode after the strict transport/error checks, while the production worker remains
stopped. Its explicit expected-delta inventory must match every registered survey
write. Each operation uses fresh synthetic setup through the real HTTP endpoints;
private invitation material is read only inside the test process and is not retained.

The test holds the operation's actual survey advisory lock, respondent survey row
lock or settings singleton row lock in PostgreSQL. It submits two identical HTTP
requests and waits until both backend calls are observed blocked through
`pg_blocking_pids`, including queue dependencies. Only then does it release the
lock. This proves overlapping server-side work, rather than assuming that two
asynchronously submitted requests necessarily overlap.

Both calls must succeed with the same response validated by the actual transport
model. The test checks persisted business values and exact table-count deltas:
for example, one immutable publication, one participation, one invitation/outbox
pair or one export-job/outbox pair. Every unlisted survey/outbox table must retain
its count. Validation produces no changed row contents. A third exact retry must
return the same result and leave full row-content digests unchanged across all
survey/outbox tables.

For nineteen operations, a changed request must return the documented 409 code
without changing any row contents. Draft validation has no operation key, so its
changed expected revision returns `revision_conflict`; the other eighteen return
`idempotency_conflict`. Anonymous start identity includes the resume-secret scope,
so changing that secret is not a same-key conflict. Invitation redemption has no
operation ID: repeat redemption must bind the same token to exactly one persisted
participation. Neither special case is falsely classified as a changed-key test.

This verifies duplicate operations and their persistence outcomes. Independent
competing revision writes, cross-operation lifecycle races, changed authorization,
worker execution and capability semantics still require their dedicated proofs.


A dedicated cross-survey case holds the participation table until two requests
with one credential are blocked on their independent inserts. The global
`resume_digest` uniqueness constraint selects exactly one participant; the other
request must return 409 `idempotency_conflict`, not a database-error 500. Exact
winner replay succeeds, loser replay and a new operation ID with the winner's
credential conflict; every replay leaves all row contents unchanged. The error
must disclose neither the credential nor the winning participation ID.

The insertion uses `ON CONFLICT(resume_digest) DO NOTHING RETURNING ...` and maps
an absent inserted row to the domain conflict. This handles the cross-survey race
atomically; a preceding existence check alone would not establish that guarantee.
The normal stored-receipt path still runs first for an exact successful retry.

[Accepted live results](proofs/SURV-000.md#concurrent-replay-for-every-write) cover
the complete concurrent inventory, collision handling and respondent regression.


## Competing revision verification

The `--competing-revisions` mode covers all 14 registered request models with
`expectedRevision`, using two ordered, observed persistence-lock waiters.
Distinct operation keys share one revision; validation has no key. Revision
advancing operations reject the second request. Duplication and invitation
creation can both succeed because they do not advance the source survey
revision; distinct targets/recipients and exact persistence deltas are checked.
Revocation coalesces the revoked state while retaining distinct operation
receipts. Completion returns `closed` to the second operation, and a different
permanent-deletion operation conflicts with the durable first intent.

[Accepted real-service and browser evidence](proofs/SURV-000.md#competing-revisions-for-every-revision-bearing-write)
records every expected result, winning stored value and unchanged later retry.
These are operation-specific contracts, not a universal claim that every pair
of requests at one revision must return exactly one success.
