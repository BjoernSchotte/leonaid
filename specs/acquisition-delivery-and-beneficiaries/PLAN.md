# Acquisition orders: delivery details, delivery windows, and beneficiaries

Status: Implementation in progress; foundation proven, end-to-end acceptance pending.
Date: 2026-09-06

## Outcome and scope

Anna can capture a Krapfentaxi order with a delivery address, an optional different billing address, a selectable delivery window, an optional delivery contact, and delivery instructions. Charity administrators configure any number of delivery dates and any number of windows per date. Anna's mobile overview shows who benefits from the selected action beside its existing goal, without adding a large homepage section.

Delivery capture is mandatory scope for both order-entry channels: Anna's acquisition interface and an interested visitor's order form on the charity action's Astro website. The Charity Admin backend owns their action-level configuration and form definitions. Completing only one entry channel does not complete this plan. Keep non-delivery actions, such as sponsorship-only actions, unaffected.

| Surface | Required outcome |
| --- | --- |
| Charity Admin backend | Configure action delivery dates/windows and the effective order-form definition; review all captured delivery data |
| Anna's acquisition interface | Capture delivery/billing addresses, a window, contact, and instructions under the same delivery rules; show compact beneficiaries on the overview |
| Public Astro charity website | Render these fields from the Core-owned form definition and submit them to Core, including on the EmDash-backed campaign website after its cutover |

Implementation and isolated live verification were authorized after the plan review. Progress and evidence are recorded in `PROGRESS.md`; production deployment is not implied.

## Evidence and current gaps

### Legacy website inspected in the In-App Browser

Source: [Lions Krapfentaxi](https://lions-krapfentaxi.de/), inspected on 2026-09-06.

The visible website says no delivery tours are currently planned. Entering the synthetic area postcode `97070` produces “für diese Postleitzahl gibt es keine Liefertermine”. Therefore the later steps could not be exercised as an active checkout. The following inventory comes from the page's existing form DOM, including currently hidden steps; required attributes are not proof of successful end-to-end validation. No order was submitted.

| Area | Existing form fields and behavior evidenced by markup |
| --- | --- |
| Billing/orderer | Optional company; required salutation, first name, last name, orderer email, street and house number, postcode, city; optional invoice email |
| Address reuse | Checkbox stating that the billing address corresponds to the delivery address or one of the delivery addresses |
| Delivery | Company/recipient, street and house number, postcode, city, and required telephone number on the delivery day |
| Scheduling | Delivery date and “Früheste Anlieferung” selectors; embedded dates are 11 and 12 February 2026, not verified current availability |
| Other delivery fields | Box quantity, a special-quantity callback checkbox, a business-partner card checkbox, and an additional-delivery-address control |
| Free text/contact | No dedicated delivery-contact name or free-text delivery-instructions field found in the order form markup; the separate contact form has a message textarea |

Do not copy the historical dates, salutation requirements, newsletter checkbox, or special-order options into this scope. The old site supports multiple addresses; this plan deliberately proposes one destination and one window per order, as requested. Multiple destinations and quantity allocation would require a separate fulfillment model.

### Checkout touchpoints at initial plan review

All paths below are repository-relative. This table records the starting gaps, not the current implementation status; consult `PROGRESS.md` for implemented and verified checkpoints.

| Area | Current implementation | Required change |
| --- | --- | --- |
| Internal capture | `packages/features/src/commitments/commitment-capture.tsx` submits an invoice recipient but no delivery recipient | Add delivery-first capture, address reuse, contact, instructions, and window selection |
| Core snapshots | `src/leonaid/domain/commitments.py` already has `DeliveryRecipientSnapshot` and `InvoiceRecipientSnapshot`; delivery currently contains recipient name, street, postcode, city, country | Extend delivery information compatibly; retain distinct invoice data |
| Application/persistence | `src/leonaid/application/commitments.py` already carries and fingerprints delivery recipients; `src/leonaid/adapters/postgres/commitments.py` stores and reads them | Wire internal transport, schedule validation, and new snapshot fields through all paths |
| HTTP contract | `src/leonaid/entrypoints/fastapi/schemas.py`: `CreateCommitmentRequest` and `CommitmentResponse` omit delivery; capture context exposes offerings only | Add input/output delivery contracts and available windows |
| Public orders | `apps/public/src/components/PublicAction.astro` and `apps/public/src/actions/index.ts` already implement delivery/billing addresses and `billingSameAsDelivery`; a general order message also exists | Reuse behavior; add dedicated delivery contact/instructions and scheduling without duplicating the address feature |
| Backend action editor | `packages/features/src/action-admin/manage-action.tsx` and `manage-sections.tsx` already manage beneficiaries | Add a delivery configuration section, reusing action permissions and revision handling |
| Dashboard | `packages/features/src/dashboard/dashboard.tsx` contains the existing goal card; `DashboardResponse` in `schemas.py` has no beneficiaries | Add a scoped beneficiary projection and compact display |

Preserve the architectural boundary: Twenty owns CRM parties and relationships; LeonAid Core owns action configuration and order snapshots. Delivery-specific addresses and notes must not silently overwrite CRM records.

### Parallel EmDash integration: verified dependency snapshot

Read-only inspection on 2026-09-06 found branch `codex/analysiere-emdashintegration` at `08e2169`. This is a moving implementation baseline, not a merged dependency or a claim that the campaign website is complete.

- Its `specs/emdash-campaign-microsite-spike/PLAN.md` keeps offerings, prices, availability, order-form configuration, privacy text, and submissions authoritative in Core (section 2.1).
- The new Astro application is `apps/campaign-site`, alongside `apps/public`. Its current files include `astro.config.mjs` and `src/closed-bootstrap.ts`; public campaign rendering is not yet implemented in that snapshot. Database provisioning has evidence, but this does not prove public ordering.
- EMS-010 defines route ownership; EMS-050 plans canonical campaign rendering; EMS-085 explicitly requires working form transport after migration. Existing Astro Actions belong to the app serving them: copying `PublicAction.astro` into the campaign app alone cannot establish submission parity.
- `apps/public` initially owns existing public routes. The intended campaign URL is `/campaigns/<archive_slug>/`, with `/krapfentaxi` becoming a Core-managed alias. Order POSTs must retain valid ownership and must not be redirected as part of the cutover.

Before DEL-02/DEL-04 implementation, inspect the latest EmDash branch again and reconcile its actual rendering, shared-component, and action-route decisions. Do not edit or cherry-pick the active parallel worktree as part of this plan update. Integrate against the agreed EmDash baseline before declaring final public-site acceptance; if it remains unfinished, report campaign-site acceptance as pending.

Implementation recheck on 2026-09-06: the parallel branch has advanced to `eadd30e` (CMS routing quality gate). Its campaign source still consists of `closed-bootstrap.ts` and `database-ready.ts`; it has no public order renderer. The shared Core form contract can proceed independently, but this does not complete DEL-04 or EmDash parity acceptance. Recheck again when the renderer becomes available.

Latest read-only recheck on 2026-09-06: `codex/analysiere-emdashintegration` is at `cd9518d`, recording the browser dashboard quality checkpoint after Core-session dashboard access. The campaign source now also includes bootstrap controls and Core identity/authentication adapters. It still has no public campaign order renderer. Dashboard authentication evidence does not satisfy EMS-050/085 or delivery-order acceptance. Recheck the actual serving-app action routes and renderer at integration time; do not duplicate this parallel work or assume its current commit is the final integration baseline.

### Form definitions are implementation scope

Current `OrderFormConfiguration` in `src/leonaid/domain/action_templates.py` defines address requirements, buyer contact requirements, and a general message option. These values are serialized into template/action configuration and projected through `OrderFormConfigurationResponse` and `PublicOrderFormResponse`. Persistence is handled in `src/leonaid/adapters/postgres/actions.py` and `public_orders.py`; public submission validates form requirements in `src/leonaid/application/public_orders.py`.

Extend that complete chain, not just rendered inputs:

- Define a typed delivery section in the effective form contract: delivery enabled/required, window required when delivery is enabled, optional delivery-contact name/phone, and optional multiline delivery instructions with their limits. Keep buyer contact fields distinct from delivery contact fields and general messages distinct from instructions.
- Make action delivery configuration the authority for delivery/window requirements. Project these into the form definition; do not introduce independently editable flags that allow the schedule, acquisition form, and public form to disagree. Newly enabled delivery forms include the requested optional contact/instruction fields in both channels.
- Extend template defaults, serialization/deserialization, action-instance persistence, admin configuration reads/writes, public projections, capture context, and generated client types. Existing instances need an explicit compatible upgrade/enablement path; changing only the Krapfentaxi template does not update them.
- Validate contradictory definitions on the server, such as requiring a window while delivery is disabled. Apply delivery completeness rules to both acquisition and public submissions, with the documented internal-draft exception. Preserve channel-specific buyer identity, public consent, and anti-abuse behavior.
- Render from the effective contract in each frontend and enforce the same requirements at the Core boundary, including for clients that bypass HTML validation. Admin changes must reach both entry channels on refresh without an EmDash publication, rebuild, or hard-coded form change. Revalidate stale forms at submission and preserve input when configuration changes invalidate a selection.
- Keep operational form definitions, submitted addresses, contacts, notes, and orders out of EmDash content records. EmDash owns editorial presentation only and cannot hide required fields or override Core validation through editorial settings.

Prefer shared typed field mapping, limits, validation helpers, and compatible Astro form components across public renderers. Keep serving-app submission adapters explicit; reuse the existing Astro Action implementation where the EmDash integration permits it, or use the Core order API with equivalent server validation and progressive enhancement. Do not create a second CMS order pipeline.

## Product decisions proposed for implementation

### 1. Delivery-first order capture

Form sequence: buyer/offering/quantity, delivery address, delivery date and window, optional delivery details, billing, review and save.

- Require recipient/company name, street and house number, postcode, city, and country for a complete delivery order. Reuse existing address field conventions and default country `DE`; do not infer a new geographic delivery restriction from the legacy site's postcode gate.
- Default “Rechnungsadresse entspricht der Lieferadresse” to checked. Derive the invoice address from the current delivery fields at submission, not from a one-time copy. Invoice email remains independently editable.
- Unchecking reveals a separate invoice address. Preserve that draft when toggling off/on within the current form, but never submit hidden stale billing values while reuse is enabled.
- Prefill only available, authorized CRM values. Missing street data must remain visibly incomplete; a CRM buyer and a delivery recipient may differ.
- Add optional “Ansprechpartner bei der Lieferung” and “Telefonnummer am Liefertag”. Proposed limits: name 200 characters and phone 50 characters. Phone is optional under this plan, despite the legacy form requiring it; make that distinction explicit in product review. Do not require a CRM person record or infer the delivery contact from the buyer.
- Add a separate multiline “Abteilung / Lieferhinweise” field, optional, maximum 1,000 characters. Examples: department, entrance, floor, and directions inside a building. Preserve internal line breaks, trim surrounding whitespace, render as text, and normalize empty input to null.
- Keep general order messages separate. Do not repurpose the current `message`, which normalizes whitespace and also serves non-delivery communication.
- Show delivery address, full date/time range, contact, instructions, and invoice address in the saved order detail and administrator review. Invoice generation continues to use the invoice snapshot; delivery notes are not automatically printed on invoices.
- Changing action clears action-specific window selection and prevents cross-action submission. Changing buyer must not silently reuse the previous buyer's delivery/billing/contact information.
- Keep current draft semantics: an internal draft may omit the complete delivery block/window; any provided block must be valid. Mark missing delivery requirements explicitly and require completion before becoming review-ready or confirmed. Public submission always requires complete delivery data when enabled. Do not broaden this into arbitrary partial-address draft persistence.

### 2. Flexible delivery dates and windows

Use Doodle-like date grouping as an interaction concept: “Tag hinzufügen”, then repeated start/end rows and “Zeitfenster hinzufügen”. This is scheduling configuration, not a poll or an external Doodle integration.

- Introduce typed, action-scoped delivery configuration with an explicit enabled state and IANA timezone, initially `Europe/Berlin`. Enable it by default for newly created Krapfentaxi actions; do not impose it on every charity action.
- Each date has zero or more draft window rows; saving an enabled, usable schedule requires at least one date with at least one complete window. Support variable counts, including three windows on each of two days and unequal counts on additional days. Avoid fixed arrays or weekday enums.
- Each persisted window has a stable ID, action ID, local date, start time, end time, and selectable/retired state. Store timezone in action delivery configuration and preserve it in order selection snapshots.
- Validate real calendar dates, valid local times, end after start, unique date/time ranges, and dates inside the action's date range. Reject overlapping windows on one date; adjacent windows are allowed. Overnight windows and ambiguous/nonexistent daylight-saving local times are outside scope and rejected with actionable errors.
- Sort dates and windows chronologically. The customer chooses exactly one window; changing the date clears any window selected on the previous date. Never auto-select the first window without an explicit user choice.
- Provide a convenience action to copy one day's windows to another date; create fresh IDs and run the same validation. A calendar grid is optional, not required for the first release.
- Reuse the action's admin authorization and optimistic revision conventions. Reject stale saves with a conflict response and retain the unsaved draft for reconciliation.
- Referenced windows cannot have their date/time changed or be hard-deleted. Retire them for new orders and create replacements. Existing orders retain the booked date/time snapshot; no silent rescheduling or customer notification is implied.
- Validate and save selection in the same transaction as the order, with a consistent lock/revision strategy shared by schedule writes. Reject foreign-action, retired, missing, elapsed, or concurrently invalidated windows. Return a recoverable selection error and preserve other form input.
- If delivery is enabled but no future selectable windows exist, block public submission and internal review-ready submission with a clear message; internal draft capture remains possible. Do not fall back to free text.
- Slot capacities, route optimization, recurring schedules, delivery assignments, and automated rescheduling are out of scope. An available window is a configured selectable interval, not a capacity guarantee.

### 3. Compact beneficiary motivation

- Product clarification: a charity action typically has exactly one beneficiary. Optimize the default layout for that case; multiple beneficiaries are the expandable variant.
- Use the selected action's existing beneficiary records, including all beneficiaries; no new independent list or hard-coded charity names.
- Add a compact “Für: …” row inside the existing goal card. For one beneficiary, show its name directly without requiring expansion. For multiple beneficiaries, show the first organization's name and an accessible “+N weitere” disclosure.
- Limit the collapsed name area to two lines and the added row to at most 64 CSS pixels at normal text size on 360–430 px mobile widths. The full name/list remains reachable by keyboard and touch; enlarged text may grow naturally rather than clip.
- The disclosure reveals all names and existing public descriptions. Keep long descriptions, logos, and a separate beneficiary card off the collapsed homepage.
- With no beneficiaries, omit the row without reserving space. Display beneficiaries even if the goal is not configured. Reset expanded state on action change.
- Extend the authorized dashboard response with a beneficiary projection from Core rather than adding an admin-only request from the PWA. Keep goal calculations and ordering unchanged.

## Contract, persistence, and compatibility design

Proposed names below are implementation targets, not existing API guarantees.

1. Add a typed delivery configuration/window module in domain, application, and PostgreSQL layers. Use relational action/window references, not a generic JSON settings bag. Add a new Alembic migration after the current head; do not edit applied migrations such as `0011_public_orders.py`.
2. Extend `DeliveryRecipientSnapshot` with optional contact name, phone, and instructions; old JSON must deserialize with null defaults. Keep billing serialization independent: `PublicOrderInvoiceRecipientRequest` currently inherits the delivery request, so split/rework that inheritance before introducing delivery-only fields.
3. Add nullable order window ID and a server-created date/start/end/timezone snapshot. Enforce action ownership through database constraints and application validation. The server derives snapshot text and times; clients submit the ID, never authoritative times.
4. Extend internal create/read/review contracts, `CommitmentDraft`, public-order drafts, repository mappings, and fingerprints. Include every new field in idempotency comparison. Exact retries return the original result even if the window has since retired; a changed payload with the same key conflicts. Fresh submissions revalidate availability.
5. Add scoped schedule read/write endpoints through `src/leonaid/entrypoints/fastapi/routes.py`; extend capture context and the public action/order-form projection with enabled state, timezone, and selectable windows. Public reads expose no contacts, notes, or booked-order identities.
6. Extend dashboard application/repository/transport projections with beneficiary IDs, names, and public descriptions. Preserve existing authorization and action isolation.
7. Regenerate OpenAPI and `packages/api-client/src/generated.ts` using `./leonaid generate-api-client`; update all consumers and contract fixtures. Never hand-edit generated types.
8. Existing orders retain unknown/null delivery details and windows; never fabricate historical selections. Existing confirmed/invoiced orders remain readable and valid. Existing draft/review-ready orders require explicit completion before future delivery-sensitive transitions once scheduling is enabled. Provide an authorized completion path for these orders; do not make missing fields impossible to repair.
9. Existing actions start with delivery configuration disabled until an administrator configures and enables it. New Krapfentaxi template instances carry the intended delivery-enabled configuration but cannot accept complete orders until configured. Deployment must coordinate enabling existing actions with refreshed web/PWA/public clients; stale clients receive clear missing-selection errors.
10. Do not log free-text notes or contact values, publish them in analytics, or expose them through public order retrieval. Include new fields in existing export/erasure handling where applicable, and use synthetic test data.

## Implementation work packages

### DEL-01 — Domain and migration

Dependencies: none.

- [ ] Implement delivery configuration/window invariants and snapshot extensions.
- [ ] Extend typed order-form definitions, template defaults, and existing action-instance compatibility; establish one authoritative delivery policy for both entry channels.
- [ ] Add schema migration, reference constraints, old-snapshot defaults, and fixtures.
- [ ] Define retirement, timezone immutability once booked, and action-date-edit validation against existing delivery dates.
- [ ] Prove old orders still load without invented delivery data and non-delivery commitments remain unaffected.

### DEL-02 — Backend administration and order contracts

Dependencies: DEL-01.

- [ ] Add authorized schedule reads/writes and revision conflict handling.
- [ ] Wire effective form definitions through action persistence, admin configuration, capture context, public projections, and server validation for both order channels.
- [ ] Extend internal/public order creation, readback, review transitions, legacy-order completion, and idempotency.
- [x] Implement transactional availability checks and protect referenced windows from mutation. Evidence: both acquisition/public booking-retirement races and reference protection in `PROGRESS.md`.
- [ ] Regenerate API client and prove action/party authorization remains enforced.

### DEL-03 — Action configuration UI

Dependencies: DEL-02.

- [ ] Add delivery configuration to `packages/features/src/action-admin/manage-action.tsx` and a focused section/component alongside `manage-sections.tsx`.
- [ ] Support date/window add, edit, copy, retire, validation, empty state, and unsaved revision-conflict recovery.
- [ ] Explain referenced-window restrictions and no-available-window state in German UI copy.
- [ ] Show the effective order-form delivery section in the Charity Admin backend, including required address/window fields and optional contact/instructions; changes must govern both Anna's form and the public form.

### DEL-04 — Internal and public ordering

Dependencies: DEL-02; DEL-03 provides usable configured test actions.

- [ ] Extend `commitment-capture.tsx`, `commitment-admin.tsx`, and related styling with delivery/billing/contact/instructions/window behavior.
- [ ] Extend `PublicAction.astro`, `PublicOrderEnhancement.astro`, and `apps/public/src/actions/index.ts` using the same backend rules, preserving the existing public address toggle and validation flow.
- [ ] Reconcile with EmDash EMS-010/050/085 and extend the actual `apps/campaign-site` form renderer and serving-app transport once available. Reuse shared definitions/components where appropriate; verify both canonical campaign and alias entry points rather than assuming parity from copied markup.
- [ ] Preserve anonymous submission with and without JavaScript, consent/version checks, anti-abuse controls, idempotency, server pricing, and recoverable error/success feedback across the public renderer transition.
- [ ] Preserve user input on validation, network, and retired-window errors; make exact retry versus edited resubmission explicit in command-key handling.
- [ ] Verify saved details, legacy completion, and correct invoice recipient end to end.

### DEL-05 — Dashboard motivation

Dependencies: independent of DEL-01–04; requires its own dashboard contract/client regeneration.

- [x] Extend `src/leonaid/application/dashboard.py`, `src/leonaid/adapters/postgres/dashboard.py`, and response mapping with authorized beneficiaries.
- [x] Add the compact row/disclosure in `packages/features/src/dashboard/dashboard.tsx` and `dashboard.css`.
- [x] Verify no-beneficiary, single/multiple, long-name, missing-goal, and action-switch states. Evidence: beneficiary checkpoint in `PROGRESS.md`; final integrated In-App Browser acceptance remains under DEL-06.

### DEL-06 — Integration and visual acceptance

Dependencies: DEL-01–05.

- [ ] Run relevant domain, repository, API contract, component, and browser checks.
- [ ] Inspect the implemented mobile dashboard and ordering UI in the In-App Browser using synthetic data; compare collapsed goal-card height before/after at 360, 390, and 430 px widths.
- [ ] Verify 200% text zoom, keyboard disclosure operation, labels, error focus, touch targets, and absence of horizontal overflow.
- [ ] Record commands/results and remaining limitations in this spec directory before marking implementation complete.
- [ ] Prove the same configured action works through Anna's form, the existing public renderer, and the EmDash campaign renderer on the integrated baseline. An unfinished EmDash renderer leaves this acceptance item open.

Use one synthetic action for this cross-surface acceptance: configure two delivery days with three windows each in Charity Admin, then add a third day with a different count. Refresh Anna's form and the public form and compare their effective requirements and available windows with the saved admin configuration. Submit one order through each entry channel and verify their delivery, separate/reused billing, contact, instructions, and selected-window snapshots in administrator review and PostgreSQL. Repeat the public journey through the integrated EmDash canonical route and alias, with and without JavaScript. Finally retire a window after both forms have loaded: both must reject the stale selection, preserve unrelated input, and permit an explicit replacement selection. No CMS publication or site rebuild may be needed for these operational changes.

## Acceptance and test matrix

| Scenario | Expected proof |
| --- | --- |
| Address reuse | Editing delivery updates submitted billing while checked; separate billing survives toggling; invoice email remains independent |
| Different parties | Buyer, delivery recipient, delivery contact, and invoice recipient can differ and round-trip without CRM mutation |
| Instructions | Multiline department/directions text survives create/read; blank is null; over-limit input is rejected; HTML is displayed as text |
| Variable schedule | Two days with three windows each, then a third day with a different count, all render and persist without code changes |
| Invalid schedule | Invalid/overlapping/duplicate/overnight/DST-invalid ranges fail; adjacent windows succeed |
| Selection safety | Missing, retired, past, and foreign-action windows fail for complete delivery orders; concurrent retirement cannot produce a new invalid booking |
| Booking history | Retiring a booked window preserves saved times; attempts to mutate/delete it fail; exact order replay still succeeds |
| Drafts and migration | Optional incomplete delivery remains draft-only; legacy completion works; historical confirmed orders load; sponsorship-only actions are unchanged |
| Authorization | Acquirers cannot edit schedules or view other parties' orders; unrelated-action administrators cannot mutate schedules; public reads contain configuration only |
| Beneficiaries | Zero/one/many/long names, unconfigured goal, action switch, keyboard/touch expansion, and mobile height budget pass |
| Billing regression | Invoice creation uses the correct invoice snapshot and does not substitute delivery notes/contact fields |
| Definition propagation | Admin configures delivery once; both entry channels expose the same address/window/contact/instructions contract; existing action instances and new template instances behave correctly |
| API enforcement | Bypassing HTML validation cannot submit a complete order missing required delivery fields; stale form/configuration errors preserve input; optional contact remains optional in both channels |
| EmDash parity | Identical synthetic orders through legacy Astro and campaign Astro persist equivalent delivery snapshots; canonical URL and alias work with and without JavaScript |
| Editorial independence | Editing/publishing EmDash content cannot change delivery requirements or order data; Core window changes reach the campaign form without CMS publication |
| Transport/cutover | Serving-app action route, origin/CSRF protections, consent, retries, and success/error feedback remain valid; order POSTs are not redirected and accepted orders survive renderer rollback |

Extend existing suites such as `tests/e2e/commitments.spec.mjs`, `action-admin.spec.mjs`, `public-orders.spec.mjs`, `dashboard.spec.mjs`, `tests/unit/test_public_orders.py`, and `test_dashboard_metrics.py`; add focused schedule domain/repository tests. Cover real persistence and transaction races, not just component mocks.

Repository verification entrypoints for implementation (not executed for this documentation-only plan):

```sh
rtk ./leonaid generate-api-client
rtk ./leonaid test-actions
rtk ./leonaid test-action-admin
rtk ./leonaid test-commitments
rtk ./leonaid test-public-orders
rtk ./leonaid test-dashboard
rtk ./leonaid test-pwa
rtk bun run typecheck
rtk bun run test:components
rtk bun run build:web
rtk bun run build:pwa
rtk bun run build:public
rtk git diff --check
```

Run the existing invoice regression gate when changing review/invoice transition code, and the OpenAPI compatibility checks for generated contract changes. A successful build alone does not satisfy DEL-06.

On the integrated EmDash baseline, also run the applicable EMS-010/050/085 route, public rendering, and demo-migration gates from `specs/emdash-campaign-microsite-spike/PLAN.md`, including campaign-site build/type checks as defined there at implementation time. Run the extended public-order scenarios against both renderer entry points. A closed-runtime or PostgreSQL-only EmDash test is not evidence that these delivery forms work.

## Review assumptions

These choices make the plan executable without claiming they were explicitly requested: one destination/window per order; optional contact name and phone; no slot capacities; non-overlapping same-day windows; delivery-first address reuse; explicit enablement for existing actions. If product review changes these choices, update the affected model and acceptance criteria before implementing them. No implementation approval is implied by this plan.
