# SURV-030 — Lifecycle and version evidence

Date: 2026-09-06. Status: partial; lifecycle UI and existing-baseline migration
acceptance remain open. Checked items: 030.2, 030.A2, 030.A3.

## Implementation

The real API now exposes a protected survey summary, revisioned lifecycle
commands (end, archive, unarchive, trash, restore) and idempotent duplication.
Survey lifecycle revision is separate from draft revision. Each lifecycle write
locks the same survey row as response saves/completion and publication. The
transaction that obtains the row first determines the close/submit ordering;
a write after closure cannot bypass it with an old revision or operation key.

Ending or trashing an active survey records the server cutoff and classifies
open participations as partial. A stored partial marker remains partial on read;
only a successfully accepted changed answer can resume it while access is open.
Completed responses remain completed. Trash timestamps are cleared on restore.
A published survey restores to ended; an unpublished survey restores to draft.
Neither archive restoration nor trash restoration opens public participation.

Duplication copies the latest immutable published questionnaire when present,
otherwise the draft. It creates a standalone draft owned by the requesting
member, with new identity, no publication, no participation/resume credentials,
no explicit grants and no action association. Existing questionnaire IDs remain
stable. Invitations are not implemented yet; duplication does not create them.
The generated OpenAPI and TypeScript client include the new routes.

## Live verification

`./leonaid test-surveys-lifecycle` rebuilt the current source in isolated Compose
project `leonaid-surveys-833458328-24940`, with fresh volumes, explicit unused
subnets and no published host ports. Migration, real API/PostgreSQL foundation,
existing response contracts and the lifecycle contract passed. The member/public
Chromium infrastructure test passed in 1.1 seconds; it is not lifecycle UI proof.

`tools/surveys/lifecycle.py` verifies through real HTTP and SQL:

- All 25 status/action combinations: permitted transitions succeed; forbidden
  transitions reject without changing the summary. Also covers the distinct
  unpublished trash → draft restoration edge.
- Two simultaneous draft saves at one revision yield exactly one success and
  one conflict. Publication contains the winning draft, not a lost/stale edit.
- Existing participations restore their original immutable version after v2;
  new participations bind v2. Two simultaneous publications at one revision
  yield one success and one conflict, with exactly three total versions.
- Concurrent end/complete produces either a completed response accepted before
  closure, or a rejected completion and partial response. Subsequent writes and
  public access fail. Repeating the end operation returns its original result.
- Ended drafts reject edits. Archive/trash/restore keeps access closed.
- Duplicate retries return the same new draft. SQL verifies the copied published
  definition and absence of participations, versions, grants and action linkage.
- Unauthenticated metadata access is rejected. The synthetic fixture rows are
  deleted by the contract's finally block.

Strict mypy passed for the adapter/transport, four domain tests passed, source
lint passed and the regenerated API client passed TypeScript checking.

## Remaining boundaries

030.A1 still requires the migration path over an existing baseline fixture;
this run proves fresh migration only. 030.A4 requires the member lifecycle UI
from SURV-060. Full persona/permission coverage, automatic scheduled closure,
retention/permanent deletion and invitations remain their respective later work.
No work package or entire spike completion is claimed by this evidence.
