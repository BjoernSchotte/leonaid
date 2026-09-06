# Implementation evidence

## Delivery completion backend checkpoint — 2026-09-06

Added an action-manager-authorized completion service and transactional repository for draft/review-ready orders. The request carries delivery and invoice snapshots, a window ID and an optimistic hash of the current completion fields/status. The repository locks action then order, rejects stale edits and closed/invoiced orders, preserves already booked window IDs/times (including retired windows), and transitions successfully completed drafts to review-ready. Prices, quantities, buyer records and order lines remain unchanged. A separate command receipt provides exact replay and changed-payload conflict handling; the audit event records only status metadata, without addresses or notes.

Invoice issuance now locks the action and versioned delivery configuration and rejects missing delivery/address/window snapshots when delivery is enabled. Existing invoice/command replay occurs before the new completeness guard. Retired booked windows remain valid historical selections; issuance does not reinterpret them as fresh availability requests.

The real PostgreSQL foundation gate passes authorization denial for acquirers/drivers/unrelated managers, missing-order rejection, incomplete-delivery invoice denial, two simultaneous edits with exactly one winner, correct recipient/window readback, unchanged pricing/lines, retirement plus exact replay, changed-key-payload rejection, one audit entry and confirmed-order protection. After repair the invoice repository passes the delivery guard and reaches the fixture's intentionally missing invoice profile. This is a guard-path proof, not proof of a newly issued invoice for the repaired order. Focused Ruff, Mypy and 212 unit tests pass.

Integration remains open: this checkpoint supplies the backend service/repository; it is not yet exposed through HTTP or the administrator UI. Add its scoped endpoint, response version, generated client and completion form next, then prove a repaired order through actual invoice issuance and invoice recipient readback. The full `./leonaid test-invoices` gate passed on the changed repository: real server contract, Fresh Login, invoice issuance, immutable snapshots and the finance browser view. It used its own Compose project (`leonaid-362a-delivery-invoice-20260906a`), ports 18266/18666 and the optional dedicated subnet override added to this test runner. Other outstanding plan acceptance remains unchanged.

## Public booking/retirement concurrency checkpoint — 2026-09-06

The deterministic PostgreSQL proof now exercises both the acquisition repository and `AsyncpgPublicOrderRepository.order_command` / `record_order` / `complete`. It configures a synthetic published action and runs retirement-first and booking-first for each channel, observing real PostgreSQL blocking before releasing the first transaction.

All four cases pass. Retirement-first produces `delivery_window_unavailable` and persists no order. Booking-first stores exactly one order and allows later retirement; exact replay retains its ID, delivery recipient and immutable window snapshot. Public replay additionally leaves exactly one consent record and one `public_order_received` activity. The public command-receipt path is used rather than substituting direct inserts for order creation.

`tools/delivery/test-foundation.sh` passed in its own ephemeral PostgreSQL container/network with no host port or shared volumes, including all existing migration, schedule, template and order checks. Focused Ruff and Mypy pass. This test-only checkpoint closes the separately forced public repository race left open in the preceding entry. HTTP/browser transport and CRM matching were proven by the preceding full public-order gate; this repository race does not repeat those boundaries. Legacy order completion/review/invoice safeguards, remaining form/admin edge cases and EmDash/integrated visual acceptance remain open.

## Booking/retirement concurrency checkpoint — 2026-09-06

A deterministic real PostgreSQL race exposed a correctness bug: acquisition creation starts a Serializable transaction before waiting for the action lock. Schedule saves lock that action but update the separate delivery configuration row. After retirement committed, a waiting booking could therefore retain its earlier snapshot and accept the retired window. The pre-fix live proof reproduced an invalid persisted review-ready order.

`select_order_window` now locks the versioned delivery configuration row after the action row. PostgreSQL rejects a stale Serializable snapshot on this row, allowing the existing bounded acquisition transaction retry to read current configuration and return `delivery_window_unavailable`. The action/configuration lock order is shared with schedule writes.

`tools/delivery/concurrency.py` delegates every SQL operation to the real repositories and connections, pausing once immediately after an actual action-row lock. A third PostgreSQL connection observes `pg_blocking_pids` before releasing either transaction; timing sleeps do not stand in for lock evidence. Both forced orders pass: retirement-first rejects the new booking with zero persisted rows; booking-first commits exactly one order, allows retirement afterward, preserves the selected time snapshot and returns the same order on exact replay. All other foundation migration, schedule, action-default and order tests pass. Ruff, Mypy over 112 source files and 212 unit tests pass. The proof creates and removes only its own ephemeral database/network, without host ports or shared volumes.

Scope: this deterministic race uses the acquisition repository. The public repository uses the same selection helper under Read Committed; its own forced concurrent booking/retirement proof remains open. The full `./leonaid test-public-orders` regression also passes on the shared helper change: real Core/Twenty contract, JavaScript/no-JavaScript browser success and rejection/recovery, exact retry after a lost response, and exactly three persisted browser orders. It used its own Compose project (`20260906g`), ports 18265/18665 and subnet override. This checkpoint does not complete legacy order repair/review/invoice guards, all admin and form edge cases, EmDash integration or final visual acceptance.

## Public error recovery and retry checkpoint — 2026-09-06

Public Astro forms now retain submitted buyer, delivery, billing, quantity, contact, instructions, message and consent values on server rejection, including without JavaScript. Retention is request-local; no browser storage or CMS record is introduced. Consent is retained only for the same privacy version. Textarea content is escaped without template indentation changing its value. The server-rendered quantity/value preview uses retained quantities and current Core prices. Address length limits now match the transport contract, and delivery options sit inside the delivery fieldset.

Enhanced submission distinguishes known rejection from an unknown outcome. Editing after a known rejection creates a new command key; uncertain outcomes preserve the key and block changed payloads until the original submission is resolved. A delivery refresh control reloads Core's available windows and access token, preserves other inputs and clears unavailable selections.

The isolated `./leonaid test-public-orders` gate passed with real Core, Twenty, PostgreSQL and Chromium (final project suffix `20260906f`, ports 18265/18665, dedicated subnet override). Browser evidence covers an unavailable window ID rejected by Core, input retention, explicit reload/reselection and a new command key; a real accepted order whose HTTP response is deliberately lost, blocked edited resubmission and successful exact retry; and a JavaScript-disabled server rejection with retained separate billing, consent, quantity, selection and literal multiline instructions, followed by successful correction. PostgreSQL confirms exactly three browser orders, correct snapshots and invoice recipients. The no-JavaScript error page also proves three boxes / 72 pieces / EUR 108.00. The first run exposed textarea indentation, and visual inspection exposed a stale total preview; both were corrected and the full gate rerun successfully. Astro type checking, focused Ruff/Mypy and diff whitespace checks pass.

Evidence boundary: the public unavailable-selection test inserts an absent ID in the client; it does not prove concurrent administrator retirement (Anna's separate gate covers actual retirement after load). Remaining public work includes full policy enable/disable changes while a form is open, zero-window recovery, no-JavaScript unknown-outcome cases, editable country handling and integrated In-App Browser acceptance. Legacy completion/review/invoice safeguards, remaining admin conflict/draft cases and adversarial transaction races remain open. EmDash was rechecked read-only at `09ff352`; its public campaign renderer is still absent, so canonical/alias parity remains required.

## Public Astro delivery checkpoint — 2026-09-06

The existing public Astro renderer now reads the Core delivery definition and renders a required window selector grouped by date, optional delivery-contact name/phone, and dedicated multiline instructions with the configured limits. The existing Astro Action forwards these values through the Core public-order API. HTML-form CRLF line endings are normalized to LF before the instructions length check, preserving internal line breaks consistently with acquisition capture.

Invoice email is independently editable while address reuse is enabled, with the buyer email as the fallback. Separate billing fields are available in the server-rendered page so a visitor without JavaScript can uncheck address reuse and supply a different invoice recipient. JavaScript retains the existing show/hide enhancement.

`./leonaid test-public-orders` passed in an isolated real Core/Twenty stack. The browser creates a new-company order and an existing-company order with JavaScript, then a private-person order with JavaScript disabled and reduced-motion preference, using a separate billing address. PostgreSQL verification proves contact/phone, literal HTML-like multiline instructions, server-derived date/time snapshots, independent invoice email, and correct reused/separate billing addresses for all three orders. Existing legal configuration, consent, price, CRM mapping, idempotency/abuse and activity-event contract checks still pass. Astro type checking and focused Python lint/type checks pass. Mobile form and server-rendered success screenshots were inspected.

This proves successful submission through the legacy Astro renderer, including the JavaScript-free transport. Public stale-window recovery, edited-versus-exact retries, input preservation after a JavaScript-free server rejection, further layout/field-limit alignment and final In-App Browser acceptance remain open. The EmDash renderer is still absent at parallel branch `9ed7438`; its canonical/alias transport integration remains required. Tests use their own project, loopback ports 18265/18665 and an optional subnet override, without changing foreign resources.

## Beneficiary dashboard checkpoint — 2026-09-06

The authorized dashboard snapshot now reads the selected action's beneficiaries in the same repeatable-read transaction as its metrics. The response contains IDs, organization names, public descriptions, and stable display order. The existing service role gate still conceals unrelated actions; no administrator-only request is added to Anna's interface.

A compact row inside the goal card shows the first beneficiary directly. Multiple entries show `+N weitere`; the native disclosure exposes every full name and description, including long names. It is keyed by action ID so switching actions resets expansion. No beneficiaries produces no row; missing goal configuration does not suppress beneficiaries.

`./leonaid test-dashboard` passed against an isolated real CRM/Core stack: SQL records match the dashboard projection, unrelated-role access is concealed, and a synthetic zero-beneficiary action returns an empty list. All four browser scenarios pass. Added geometry checks at 360/390/430 px prove the goal-card height increase is at most 64 CSS pixels and there is no horizontal overflow. Tests cover one/multiple/long names, keyboard expansion, 200% root text sizing, missing goal, empty list, action switching and Axe checks. The 360 px screenshot was visually inspected. All frontend type checks, Mypy over 111 source files, focused Ruff, and 212 unit tests pass; OpenAPI/client regenerated.

The test uses its own Compose project, loopback ports 18264/18664, and an optional subnet override; no foreign resources were changed. Public Astro/EmDash forms, legacy completion/review safeguards, remaining order edge cases and final integrated In-App Browser acceptance are still open. The parallel EmDash branch is at `a4d1977` with authentication source, but still no public campaign renderer.

## Acquisition delivery capture checkpoint — 2026-09-06

Anna's capture form consumes the Core delivery definition for address/window requirements, optional contact/instructions, and field limits. It offers date-grouped explicit window selection, clears selection when the date changes, and supports delivery-address reuse for billing with an independent invoice email. The separate billing draft survives toggling; submission derives reused billing from the current delivery address. Buyer changes clear delivery details. An explicit deferral option keeps missing delivery data draft-only; draft submission also permits a missing window while server validation still checks any supplied address block.

Saved delivery address, contact, multiline instructions, and date/time snapshot now appear on the success screen and in an expandable administrator order detail. HTML-like instructions are rendered as text. Changed submissions receive a new command key after a known validation rejection; uncertain network outcomes require the original payload to be retried or checked before editing/resubmitting. Delivery errors refresh configuration without resetting address inputs and provide an explicit reload control.

The isolated `./leonaid test-commitments` gate passed the real CRM/HTTP/browser/PostgreSQL journey: configure delivery via the administrator API, capture as Anna, prove address-reuse behavior and invoice email, read back all delivery fields, inspect them in the administrator UI, and compare unchanged Golden totals across browser/API/database. Eleven tests passed with sixteen deliberate skips for single-execution write scenarios; nine Chromium/Firefox/WebKit viewport combinations passed responsiveness/accessibility checks, including 200% root text sizing in mobile Chromium. Feature type checking and diff whitespace checks passed. Screenshots were inspected locally; success-heading focus/scroll was subsequently improved.

The final isolated run also passed stale-window recovery: retire the selected window through the administrator API after the form loads, reject the stale submission, preserve address/instructions, reload selectable windows, choose the replacement, and persist exactly one order with a new command key. Success-heading focus/scroll corrections were included in this run. Remaining scope includes actual persisted draft/different-billing browser cases, unknown-network retry proof, legacy-order completion and review guards, public Astro ordering, dashboard beneficiaries, and integrated EmDash acceptance. EmDash was rechecked at `205c649`; only closed bootstrap/database/identity mapping source exists, with no public order renderer yet.

Test isolation uses its own Compose project and loopback ports 18263/18663. Docker's automatic address pool became exhausted by concurrently active projects; the commitment test runner now accepts an optional Compose override for separately allocated test subnets. No foreign networks or volumes were removed.

## Delivery editor checkpoint — 2026-09-06

The action management UI now has a delivery tab with date/window creation, copying a day's windows with fresh IDs, retirement controls, and save feedback. It displays the effective required address/window and optional contact/instructions policy for both acquisition and public ordering. The server rejects schedule changes for archived actions.

The isolated `./leonaid test-action-admin` gate passed with real HTTP, React, and Chromium: create two dates with three adjacent windows each, copy, save, reload, verify six persisted windows, check mobile document width at 390 px, run Axe on the editor, and continue the existing full action lifecycle with keyboard tab navigation. Screenshots were inspected locally. The layout now constrains the page grid so horizontal tab scrolling does not widen the document. Subsequent visual corrections separate the section heading from its explanation and accommodate all six desktop tabs.

The PostgreSQL foundation gate also passes with an additional archived-action rejection proof after the valid action status sequence. Focused Ruff and frontend feature type checking pass.

This is a usable configuration checkpoint, not full DEL-03 acceptance. Further proof/handling remains for unsaved tab changes, in-place revision-conflict reconciliation, referenced-window errors, unequal window counts, broader mobile sizes and zoom. Acquisition/public form rendering, saved order review/completion, dashboard beneficiaries, full public submission, and EmDash parity remain open. The EmDash branch was rechecked at `eadd30e`; its public order renderer is still absent. Tests use a dedicated Compose project and loopback ports 18262/18662; only their own resources are removed.

## Effective form configuration checkpoint — 2026-09-06

Admin action configuration, acquisition capture context, and the published public order form now expose the same typed delivery definition: required address/window, optional contact/instructions and limits, timezone/revision, and future non-retired windows. Public projection is only requested after the existing publication/submission gate. It contains no submitted contacts or order data.

New action persistence initializes delivery enabled for Krapfentaxi templates and disabled for blank templates; existing migration defaults stay disabled. Action detail changes acquire the same action lock and reject periods excluding configured delivery dates.

`tools/delivery/test-foundation.sh` passed with the new real action-repository proof: instantiate both templates, read their persisted defaults, configure a window, project the effective definition, reject an incompatible period edit, and omit elapsed windows. Prior acquisition-order and schedule proofs still pass. Full Python source/live-tool Mypy and 212 unit tests pass; OpenAPI/client regenerated and diff whitespace checked.

Still pending: the actual HTTP/browser journeys and UI consumers of this definition, full public-order live execution, review/completion handling, adversarial concurrency, beneficiary dashboard, and EmDash integration. This proof verifies persisted configuration and the shared projection, not the rendered forms.

## Order persistence checkpoint — 2026-09-06

Both internal/public order drafts and transport mappings now carry delivery window IDs and delivery-specific contact/instructions. Their fingerprints include selected windows while preserving historical hashes when no window is supplied. Delivery fields no longer leak into the invoice request through inheritance. Both repositories derive and persist the selected time snapshot, then expose it on internal reads/replays.

The isolated PostgreSQL proof now creates actual acquisition orders with real sponsor assignments and priced offerings through `AsyncpgCommitmentRepository`. It proves required delivery data, rejection of unknown windows, incomplete draft support, snapshot/contact readback, exact replay after retirement, refusal of fresh orders on retired windows, and changed-payload idempotency conflicts. Existing schedule/migration proofs continue to pass.

Validation: 212 unit tests, full Python source Mypy, focused Ruff, generated OpenAPI/client, and all frontend type checks pass. The public repository is wired but its full anonymous submission path is not yet live-proven. Remaining work includes effective form/capture-context projection, action defaults and period changes, legacy order completion/review guards, all UI work, HTTP/browser tests, concurrency across booking/schedule transactions, and EmDash integration. Existing action SHARE locks conflict with schedule UPDATE locks; the adversarial booking race still needs its explicit proof.

## Delivery administration checkpoint — 2026-09-06

Added the authorized delivery service, transactional PostgreSQL repository, GET/PUT action delivery endpoints, and regenerated OpenAPI/client. Acquirers can read their action configuration; only action managers can save it. Schedule saves share an action-row lock, check revisions and periods, protect booked windows/timezones, and reject foreign IDs even during upsert.

The extended `tools/delivery/test-foundation.sh` passed against isolated real PostgreSQL: two concurrent writes yield one success and one revision conflict; booked timezone/removal changes fail; foreign-window attempts roll back without changing either action; real service calls with role principals enforce read/write restrictions. Full unit suite remains 211 passing; focused Ruff/Mypy pass.

Scope of evidence: repository and application service are live against PostgreSQL. Endpoint contracts are generated and type-checked, but authenticated HTTP, UI, public ordering, and booking-versus-schedule concurrency remain to be proven. No DEL work package is marked complete on this narrower evidence.

## Foundation checkpoint — 2026-09-06

Implemented delivery schedule domain values with action isolation, chronological sorting, variable day/window counts, overlap rejection, local timezone/DST validation, and selectable-window checks. Added optional normalized delivery contact/phone and multiline instructions with limits; absent fields preserve historical serialization/fingerprints.

Migration `0027_delivery_windows` adds relational action configuration/windows and nullable order selection snapshots. Existing actions remain disabled and historical orders receive no invented dates. PostgreSQL protects referenced window times and action ownership.

Verified:

- `rtk proxy sh tools/delivery/test-foundation.sh`: PASS against real PostgreSQL 16.9. Applies all existing migrations, inserts synthetic historical data, upgrades twice, round-trips notes/contact, rejects booked-window mutation/deletion and cross-action references, allows retirement, and rehearses downgrade/re-upgrade.
- Full unit suite: 211 passed in the pinned UV/Python Docker image.
- Mypy: delivery domain and live proof script passed.
- `git diff --check`: passed.

Isolation: a newly created internal Docker network, ephemeral PostgreSQL tmpfs, no host ports, no shared Compose project or persistent volumes. Cleanup uses only IDs returned by this test's creation calls. The existing development stack and parallel EmDash resources were not changed.

Remaining: DEL-01 is not fully complete. Template/form configuration wiring, new-action defaults, booked-timezone and action-date changes, transactional schedule/order concurrency, all API/UI integration, beneficiary display, integrated EmDash proof, and full acceptance remain open. The current migration trigger alone does not prove the eventual concurrent booking/update protocol. This checkpoint does not claim a usable delivery-order flow.

Parallel EmDash baseline rechecked at implementation start: branch `codex/analysiere-emdashintegration`, commit `754afa3`; `apps/campaign-site/src/closed-bootstrap.ts` still denies public access. Reconcile the later renderer/transport before public campaign acceptance.
