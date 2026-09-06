# Implementation evidence

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
