# SURV-000 — Consolidated contract acceptance

**000.A1, 000.1, 000.2, 000.5, 000.T1 and 000.S1 are accepted.** This review
reconciles existing executed proofs against source checkpoint `419738d`; it is
not a new service run. The required clean-stack, dependency and foundation
criteria 000.A2–A4 retain their separately accepted live evidence. It does not
accept the repeated Survey aggregate, current CI Journey failure, outstanding
legacy regressions or independent host-loss recovery.

## Current transport and persistence inventory

The [machine-readable reconciliation](assets/SURV-000-contract-reconciliation.json)
compares all 21 current POST/PUT/PATCH/DELETE routes with the recorded real-API
error and replay inventories. Operation ID, method, concrete path and actual
response model match. Each has strict DTO/error-envelope checks, request-ID
correlation, unchanged full survey/outbox contents after rejection, observed
concurrent lock waiters, verified stored outcome and unchanged later replay.

[WRITE-CONTRACTS.md](../WRITE-CONTRACTS.md#complete-transport-inventory) defines
operation-specific authorization, invalid-input handling, revision namespace,
retry identity and successful persistence for each of those 21 entries. Its
exceptions are deliberate: validation does not write, token redemption has no
operation key, invitation writes do not advance the survey revision, and a
failed external deletion acknowledgement can leave a durable retryable intent.
An arbitrary 503 therefore does not imply that every operation rolled back.

The current `write_replay_live.py` and infrastructure harness hashes still match
[the accepted 14-operation competing-revision run](SURV-000.md#competing-revisions-for-every-revision-bearing-write).
The contract runtime files (domain/application, survey HTTP router, PostgreSQL
survey/export repositories, package contracts and shared model/answer validation)
have no diff from checkpoint `d55e48d`, which delivered that run. No new runtime
behavior is inferred from a changed proof document.

## Authorization, errors and operations that interact

| Obligation                                                   | Reconciled source and actual evidence                                                                                                                                                                                                                                                                                                                             |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Member writes and action association                         | `may_access_survey`, the write inventory and `permissions_live.py` map all nine capabilities independently across 14 personas and four resources. [Consolidated permission acceptance](SURV-060.md#consolidated-surv-060-acceptance) includes valid single-grant mutations, missing/changed authority and foreign child IDs with unchanged denied SQL state.      |
| Global and per-survey settings                               | `timeouts.py` rejects ordinary-member global GET/PUT with 403 and survey override with 404, then verifies both stored settings remain unchanged; invalid values, stale revisions and changed-key retries are independently rejected. [Live settings/timeout evidence](SURV-050.md#live-scenarios).                                                                |
| Invitation create/revoke and erasure after content removal   | [Special-scope evidence](SURV-060.md#invitation-and-deletion-special-scopes) exercises populated invitations, foreign-ID/unauthorized revocation, four successful invitation-only browser journeys and exact requester-bound deletion replay after actual erasure.                                                                                                |
| Respondent credential and final-answer boundary              | [Shared-Core validation](SURV-010.md#shared-core-backend-integration) and [invitation access](SURV-060.md#invitation-credential-and-expired-resume-acceptance) cover partial versus final values, expired/revoked access and actual validator outage/recovery. Malformed values and unavailable validation preserve the previous persisted answer/revision/state. |
| Duplicate operations and stale revisions                     | All 21 writes have recorded concurrent replay outcomes; all 14 revision-bearing requests have observed competing-revision outcomes. [Exact replay](SURV-000.md#concurrent-replay-for-every-write) also covers a credential collision across surveys without a duplicate participation. Outcomes are operation-specific, not universally one success/one conflict. |
| Draft save versus publication; close versus completion       | [Observed lifecycle lock orders](SURV-030.md#observed-lifecycle-lock-orders) runs all eight ordered cases twice and checks immutable version contents, winning state and unchanged retries.                                                                                                                                                                       |
| Save/completion/export versus deletion                       | [Six deterministic deletion interleavings](SURV-090.md#deterministic-deletion-interleavings) observe the real database lock ordering, verify late access rejection and relational/exact-object erasure, and prevent recreation after deletion. This is not an exhaustive scheduler-interleaving claim.                                                            |
| Selection/export authorization, quotas and terminal products | The product-specific raw/report capability mapping, requester-bound jobs and [SURV-080 evidence](SURV-080.md) remain separate from aggregate browsing. [Export admission](SURV-090.md#export-admission-and-log-acceptance) rejects excessive jobs without job/outbox insertion.                                                                                   |

The private browser/HTTP error envelope and the neutral package's normalized
`SurveyError` remain distinct contracts. The Python repository port still accepts
operation names and dictionaries; versioned HTTP DTOs and typed package adapters
do not establish static typing at every Python application boundary.

## C-01–C-15 fixture reconciliation

[CAPABILITIES.md](../CAPABILITIES.md#5-capability-to-fixture-evidence-index) maps
every required capability to concrete fixtures, named tests and actual proof
sections. The review follows all 15 rows and their linked source/proof boundaries:

| Capability | Reviewed assertion coverage                                                                                                                                                           |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C-01       | Editor page/question moves, multi-page respondent restoration and observed last-page counts. Progress does not establish why someone abandoned a survey.                              |
| C-02       | Text/comment authoring, server length/Unicode boundaries, authorized raw text and parsed tabular/report outputs.                                                                      |
| C-03       | Single-choice/dropdown authoring and execution, scalar identity validation and exact aggregate distributions. The separate whole-Journey CI timeout remains open.                     |
| C-04       | Checkbox authoring and choice-count limits, unique allowed-value validation and documented multiple-choice percentage denominators.                                                   |
| C-05       | Rating and 0–10 NPS templates, valid scale/range checks, distributions and hand-calculated NPS using explicit valid counts.                                                           |
| C-06       | Numeric/date authoring, strict storage/coercion and boundary cases, numeric summaries and date distributions without averaging dates.                                                 |
| C-07       | Fixed matrix authoring, real required-row correction, row/column identity checks, per-row aggregates and flattened exports.                                                           |
| C-08       | Guided conditions, shared browser/server semantics, preceding-answer constraints and hidden-question/page-chain cleanup across restoration.                                           |
| C-09       | Required and bounded values, incomplete autosave versus final validation, forged values and 192 actual API validation cases including adapter recovery.                               |
| C-10       | Titles/hints/completion text, immutable published completion, unsafe presentation rejection and bounded host logos/styles; report rendering is separately reviewed.                   |
| C-11       | Both templates created through the host, independent copies, immutable source selection and populated invitation duplication without recipients or answers.                           |
| C-12       | Import diagnostics, safe unknown-region preservation, stable IDs and roundtrip, with unsupported/unsafe execution and publication rejected.                                           |
| C-13       | Undo/redo, draft autosave, lost acknowledgements, exact queued retry and competing drafts; local edit history is not respondent answer history.                                       |
| C-14       | German UI, real keyboard alternatives/focus/error checks and axe findings, independent host translation and Unicode reports. No general screen-reader/WCAG certification is inferred. |
| C-15       | Fontless SurveyJS styles, scoped host tokens and browser-only mount; authorized restoration makes no new write. Unselected SurveyJS SSR behavior is not claimed.                      |

The question/profile limits, canonical answer cleanup, timeout snapshot and
browser-only rendering decision are consolidated in
[PROFILE-CONTRACT.md](../PROFILE-CONTRACT.md). Entity constraints, migration
ordering and existing persona fixtures are in
[ROLES-AND-DATA.md](../ROLES-AND-DATA.md). The existing real-service proofs and
packed independent consumer substantiate those choices; unsupported capabilities
remain explicitly outside the initial profile.

## Scope of acceptance

The remaining SURV-000 work was the cross-operation, role and capability
reconciliation, not an additional unnamed service test. The reviewed evidence
above closes that reconciliation and the parent contract tasks. Existing
[A2/A3 infrastructure and A4 dependency evidence](SURV-000.md) supplies the other
requirements of 000.2 and 000.T1. Historical sections saying those parent items
were open describe their earlier checkpoint and are superseded by this review.

All referenced files and Markdown fragment targets in the capability, write,
role, profile and implementation-checklist documents resolve. That mechanical
link check is supporting evidence only; it does not replace the assertion review
or claim that all remaining spike tasks are complete. Own license remains
**UNDEFINED**; commercial SurveyJS components remain excluded.
