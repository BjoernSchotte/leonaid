# Native CRM and Twenty migration

**Status:** Draft for review · 2026-11-21

**Repository baseline:** `991633899b1448050c2aca239876b7716d85c498` on `main`

## 1. Decision and scope

Make LeonAid Core the system of record for companies and people. Store the
records in Core PostgreSQL, provide a contact administration surface through
the existing Core API, and retire Twenty after a verified migration. Start with
the existing `CrmGateway` as the compatibility boundary. Add event contracts
that can support automation, then deliver the first workflow as a separate
increment.

LeonAid already owns actions, acquisition assignments and history, orders,
donations, invoices, tasks, Inbox cases, consent, and action-level
authorization. A sponsor or donor is a company or person in a business context.
Those roles are represented by the existing assignments and transactions.
Issued documents and business snapshots retain their original meaning when a
contact is edited.

The replacement release covers contact persistence, search and matching,
administration, import, privacy integration, and deployment without Twenty.
Future increments cover typed custom fields and configurable workflows.
A generic object builder, opportunity pipeline, arbitrary script execution,
and a visual workflow editor are outside the replacement release. The scope
of historical Twenty-only records depends on the installation inventory.

## 2. Current Twenty contract

| Consumer                        | Operations and behavior to preserve                                                                                                                                                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Acquisition and sponsor capture | Read companies and people by ID or ID list, load company contacts, find candidates by normalized name and literal search, reuse or create the selected party and contact, and preserve assignment visibility and idempotency.                           |
| Activity boards                 | Hydrate permitted parties and company contacts in batches. Preserve the handling of a CRM record that has disappeared and the existing contact restrictions.                                                                                            |
| Public order form               | Find or create the buyer and, when applicable, its company contact. Preserve company-scoped person matching, ambiguity errors, targeted e-mail disambiguation, deterministic create IDs and request replay. Order and recipient snapshots live in Core. |
| Inbox                           | The `inbox.contact_link.v1` job creates or recovers a person using a known ID. Case managers can search for and explicitly link a person. A changed or unproven outcome enters the existing review path.                                                |
| Search, donations and documents | Global sponsor search uses the locally synced name-and-city index. The donor picker uses the action's acquisition parties. Document and donation references can contain CRM IDs, while document bytes and issued snapshots have their own owners.       |
| Contact operations              | LeonAid's Excel/CSV tooling uses search, single-row create and controlled update with dry-run and per-row decisions. The Pilot Twenty UI is a system administration surface reached via an SSH tunnel. CRM erasure is a manual follow-up today.         |

The [semantic port](../../src/leonaid/application/crm.py) and its
[Twenty implementation](../../src/leonaid/adapters/twenty/gateway.py) cover
`GET`, `POST` and `PATCH` on `/rest/companies` and `/rest/people`. GraphQL
`createCompanies` and `createPeople` are implemented and exercised in the
gateway contract test. No live application callers were found. Twenty-specific
batch sizes, pagination, rate limiting and HTTP retry classifications belong
to the adapter. The repair CLI updates the Twenty-only `leonaidMatchKey`
field, and the sponsor-search worker reads records by IDs and by `updatedAt`.

The [metadata manifest](../../infra/twenty/schema.json) provisions
`charityAction`, `acquisitionAssignment`, their relations and views, and
integration permissions. These are documented as Core-owned read models.
No regular Core callers were found for those objects, opportunities, generic
CRM activities, Twenty workflow execution, or Twenty webhooks. The live
inventory must separately account for data and automations maintained directly
in Twenty.

Sources for application behavior are the [order service](../../src/leonaid/application/public_orders.py),
[sponsor matching](../../src/leonaid/application/sponsor_matching.py),
[Inbox worker](../../src/leonaid/modules/inbox/jobs.py),
[search repository](../../src/leonaid/adapters/postgres/search.py),
[import contract](../../infra/twenty/README.md) and
[Pilot admin guide](../../apps/docs/src/content/docs/en/ops/how-to/install-on-a-vps.md).

## 3. Data model and write semantics

### 3.1 Contact records

The names below describe the intended schema. Repository naming and column
types should follow the existing PostgreSQL conventions.

| Model              | Fields and constraints                                                                                                                                                                                                                                                         |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `crm_company`      | UUID primary key, display name, street lines 1 and 2, postal code, city, region, country, derived match key, revision and timestamps. Use existing postal address validation and preserve postal codes as text.                                                                |
| `crm_person`       | UUID primary key, given name, family name, primary e-mail, primary phone, nullable company foreign key, derived match key, revision and timestamps. Preserve the existing port's phone normalization. A company has zero or more people, and a person has at most one company. |
| CRM audit entries  | Use the Core audit facility for actor, operation, subject ID, changed field keys and request correlation. Minimize personal data in audit payloads and use existing retention.                                                                                                 |
| Migration evidence | Per-run export manifest and reconciliation report with source fingerprint, dispositions and target revision. Store sensitive input and row-level reports in restricted migration storage with an explicit expiry. Counts and digests can be retained as operational evidence.  |

Keep the original Twenty UUID for each migrated row. Preserve identity as
`(party kind, UUID)` wherever the existing model can represent either kind.
New records use UUIDs, including caller-supplied IDs where existing commands
use them for safe replay. Historic references and snapshots are verified as
part of migration. The presence of historic or erased references means that
adding mandatory foreign keys across all existing consumers requires a separate
decision. The new live person-to-company relationship can use a database
foreign key from the outset.

E-mail, phone and names are contact attributes. They are not globally unique
identifiers. Persist the existing normalized match key in the same transaction
as a name change and index it by kind. Retain literal lookup where the caller
uses it for search or for inputs with no useful normalized key. Keep company
context and comparison rules specific to the existing use case. Multiple
candidates remain visible for resolution and are never silently merged.
Changes to normalization require a deliberate backfill and re-index.

### 3.2 Commands and transactions

- Map the existing gateway reads and writes to PostgreSQL. Retain one coherent
  backend choice across API, workers and operator tools. A native backend
  installation must start without a Twenty integration key. A missing native
  schema or incomplete migration blocks readiness for the native configuration.
- Share a transaction explicitly where one command should commit a contact
  with its dependent record or outbox event. Calling a pool-backed gateway
  from a transaction does not share that transaction on its own. Keep
  transaction boundaries visible in the command/repository wiring. Avoid
  acquiring a second connection while holding a command lock on the first.
- Preserve command receipts, selected-candidate revalidation, and public-form
  and Inbox recovery behavior during the backend change. Replaying the same
  create intent returns the same record. Reuse of that ID with a different
  intent produces a conflict. Existing command locking and contact-level
  serialization must be tested with concurrent writes from different entry
  points, without relying on a global name uniqueness constraint.
- Add optimistic revision checks for staff edits, including explicit semantics
  for setting a value, clearing an optional value, and omitting a field. Imports
  retain the current rule that blank cells do not clear existing values.
- Preserve existing notification timing, buyer data snapshots and consent
  behavior. Reuse the current domain services for orders, activities, Inbox,
  tasks, and finance. Simplify transport-outcome recovery only after proving
  the corresponding local operation is atomic or safely repeatable.

## 4. API, roles and privacy

**Compatibility.** Keep current acquisition, Inbox, public order, donation
and document API shapes initially. Existing `twentyId`, `contactTwentyId`
and related fields continue to resolve stable UUIDs, including on older PWA
drafts and command replays. Use provider-neutral identifiers in new endpoints.
An eventual rename belongs in an explicit API-version and client compatibility
change with an upgrade test against an installed PWA.

**Contact administration.** Add a Core-authenticated, system-admin-only
surface with paginated company/person lists, detail, create and revision-aware
edit. A person can be linked to, moved between, or unlinked from companies.
Company details can list associated people. Authorized staff can review import
decisions. The first release keeps the broad directory privilege with the role
that currently administers Twenty. Additional directory privileges require a
separate policy decision. Existing scoped contact operations continue through
their action or case policies. Company lookups and global search must not
broaden access through a join. Public requests get only their existing business
response and cannot read the contact directory.

**Privacy and retirement of records.** Extend the existing privacy lookup and
export to include native records, including contacts found only in CRM. Apply
the existing legal configuration, suppression and review policies to
erasure or anonymization of the contact and related pending work. Preserve
records with a retention obligation, such as issued finance documents, under
the existing policy. Establish what historical references remain and what a
reader sees when a party becomes unavailable. Do not cascade-delete orders,
assignments, or documents. Block any admin action that would silently reassign
dependent records. A merge command and alias handling can be specified when
needed. Keep audit and job logs free of e-mail addresses, phones and raw
contact payloads.

**Integration points.** The change reaches the
[FastAPI composition root](../../src/leonaid/entrypoints/fastapi/platform.py),
[worker bootstrap](../../src/leonaid/bootstrap/worker.py),
[sponsor search projection](../../src/leonaid/application/sponsor_search.py),
[privacy repository](../../src/leonaid/adapters/postgres/privacy.py),
[contact importer](../../tools/twenty/import_contacts.py),
[generated API client](../../packages/api-client/src/generated.ts), and the
admin and Inbox UI. Query the native contact tables for sponsor search while
preserving ranking, result shape and assignment filters. Any retained
projection must have a local maintenance and rebuild path. Remove the external
poller and match-key repair only once the native path is verified.

## 5. Events and workflows

### 5.1 Event foundation

Define versioned events for committed changes needed by actual consumers.
Initial examples are `crm.company.updated.v1`, `crm.person.created.v1`,
`crm.person.company_changed.v1` and
`acquisition.assignment.status_changed.v1`. The last event belongs to
acquisition. An audit entry or an existing event-like name does not establish
a workflow contract. An unchanged update, failed transaction, duplicate
command replay, or migration backfill must not emit another business trigger.

Write the event to the existing PostgreSQL outbox in the same transaction as
the business change. The envelope contains a stable event ID, type/version,
entity type and ID, revision where applicable, occurrence time, action scope
when available, and correlation. Carry only the typed transition data required
by the event contract, such as previous and current status. Keep names,
addresses and complete contact snapshots out of the envelope. Events created
by workflow commands also carry causation and a bounded chain context.

The [outbox worker](../../src/leonaid/application/outbox.py) already supports
claims, bounded retries, delays and dead letters. The
[registry](../../src/leonaid/bootstrap/registry.py) maps each type to one
handler. Introduce one dispatcher per supported event type, backed by shared
code when a second consumer needs it. Evaluate published rules against the
recorded change and persist one run per matching rule version. Create the run
and its outbox step job in a single transaction. Deduplicate on event ID and
rule version so a retried dispatcher produces the same run. The first rollout
can use one code-defined rule with these semantics before adding a rule
authoring surface.

### 5.2 Configurable rules

| Record                | Responsibility                                                                                                                                                                                                                                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Workflow definition   | Stable identity, scope, owner and lifecycle. Only authorized administrators can publish, pause or retire workflows for their scope.                                                                                                                                                                                 |
| Workflow version      | Immutable published trigger, typed conditions and ordered actions. Store the exact version selected at dispatch. Define activation by event occurrence time, and keep historical versions while they have in-flight runs or retained evidence. Pausing has explicit semantics for future dispatch and pending runs. |
| Workflow run and step | Event ID, version, subject, step state, next eligible time, attempts, failure code and correlation. Each side-effecting command has a stable key derived from run and step. An administrator can see what ran and retry a failed step with the same key.                                                            |

Start with a finite catalog of trigger fields and existing commands. A useful
first rule is to create a follow-up task for the current responsible person when
an acquisition assignment transitions into the committed status. Scope the
rule to a chosen action. Before creating the task, recheck the action, subject
and responsible person's eligibility through the task command. Record a skipped
run if the action is closed, the record is gone or the recipient is no longer
eligible. Bound retries and causal depth. Prevent loops through self-triggering
rules, and preserve the original version for in-flight runs. Delay and retry
use the existing worker facilities. Add external notifications only through
approved mail or push commands with the applicable suppression and consent
checks.

### 5.3 Custom fields

Add typed, versioned field definitions when the first installation needs
additional attributes. Each definition has a stable key, target entity type,
value type, validation rules and access policy. Enable indexing for concrete
search and filter requirements. Use stable choice IDs so labels can change
without changing rule meaning. A field used by a published workflow needs
explicit retirement or a rule update. Fixed-schema fields continue to own
match keys, relationships and authorization-relevant invariants. Custom
relationships, arbitrary custom objects and the workflow designer can be
considered after the first concrete extensions.

## 6. Migration and operations

### 6.1 Inventory and rehearsal

1. Obtain a read-only, installation-specific inventory from supported Twenty
   APIs and authorized administrative exports. Record active and archived
   companies and people, relationship shape, services and external writers.
   Inspect custom fields, additional channels, lists/views, notes, activities,
   files, workflows, and data in the two LeonAid read models. The runtime
   integration key is deliberately too narrow to establish this inventory.
2. Record a decision for each populated data class. Map it to the native
   model, preserve it in a restricted archive with owner and retention, or
   exclude it with explicit approval. Preserve original IDs and provenance in
   the chosen destination. Empty and unsupported fields, invalid values,
   duplicate IDs and orphan relationships receive explicit dispositions.
   Never guess a matching contact or discard a real value to get a clean run.
3. Inventory Core references at this revision and on the actual deployment.
   Cover acquisition and activity references, order and contact snapshots,
   consent, Inbox links and pending contact IDs, generated documents, donation
   snapshots, command receipts, and references in events or in-flight jobs.
   Classify IDs as live, intentionally historical/erased, or unresolved. An
   ID reserved for an in-flight create is distinct from a missing live record.
4. Build a separate import mode for migration. The existing spreadsheet import
   matches by business names and is useful for ongoing intake. Migration
   matches by source UUID and source identity. Import companies first, then
   people and relations. Re-running the same source release is a no-op. A
   changed or conflicting export needs a new run and report. Keep writes and
   workflow dispatch disabled for public traffic during the rehearsal.
5. Rehearse with representative data on staging. Produce counts by type and
   disposition, canonical digests over migrated fields, relationship checks,
   and a reference report comparing source and target. Demonstrate a repeat
   import, a failed or interrupted run, and a restore. Record the observed
   duration and schedule the production window using that evidence.

### 6.2 Production cutover

| Step    | Action and gate                                                                                                                                                                                                                                                                                                                                                     |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prepare | Build and validate additive migrations and the adapter switch. Verify the exact deployment artifacts, configuration, backup/restore, operator roles and staging evidence. Inventory open jobs and define whether each drains, pauses or resumes after cutover. Rehearse the maintenance window and rollback procedure.                                              |
| Freeze  | Put public and staff write entry points into maintenance. Quiesce API commands and CRM-writing workers. Pause direct Twenty admin/import access and other writers. Confirm there are no active writers and capture a consistent Core, Twenty and file recovery point.                                                                                               |
| Load    | Take the authoritative export while writes remain frozen. Import by UUID, then run the approved reconciliation. Require zero unresolved live references and a recorded disposition for each allowed exception. Keep domain workflows quiet during the import.                                                                                                       |
| Switch  | Select the native backend for all API and worker instances as one deployment. Keep external writes closed. Run readiness and isolated role-scoped smoke checks with synthetic or approved test data. Check pending CRM-related jobs against the migrated identities before releasing their workers.                                                                 |
| Reopen  | Open writes only after the evidence and the post-write recovery plan are accepted. Observe CRM errors, order submissions, Inbox queue outcomes and search checks. Record the time of the first authoritative native write. Twenty remains frozen as a recovery source during the observation window.                                                                |
| Retire  | After the observation and recovery gates, remove Twenty server, worker, PostgreSQL and Valkey, provisioner, repair timer, routes, secrets, alerts and bootstrap dependencies. Update backup/restore, upgrade, seed and test paths and prove a fresh install and restore with Twenty absent. Handle retained backups and archives under the agreed retention policy. |

### 6.3 Rollback boundary

Before reopening writes, keep the original recovery point and configuration
available. If a gate fails, keep maintenance active, stop the native release,
restore or revert to the verified pre-switch services and configuration as
appropriate, and check the original business paths before reopening.

After the first authoritative native write, restoring the old snapshot alone
would lose data. The default recovery direction is to keep native PostgreSQL
authoritative and recover forward from the current data and verified Core
backups. A switch back to Twenty after that point requires a separately
rehearsed UUID-preserving reconciliation of native creates, edits, deletions,
relationships and dependent Core records, under a new freeze and backup.
If that reverse path is unavailable, the cutover decision must accept
forward-only recovery after reopening. There is one authoritative writer at
every stage.

## 7. Delivery order and acceptance

1. **Contract and native adapter.** Add additive migrations and native reads
   and writes behind the port. Test supplied IDs, empty reads, conflicting
   matches, partial edits, sorting and missing contacts. Prove concurrently
   retried order, sponsor and Inbox commands behave correctly.
2. **Core integration and administration.** Deliver contact admin, privacy
   integration, import and direct sponsor search. Exercise public orders for
   company and person, activity/contact selection, assignment handover,
   sponsor search and donor selection, document references, Inbox linking and
   review, and offline PWA draft replay. Include positive and negative
   authorization across actions, a public user and a system administrator.
3. **Migration rehearsal and switch.** Achieve the gates in §6, including
   scoped production smoke checks before reopening, import repeatability,
   absence of new duplicates, stable UUIDs, and backup/restore evidence.
4. **Twenty retirement.** New installs, restored migrated installs and
   monitoring all work with the four Twenty services absent. No API, worker,
   proxy or operator entry point requires a Twenty token.
5. **First event consumer.** Prove no event on rollback or replay, one event
   per committed transition, one task per rule and event under retries, skip
   on permission or state changes, and no loop or duplicate side effect.
   Add typed custom fields and rule configuration in separate reviewed
   increments when a concrete use case requires each.

Use the existing [gateway contract](../../tools/twenty/gateway_contract.py),
[policy contract](../../tools/policy/contract.py),
[Inbox worker contract](../../tools/inbox/jobs_contract.py),
[public order contract](../../tools/public_orders/contract.py),
[sponsor search contract](../../tools/sponsor_search/contract.py),
[privacy contract](../../tools/privacy/contract.py) and
[golden journey](../../tools/golden_journey/contract.py) as behavioral
references. Run native integration checks against real PostgreSQL. Use
staging to prove migration and restore, and production smoke verification to
prove the actual installation. An application test alone does not accept a
live cutover.

## 8. Decisions required before production

- Confirm the owner and disposition of Twenty-only data and the export access
  required to inventory it.
- Confirm which staff need directory-wide contact management and approve any
  expansion beyond system administration.
- Confirm the maintenance window, acceptable restore point and post-write
  recovery strategy based on rehearsal evidence.
- Choose the first workflow and measure its operational value before funding
  a rule editor or schema builder.

This draft is based on repository contracts. Production data, manual Twenty
use, source export completeness and deployment behavior remain to be verified.
