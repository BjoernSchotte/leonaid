# Surveys spike — provisional outcome

Date: 2026-09-08. Status: **implementation and acceptance remain in progress**.
Last reviewed source checkpoint: `5aedbe5` (route loading and complete feature flags/UI/UX regressions delivered).
The complete automated Survey CI at `5aedbe5` now also passes all 38 checks
twice. Overall spike acceptance remains open, including the Caddy correction
and the remaining recovery/delivery obligations.
The [complete local Journey repetition after route loading changed](proofs/SURV-100-UI-UX.md) passes with the strengthened rating helper.
The [104-task/capability review](TRACEABILITY.md#review-decision) accepts 100.A4
and closes task 100.2 against its existing complete-journey proof.
This report does not accept SURV-100.4 or the full spike. Own LeonAid/package
license and public package name remain **UNDEFINED**; publication is not enabled.

## Implemented behavior and evidence

| Area | Implemented scope | Evidence and current boundary |
| --- | --- | --- |
| Nontechnical authoring | Independent visual editor, page/question movement, keyboard alternatives, conditions, validation properties, templates, JSON roundtrip, undo/redo and draft autosave | [SURV-040](proofs/SURV-040.md); the [initial capability profile](PROFILE-CONTRACT.md) is intentionally bounded |
| Lifecycle and membership | Dedicated **Umfragen** module, standalone/action-linked surveys, draft/active/ended/archived/deleted states, publication versions, scoped roles and timeout configuration | [SURV-030](proofs/SURV-030.md), [SURV-060](proofs/SURV-060.md); published definitions and existing participations remain version-bound |
| Partial and completed responses | Server-loaded definitions, ordered snapshot saves, incomplete-response classification, resume, hidden-answer cleanup, validation and distinct completion | [SURV-010](proofs/SURV-010.md), [SURV-050](proofs/SURV-050.md); historical runner and full desktop/mobile journey proofs passed; both complete CI repetitions passed; the strengthened rating helper now passes the complete local repetition |
| Distribution | Public links and personal invitations through the existing worker/SMTP path; expiry, revocation and repeat redemption | [SURV-060](proofs/SURV-060.md); no newsletter system is required or implemented by this spike |
| Analysis | Version/status/date selections, immutable snapshots, distributions, numeric summaries, NPS, fixed-matrix rows and chart/table equivalents | [SURV-070](proofs/SURV-070.md); raw responses and aggregates have separate permissions |
| Exports | Raw-response CSV/XLSX and analysis XLSX/PDF, tied to the same selected snapshot; dedicated Typst reports and queued export jobs | [SURV-080](proofs/SURV-080.md); actual artifacts were parsed and rendered, with authorization and erasure checks |
| Package integration | Host-neutral React entrypoints and adapters; independently packed installation with its own backend, persistence/restart and browser checks | [SURV-020](proofs/SURV-020.md); the public package contract does not promise arbitrary SSR compatibility |
| Deletion and recovery | Retention/manual erasure, content-free deletion intent, export revocation and authenticated erasure checkpoint primitives | [SURV-090](proofs/SURV-090.md), [recovery contract](RECOVERY.md); independent source-host loss and the remaining compatibility cases are not accepted |

These are scoped evidence links, not an assertion that every historical test has
passed again at the revision above. The [task checklist](IMPLEMENTATION-TASKS.md)
and [scenario checklist](TEST-SCENARIOS.md) retain the individual acceptance rules.

## Package and deployment boundaries

The private `@leonaid/surveys` package is version `0.0.0`. It exposes separate
contracts, editor, runner, analysis, analytics and export-panel entrypoints with
their styles. Its direct renderer dependencies are `survey-core` and
`survey-react-ui` 3.0.3; React/React DOM are host peers. The current packed consumer
uses React/React DOM 19.2.8. The dependency gate excludes commercial Survey
Creator, Dashboard and PDF Generator, while preserving reviewed third-party and
font notices. See the [dependency disposition](DEPENDENCIES.md).

LeonAid owns identity, cookies, permissions, HTTP transport, PostgreSQL, workers,
object storage and report generation. A private SurveyJS-Core validator supplies
the same admitted answer semantics as the browser. Docker integration uses the
existing services and an internal validator service; it does not require a
SurveyJS-hosted backend. Browser rendering starts from an empty host shell and
restores data before save listeners are attached.

The package has source TypeScript/TSX exports and therefore currently expects a
compatible host bundler. It is not a standalone hosted survey service or an
already published, versioned public SDK. Existing manifest markers remain
`private: true` and `UNLICENSED` until the explicit own-license decision.

## Observed sizes and limits

The retained [independent export/package measurement](proofs/assets/SURV-080-independent-package.json)
records a 35,521-byte tarball, a 3,050,961-byte unminified respondent JS bundle and
a 532,692-byte export-client bundle for that fixture. The respondent source map
excludes editor, analysis, analytics and export UI code. These are historical
fixture/build observations, not current compressed transfer sizes, a production
bundle budget or a device-performance benchmark.

A fresh package-only build from `61b8a5c`, using pinned Bun 1.2.19 in a disposable
copy, produces a 38,684-byte tarball with exactly 21 expected regular files.
The source files and notices match the checkout byte-for-byte; the packed
manifest has the same complete JSON value. Its SHA-256 is
`d5c6fdd21fb09094c3d71598cb7b09ee01c3576564fb2d956f1099bb36da0af8`.
No font binaries, unexpected paths, links or checked private credential values
were found. This updates the tarball observation only; the bundle sizes above
were not remeasured, and final delivery review remains open.

The admitted definition profile permits at most 25 nonempty pages and 150
questions. An analysis selection is bounded to 5,000 responses and 32 MiB of
serialized source answers. The complete [profile limits](PROFILE-CONTRACT.md)
and [analysis behavior](proofs/SURV-070.md#immutable-analysis-snapshots) distinguish
definition/answer bounds from raw request limits. These caps do not prove latency
or throughput: representative load, synchronous survey-lock duration and target
device/network measurements remain necessary before production sizing.

## Outstanding acceptance

The task inventory has **96 accepted and 8 open tasks**. The open parent tasks
retain their full acceptance criteria; counts of passing child tasks do not
accept an incomplete parent.

- **Corrected Caddy integration (100.3i / 100.S2h):** the security job on
  `5aedbe5` still reports one critical finding, CVE-2026-56854 in
  `golang.org/x/crypto` 0.52.0, fixed in 0.55.0. The private candidate builds
  Caddy 2.11.4 with the corrected dependency. Both architecture image scans,
  bounded route checks, complete SBOM generation and the actual application
  security suite pass. The complete survey pilot also exits zero, including
  manifest-bound release, encrypted backup, all five invalid-checkpoint
  rejections, valid restore and 20 independent cleanup inventories. The
  baseline-only repetition also passes with all 20 cleanup inventories;
  the reviewed changes are now integrated and require the final branch CI. The rejected VEX proposal is not delivered or
  active; scanner policy is unchanged. The [candidate evidence](proofs/SURV-100-CADDY.md)
  separates actual image scans, synthetic upstream probes and real application
  tests, and records the completed pilots separately from pending branch acceptance.
- **Independent recovery (090.2 / 090.2b):** source-host loss with independently
  retained current erasure state and the required backup compatibility cases
  remain unproven. Removing an isolated Docker project on the same host does
  not establish host-loss recovery. A separate recovery host and independently
  retained backup/checkpoint source are still required. Backups predating
  installation identity migration 0034 are unsupported.
- **Aggregate and regression acceptance (100.1 / 100.3):** all 42 named legacy
  suites have delivered scoped evidence, but final cross-harness cleanup and
  affected integration checks on the final revision remain open. The three
  standalone harnesses now reject existing resource names and unreadable Docker
  inventories, and propagate cleanup failure while attempting remaining
  removals. Real volume-collision, busy-volume cleanup/retry and unavailable-
  daemon checks pass. All three complete service runs also pass, including
  four browser tests and twelve independent cleanup inventories
  ([evidence](proofs/SURV-100-STANDALONE-RESOURCES.md)). Their safety test is included in the revised aggregate manifest
  (39 checks per pass); the final revision therefore requires 78 successful
  executions over two passes. Historical successful runs do not accept
  subsequently changed inputs. A partial,
  cancelled or interrupted aggregate is not a pass.
- **Delivery (100.4 / 100.A5):** the final package/dependency/notices/artifact
  review and this outcome report must be reconciled with the final source
  revision. Own licensing and publication remain undecided.

## Accepted regression results

The [UI/UX delivery](proofs/SURV-100-UI-UX.md) accepts task 100.3m. The complete
feature-flag run passes persistence, restart, authorization and cleanup checks
in 718.487 seconds. Both UI browser tests pass in a complete 451.121-second run,
including screenshot and accessibility assertions. The reviewed desktop
reference includes the intended navigation and existing danger-color changes;
mobile reference and comparison tolerance remain unchanged. Theme-menu audits
wait for the actual transition boundary and cover both opened menus.

Lazy loading the survey route removes SurveyJS/editor code from the initial
admin entry source map. The production build has 727,523 bytes of initial
JavaScript and 161,847 bytes of CSS. The complete UX suite passes all four tests
in 641.881 seconds under its original mobile viewport, CPU/network settings and
budgets. Charity-Admin records LCP 1,204 ms, main-thread time 581 ms and 894,266
transferred bytes. These are fixture measurements, not general throughput or
production-device guarantees. The complete survey Journey repetition after
this change passes five browser tests, all persisted-data/export/erasure checks
and independent cleanup in 542.636 seconds.

The [dropdown repair](proofs/SURV-100-DROPDOWN.md) and
[rating-helper proof](proofs/SURV-100-RATING-JOURNEY.md) retain the original
pointer interaction and complete desktop/mobile journeys. The strengthened
helper asserts the actual selected value. Its controlled temporary-visibility
reproduction explains why the old helper could falsely report a selection; it
does not establish the root cause of historical CI failures.

The [three Restic modes](proofs/SURV-100-RESTIC-CLEANUP.md) pass in 1,782.298 s,
2,005.203 s and 1,869.274 s, with 21 independently empty resource inventories.
An actual in-use archive volume makes cleanup fail; removal succeeds after its
release. The durable mode additionally proves retained deletion intent through
archive outages, exact retries and source-project removal. This closes the
scoped cleanup defect while independent host-loss recovery stays open.

The full set of 42 legacy suites includes
[operations/dashboard/security](proofs/SURV-100-OPERATIONS.md),
[seed](proofs/SURV-100-SEED.md), [backup](proofs/SURV-100-BACKUP.md),
[upgrade/rollback](proofs/SURV-100-UPGRADE.md) and
[privacy/testkit/Golden Journey](proofs/SURV-100-PRIVACY-TESTKIT-GOLDEN.md).
The upgrade run retains all failure paths and nine browser journeys. Golden
Journey passes nine browser tests and deterministic reset comparison in
1,379.483 seconds. Each proof records its own source and cleanup boundary;
these are not 42 reruns on the eventual final revision.

## CI and package evidence boundaries

The accepted [complete survey CI repetition](proofs/SURV-100-CI-REPEAT.md) at
`e030836` runs all 38 checks twice, with 76 zero exits. Its tested merge
`738c1d216f67dfeeccb2db0180fc426adf8d4dd1` has no file differences from that branch
revision. It accepts 100.A1 at that checkpoint. Subsequent changes and the
final cross-harness reconciliation remain separate obligations.

The [packed-consumer job at 61b8a5c](https://github.com/BjoernSchotte/leonaid/actions/runs/34211453017/job/102013534600)
passes both executions in 61.317 s and 22.016 s. Tested merge
`5b998b453ebcca68668feaf00125ed96bbe08bc8` has no file differences from the branch
revision. The harness packs and installs outside the workspace, checks the six
runtime packages and bundle boundaries, then exercises authoring and responses
across a real SQLite-backed process restart. Notice presence is checked there;
exact notice contents and the XLSX runtime require the separate dependency
review. This job does not accept full CI or final delivery.

At the inspected `5aedbe5` checkpoint, the
[Survey workflow](https://github.com/BjoernSchotte/leonaid/actions/runs/34241342112)
has completed all eight groups successfully. The eight structured reports match
the current test inventory: all 38 checks each pass twice, with 76 zero exits. Their tested merge
`cf3677d7d9f1d53fd5c072f57a2fd060fbcb5d9c` has no file differences from
`5aedbe5`. This proves the complete automated Survey matrix at that revision;
it does not accept the corrected Caddy candidate or independent host-loss
recovery. In the
[main workflow](https://github.com/BjoernSchotte/leonaid/actions/runs/34241342078),
the completed run has eleven successful jobs and one failed Security job;
artifact probe and pilot cold rehearsal are skipped. Separate API
contract and dependency-pins workflows pass. These are an observed status
snapshot, not final-revision acceptance or a detailed artifact review of every
new group. The earlier `99000e1` recovery failure only exposed
`image-build-failed` metadata; its underlying build error remains undetermined
and is not treated as proof of a deletion-behavior defect.

Follow the [test gate](TEST-GATE.md), individual task proofs and
[PR](https://github.com/BjoernSchotte/leonaid/pull/4) for accepted results.

## Work before production or publication

Complete the outstanding acceptance above, choose and prove the external
recovery deployment, measure representative workload/device behavior and define
operational retention and distribution settings. Resolve the package's public
name, release/versioning contract and own OSS license before publishing it.
The supported feature profile must remain explicit: uploads/signatures, repeated
groups, advanced matrices, rich expressions, multilingual questionnaires and
other [post-spike extensions](CAPABILITIES.md#2-post-spike-extensions) require
separate authoring, validation, persistence and reporting work.

The current evidence supports continued completion of this spike. It does not
support a production-ready or fully accepted declaration yet.
