# Survey roles, persistence and fixture foundation

Own license: **UNDEFINED**. This records the implemented SURV-000 foundation;
it does not change any authorization policy or claim final spike acceptance.
Write DTOs, errors and revision/replay rules are in [WRITE-CONTRACTS.md](WRITE-CONTRACTS.md).
Question semantics and their fixture index are in [CAPABILITIES.md](CAPABILITIES.md).

## Role and resource mapping

Authoritative policy: `src/leonaid/domain/surveys/__init__.py` and
`src/leonaid/domain/policies.py`, applied with current persisted authority by the
PostgreSQL adapters. Survey capabilities are resource grants, not new global roles.

| Current actor / scope | Effective survey access |
| --- | --- |
| Inactive or suspended account | No member survey access; previously issued sessions/grants cannot preserve authority |
| System administrator | All nine survey capabilities; installation-wide timeout and retention settings |
| `charity_admin` for the linked action | All nine capabilities for that action's surveys; may create an action-linked survey |
| Standalone survey owner | All nine capabilities on that survey |
| Owner of an action-linked survey | All nine capabilities only while a valid role in that action remains |
| Explicit single-capability grantee | Only the granted capability; an action-linked survey additionally requires current membership in that same action |
| Ordinary action member without ownership/grant | Membership alone does not grant survey capability |
| Unrelated member / foreign action | No access; ownership or a grant on a different resource does not transfer |
| Anonymous respondent | Separate participation credential, no member survey capability and no automatic account/CRM/order association |
| Personal invitation respondent | Separate attributable invitation-to-participation relation, with expiry and revocation enforced |

An active authenticated account may create a standalone survey and become its
owner. Action association is stricter: the action must exist and be manageable by
that account. The nine capability values are `design`, `publish`, `archive`,
`view_aggregates`, `read_responses`, `export_raw`, `export_reports`,
`manage_invitations`, `delete`. A grant to view aggregates does not imply raw
response/export/invitation access. Export jobs additionally belong to their
requester; global administration has the separately tested exception.

The exact operation-to-capability mapping is in the write inventory. Two notable
boundaries are retained: a publisher may review a validated draft without design
permission, and export-only users may freeze an export selection without gaining
raw-response or aggregate browsing permission. Deletion-status access after
erasure is restricted to the requester or system administrator. Replaying an
already committed erasure request is bound to its original requester/key/revision.

## Entities and constraints

| Entity | Durable purpose and enforced boundary |
| --- | --- |
| `survey` | Owner and optional action FKs; bounded nonblank title; five-state enum; positive summary revision; access-mode enum; bounded timeout override; deleted status iff deletion timestamp exists |
| `survey_grant` | Unique survey/user/capability triple; only nine known capabilities; cascades with survey/user removal |
| `survey_draft` | One JSON object per survey, with independent positive draft revision; cascades with survey removal |
| `survey_version` | Immutable JSON definition, schema hash, renderer/profile labels and publication timestamp; unique survey/version number; update-blocking trigger; composite FK ensures the published pointer belongs to the same survey |
| `survey_participation` | Unique resume digest; same-survey version FK; full JSON answer snapshot, page, revision, status and clocks; effective timeout fixed at creation; completion status iff completion timestamp exists; no member/CRM/order FK |
| `survey_operation` | Survey/scope/operation-ID primary key; request hash and original response for transactional replay; cascades with survey removal |
| `survey_settings` / `survey_settings_operation` | True singleton with timeout and revision; actor/key replay receipts; retention defaults disabled and requires a configuring actor when enabled |
| `survey_invitation` | Recipient details, unique token digest, encrypted mail payload, expiry/revocation/delivery clocks; unique participation association; composite FK prevents cross-survey redemption; redemption timestamp iff participation is linked |
| `survey_analysis_snapshot` | Frozen public aggregate payload and separate private response array; IDs in payload must match relational survey/version IDs; update-blocking trigger; cascades with survey/version removal |
| `survey_export_job` | Immutable job input and requester/key uniqueness; composite snapshot FK; outbox event reference; exact object version/hash/size/render version required before available status; deletion is deliberately not cascaded before object cleanup |
| `survey_deletion` | Content-free erasure ledger, independent of survey/user/outbox FKs; persists after content removal; survey insert/update trigger rejects erased IDs |
| `survey_recovery_identity` | Opaque installation UUID in a true singleton; retained with backups and bound into external deletion checkpoints |

`survey_participation_effective` is a view, not another answer copy. It classifies
overdue in-progress rows using statement time and the participation's stored
timeout even while the worker is stopped. Inactivity changes classification only.
Retention uses separate ended/archive and trash clocks; it never treats respondent
inactivity as deletion authority.

Permanent cleanup removes recorded object versions before their export job
references and survey-owned content. The independent deletion ledger remains.
Its surviving identity and the no-recreation trigger are intentional exceptions
to the normal survey FK/cascade graph. Recovery must reapply deletion records
before reopening access; see [RECOVERY.md](RECOVERY.md) for current proof and
remaining cutoff/interruption/compatibility work.

## Migration sequence

These are the actual Alembic revisions under `migrations/versions/`, each linked
to its immediate predecessor. None silently assigns a production retention policy.

| Revision | Change / data treatment |
| --- | --- |
| `0027_surveys` after `0026_invoice_payment_snapshot` | Adds core survey, grants, drafts, versions, participations, replay and settings tables; no existing product data transformed |
| `0028_survey_timeouts` | Adds global settings replay, effective-status view and deadline index; no answer rewrite |
| `0029_survey_invitations` | Adds attributable invitations and same-survey participation relation; existing anonymous rows remain unassociated |
| `0030_survey_analysis` | Adds immutable analysis snapshots and separately stored private rows; no response rewrite |
| `0031_survey_exports` | Adds durable export job/object references and immutable input trigger; no existing survey/answer rewrite |
| `0032_survey_deletion` | Adds content-free ledger and erased-ID guard; automatic downgrade is refused because removing it permits recreation |
| `0033_survey_retention` | Adds disabled-by-default policies and dedicated lifecycle clock; existing ended/archived surveys start their clock at migration time |
| `0034_survey_recovery_identity` | Adds one installation UUID; no survey content changed; automatic downgrade is refused to preserve checkpoint identity |

This sequence is a source-reviewed description, not a claim that arbitrary
backups/downgrades are supported. Empty/current and upgrade migration evidence is
recorded in the work-package proofs; supported preceding-backup recovery remains
an explicit open SURV-090 requirement.

## Deterministic fixture behavior and isolation

`tests/fixtures/surveys/krapfentaxi.json` and `golf.json` contain three-page
synthetic questionnaire definitions. `tools/surveys/browser_seed.py` publishes
them through the real API. Validation, condition and aggregate golden fixtures
extend those cases without depending on real customer data.

`tools/surveys/permissions_live.py` creates 14 named personas: administrator,
owner, action manager, ordinary member, outsider and nine distinct single-grant
accounts. Four scopes cover standalone ownership, an action membership scope,
a foreign action and a foreign standalone survey. Expected capability sets are
specified independently of the production policy function. Fresh UUIDs/tokens
isolate invocations; behavioral expectations, relationships and question data are
deterministic. Credentials are temporary rather than checked-in fixture constants.

The harness also creates real publications, anonymous responses, snapshots,
exports and invitation fixtures. It verifies filtered lists/counts, direct read
and write authorization, changed authority, foreign child IDs, and unchanged SQL
after denied writes. Browser scenarios use the resulting actual sessions on
desktop/mobile, including publisher-only, lifecycle and Mailpit invitation flows.

`tools/surveys/infrastructure.sh` runs these fixtures in a fresh per-invocation
Compose project with explicit currently unused subnets and no published host
ports. Only owned containers/volumes/networks are removed. Sanitized reports are
copied to ignored local artifacts and selectively committed; session files and
raw traces are never evidence intended for publication. Foundation failure
diagnostics have a separately tested restricted reporter/collector.

The [SURV-000 fixture acceptance](proofs/SURV-000.md#persona-and-fixture-foundation)
combines the current full permissions run with the existing questionnaire/editor,
migration and deliberate-failure proofs. It does not replace the complete
SURV-100 author-to-deletion journeys or their aggregate CI gate.
