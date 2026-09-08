# Surveys spike — outcome

Date: 2026-09-08. Status: **functional spike accepted in the agreed scope**.
All 101 in-scope tasks are accepted; three original full-recovery obligations
remain deferred before production. The agreed closeout uses the existing automated gates and the final Codex
in-app-browser walkthrough. Independent physical host-loss recovery and newest
deletion-cutoff provenance are explicitly deferred to deployment acceptance
before production use; they are not successful test results.

The [final browser walkthrough](proofs/SURV-095-IN-APP-BROWSER.md) exercised the
module, authoring, participants, invitations, analysis, downloads and lifecycle.
It found and verified a small publication-refresh correction in both analysis
host branches. The four complete existing E2E journeys pass with a regression
assertion for this correction. No feature or dependency was added for closeout.
Own license and public package name remain **UNDEFINED**; publication stays off.

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
| Deletion and recovery | Retention/manual erasure, content-free deletion intent, export revocation and authenticated erasure checkpoint primitives | [SURV-090](proofs/SURV-090.md), [recovery contract](RECOVERY.md); local cross-revision restore is proven; physical host-loss acceptance is deferred before production |

These are scoped evidence links; historical proofs retain their exact tested
revision. The [task checklist](IMPLEMENTATION-TASKS.md)
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
were not remeasured, and this is a scoped package-size observation.

The admitted definition profile permits at most 25 nonempty pages and 150
questions. An analysis selection is bounded to 5,000 responses and 32 MiB of
serialized source answers. The complete [profile limits](PROFILE-CONTRACT.md)
and [analysis behavior](proofs/SURV-070.md#immutable-analysis-snapshots) distinguish
definition/answer bounds from raw request limits. These caps do not prove latency
or throughput: representative load, synchronous survey-lock duration and target
device/network measurements remain necessary before production sizing.

## Acceptance and remaining work

The [closeout evidence](proofs/SURV-100-CLOSEOUT.md) binds the reviewed CI revision,
changed-source hashes, local regression and final artifact review. The
[task inventory](TRACEABILITY.md) distinguishes accepted spike work from the
three original recovery obligations deferred before production. The existing
[local cross-revision restore](proofs/SURV-090-CROSS-REVISION.md) remains evidence
for its exact two revisions and recovery-identity schema, not arbitrary backups.

The Caddy correction is integrated without a scanner exception. Both architecture
images, application security, release/restore binding and SBOM generation have
[recorded proof](proofs/SURV-100-CADDY.md); main CI at `913c2f7` passes Security,
Build, Integration, Contract, Golden Journey and all five existing E2E groups.
The [standalone cleanup checks](proofs/SURV-100-STANDALONE-RESOURCES.md) and complete
Restic cleanup proofs remain required parts of the aggregate evidence.

Before production, prove recovery on an independent target with an independently
retained, authenticated newest deletion cutoff. Define operational retention,
backup/checkpoint storage and actual mail distribution settings. Measure the
representative workload and target devices before making capacity promises.
Before publishing the package, choose its name, release contract and OSS license.

Uploads/signatures, repeated groups, advanced matrices, rich expressions and
multilingual questionnaires remain [post-spike extensions](CAPABILITIES.md#2-post-spike-extensions).
Do not add them to close this spike. Their authoring, validation, persistence and
reporting requirements need separate product decisions.

This outcome does not claim production readiness, arbitrary SurveyJS JSON
support, commercial-component licensing or package publication.
