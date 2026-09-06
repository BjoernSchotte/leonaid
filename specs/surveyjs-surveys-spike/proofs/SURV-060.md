# SURV-060 — Member module and scoped management

Baseline `c75b8c7` plus this commit's module, API/client and browser changes.
The initial increment delivered member navigation, lifecycle and timeout UI.
The personal invitation increment below adds live evidence for 060.A3;
complete capability coverage, credential scans and test-participation isolation remain open.

## Task ledger

| Task | Criteria | Delivery / named evidence | Remaining acceptance |
|---|---|---|---|
| 060.1 | A4, A5 | `apps/web/src/surveys.tsx`, generated client, scoped list/summary and action creation; `surveys-module.spec.mjs` | Delivered; complete persona coverage and new-versus-existing participation/test-data UI evidence remain open |
| 060.2 | A1, A4 | Existing policies now govern lists/counts, summary capabilities, action linking and hidden publish controls; `module.py seed` | Aggregate/export/invitation/deletion capability matrix is not complete |
| 060.3 | A2, A3 | Anonymous runner plus personal invitation API, member UI, worker/Mailpit delivery and PostgreSQL verification | A3 accepted below; A2 credential scans and full retry/failure coverage remain open |
| 060.4 | A5 | No completion claim | Preview/test participation isolation remains open |
| 060.T1 | A1, A2 | Real member list/count/search/pagination and action-scope negative scenarios | Full capability and invitation coverage remain open |
| 060.T2 | A3, A4, A5 | Admin lifecycle/settings, mobile designer and personal invitation browser scenarios | Full persona coverage, timeout snapshot effect and test-data exclusion remain open |

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
open. Delivery failure/cancellation status needs follow-up: a queued invitation
skipped because its survey closed can still appear queued, and its encrypted
mail body needs a defined cleanup path. No full production delivery-status,
retention, visual or accessibility acceptance is claimed by this increment.
