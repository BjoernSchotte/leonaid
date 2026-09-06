# Implementation evidence

## Mobile dashboard text scaling and direct In-App measurements — 2026-09-06

Authenticated In-App Browser inspection on the disposable review stack covered 360, 390 and 430px widths. A single beneficiary added 60px to the goal card (44px disclosure row); multiple beneficiaries expanded through the native disclosure, including keyboard Enter. At 200% root text size, direct inspection found horizontal overflow at 390px (document width about 428px). Constraining the dashboard grid track and action selector and allowing text wrapping removes that overflow. After rebuilding the PWA, measured document widths were 345/375/415px at viewports 360/390/430px.

Expanded the existing enlarged-text browser assertion to all three widths. The isolated dashboard gate `leonaid-362a-delivery-dashboard-20260906b`, ports 18264/18664 and worktree network override, passed all four Chromium scenarios in 6.4 seconds, including long beneficiary names, keyboard disclosure and accessibility checks. The direct browser review stack was removed before starting this gate. Full mobile ordering and EmDash renderer acceptance remain open; read-only parallel baseline `9569150` still has no public order renderer.

## No-JavaScript reload preserves the complete failed-navigation POST — 2026-09-06

Extended the accepted-response-loss browser scenario with direct page reload before exercising history Back. After the actual server acceptance and deliberate response abort, reload repeats a byte-identical POST: the test compares the entire request body to the original, including command ID, latest invoice-city correction and multiline delivery instructions. No input is re-entered for this path. The returned success reference equals the originally accepted reference. The existing history-Back recovery then also runs and returns that same order; PostgreSQL still finds exactly the three intended browser orders.

The first proof attempt used LF for a raw HTML form transport comparison; HTML serializes textarea line breaks as CRLF. The corrected test asserts the complete identical body and the expected CRLF transport value. Application persistence continues to normalize line endings as previously proven.

`./leonaid test-public-orders` exited 0 in isolated project `leonaid-362a-delivery-public-20260906x`, ports 18265/18665 and worktree network override. The expanded original order journey passed in 21.8 seconds; policy, cross-surface/admin and final PostgreSQL checks pass. Own stack was cleaned up. This proves latest-input preservation for direct reload/retry without JavaScript in Chromium. Browser history Back still restores an earlier form state, as documented separately; it is not the same recovery operation. Mobile In-App and EmDash acceptance remain open.

## No-JavaScript accepted-response loss and history retry — 2026-09-06

The new real browser test accepts the no-JavaScript order through the actual Astro/Core path, extracts its successful reference, then aborts only the browser response. Returning through browser history previously regenerated the command identity and could create a duplicate. A deterministic successor on an error page did not solve the GET history reload, so that abandoned change is not retained.

Active order pages now establish an opaque random `orderAttempt` in their GET URL, and the form action carries it forward. The hidden command keeps that identity across server-rendered validation errors and history reloads. Initial GETs without a valid attempt redirect to the same route with the identifier; order POSTs never redirect. Canonical metadata remains unchanged and no personal data is encoded in the identifier. A known validation rejection creates no order, so its corrected no-JavaScript POST can safely retain the same identity; changed payloads after acceptance remain protected by Core idempotency comparison.

Important limitation: Chromium history restores the earlier invalid POST form, including its invalid invoice-city value, rather than the last correction before the lost response. The test explicitly corrects that field again; preserved instructions and command identity are asserted. Resubmission returns exactly the original accepted reference, and the database still contains exactly the three expected browser orders. This proves duplicate prevention, not complete latest-input restoration after a browser navigation failure. That retention limitation remains open.

Final `./leonaid test-public-orders` run `leonaid-362a-delivery-public-20260906v`, ports 18265/18665 and worktree subnet override exited 0. All existing policy/integration/admin and PostgreSQL checks pass, including the integrated journey in 4.9 seconds. Earlier runs s/t/u exposed the identity and history-state issues described above. Own test stacks were cleaned up. Final mobile In-App and EmDash acceptance remain open.

## Acquisition action-switch isolation — 2026-09-06

Extended the disposable acquisition fixture after its existing authorization contract: transition the third Golden action through scheduled to active and authorize Anna there without assigning any sponsors or offerings. The browser explicitly selects the original action in the sponsor workspace, fills private delivery fields, selects a window and enables deferred delivery, switches to the empty second action and verifies that saving is disabled. Returning to the original action clears street, contact, instructions, date and deferred mode and restores address reuse. It then completes the existing regular order/retry journey. No production change was needed for this tested path.

The initial setup attempted draft-to-active directly and correctly failed the database lifecycle constraint. A second run exposed the old browser helper's assumption about the default action; the helper now explicitly selects its intended action. The final run `leonaid-362a-delivery-commitments-20260906p` completed `./leonaid test-commitments` with exit 0, ports 18263/18663 and worktree subnet override. Eleven browser checks passed in 43.9 seconds (16 intentional skips); Browser/Admin API/PostgreSQL agree on 10 orders, 31 boxes/744 pieces and EUR 1,116.00. Ruff/Mypy and diff checks pass. All own test stacks were cleaned up. Final mobile In-App and EmDash acceptance remain open.

## Effective order rules and empty availability in Charity Admin — 2026-09-06

Added an effective-form summary to the delivery editor, read from Core's existing delivery/order-form projection. It distinguishes saved rules from local edits and displays delivery/address requirements, optional contact/instruction limits, timezone and currently selectable window count. With delivery enabled and zero selectable windows it explains that public and review-ready acquisition orders are blocked while internal drafts remain possible. A refresh button retries reads and rechecks time-dependent availability. Read errors do not display stale rules as current. The saved configuration revision keys the query, so successful schedule saves refresh the summary without discarding local editor state.

The real public-policy browser test creates only elapsed/retired availability, opens Charity Admin and verifies the zero-window warning and required-field/limit copy; restoring a future window and refreshing removes the warning and shows one window. The integrated Admin save automatically shows seven windows after configuring 3/3/1. Both entry channels, stale rejection/recovery, successful orders, visible admin details and PostgreSQL readback continue to pass.

`bun run typecheck` passed across API client, UI, features, web, PWA and public Astro (zero errors/warnings). `./leonaid test-public-orders` exited 0 on isolated project `leonaid-362a-delivery-public-20260906r`, ports 18265/18665 and worktree subnet override. The shared journey passed in 5.0 seconds. Own stack was cleaned up. Together with the prior admin add/edit/copy/retire/conflict/discard proofs, this completes DEL-03; integrated EmDash and final mobile In-App acceptance remain open.

## Shared orders visible in administrator review — 2026-09-06

The integrated browser journey now navigates to `/admin/orders` after creating both recovered orders. For each actual order ID, it opens the delivery/billing disclosure using keyboard Enter, verifies contact, phone, multiline instructions, timezone and the appropriate reused/separate invoice address, and closes it again using Enter. This proves the visible reviewer path in addition to admin API and PostgreSQL readback.

`./leonaid test-public-orders` exited 0 for isolated project `leonaid-362a-delivery-public-20260906q`, ports 18265/18665 and worktree subnet override. The full shared Admin configuration, both stale rejections, explicit replacements, both successful orders and visible Admin review passed in 6.5 seconds. Existing public scenarios and final PostgreSQL verification pass. Own stack was cleaned up. Exact mobile In-App acceptance and integrated EmDash renderer acceptance remain open.

## Retirement after both order forms selected the same window — 2026-09-06

The shared 3/3/1 journey now fills both forms and selects the third-day window before retiring it through the Admin editor. Anna receives `delivery_window_unavailable`; the public form presents delivery feedback. Both preserve their delivery address and multiline notes, and public separate billing and privacy acknowledgement remain intact. Admin order-list counts before and after the two rejected submissions are equal.

Both users explicitly refresh availability, the retired public option disappears, and no replacement is selected automatically. They explicitly choose a second-day window and complete their original orders. Admin readback and PostgreSQL verify both saved selections and delivery/billing snapshots against that replacement. No service rebuild or CMS publication takes place between configuration, rejection and recovery.

`./leonaid test-public-orders` exited 0 on isolated project `leonaid-362a-delivery-public-20260906p`, ports 18265/18665 and worktree network override. Existing order journeys pass, policy checks passed in 11.2 seconds and the integrated configuration/rejection/recovery/order journey passed in 6.1 seconds. Final PostgreSQL verification passes and own stack was cleaned up. Administrator UI detail inspection, exact mobile In-App acceptance and EmDash renderer acceptance remain open.

## Both orders persisted after shared Admin configuration — 2026-09-06

Continued the same-action 3/3/1 browser journey with an actual review-ready acquisition order and an anonymous public order selecting the third day's configured window. Both use identical delivery address, optional contact/phone and multiline instructions. Anna keeps address reuse enabled; the public buyer supplies a separate billing address. Admin list API readback proves exactly two matching integration orders, identical server-derived delivery-window snapshots and the intended different billing streets. The final PostgreSQL verifier independently locates the acquisition order by returned ID and the public order by success reference and checks both snapshots.

`./leonaid test-public-orders` exited 0 with isolated project `leonaid-362a-delivery-public-20260906o`, ports 18265/18665 and worktree subnet override. Existing order paths passed in 19.8 seconds, policy recovery in 8.9 seconds and shared configuration plus both orders in 3.0 seconds. Existing three-order persistence/retry assertions still pass because the integration orders have a distinct synthetic contact marker. The disposable rate-attempt table is cleared between independent browser scenarios; production anti-abuse code is unchanged. Ruff/Mypy and diff checks pass. Own stack was cleaned up. Final administrator UI inspection, retiring a selection loaded in both forms, exact mobile In-App acceptance and integrated EmDash ordering remain open.

## Same-action admin-to-acquisition/public policy propagation — 2026-09-06

Added a shared live browser journey in the public gate. It opens Anna's capture and the anonymous Astro form before changing configuration, then uses the Charity Admin delivery editor on that same Golden action to extend its booked first-day interval into three windows, copy them to a second day and add one interval on a third day. An actual successful PUT and subsequent read confirm 3/3/1 persisted windows.

Without a service rebuild or content publication, reloading Anna and using public availability refresh exposes exactly the same seven window IDs. The test compares the capture API projection, each date's internal selector options and the public selector against the saved configuration. Selection stays empty after changing dates/refreshing; contact and instruction fields are present in both forms. A synthetic policy evidence JSON is retained in `.artifacts/poc072/delivery-cross-surface-policy.json`. Disposable Anna/admin sessions are written to a mode-600 temporary environment file.

`./leonaid test-public-orders` exited 0 with isolated project `leonaid-362a-delivery-public-20260906n`, ports 18265/18665 and worktree network override. The existing three-order journey passed in 20.1 seconds, stale-policy journey in 9.1 seconds and the new shared configuration journey in 2.3 seconds. Existing Core/Twenty and PostgreSQL proofs pass; own stack was cleaned up. Creating and reviewing both orders after this shared configuration, integrated retirement recovery, and EmDash parity remain open. Read-only EmDash baseline `e0bdb7c` adds campaign draft creation but still has no public order renderer.

## Delivery extras removed by subject anonymization — 2026-09-06

The requirement audit found that the existing privacy anonymizer replaced address fields but retained the new delivery contact name, phone and instructions. Updated only the delivery snapshot expression to remove those three JSON keys before applying the existing anonymized address. Billing and legally retained invoice/document records keep their established handling.

The real privacy fixture adds synthetic contact/phone/multiline-instruction values to an existing operational order. After the authenticated System Admin browser flow performs lookup, export, suppression and anonymization, PostgreSQL assertions require all three keys to be absent. Existing invoice/document hash, authorization, fresh-login and suppression checks remain intact. The export remains the existing reference-based report; this change does not invent a new export format.

`./leonaid test-privacy` passed with project `leonaid-362a-delivery-privacy-20260906a`, ports 18267/18667 and the explicit worktree network override newly supported by this gate. The browser check passed in 2.9 seconds and the final database contract passed. Ruff/Mypy, shell syntax and diff checks pass. The gate cleaned up its own resources. Integrated ordering and EmDash acceptance remain open.

## Buyer-switch isolation in acquisition capture — 2026-09-06

Extended the real acquisition browser journey to fill delivery address/contact/phone/instructions, choose a window and enter separate invoice street/email, then switch to another authorized sponsor and back. The UI clears private delivery and invoice drafts, resets date selection and restores address reuse; previous values do not reappear on return. Existing implementation passed without a source change. The same journey then creates the normal order and proves retirement/retry recovery.

`./leonaid test-commitments` exited 0 for isolated project `leonaid-362a-delivery-commitments-20260906m`, ports 18263/18663 and the worktree subnet override. Eleven checks passed in 35.9 seconds (16 intentional skips); admin API and PostgreSQL agree on 10 orders, 31 boxes/744 pieces and EUR 1,116.00. Own test resources were cleaned up. This closes the buyer-switch evidence gap; action-switch and full cross-surface/EmDash acceptance remain open.

## Direct In-App public form review — 2026-09-06

The isolated public-order gate exited 0 with project `leonaid-362a-delivery-review-20260906`, ports 18265/18665 and the worktree network override. The opt-in `LEONAID_PUBLIC_ORDER_TEST_KEEP_FOR_REVIEW=1` now retains only a successful test stack for direct review; default and failed runs still clean up automatically. Temporary proof files are removed in both cases.

Opened the actual public form in the In-App Browser over local HTTP. Screenshots and direct interactions verified delivery fields, multiline department/directions, optional contact, separate billing disclosure and preservation of a typed billing recipient across collapsing/reopening. Refreshing availability retained the contact/instructions and left the window unselected with an updated status. No order was submitted during this manual review.

The screenshot exposed an unstyled refresh button. Added a secondary button style with a 2.75rem minimum height, inherited typography and existing theme tokens; the hidden attribute remains effective without JavaScript. Rebuilt only this project's public service successfully and verified the corrected button and working refresh directly in the In-App Browser. This desktop inspection does not claim the remaining exact mobile widths or integrated authenticated journey. Local HTTPS was rejected for an untrusted development certificate; no trust settings were changed.

Read-only EmDash baseline is now `3f39ed7`; campaign-site still has no public order renderer. Full EmDash and cross-surface acceptance remains open.



## Historical order repository read after migration — 2026-09-06

Replaced the foundation migration fixture's empty customer object and missing line with a valid pre-0027 confirmed acquisition order: historical buyer snapshot, priced offering and one EUR 5 line. After upgrading to head, the proof reads it through `AsyncpgCommitmentRepository._get`, not only SQL column assertions. Status, buyer, line and total remain unchanged; delivery recipient, window ID and snapshot remain null. No historical selection is fabricated.

The full isolated foundation gate with `LEONAID_DELIVERY_FOUNDATION_SUBNET=172.30.81.0/24` exited 0, including the new historical read, sponsoring-order regression, migration round-trip, both booking race channels and explicit historical completion. Ruff/Mypy pass. Own temporary PostgreSQL/network resources were cleaned up. The matching DEL-01 compatibility checkbox is now complete on repository/migration evidence; integrated browser and EmDash acceptance remains open.


## Non-delivery sponsorship order regression — 2026-09-06

Expanded `tools/delivery/form_configuration.py` beyond checking the blank template's disabled default. It now uses a real persisted blank action, enables ordering, inserts a synthetic sponsoring offering and creates a review-ready admin order with a billing recipient but no delivery recipient/window. Real PostgreSQL readback preserves null delivery fields and the priced line/total. Exact command replay returns the same order ID.

`LEONAID_DELIVERY_FOUNDATION_SUBNET=172.30.81.0/24 sh tools/delivery/test-foundation.sh` exited 0; the new `non-delivery-order` proof and all existing migration, order, concurrency, history and form proofs pass. The sponsorship total is EUR 5.00 and billing stays unchanged. Ruff/Mypy pass. The test used its own ephemeral database/network without host ports and cleaned its resources. ACCEPTANCE.md now records this concrete regression evidence; broader integrated channel/template coverage remains open.


## Acquisition retry after accepted order and HTTP server failure — 2026-09-06

Fixed Anna's changed-payload retry guard to treat HTTP 5xx responses as an unknown submission outcome, alongside network failures and incomplete idempotency receipts. Previously a typed server error allowed a changed payload to rotate the command key, potentially duplicating an order already accepted before the response failed. The UI now explains the uncertain outcome and requests an unchanged retry.

The live browser proof sends the actual booking to Core, waits for its successful 201 response, and only then substitutes a typed 503 response. Changing the delivery street and resubmitting is blocked locally with exactly one intercepted POST; restoring the original address and retrying returns the identical order ID with `replayed=true`. Existing retirement recovery and saved delivery/billing/contact/window assertions still pass. The first run (`...commitments-20260906k`) used an incomplete simulated error without requestId and consequently exercised generic network-error handling; the corrected final run uses the full API error contract.

Evidence: `./leonaid test-commitments` exited 0 with isolated project `leonaid-362a-delivery-commitments-20260906l`, ports 18263/18663 and worktree subnet override. Eleven browser checks passed (16 intentionally skipped combinations) across nine browser/viewport layouts in 41.8 seconds. Admin API and PostgreSQL agree on 10 orders, 31 boxes/744 pieces and EUR 1,116.00; no duplicate booking was created. Feature TypeScript and diff whitespace checks pass. Own Docker resources were cleaned up. Overall integrated In-App and EmDash acceptance remain open.


## Stale public delivery-policy submission proof — 2026-09-06

Extended the real browser acceptance to load a disabled-delivery form, fill valid buyer/address/quantity/consent data, activate delivery through the admin API and submit the stale form without refreshing first. Both JavaScript and no-JavaScript requests are rejected with delivery feedback, preserve recipient/quantity/consent, and expose the now-required selector (explicit refresh for JavaScript; SSR error response for no JavaScript). Selecting a valid window remains possible. Authorized order-list counts before/after confirm that the rejected attempts create no orders. The existing three successful persisted order journeys remain unchanged.

The first run (`...public-20260906k`) timed out on checkbox interaction before submission; the new contexts now use the same reduced-motion/mobile settings as the established no-JavaScript test. The second (`...l`) reached submission but hit the accumulated rate limit from earlier scenarios. The gate now runs the two browser scenarios separately and clears only `public_submission_attempt` in its disposable database between them. Production rate-limit code is unchanged and remains proven by the preceding server contract.

Final evidence: isolated project `leonaid-362a-delivery-public-20260906m`, HTTP 18265/HTTPS 18665 and worktree subnet override completed `./leonaid test-public-orders` with exit 0. Original order journey passed in 19.6 seconds; policy/empty-state/stale-submit journey passed in 9.8 seconds. Real Core/Twenty contract and PostgreSQL order verification pass. Original policy is restored and own Docker resources are cleaned up. Remaining integrated Anna/public/In-App/EmDash acceptance is not claimed complete.


## Public empty availability and required-label consistency — 2026-09-06

The visible delivery-window required hint now follows the same Core requirement as the actual select, both on SSR and after policy refresh. The live policy test additionally retires all future configured windows while retaining an active past window, producing valid enabled configuration with no selectable future windows. The loaded JavaScript form shows only the empty option, explains unavailability and retains its recipient. A separate no-JavaScript page shows the same empty selection and explains that ordering needs an available window. Restoring the original configured windows makes the choices available again through refresh.

Evidence: isolated project `leonaid-362a-delivery-public-20260906j`, ports 18265/18665 and worktree subnet override completed `./leonaid test-public-orders` with exit 0. Both Chromium tests passed (24.6 seconds), including existing three persisted order journeys and no-JavaScript coverage. The Core/Twenty contract and PostgreSQL verification pass. Astro typecheck and whitespace checks pass. The test restored the original schedule and cleaned its own Docker resources.

Remaining scope is unchanged: stale-policy submission recovery, broader cross-channel acceptance, final In-App Browser inspection and integrated EmDash parity are still open. This checkpoint proves empty availability rendering/refresh, not every submission outcome.


## Public delivery policy refresh checkpoint — 2026-09-06

Fixed the public refresh behavior to apply current enabled/required/contact/instructions rules as well as window options. Delivery controls are present even when initially disabled, so later activation can reveal them without discarding address input. Disabling removes the window requirement and disables its submission. The JavaScript refresh button is available immediately; no-JavaScript rendering continues to use server-projected rules. Existing selected windows survive only if still available.

Live evidence: `./leonaid test-public-orders` completed with exit 0 using isolated project `leonaid-362a-delivery-public-20260906i`, ports 18265/18665 and the worktree subnet override. Two Chromium tests passed (25.6 seconds): the existing three order journeys and a new real-admin policy propagation journey. The latter disables delivery after page load, refreshes and checks that selection is disabled/nonrequired while the recipient survives; it then loads a disabled page, enables delivery via the real admin API, refreshes and checks that required selection, contact and instructions become available with the recipient retained and no automatic selection. Original policy is restored in cleanup. Existing public Core/Twenty contract and PostgreSQL order verification pass, including the no-JavaScript order path. Astro typecheck and helper Ruff/Mypy pass. Own Docker resources were cleaned up.

The helper creates a disposable synthetic admin session and passes it through the test's temporary proof directory, which is removed by the gate; no session credential is committed. Remaining acceptance includes stale-policy submission itself with/without JavaScript, empty availability, final integrated In-App inspection and EmDash parity.


## Editable public delivery and billing countries — 2026-09-06

Removed the public Astro action's hardcoded DE delivery/invoice country. The public form now exposes separate two-letter country fields with autocomplete, labels, validation/error targets and retained SSR values. Existing forms without these new fields retain the DE default. Submitted lowercase codes normalize to uppercase. Shared billing uses the current delivery country; separate billing uses its independently supplied country.

Live evidence: isolated `leonaid-362a-delivery-public-20260906h` on ports 18265/18665 with the worktree subnet override completed `./leonaid test-public-orders` with exit 0. The three existing browser journeys (including no-JavaScript submission, stale-window/input retention and exact retry scenarios) enter `at` for delivery. PostgreSQL verification asserts AT for every delivery, AT for reused billing, and DE for the separate-billing journey. Existing Core/Twenty contract, consent, pricing, idempotency, activity and anti-abuse checks pass. Astro typecheck reports zero errors/warnings; verifier Ruff and whitespace checks pass. Own Docker resources were cleaned up.

Remaining: policy changes after page load and other cross-channel acceptance remain open, as do final In-App Browser inspection and integrated EmDash renderer parity.


## Variable delivery days, discard recovery and error focus — 2026-09-06

Delivery editor errors now receive programmatic focus on a single wrapper while the existing StatusMessage remains the alert. Expanded the real admin browser journey to save three days with 3/3/1 windows, reject an end before its start without losing the entered start, and verify error focus. A second real concurrent save retires a window; after conflict, explicitly discarding local edits restores the saved times and retirement checkbox. The effective order-form response contains six selectable windows while all seven configured windows survive reload.

Validation: `./leonaid test-action-admin` with isolated project `leonaid-362a-delivery-admin-20260906l`, ports 18262/18662 and the worktree network override exited 0. The React component gate and full admin lifecycle browser journey passed (17.3 seconds), including existing mobile overflow/Axe checks. Feature TypeScript checking passed. Own Docker resources were cleaned up. This proves the previously untested discard branch and unequal-day counts, but does not replace the integrated Anna/public/EmDash acceptance or the final In-App Browser inspection.


## Delivery editor tab retention and conflict recovery — 2026-09-06

The delivery editor remains mounted inside its hidden management panel, retaining unsaved dates/windows across tab switches. A revision conflict now offers an in-place read-only comparison of the latest saved configuration (revision, enabled policy, timezone, dates, times, retirement). The admin can explicitly retain their local plan on the compared revision and save, or explicitly discard their input and load the saved plan. The comparison explains that saving the retained plan replaces the compared configuration; immutable booked-window guards still apply server-side. A later concurrent write is still protected by revision validation.

Live evidence: `LEONAID_ACTION_ADMIN_TEST_PROJECT=leonaid-362a-delivery-admin-20260906k` with HTTP 18262, HTTPS 18662 and the isolated network override completed `./leonaid test-action-admin` with exit 0. The browser creates two days with three windows each, switches away/back before saving, verifies all six windows remain, performs an actual competing API save, receives a revision conflict, compares the saved October 3 window, explicitly retains its own plan, saves and reloads the six original windows. Existing mobile layout/Axe and action lifecycle assertions pass, as does the React component gate. Frontend feature typecheck and diff whitespace checks pass. The test removed its own Docker resources.

Added optional `LEONAID_ACTION_ADMIN_TEST_COMPOSE_OVERRIDE` support to the existing gate so its networks can use worktree-reserved subnets. No foreign Docker resources were changed.

Remaining for DEL-03: unequal per-day counts and additional edit/retire/error-focus acceptance still need evidence; the discard-current-input branch is implemented but not yet browser-proven. Full cross-surface/In-App/EmDash acceptance remains open.


## Historical completion HTTP and admin UI checkpoint — 2026-09-06

Added strict `confirmHistoricalDelivery` to the completion HTTP request and regenerated OpenAPI/client. The new manager-only completion context returns the shared future-order definition plus separate configured, already ended windows (including retired ones). Ordinary capture/public projections remain future-only. The admin editor exposes an unchecked explicit historical confirmation; switching modes clears date/window selection, with no historical default. Already booked snapshots remain fixed.

Live proof: isolated invoice project `leonaid-362a-delivery-invoice-20260906j`, ports 18266/18666 with the worktree network override, completed with exit 0 and cleaned its resources. The first attempt (`...i`) failed because its synthetic enabled schedule contained only retired windows; the corrected fixture retains a future active window alongside the historical retired one. No production validation was loosened.

The Chromium flow at 390px selects the September 2 historical window on a completed action, verifies the confirmation starts unchecked and no date is preselected, retains local input across a real competing-save conflict, explicitly reconciles the stored state and saves separate billing. Axe reports no serious/critical violations; focus, 200% text size and horizontal overflow assertions pass. The rendered `.artifacts/poc090/invoice-delivery-completion.png` was visually inspected. The competing HTTP write makes the first historical assignment; browser persistence then preserves that booked snapshot during reconciliation.

The authenticated HTTP proof independently completes a legacy draft with a retired September 3 window: unconfirmed submission fails, the explicit confirmation succeeds and replays, then actual invoice issuance uses the separate billing recipient and original total. Anna/finance/anonymous cannot read the historical context; ordinary form windows exclude the past selection. Existing invoice fresh-login and finance-read-only checks also pass. Python Mypy (113 files), Ruff, 213 unit tests and all frontend type checks pass.

Remaining: the overall plan is still incomplete. Additional ordering recovery/configuration cases, admin unsaved-tab and revision reconciliation, integrated In-App Browser acceptance and EmDash parity remain. Parallel EmDash read-only baseline `5dee14e` still has no public order renderer; no changes were made in that worktree.


## Explicit historical completion backend checkpoint — 2026-09-06

The user approved historical delivery completion explicitly. PLAN.md now records the exception: an action manager can confirm an existing draft/review-ready order's configured, already ended delivery window, including a retired window. New acquisition/public submissions retain future-only availability. No window is inferred or invented; existing booked snapshots remain unchanged.

Implemented the application-command confirmation, a separate historical domain selector, server-derived snapshot persistence and a privacy-safe audit confirmation. False/absent confirmation preserves the previous command fingerprint; true confirmation participates in idempotency. The exception is not exposed through the HTTP request or UI yet.

Live evidence: `tools/delivery/test-foundation.sh` exited 0 against disposable PostgreSQL. A real existing draft rejects an unconfirmed past selection, a missing/unknown ID and a not-yet-ended historical selection; explicit confirmation stores a configured retired window, preserves prices/lines/buyer, replays exactly once and creates one historical audit event. Omitting confirmation on replay conflicts. All existing migration, booking race, invoice guard and completion proofs also pass. Ruff and Mypy (114 files) pass; 213 unit tests pass. The test created its own internal Docker network and tmpfs database, used no host ports, and cleaned up its own resources.

Remaining for this decision: manager-only historical selection context, explicit admin form confirmation, generated HTTP contract, and authenticated HTTP/browser evidence. This backend checkpoint does not establish end-to-end historical completion or complete DEL-02/DEL-03.

## Completion context, focus and zoom checkpoint — 2026-09-06

Added authenticated `GET /api/v1/actions/{action_id}/delivery/order-form`, projecting the same Core delivery definition with private/no-store caching. It uses existing delivery read authorization and is independent of the new-order capture status gate. The completion UI now consumes this route, so a completed action does not prevent loading its effective delivery rules. New-order capture gates are unchanged.

The editor focuses its heading when opened, returns focus to the row trigger when closed/saved, and falls back to the page heading if the saved order leaves the active filter. The conflict comparison now includes the complete stored invoice address and email. The no-window message distinguishes completion from optional draft capture.

The full isolated invoice gate passed with the synthetic action actually transitioned to `completed` through the authorized API before the browser completion. The test verifies the new no-store projection, open/close/save focus, 200% root text sizing without document overflow, and the existing mobile completion, conflict/reconciliation, API persistence and actual invoice issuance proofs. All frontend type checks, Python Mypy and 212 unit tests pass. Project `leonaid-362a-delivery-invoice-20260906h` used ports 18266/18666 and the dedicated subnet override, with successful cleanup.

Evidence boundary: this proves completed action status with a still-future configured window. It does not solve missing delivery information after all delivery times have elapsed. A product clarification is pending on explicit administrative confirmation of a historical configured window; until resolved, elapsed-window validation remains unchanged. Other recovery/admin/EmDash and final integrated visual acceptance items remain open.

## Administrator completion form checkpoint — 2026-09-06

Draft and review-ready rows in the administrator order list now open an inline delivery/billing completion form. It reuses the shared delivery inputs and effective capture definition, supports address reuse or separate billing with independent invoice email, and hides draft deferral. Already booked window IDs/times remain fixed. Inputs are disabled during submission; known rejections and unknown outcomes retain the established command-key rules.

The editor freezes the version seen when opened. A conflict keeps local inputs, offers a read of current saved details, and requires an explicit comparison/acceptance step before using the newer version. Its pending form is not silently rebased by a background list refresh. Only one completion form is open in the list at a time.

The extended real `./leonaid test-invoices` gate passed: create a separate synthetic draft through the API, complete it in the administrator UI at 390 px with different delivery/billing addresses and multiline notes, check Axe for critical/serious findings, check document and element boundaries for horizontal overflow, perform a real competing HTTP completion while the form is open, prove rejection/input retention, compare the saved state explicitly, resubmit, and read the correct recipients/window and unchanged total back through the API. The existing invoice browser gate and repaired-order-to-issued-invoice HTTP proof also pass. The mobile screenshot was inspected. Feature type checking, focused Python lint/type checks and diff whitespace checks pass.

The live iterations exposed an incorrect test route, unconstrained mobile grid tracks and duplicate alert semantics; these were corrected before the successful final run (`leonaid-362a-delivery-invoice-20260906g`, ports 18266/18666, dedicated subnet override). Cleanup completed. The HTTP fixture now preserves the window booked by the UI scenario when adding its own window.

Remaining: the editor currently loads its effective definition through capture context, whose action-status gate needs reconciliation for completion on completed actions. Broader zero-window/policy-change/unknown-outcome recovery, focus after closing/saving, text zoom and integrated In-App Browser acceptance remain open. EmDash parity and the remaining plan items are not marked complete by this checkpoint.

## Delivery completion HTTP and invoice checkpoint — 2026-09-06

The completion service is now wired into FastAPI at `POST /api/v1/actions/{action_id}/commitments/{commitment_id}/delivery-completion`, with action-manager authorization, validated typed input, Idempotency-Key handling and no-store responses. Internal commitment responses expose `deliveryCompletionVersion` for optimistic edits. OpenAPI and the TypeScript client were regenerated from the source schemas.

The extended `./leonaid test-invoices` gate passed against real HTTP, Core PostgreSQL and Twenty. After the unchanged invoice browser journey, `tools/delivery/http_completion.py` enables scheduling for the synthetic action, proves incomplete delivery blocks issuance, denies anonymous/acquirer/finance completion requests, completes the existing draft with a different invoice recipient, proves version change and stale-edit rejection, and replays the exact completion. It then actually issues the invoice, compares its recipient with the supplied billing snapshot and its gross amount with the original order, rejects editing the now-invoiced order, and verifies exactly one invoice and one completion audit event in PostgreSQL.

All frontend type checks, Python source/live-proof Mypy, focused Ruff and 212 unit tests pass. The isolated test used project `leonaid-362a-delivery-invoice-20260906b`, ports 18266/18666 and the dedicated subnet override; cleanup completed successfully. This advances the previous guard-only evidence to an actual repaired-order-to-invoice journey.

The administrator completion form and its browser acceptance remain open; there is no claim yet that an operator can perform the entire repair through the UI. Remaining admin/form edge cases and integrated visual acceptance also remain open. The parallel EmDash branch was inspected read-only at `50598b9`; it has progressed into campaign binding/content authorization but still lacks the public order renderer required for campaign/alias parity.

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
