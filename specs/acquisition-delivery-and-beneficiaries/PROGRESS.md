# Implementation evidence

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
