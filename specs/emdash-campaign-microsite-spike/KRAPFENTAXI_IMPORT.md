# Krapfentaxi import operator contract

This is an isolated-spike operator, not production activation. It imports the
pinned original demo into a **draft** and never changes aliases, Core actions,
orders, CRM data or publication state. The existing public demo stays in place.

## Reproduce the live proof

```sh
./leonaid test-emdash-spike --case krapfentaxi-source
./leonaid test-emdash-spike --case krapfentaxi-migration
```

The migration proof creates a unique Docker project, uses private PostgreSQL and
RustFS volumes, publishes no host ports, and removes only its own resources.
It does not leave behind an editable demo deployment.

## Operator invocation

Inside an explicitly selected CMS operator container running the pinned Bun
image, the CLI contract is:

```sh
bun tools/emdash_spike/krapfentaxi-import-cli.mjs dry-run krapfentaxi-2026 /run/secrets/core-session
bun tools/emdash_spike/krapfentaxi-import-cli.mjs apply krapfentaxi-2026 /run/secrets/core-session
```

Do not run these against a default Compose project or infer a target from another
checkout. `infra/emdash-spike/import-runtime.test.yml` defines the proof operator.
Production operator wiring and activation remain separate plan gates.

Prerequisites:

- Exact current campaign schema and installed binding/media guards in the
  dedicated `emdash` database. The importer refuses schema drift; it does not
  install or upgrade editorial schema automatically.
- An existing Core action resolved from the requested Krapfentaxi archive slug.
  This initial operator supports the currently published demo, not inactive or
  archived action imports.
- An authorized Core user who has already entered EmDash through the shared
  login, so an enabled CMS identity mapping exists. The same Core subject must
  resume an interrupted import; a new valid session for that subject is allowed.
- A read-only mounted regular session file with mode `0600` or stricter,
  containing only the Core session token. Never put token bytes on the command
  line, in the source checkout, import journal, PR, or application logs.
- Only dedicated CMS PostgreSQL and scoped RustFS credentials. No Core database,
  Twenty, order-submission or object-store administrator credentials are needed.

## Results and retries

`dry-run` reports `create`, `resume` or `preserved` without CMS/database/storage
writes. It resolves and checks Core authority, so normal Core session-read
bookkeeping may still occur. `apply` returns `imported` or `preserved`.
Printed IDs and fingerprints are operator diagnostics, not public artifacts.

The private `leonaid_krapfentaxi_import` table records the original manifest,
fingerprint, initiating Core/CMS identities, reserved media IDs and final content
ID. Reservation and journal update commit together. Object upload uses the
existing durable media-attempt mechanism; confirmation verifies actual stored
bytes and dimensions. Final draft creation and journal completion commit together.

After an interrupted or uncertain call, retry with the same source, action and
Core subject. A completed import is preserved even if editors have since changed
or published the page. No automatic overwrite, adoption of unrelated existing
content, journal reset, or cross-campaign media deduplication is performed.
Conflicts and drift require operator review; do not delete the journal to bypass
them. Concurrent apply calls are rejected instead of racing to create records.

Include this journal and the corresponding CMS media/attempt tables and private
objects in the forthcoming CMS backup/restore contract. Never roll back the
whole Core database to undo an import: subsequently accepted orders must survive.

## Remaining acceptance gates

The live proof covers real Core authorization, actual original assets in private
RustFS, dry-run/CLI permissions, durable interruption checkpoints, concurrency,
real final-write database failure, ambiguous success, later-editor preservation,
and logout denial. The same isolated case then starts its own login frontend,
SMTP capture and worker, and proves actual assigned Charity Admin login and
native text/image editing in Chromium, Firefox and WebKit. Drafts remain private;
Publish exposes changes on the next ordinary anonymous canonical-page request
without restarting or rebuilding the CMS. A subsequent draft remains private.
Mobile/no-JavaScript and desktop/JavaScript rendering are checked in each engine.

Process-kill/restart recovery, backup/restore, final visual acceptance with the
original assets, themed-page accepted orders and alias cutover remain open in
`PLAN.md`. The canonical-page browser proof does not prove short-alias delivery
or successful order processing merely by finding the order form.

Original image provenance and rights notices are retained in the manifest. This
does not grant or claim production publication rights.
