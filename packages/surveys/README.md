# Neutral surveys package

Implementation in progress; the public package name and own OSS license remain
UNDEFINED. The private package manifest uses UNLICENSED until that decision.
The package now exposes initial contracts, a React respondent runner and scoped
styles. The editor and analytics entrypoints are still pending. This is not yet
a usable survey authoring package.

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
support or hydration parity across additional hosts yet. The runner currently
ships German UI text; configurable translations remain required follow-up work.
The host can set `--survey-accent` and `--survey-font`; the stylesheet maps these
to SurveyJS 3's actual `--sjs2-*` tokens on its theme root. It imports the fontless
upstream stylesheet and uses host-provided fonts.

Tests live in `tools/surveys/saves.test.ts` and
`tests/e2e/surveys-runner.spec.mjs`. `./leonaid test-surveys-runner` builds a fresh
isolated stack and exercises actual services before the browser scenarios.
