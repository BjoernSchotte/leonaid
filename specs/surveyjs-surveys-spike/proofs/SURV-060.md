# SURV-060 — Member module and scoped management

Baseline `c75b8c7` plus this commit's module, API/client and browser changes.
The initial increment delivered member navigation, lifecycle and timeout UI.
The personal invitation increment below adds live evidence for 060.A3;
preview isolation and timeout snapshot behavior are now accepted below. Complete
capability coverage remains open; invitation credentials and expired resume access are accepted in the final section.

## Task ledger

| Task | Criteria | Delivery / named evidence | Remaining acceptance |
|---|---|---|---|
| 060.1 | A4, A5 | `apps/web/src/surveys.tsx`, generated client, scoped list/summary and action creation; `surveys-module.spec.mjs` | Delivered; A5 accepted below; complete persona coverage remains open |
| 060.2 | A1, A4 | Existing policies now govern lists/counts, summary capabilities, action linking and hidden publish controls; `module.py seed` | Aggregate/export/invitation/deletion capability matrix is not complete |
| 060.3 | A2, A3 | Anonymous runner plus personal invitation API, member UI, worker/Mailpit delivery and PostgreSQL verification | A2/A3 accepted; final credential and expired-resume evidence below |
| 060.4 | A5 | Actual preview completion, backend timeout change, public participation and separate persisted analysis snapshots below | Accepted |
| 060.T1 | A1, A2 | Real member list/count/search/pagination and action-scope negative scenarios | Full capability and invitation coverage remain open |
| 060.T2 | A3, A4, A5 | Admin lifecycle/settings, mobile designer and personal invitation browser scenarios | A5 accepted below; full persona coverage remains open |

## Behavior and boundaries

Authenticated members receive an Umfragen navigation entry. This does not give
access to other backoffice areas or anyone else's survey. The existing default
redirect for purely operational members remains in place outside survey routes.
A unit test verifies their only web navigation entry is surveys.

GET `/api/v1/surveys` supports status, literal title search and offset pagination
(50 results per page). Authorization is applied in SQL before count/pagination;
returned rows are also checked against the domain capability function. A
repeatable-read transaction keeps the count and page consistent. The response
includes only actions the member can manage as creation choices. GET summary
returns current capabilities and rejects inaccessible resources. The host uses
GET/list capabilities for controls and refreshes summary after mutations.

Creating a standalone survey assigns its creator as owner. Creating an
action-linked survey checks actual action management rights and action existence
before writing. Explicit survey grants do not bypass membership scope on an
action-linked survey. A design-only member can open the editor, but its publish
control is absent and the server independently rejects publication.

The neutral editor's optional `canPublish` flag controls presentation only; it
defaults to true for existing hosts. Optional `onSaveStateChange` reports its
save state. LeonAid uses that signal to disable lifecycle/settings actions while
the draft has unacknowledged changes. Backend authorization remains mandatory.

The member UI provides search/status filters, creation/action selection,
publication through the editor, end/archive/unarchive/trash/restore controls,
survey timeout override/inheritance and administrator-only global timeout forms.
Trash uses an inline consequence/confirmation step. Closed surveys do not mount
an editable draft, and restoration explicitly remains closed.

## Integration and browser evidence

`./leonaid test-surveys-lifecycle` succeeded as
`leonaid-surveys-833458328-88804`, exit **0**. The real stack passed its database
foundation, response contract and existing 25 lifecycle/action pair checks,
including publication/closing races, immutable versions and duplication.

`tools/surveys/module.py seed` created a real member, session, action and three
synthetic surveys. It proved:

- A standalone design grant exposes exactly one survey and only the design
  capability; private title search returns zero authorized results.
- A grant on an action-linked survey initially exposes nothing without action
  membership. After adding actual membership, the list contains exactly the two
  authorized surveys, while action-creation options remain empty for an acquirer.
- Counts remain authorization-filtered across offsets/status filters; negative
  offsets fail validation. A forbidden action-linked creation writes nothing.
- Global settings, foreign summaries, publication and trash are rejected for
  the unauthorized member through actual API calls.

Three Chromium scenarios passed through the real services: the infrastructure
journey plus these two tests in `tests/e2e/surveys-module.spec.mjs`:

1. `member manages lifecycle and timeout through the real module` (1440 × 1000)
   navigates from the main sidebar, changes/restores the global timeout, creates
   an action-linked survey, saves its override as three seconds, publishes, ends,
   archives, trashes and restores it. Reload retains ended status and no editor;
   the public API rejects access and the public page has no start control.
   Search/status filtering then finds the correct ended survey.
2. `designer sees scoped surveys without publish or delete controls on mobile`
   (390 × 844) sees only the two granted surveys, no global settings and no
   publish/trash controls. A direct publication request is rejected, and direct
   navigation to a foreign survey renders an error without an editor.

`module.py verify` then inspected PostgreSQL: the browser-created survey was
ended, retained the selected action ID and three-second override, and the global
default was restored to 1800. The successful harness verified cleanup of its
own containers/volumes/networks; seven unused explicit subnets and no host ports
kept it separate from other worktrees.

The first run (`…-88260`) passed backend checks and the mobile designer journey
but failed selecting the action with an exact label locator. Its trace confirmed
the intended UUID and the rendered combobox. Selecting by accessible combobox
role/name fixed the test; the repeated full run passed. The failed run is not
acceptance evidence.

## Visual review

Inspected the actual synthetic desktop lifecycle and mobile designer captures.
The lifecycle status/actions and closed-state explanation were readable; the
mobile controls wrapped without clipping in the captured state. This is not a
claim of every mobile/dark-mode/editor state or full accessibility acceptance.

![Closed lifecycle state](assets/SURV-060-lifecycle.png)
![Design-only mobile view](assets/SURV-060-designer-mobile.png)

## Supporting checks

Web TypeScript and Mypy on the four changed application source files passed.
Ruff passed on changed Python source and fixture files. The identity, policy and
migration unit selection passed 32 tests; the OpenAPI policy suite passed four.
The generated OpenAPI/client includes the previously delivered timeout APIs.

The frontend transport check initially rejected the independent demo's own
backend fetch. The corrected check exempts only its two fixed local routes in
the exact demo client file; negative fixtures still reject LeonAid API calls,
other routes and the same direct fetch from a regular web client. The independent
demo must not acquire a LeonAid-client dependency merely to satisfy this check.

`./leonaid test-surveys-package`, project `surveys-package-833458328-88872`, exited
zero: actual packed installation, permissive bundle/notice inspection and both
browser phases passed (2.9s and 893ms) with real restart and cleanup. The new
optional editor props do not enter the respondent bundle.

`./leonaid test-surveys-editor`, project `leonaid-surveys-833458328-89326`, exited
zero: all seven Chromium scenarios passed in 1.2 minutes, including both complete
sample authoring journeys, keyboard/accessibility checks, JSON import and
interrupted-save/two-tab draft recovery. Its isolated resources were removed.
The complete SURV-060 work package remains open.

## Personal invitations

Verified on 2026-09-07 against baseline `c19278d` plus this commit's invitation
implementation. **060.A3 and 060.S3 are accepted.** Task 060.3 remains open
because its additional 060.A2 / 060.S2 checks are not complete.

### Delivered behavior

The draft's access mode can be anonymous or personal invitation. Publication
fixes that choice. A member with `manage_invitations` can create, paginate and
revoke personal invitations through the member UI and generated API client.
Creation validates the recipient and a 1–90 day lifetime, checks the survey
revision and atomically writes one invitation, one outbox event and a durable
operation result. The browser retains the exact operation after an uncertain
response so retry cannot create a second logical invitation.

Migration `0029_survey_invitations` stores the recipient separately from response
answers. Only a SHA-256 token digest is stored as the credential; the queued mail
body is encrypted with the existing mail-payload adapter. The outbox event has
an empty payload. The worker checks current survey status, deadline, revocation
and expiry before SMTP delivery, uses the existing delivery ledger and stable
Message-ID, and clears the encrypted body after confirmed delivery.

The mail's personal URL carries its credential in the fragment. The public UI
explains that answers are attributable before the recipient starts. Redemption
creates or restores the one participation attached to that invitation, sets its
Secure/HttpOnly/SameSite=Lax resume cookie and removes the fragment. The server
checks invitation revocation and expiry on redemption, restoration, saves and
completion. Revoking an invitation therefore also removes resume access.

### Integration and E2E acceptance

`./leonaid test-surveys-invitations` passed as
`leonaid-surveys-833458328-5320`, exit **0**. The test harness used real API,
PostgreSQL, outbox worker, SMTP/Mailpit, member UI and public UI, with no host
ports. Its isolated containers, networks and volumes were removed successfully.

`tools/surveys/invitations.py prepare` runs while the real worker is stopped:

- Creates four synthetic invitation-only surveys and checks idempotent access
  selection, immutable access mode after publication and anonymous-start denial.
- Checks authentication, malformed recipient/expiry rejection, exact creation
  replay and changed-payload rejection without a second invitation.
- Confirms listings expose neither token nor mail payload nor participation ID;
  inspects digest/encrypted payload separation and the empty outbox payload.
- Revokes one invitation, expires another and closes a third survey before
  restarting the worker.

The `recover` phase waits for actual outbox processing and verifies Mailpit
received only the valid fixture invitation. Invalid redemption is denied.
Repeated valid redemption returns the same participation. Saving a real answer
and then revoking access makes restoration, subsequent writes and redemption
fail; PostgreSQL retains the one separately attributable participation.

Two Chromium tests passed in **3.9 seconds**, including the infrastructure test
and `tests/e2e/surveys-invitations.spec.mjs`:

1. The administrator creates and publishes an invitation-only questionnaire
   through the real member UI at 1440 × 1000, then submits a personal invitation.
2. After the server commits, the test first loses the response, then substitutes
   a synthetic 500 response for a successful retry. A third attempt succeeds.
   All three request bodies are identical; only one invitation and one Mailpit
   message exist.
3. A recipient at 390 × 844 opens the actual message's link (only its origin is
   mapped to the isolated proxy), sees the attribution notice, starts, saves an
   answer and completes. The URL fragment is removed and the secure resume
   cookie exists. Recorded request URLs contain no invitation credential.
4. The administrator revokes the invitation. Reloading the recipient's resume
   URL and opening the original invitation both fail to grant access.

`invitations.py verify` independently checks PostgreSQL: exactly one completed
participation contains the submitted answer, its invitation retains the intended
synthetic recipient and `revoked_at` is set. Ephemeral credential-bearing fixture
state is removed; committed proof contains no credentials.

### Migration and regression checks

`./leonaid test-surveys-migrations` passed as
`surveys-migrations-833458328-4549`, exit **0**. Both an empty database and upgrade
from revision 0026 reach 0029. All 46 existing table fingerprints remain unchanged
in the upgrade path. Fourteen database invariants pass, including the new
same-survey invitation/participation foreign key and matching redemption state:
[empty database](assets/SURV-060-migrations-empty.json),
[upgrade](assets/SURV-060-migrations-upgrade.json),
[baseline](assets/SURV-060-migrations-baseline.json).

`./leonaid test-surveys-runner` passed as
`leonaid-surveys-833458328-5855`, exit **0**, including the existing anonymous
runner and recovery checks, with successful isolated-resource teardown.
`./leonaid test-surveys-lifecycle` also passed as
`leonaid-surveys-833458328-6899`, exit **0**, covering the existing lifecycle,
scheduled closure and member-module journey, with successful cleanup.
Final web TypeScript, changed-file Ruff and `tools/openapi/check_frontend.py`
checks passed. The generated OpenAPI/client includes the access and invitation
routes. Changed application-source Mypy and runtime imports also passed.

### Failed attempts and remaining boundaries

The first invitation run (`…-4102`) failed because the new SMTP handler evaluated
an asyncpg generic annotation at import time. Postponed annotations fixed the
runtime import. The second (`…-4748`) passed the backend checks but its browser
test failed locating the access-mode select. Selecting the actual accessible
combobox by role/name fixed the locator. Both failed runs cleaned up; only the
complete repeated run supplies acceptance evidence.

This proves one logical invitation under the tested request retries. SMTP cannot
guarantee physical exactly-once delivery across a crash after remote acceptance
and before the local delivery ledger is committed. That crash window has not
been fault-injected here.

060.A2 / 060.S2 remain open for complete retry/failure coverage and seeded
credential scans of application logs and exports. Export implementation is still
pending. Full persona/capability coverage and preview/test isolation also remain
open. At this increment, delivery failure/cancellation status still needed
follow-up; the subsequent delivery-state increment below resolves the queued
display and skipped-payload cleanup. No full production retention, visual or
accessibility acceptance is claimed.

## Invitation delivery states and SMTP recovery

Baseline `e01d4d1` plus this increment, verified on 2026-09-07. The list API now
derives `retrying` and `failed` from the existing outbox state, without exposing
error details or mail content. A skipped unsent message whose encrypted payload
has been cleared is `cancelled`. Revocation, expiry, redemption and confirmed
delivery retain their existing precedence. The member UI names these states in
German and provides an explicit status-refresh action. An exhausted automatic
retry directs the member to administration; this increment does not add a second
retry mechanism outside the existing outbox administration.

Before skipping an expired/revoked invitation or a closed/deadline-expired survey,
the worker removes its encrypted mail body in the same locked transaction.
Transient delivery failure rolls that transaction back so a subsequent attempt
can still deliver. A dead-letter message retains the protected body for existing
administrative retry; revocation clears it. Global expiry/retention cleanup for
dead-letter messages remains a SURV-090 obligation.

The live fixture now creates five invitations with the actual worker stopped.
It seeds one event at four prior attempts to exercise the final configured
attempt without waiting through the earlier backoff intervals. The harness then
stops the actual SMTP/Mailpit service and starts the worker. The failure phase
requires these real API list states:

| Fixture | Expected status | Persisted outcome |
|---|---|---|
| Valid, temporary SMTP failure | `retrying` | One invitation/event, protected mail retained for automatic retry |
| Final attempt, SMTP failure | `failed` | Actual dead-letter transition after the worker's failed send |
| Survey closed before processing | `cancelled` | No SMTP delivery; protected body cleared |
| Invitation expired | `expired` | No SMTP delivery; protected body cleared |
| Invitation revoked | `revoked` | No SMTP delivery; protected body cleared |

After SMTP restarts, only the temporary-failure fixture is delivered. The
dead-letter fixture remains failed and absent from Mailpit; revoking it clears
its protected body and prevents redemption. The original exact-redemption,
saved-answer, revoke and database-association checks still pass. The browser
journey also explicitly refreshes the delivery status and sees `Versendet` before
opening the delivered questionnaire.

The first expanded run, `leonaid-surveys-833458328-7947`, passed the real outage,
recovery, two Chromium tests (4.0s), SQL verification and isolated cleanup, exit
zero. A parallel TypeScript check found a missing success-message argument on
the refresh action. It was corrected after that run ended; final TypeScript and
Mypy on the three changed application files then passed. Ruff passed the changed
Python files.

The final-source command `./leonaid test-surveys-invitations` passed as
`leonaid-surveys-833458328-8538`, exit **0**: actual SMTP outage/recovery, all five
delivery-state fixtures, two Chromium tests (4.0s), database verification and
successful isolated teardown. Seven unused explicit subnets and no host ports
kept the run separate from parallel worktrees. This repeated run includes the
corrected status-refresh success message.

This adds concrete coverage to 060.S2, but does not close 060.A2 / 060.S2: seeded
credential scans in exports and captured application logs are still missing.
The SMTP acknowledgement/local-ledger crash window described above is unchanged.


## Preview isolation and timeout snapshot acceptance

Production source: `a5ed129`, unchanged for this increment. New test paths:
`tests/e2e/surveys-preview.spec.mjs` and `tools/surveys/preview_live.py`, wired
through the isolated harness's `preview` mode.

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" preview
```

Final project `leonaid-surveys-833458328-21306` completed with exit **0**. Both
Chromium tests passed in 5.5 s, followed by independent PostgreSQL verification.
The named scenario `backend timeout changes preserve existing participation and
preview stays outside real analysis` runs at 1440 × 1000 against actual services.

1. The seed creates and publishes a real single-question survey through the API,
   with a 60-second override. It inserts exactly one completed synthetic response
   with `is_test=true` directly into PostgreSQL, explicitly as test setup.
2. The browser opens the actual editor preview, enters a unique preview marker,
   completes it and returns to editing. No public participation POST/PUT is sent.
3. It starts and saves an ordinary response through the public API, obtaining a
   60-second participation timeout. Through the real backend UI it changes the
   survey override to one second, then starts and saves another ordinary response.
4. The new participation becomes partial under its one-second snapshot. Restoring
   the first participation still reports 60 seconds, in-progress status and its
   exact answer. The test then completes that older participation normally.
5. After reload, it opens **Antworten auswerten** and submits the default real-data
   analysis through the UI: its actual returned snapshot contains exactly two
   participations. Selecting **Nur Testteilnahmen** and submitting again yields
   exactly one participation and `isTest=true`.
6. The SQL verifier waits, with a bounded deadline, for the real worker's durable
   partial mark. It confirms exactly three stored participation rows, two real
   timeout snapshots (60 and 1), completed/partial statuses, no preview marker,
   and two stored analysis snapshots with the expected distinct sources/counts.

The preview intentionally remains an in-browser simulation; it does not persist
an author test participation. The separate seeded `is_test` row proves the existing
analysis exclusion boundary and is not described as a browser-created test response.
This acceptance does not introduce or claim a persisted test-response authoring UI.

The initial run `...20657` reached the analysis step but failed because the test
had not expanded the collapsed analysis panel. The corrected final run performs
that actual UI navigation. No production validation, timing or access rule was
relaxed. Raw failure artifacts remain ignored locally; the retained result is
[SURV-060-preview-timeout.json](assets/SURV-060-preview-timeout.json), containing
only counts, configured synthetic intervals and boolean assertions.

The final run used fresh volumes and currently unused explicit subnets, published
no host ports and verified owned-resource teardown. Probe Ruff, browser formatting,
shell syntax and `git diff --check` passed. No new visual/a11y review is claimed.

060.A5, its 060.S5 scenario and implementation task 060.4 are accepted. The parent
060.T2 remains open for full persona/resource E2E coverage (A4); the whole module
also retains its A1/A2 permission and credential-log acceptance work.


## Invitation credential and expired-resume acceptance

**060.3 / 060.A2 / 060.S2 are accepted.** Production baseline: `7b86291`,
unchanged. This increment extends actual-service test coverage without changing
runtime dependencies, migrations or the UNDEFINED license decision. The full
persona matrix (060.A1/A4) still prevents completion of 060.T1/T2 and SURV-060.
Earlier open-status statements describe their historical increments.

```sh
rtk proxy sh tools/surveys/infrastructure.sh "$PWD" invitations
```

Project `leonaid-surveys-833458328-37251` exited **0**. The existing API creation,
exact replay and changed-payload conflict checks passed. The worker processed
six synthetic invitations with actual Mailpit stopped: two retryable deliveries,
one seeded final-attempt failure and revoked/expired/closed cancellation cases.
After Mailpit restarted, exactly the two eligible fixture recipients received
messages; the dead-letter case remained undelivered until revoked. Protected
payload removal checks passed for skipped/revoked and delivered messages.

The added `expired-resume` case redeems the real invitation twice, verifies the
same participation, and saves an answer through HTTP before moving only its
synthetic expiry timestamp into the past. GET restore, PUT save, POST complete
and POST redemption then return 404. The same four operations are rejected after
actual revocation in the existing valid case. SQL verifies one participation and
its separate invitation association. This tests expiry selection deterministically;
it does not claim a month-long wall-clock wait. Existing SMTP acknowledgement
ambiguity does not become an exactly-once physical delivery guarantee.

Both Chromium scenarios passed in **4.9 s**: the foundation test and
`surveys-invitations.spec.mjs` at the existing desktop member/mobile respondent
viewports. The member creates and publishes an invitation-only survey, retries
lost/synthetic error acknowledgements with the same operation, receives one
Mailpit message, and revokes access after the recipient completes. PostgreSQL
independently verifies exactly one completed, attributable response. Direct URL
capture still proves the fragment credential does not enter request URLs.

`tools/surveys/invitation_privacy_live.py` then creates real immutable analysis
snapshots for the API-created and browser-created participations, explicitly
including all three statuses and asserting one response per snapshot. The actual
worker generates eight private objects: CSV, raw XLSX, analysis XLSX and Typst PDF
for each participation. Authenticated downloads are parsed using csv, every
uncompressed XLSX ZIP member (including metadata), and pypdf text extraction.
Raw bytes and parsed content contain none of the admin session, browser invitation
credential or six backend fixture credentials. Each expected answer remains in
its raw products and is absent from the aggregate products; these are populated
exports, not an empty-selection proof.

The harness captures actual API, worker and validator logs after both browser and
export execution. It requires actual HTTP diagnostic records and scans for all
the credential values plus the two answer markers. No marker is present. SMTP
message bodies intentionally contain their invitation links and are not treated
as application diagnostics. All credential-bearing state and unrestricted logs
stay in the temporary proof directory and are deleted with it; they are never
copied into committed artifacts. The retained
[SURV-060-invitation-privacy.json](assets/SURV-060-invitation-privacy.json)
contains only product names, counts and boolean results.

Scoped Ruff checks/format, shell syntax and diff whitespace checks passed. The
run used fresh volumes, seven currently unused explicit subnets and no published
host ports. The harness verified complete owned-resource teardown. No runtime or
test file was edited during execution, and no new manual visual/a11y inspection
or exhaustive SMTP crash-instruction coverage is claimed.
