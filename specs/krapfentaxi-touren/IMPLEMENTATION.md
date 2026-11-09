# Krapfentaxi Delivery Tours Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Managers plan per-driver delivery tours with a map in the web admin, and drivers work "Meine Tour" in the PWA (online first, offline in slice 4), behind the feature flag `delivery.tours`.

**Architecture:** A tour is a read model over `commitment_delivery` (driver × delivery day), with two nullable rank columns (base, driver) and no tour table. Ranks are ordered per window and normalised to dense ranks on read, so stops that leave a tour close up without writes. An opaque tour revision (a hash of membership and positions) makes order writes conflict-safe. New code lives in a `delivery_tours` module per layer (domain, application, postgres adapter), next to `delivery_board`. Coordinates live in `delivery_geo`. A worker loop fills it from a Nominatim-compatible geocoder. Leaflet renders the map in both apps from one shared component.

**Tech Stack:** Python 3 / FastAPI / asyncpg / Alembic, React 19 + TanStack Query, @dnd-kit (existing `TaskOrdering`), Leaflet 1.9.4, Vitest (jsdom component tests in `apps/web/src`, node tests in `apps/pwa/src`), Playwright E2E through Caddy with `csp-guard.mjs`.

**Spec:** [`specs/krapfentaxi-touren/PLAN.md`](PLAN.md). Executors read both. Spec sections are cited as §n, decisions as Dn.

## Global Constraints

- Feature flag key `delivery.tours`, off by default. The spec writes `delivery-tours`; the repo's flag keys use `<area>.<name>` (`pwa.offline_queue`), and the DB check constraint lists keys. Every new endpoint answers `404 feature_flag_disabled` while the flag is off (`FeatureFlagService.require_enabled`, surface `web` for managers and `pwa` for drivers).
- Tour = driver × delivery day (`action_delivery_window.delivery_on`), across all windows of that day (D1). There is no tour table.
- Ranks only order stops *inside* a window. Effective order = window start, then rank (§5). A write never moves a stop into another window.
- Base order belongs to the manager, driver order to the driver. Neither write touches the other (D2). A new stop goes to the end of both orders, and the driver UI marks it "neu".
- Writes replace the whole order of one tour in one command, with `expected_revision`. The same target order is a no-op before the revision check (same as `set_state`).
- Rights (§10, D9): charity admin and system admin (`may_manage_action`) plan. A driver (`ActionRole.DRIVER`) reads only their own tour and writes only its `driver_position`, plus today's state change.
- Coordinates, addresses, names and driver notes never go into audit payloads, outbox payloads, URLs, logs or telemetry (§10). Audit payloads carry ids and counts only.
- Geocoding runs on the server only. It sends only `street`, `postalcode`, `city`, `countrycodes` (§8.2), and only while `delivery.tours` is on.
- Nominatim limit: at most 1 request/s, with a User-Agent from `LEONAID_GEOCODER_USER_AGENT` (D8).
- CSP: only `img-src` gains the tile origin. `script-src 'self'` and `connect-src 'self'` stay. No CDN: Leaflet is bundled (D3, D7).
- Env (§5): `LEONAID_MAP_TILE_URL` (default `https://tile.openstreetmap.org/{z}/{x}/{y}.png`), `LEONAID_MAP_ATTRIBUTION` (default `© OpenStreetMap-Mitwirkende`), `LEONAID_GEOCODER_URL` (default `https://nominatim.openstreetmap.org/search`), `LEONAID_GEOCODER_USER_AGENT`. One added for Caddy: `LEONAID_MAP_TILE_ORIGIN` (default `https://tile.openstreetmap.org`).
- UI copy is German. The admin uses "Sie", the PWA uses "Du" (as in `delivery-board.tsx` `copy`). Touch targets are at least 44 px. Every reorder works by keyboard and by up/down buttons, not only by drag.
- Driver note: one line, at most 200 characters, label "Hinweis für den Fahrer (optional)" (§5.1).
- Migrations: next numbers are `0058_…`, `0059_…`, after `0057_pwa_offline_queue_flag`. Each needs `DATA_MIGRATION_REFERENCE`, `BACKUP_REFERENCE` and `SET LOCAL lock_timeout = '5s'` like 0057.
- OpenAPI: regenerate with `./leonaid generate-api-client`. Additive changes need no approval. If `tools/openapi/breaking.py` flags anything, add an entry to `specs/leonaid-poc/openapi-breaking-approvals.json` in the same task.
- Tests: no test doubles of I/O ports and no `page.route` (`tools/ci/no_test_doubles.py`). The geocoder test server and the tile endpoint are real HTTP servers.
- E2E: extend `tests/e2e/delivery-board.spec.mjs` (leaf `invoices`). Do not add a new leaf (CI KISS). The spec's leaf `delivery-tours` folds into it.
- Workflow: one worktree and branch per slice. Merge `main` into it; never rebase. When a task reports done, run `./leonaid test-env-stop`.

## Review Focus

1. **Old hashes stay valid when the driver note is absent.** `DeliveryContactSnapshot.payload()` feeds the public request hash, the commitment command hash and `delivery_completion_version`. An order or a replayed command without a note must hash byte-for-byte as before. Owned by Task 12 (`test_contact_payload_without_note_is_unchanged`, plus the existing `tools/delivery/legacy_replay.py`).
2. **Stops that leave or change a tour** (reassignment, cancellation, a window change by delivery completion) must not take stale positions into a new tour. A driver's queued or stale order write must then fail with a conflict and must not drop or reorder stops silently. Owned by Task 3 (`prove_tour_membership_changes`) and Task 14 (`tour-order conflict after an appended stop`).
3. **Saving the delivery configuration from the existing windows UI** sends no start point. That must keep the stored start point and must not erase it. Owned by Task 10 (`test_absent_start_point_keeps_stored_one`).
4. **No geocoding while the flag is off, for past days, or with personal data in logs.** Addresses must not reach the provider before the privacy notices are live, and must never reach audit, outbox or logs. Owned by Task 9 (`prove_geocoding_respects_flag_and_scope`).
5. **Leaflet under the strict CSP.** Leaflet must cause no `style-src-attr` or `img-src` violation, must not request the default marker PNGs, and must show the attribution. Owned by Task 11 (E2E under `csp-guard.mjs`, plus `tour-map` component test).

---

## File Structure

| File | Responsibility |
|---|---|
| `migrations/versions/0058_delivery_tours.py` | rank columns, `driver_ordered_at`, flag row |
| `migrations/versions/0059_delivery_geo.py` | `delivery_geo`, start point columns |
| `src/leonaid/domain/delivery_tours.py` | `TourStop`, ordering, revision, planned positions, tour read models |
| `src/leonaid/domain/delivery_geo.py` | `GeoPoint`, `GeocodeQuery`, `address_hash`, result acceptance |
| `src/leonaid/application/delivery_tours.py` | `DeliveryTourService`, repository protocol, flag and role checks |
| `src/leonaid/application/delivery_geo.py` | `GeocodingJob`, `Geocoder` and `DeliveryGeoRepository` protocols, manual pin |
| `src/leonaid/adapters/postgres/delivery_tours.py` | tour reads and order writes |
| `src/leonaid/adapters/postgres/delivery_geo.py` | pending selection, outcome writes, pins |
| `src/leonaid/adapters/nominatim.py` | throttled HTTP geocoder |
| `packages/features/src/delivery/tour-model.ts` | pure client helpers (reorder, sort helper, links, window hint) |
| `packages/features/src/delivery/tour-planner.tsx` (+ `tours.css`) | web "Touren" view |
| `packages/features/src/delivery/my-tour.tsx` | PWA "Meine Tour" |
| `packages/features/src/delivery/tour-map.tsx` | Leaflet wrapper shared by both views |
| `packages/features/src/offline/tour-cache.ts` | offline tour cache, minimisation, purge |
| `tools/delivery/tours.py`, `tools/delivery/geocoding.py` | real-PostgreSQL proofs, wired into `tools/delivery/foundation.py` |

Existing files touched are named per task.

---

# Slice 1: tours without a map (Stage 1a)

Demo after Task 8: with `delivery.tours` on, the dev instance shows "Touren" in `/admin/delivery` and "Meine Tour" in `/app/delivery`.

### Task 1: Migration 0058 and the `delivery.tours` flag

**Model:** cheap

**Files:**
- Create: `migrations/versions/0058_delivery_tours.py`
- Modify: `src/leonaid/domain/feature_flags.py` (enum + catalog), `src/leonaid/entrypoints/fastapi/schemas.py:240` (`FeatureFlagKeyValue`), `packages/features/src/feature-flags/openfeature-provider.tsx:18` (`FEATURE_FLAGS.deliveryTours` + `featureConfiguration`), `tools/feature_flags/contract.py`
- Test: `tests/unit/test_feature_flags.py`

**Interfaces:**
- Produces: `FeatureFlagKey.DELIVERY_TOURS = "delivery.tours"`, flag row id `95000000-0000-4000-8000-000000000004`. Columns `commitment_delivery.base_position integer NULL CHECK (base_position > 0)`, `driver_position integer NULL CHECK (driver_position > 0)`, `driver_ordered_at timestamptz NULL`, and `CHECK (driver_position IS NULL OR driver_user_id IS NOT NULL)`. Client: `FEATURE_FLAGS.deliveryTours`.

- [ ] **Step 1: Write the failing test** `test_delivery_tours_flag_ships_off_and_matches_transport_and_schema`, modelled on `test_offline_queue_flag_ships_off_and_matches_transport_and_schema`. It asserts the key is in the catalog with `default_enabled is False` and `client_safe is True`, in `FeatureFlagKeyValue`, and in the 0058 migration's `NEW_KEYS` and `INSERT`.
- [ ] **Step 2: Run** `./leonaid test-unit -k delivery_tours_flag`. Expected: FAIL (`DELIVERY_TOURS` missing).
- [ ] **Step 3: Implement** the migration (with downgrade: drop the columns, delete the flag row, restore the 0057 key check) and the catalog entry with this exact copy:
  - title `"Touren für Fahrer"`
  - description `"Planer ordnen die Lieferungen eines Liefertags pro Fahrer zu Touren, mit Karte. Fahrer sehen in der Akquise-App „Meine Tour“. Vor dem Einschalten müssen die Datenschutzhinweise für Mitglieder (Kartenkacheln) und für Kunden (Geokodierung der Lieferadresse) ergänzt sein (Rechtliche Angaben)."`
  - effect `"Lieferadressen gehen an den eingestellten Geocoder; Karten laden Kacheln vom eingestellten Kachel-Server."`
- [ ] **Step 4: Run** `./leonaid test-unit -k "feature_flag or migration"` and `./leonaid generate-api-client`. Expected: PASS, and the client diff only adds the literal.
- [ ] **Step 5: Commit** `feat(delivery): delivery.tours flag and tour rank columns (0058)`

### Task 2: Domain tour rules

**Model:** capable

**Files:**
- Create: `src/leonaid/domain/delivery_tours.py`
- Test: `tests/unit/test_delivery_tours.py`

**Interfaces:**
- Consumes: `DeliveryDrop`, `DeliveryBoardError`, `BoardDriver`, `board_day` from `domain/delivery_board.py`.
- Produces:
  - `TourStop(commitment_id: UUID, window_id: UUID, window_starts_at: datetime, window_closed: bool, base_position: int | None, driver_position: int | None, assigned_at: datetime)`, frozen.
  - `base_order(stops: Sequence[TourStop]) -> tuple[TourStop, ...]`
  - `driver_order(stops) -> tuple[TourStop, ...]`
  - `has_driver_order(stops) -> bool`, true when any `driver_position` is set.
  - `effective_order(stops) -> tuple[TourStop, ...]`, the driver order if `has_driver_order`, else the base order.
  - `new_for_driver(stop: TourStop, stops) -> bool`, which is `has_driver_order(stops) and stop.driver_position is None`.
  - `tour_revision(stops) -> str`, 16 hex chars of sha256 over the sorted `(commitment_id, base_position, driver_position)`.
  - `planned_positions(stops, ordered_ids: Sequence[UUID], *, driver: bool) -> dict[UUID, int]`
  - Read models (frozen dataclasses):
    - `TourStopView(drop: DeliveryDrop, base_rank: int, driver_rank: int | None, effective_rank: int, new_for_driver: bool)`
    - `TourWindow(window_id: UUID, starts_at: datetime, ends_at: datetime, closed: bool, stops: tuple[TourStopView, ...])`
    - `DriverTour(driver_user_id: UUID, driver_name: str, day: date, revision: str, driver_ordered_at: datetime | None, windows: tuple[TourWindow, ...])`
    - `DayTours(action_id: UUID, action_name: str, timezone: str, day: date | None, days: tuple[date, ...], unassigned: tuple[TourWindow, ...], tours: tuple[DriverTour, ...], drivers: tuple[BoardDriver, ...])`
    - `MyTour(action_id: UUID, action_name: str, timezone: str, days: tuple[date, ...], tour: DriverTour | None)`
  - Error codes: `tour_order_stale` (409, "Die Tour wurde inzwischen geändert."), `tour_revision_conflict` (409, same text), `delivery_window_closed` (409, existing text).

Ordering key inside a window: `(position is None, position, assigned_at, commitment_id)`. Windows are ordered by `window_starts_at`, then `window_id`. Ranks are dense `1..n` per window.

- [ ] **Step 1: Write the failing tests**
  - `test_unranked_stops_follow_ranked_ones_by_assignment_time`
  - `test_ranks_close_up_when_a_stop_leaves`: positions 1, 3, 4 give `base_rank` 1, 2, 3.
  - `test_windows_come_first_whatever_the_positions`: a stop in the 08–10 window with position 9 comes before a 10–12 stop with position 1.
  - `test_effective_order_uses_driver_order_only_when_set`
  - `test_new_stop_is_last_and_new_for_driver`
  - `test_planned_positions_rank_within_each_window`: ids interleaved across windows give per-window ranks from relative order.
  - `test_planned_positions_reject_missing_extra_or_duplicate_ids`: `tour_order_stale`.
  - `test_driver_may_not_reorder_a_closed_window`: `delivery_window_closed`. The manager may.
  - `test_revision_changes_with_membership_or_positions_only`
- [ ] **Step 2: Run** `./leonaid test-unit -k delivery_tours`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the functions and dataclasses listed under Interfaces.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(delivery): tour ordering rules`

### Task 3: Tour persistence and service

**Model:** capable

**Files:**
- Create: `src/leonaid/adapters/postgres/delivery_tours.py`, `src/leonaid/application/delivery_tours.py`, `tools/delivery/tours.py`
- Modify:
  - `src/leonaid/adapters/postgres/delivery_board.py:694-783` (`_assign_driver_once`: the `ON CONFLICT` update also sets `base_position`, `driver_position` and `driver_ordered_at` to NULL)
  - `src/leonaid/adapters/postgres/delivery.py:430` (a window change of an order resets the same three columns on its `commitment_delivery` row)
  - `src/leonaid/bootstrap/api.py:161` (wire `DeliveryTourService`)
  - `tools/delivery/foundation.py:273` (call `prove_tours`)
  - `tools/ci/select_suites.py:763` (`"delivery_tours": ("invoices",)` in `E2E_OWNERS`)
- Test: `tools/delivery/tours.py` (real PostgreSQL, run by `./leonaid test-delivery`)

**Interfaces:**
- Consumes: Task 2. `FeatureFlagService.require_enabled`. The read-audit insert pattern at `adapters/postgres/delivery_board.py:188-206` (move it into a module function `record_read_audit(connection, *, driver_user_id, action_id, window_ids, viewed_at, zone)` and reuse it).
- Produces:
  - `DeliveryTourRepository` protocol with:
    - `day_tours(*, action_id, day, viewed_at) -> DayTours`
    - `my_tour(*, action_id, driver_user_id, day, viewed_at) -> MyTour`
    - `save_order(*, action_id, driver_user_id, day, ordered_ids, expected_revision: str, driver: bool, actor_user_id, request_id, occurred_at) -> DriverTour`
    - `discard_driver_order(*, action_id, driver_user_id, day, actor_user_id, request_id, occurred_at) -> DriverTour`
  - `DeliveryTourService(repository, flags: FeatureFlagService)` with:
    - `day_tours(actor, action_id, *, day, viewed_at)`
    - `my_tour(actor, action_id, *, day, viewed_at)`
    - `save_base_order(actor, action_id, driver_user_id, *, day, ordered_ids, expected_revision, request_id, occurred_at)`
    - `discard_driver_order(actor, action_id, driver_user_id, *, day, request_id, occurred_at)`
    - `save_driver_order(actor, action_id, *, day, ordered_ids, expected_revision, request_id, occurred_at)`. An empty `ordered_ids` resets to the base order.
  - Audit events `delivery.tour_order_saved` (payload `{driverUserId, day, stopCount, kind: "base"|"driver"}`) and `delivery.driver_order_discarded`.

Tour membership is the same set as the board's drops (`DELIVERABLE_ORDER_STATUSES`, window of that `delivery_on`) with `driver_user_id = X`. A write locks the day's windows `FOR SHARE`, then the tour's `commitment_delivery` rows `FOR UPDATE` in id order (lock order as in `_assign_driver_once`). It then runs `planned_positions`, the no-op check, and the revision check, in that order. A driver write sets `driver_ordered_at = occurred_at`. `my_tour` picks the day with `board_day(days_with_own_stops, requested, today)` and writes the read audit for each window of the tour. The service raises `PermissionDenied` (403) for a non-manager on manager calls and for a non-driver on `my_*`, after the flag check.

- [ ] **Step 1: Write the failing proof** `prove_tours(pool, action_id, admin_id)` in `tools/delivery/tours.py` with these sections (each an `assert` or an `_expect(..., Conflict | PermissionDenied, code)` as in `tools/delivery/board.py`):
  - `flag off: day_tours and my_tour raise ResourceNotFound feature_flag_disabled`
  - `manager saves base order; repeat with stale revision but same order is a no-op`
  - `stale revision with a different order: tour_revision_conflict`
  - `driver saves own order; base ranks unchanged; driver_ordered_at set`
  - `driver order with another driver's commitment: tour_order_stale`
  - `prove_tour_membership_changes`: a newly assigned stop is last and `new_for_driver`. A reassigned stop's positions are NULL and it is gone from the old tour. A cancelled stop closes up the ranks. A window change via delivery completion resets the positions.
  - `foreign driver (driver role in another action) on my_tour: PermissionDenied delivery_board_forbidden`. This replaces the spec's policy-contract line (§12); the Golden dataset has no drivers.
  - `my_tour writes one read audit row per window and day`
  - `discard_driver_order clears driver positions; empty driver write does the same`
- [ ] **Step 2: Run** `./leonaid test-delivery`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** the adapter, the service and the two reset changes. Wire the service.
- [ ] **Step 4: Run** `./leonaid test-delivery` and `./leonaid test-unit`. Expected: PASS, including the existing `prove_board`.
- [ ] **Step 5: Commit** `feat(delivery): tour reads and order writes`

### Task 4: Tour HTTP API and client

**Model:** standard

**Files:**
- Modify: `src/leonaid/entrypoints/fastapi/schemas.py` (after `DeliveryDriverAssignmentResponse`, ~line 2709), `src/leonaid/entrypoints/fastapi/routes.py` (after `reopen_delivery_window`, ~line 5700), `packages/api-client/openapi.json`, `packages/api-client/src/generated.ts`
- Test: `tests/unit/test_openapi_policy.py` (existing policy covers the new operations), `tools/delivery/tours.py` (add an HTTP section through `httpx.ASGITransport` like `tools/delivery/http_configuration.py`)

**Interfaces:**
- Consumes: Task 3 service.
- Produces (schemas):
  - `DeliveryTourStopResponse{drop: DeliveryDropResponse, base_rank: int, driver_rank: int | None, effective_rank: int, new_for_driver: bool}`
  - `DeliveryTourWindowResponse{window_id, starts_at, ends_at, closed: bool, stops: list[DeliveryTourStopResponse]}`
  - `DeliveryTourResponse{driver_user_id, driver_name, day: date, revision: str, driver_ordered_at: datetime | None, windows: list[DeliveryTourWindowResponse]}`
  - `DeliveryDayToursResponse{action_id, action_name, timezone, day: date | None, days: list[date], unassigned: list[DeliveryTourWindowResponse], tours: list[DeliveryTourResponse], drivers: list[DeliveryBoardDriverResponse]}`
  - `MyTourResponse{action_id, action_name, timezone, days: list[date], tour: DeliveryTourResponse | None}`
  - `DeliveryTourOrderRequest{day: date, expected_revision: str = Field(min_length=1, max_length=64), commitment_ids: list[UUID] = Field(max_length=500)}`
- Produces (operations):

  | operation_id | method and path |
  |---|---|
  | `getDeliveryTours` | GET `/api/v1/actions/{action_id}/delivery-board/tours?day=` |
  | `saveDeliveryTourOrder` | PUT `/api/v1/actions/{action_id}/delivery-board/tours/{driver_user_id}/order` |
  | `discardDeliveryDriverOrder` | DELETE `/api/v1/actions/{action_id}/delivery-board/tours/{driver_user_id}/driver-order?day=` |
  | `getMyTour` | GET `/api/v1/actions/{action_id}/my-tour?day=` |
  | `saveMyTourOrder` | PUT `/api/v1/actions/{action_id}/my-tour/order` |

  Every response sets `Cache-Control: private, no-store`. Responses reuse `delivery_drop_response`.

- [ ] **Step 1: Write the failing HTTP section** `prove_tour_http`. It asserts that each of the five operations answers 200 for the right role, 403 for the wrong role, and 404 `feature_flag_disabled` with the flag off. It also asserts the `no-store` header.
- [ ] **Step 2: Run** `./leonaid test-delivery`. Expected: FAIL (404 on the route).
- [ ] **Step 3: Implement** the schemas, the routes and the response mappers `delivery_tour_response(tour: DriverTour)` and `day_tours_response(tours: DayTours)`. Then run `./leonaid generate-api-client`.
- [ ] **Step 4: Run** `./leonaid test-delivery`, `./leonaid test-unit -k openapi` and `./leonaid test-api-contract`. Expected: PASS, with no unapproved breaking change.
- [ ] **Step 5: Commit** `feat(api): delivery tour endpoints`

### Task 5: Client tour model helpers

**Model:** standard

**Files:**
- Create: `packages/features/src/delivery/tour-model.ts`
- Modify: `packages/features/src/index.ts` (exports)
- Test: `apps/web/src/tour-model.test.ts`

**Interfaces:**
- Produces:
  - `type TourPoint = { readonly id: string; readonly windowId: string; readonly lat: number | null; readonly lon: number | null }`
  - `moveStop(ids: readonly string[], id: string, direction: -1 | 1, windowOf: (id: string) => string): string[]`. A move at a window edge does nothing.
  - `placeStop(ids, id, targetId, side: "before" | "after", windowOf): string[]`. A target in another window does nothing. This is the adapter for `TaskOrdering.onMove`.
  - `nearestNextOrder(points: readonly TourPoint[], start: { lat: number; lon: number } | null): string[]`. Greedy nearest next per window, by haversine. The first window starts at `start`, or, without a start point, at the stop furthest from the centroid of all stops with coordinates. Each later window starts at the last stop of the previous one. Stops without coordinates keep their relative order at the end of their window.
  - `canSuggestOrder(points): boolean`. True when at least 2 stops in one window have coordinates.
  - `haversineKm(a, b): number`
  - `tourLengthKm(points, start): number`
  - `devicePlatform(userAgent: string): "android" | "ios" | "other"`
  - `navigationHref(stop: { lat: number | null; lon: number | null; address: string }, platform): string`, per §7.3:
    - android: `geo:<lat>,<lon>?q=<encoded address>`, or `geo:0,0?q=<address>` without coordinates
    - ios: `maps://?daddr=<lat>,<lon>`, or `maps://?daddr=<address>`
    - other: `https://www.openstreetmap.org/directions?to=<lat>,<lon>`, or the OSM search link `https://www.openstreetmap.org/search?query=<address>`
  - `callHref(deliveryPhone: string | null, orderPhone: string | null): string | null`. Returns `tel:` plus the first non-empty number with spaces, `/`, `(`, `)` and `.` removed.
  - `windowHint(startsAt: string, endsAt: string, now: Date): { kind: "upcoming" } | { kind: "running"; minutesLeft: number } | { kind: "ended" }`
  - `windowHintLabel(label: string, hint): string`. Running gives `"08–10 · noch 35 min"`. Ended gives the label only; the "Fenster vorbei" tone is set by the caller.

- [ ] **Step 1: Write failing tests** with exact values:
  - `moveStop(["a","b","c"],"b",-1,w)` is `["b","a","c"]`, and gives no change across a window edge.
  - `nearestNextOrder`: three collinear points with start at one end, in order. Without a start, it begins at the outlier.
  - `navigationHref` gives the three platform strings above for `{lat: 48.1, lon: 11.5, address: "Hauptstr. 1, 80331 München"}`.
  - `callHref(" ", "+49 (89) 123/45")` is `"tel:+498912345"`.
  - `windowHint` 25 min before the end is running with 25 minutes left.
- [ ] **Step 2: Run** `bun run --filter @leonaid/web test:components -- src/tour-model.test.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the helpers.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit** `feat(delivery): client tour helpers`

### Task 6: PWA "Meine Tour"

**Model:** capable

**Files:**
- Create: `packages/features/src/delivery/my-tour.tsx`, `packages/features/src/delivery/tours.css`
- Modify:
  - `packages/features/src/index.ts`
  - `apps/pwa/src/app.tsx:529` (route `delivery`: render `MyTourPage` when `useLeonAidBooleanFlag(FEATURE_FLAGS.deliveryTours)`, else `DeliveryBoardPage`)
  - `apps/pwa/src/navigation.ts` (with the flag on, label the item `delivery` "Meine Tour")
  - `apps/pwa/src/navigation.test.ts`
- Test: `apps/web/src/my-tour.test.tsx` (jsdom, same pattern as `delivery-board.test.tsx`)

**Interfaces:**
- Consumes: Task 4 client methods `getMyTour` and `saveMyTourOrder`, plus `setDeliveryState`. Task 5 helpers. `TaskOrdering` and `TaskOrderHandle` from `../tasks/task-ordering`.
- Produces: `MyTourPage(props: { client: LeonAidApiClient; actionId: string; actions?: readonly { actionId: string; actionName: string }[]; offline?: boolean })`. Slice 4 adds `cached?: MyTourResponse | null`. Test ids: `tour-next-stop`, `tour-stop`, `tour-done-group`, `tour-reorder`, `tour-reorder-done`, `tour-reset-order`, `tour-day`.

Behaviour (§7, §7.1, §7.3, §7.4):
- Header: window label ("Sa 05.12., 08–10 Uhr"), "3 von 9 zugestellt", and the "Karte" toggle (hidden until Task 11).
- Window groups with `windowHintLabel`. An ended window shows "Fenster vorbei" on its open stops (warning tone).
- The first open stop in effective order is the large card: recipient, full address, contact with a phone button (`callHref`), quantities ("12 Krapfen, 2 Kisten"), driver note slot (filled in Task 12), and the buttons "Navigation", "Zugestellt", "Nicht angetroffen".
- "Nicht angetroffen" has no server command today: `missed` comes only from window closure (`decide_state_change`). In slice 1 it is a local, per-device mark that moves the stop to the end of the open list, with no server write. The stop stays open, and the closure makes it missed. This is a spec gap; see the report.
- The other stops are compact rows. Done stops go into the collapsed group "Erledigt". A stop with `new_for_driver` shows the badge "neu".
- "Reihenfolge ändern" turns on edit mode: drag handles, up/down buttons, "Fertig" (`saveMyTourOrder` with the full effective order and `revision`), and "Zurück zur Planung" (`saveMyTourOrder` with `commitment_ids: []`).
- Undo toast "Rückgängig" for 10 s, which calls `setDeliveryState` with the opposite target and the drop's new revision.
- `gcTime: 0` and no polling (same as the PWA board).

- [ ] **Step 1: Write failing component tests:**
  - `shows the first open stop as the large card with navigation and tel links`
  - `delivered stop moves to Erledigt and the next stop becomes the card`
  - `undo within 10 s restores the stop`
  - `reorder by buttons then Fertig sends the full order with the revision`
  - `reorder by keyboard (space, arrow, space) moves within the window only`
  - `Zurück zur Planung sends an empty list`
  - `appended stop shows neu`
  - `ended window shows Fenster vorbei`
  - `conflict 409 shows "Die Tour wurde inzwischen geändert." and refetches`
- [ ] **Step 2: Run** `bun run --filter @leonaid/web test:components -- src/my-tour.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement** `MyTourPage` and the PWA wiring.
- [ ] **Step 4: Run** that test, `bun run --filter @leonaid/pwa test` and `bun run typecheck`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(pwa): Meine Tour for drivers`

### Task 7: Web "Touren" planner view

**Model:** capable

**Files:**
- Create: `packages/features/src/delivery/tour-planner.tsx`
- Modify:
  - `packages/features/src/delivery/delivery-board.tsx` (web only, flag on: view switch "Liste" / "Touren" kept in `?view=tours`, as `?day=` is kept today; render `TourPlanner` for `tours`)
  - `packages/features/src/delivery/tours.css`
- Test: `apps/web/src/delivery-tours.test.tsx`

**Interfaces:**
- Consumes: `getDeliveryTours`, `saveDeliveryTourOrder`, `discardDeliveryDriverOrder`, `assignDeliveryDriver`, Task 5 helpers, `TaskOrdering`.
- Produces: `TourPlanner(props: { client: LeonAidApiClient; actionId: string; day: string | null; onDayChange: (day: string) => void })`. Test ids: `tour-column` (with `data-driver`), `tour-unassigned`, `tour-save-order`, `tour-suggest-order`, `tour-driver-order-banner`, `tour-show-driver-order`, `tour-discard-driver-order`.

Behaviour (§6):
- Columns: "Nicht zugeordnet", then one per driver from `drivers` (including drivers without stops). Each column shows its count, first and last stop, and length (`tourLengthKm`, "–" without coordinates). Stops are grouped by window.
- Assign: multi-select plus "Fahrer zuordnen" uses the existing driver `OptionMenu` popover. Dragging onto another column also calls `assignDeliveryDriver`.
- Order: drag, keyboard and up/down buttons inside a window group. The local draft stays until "Reihenfolge speichern" sends `saveDeliveryTourOrder`. Leaving with an unsaved draft asks first (reuse `Modal`).
- With `driver_ordered_at`: banner "Fahrer hat eigene Reihenfolge (seit HH:MM)" with "anzeigen" (toggle the column to driver ranks, read-only) and "verwerfen" (`discardDeliveryDriverOrder`).
- "Vorschlag sortieren" is disabled while `!canSuggestOrder` (all of slice 1). The tooltip says "Für den Vorschlag fehlen Koordinaten."
- Polling `BOARD_POLL_MS` as the list does, paused while a draft is dirty.

- [ ] **Step 1: Write failing component tests:**
  - `columns per driver grouped by window with counts`
  - `assign selected stops to a driver calls assignDeliveryDriver`
  - `button reorder then save sends saveDeliveryTourOrder with revision and day`
  - `drag across windows is ignored`
  - `driver order banner shows time; verwerfen calls discard`
  - `Vorschlag sortieren disabled without coordinates`
  - `polling paused while draft dirty`
- [ ] **Step 2: Run** `bun run --filter @leonaid/web test:components -- src/delivery-tours.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement** the view and the view switch.
- [ ] **Step 4: Run** the test, the existing `src/delivery-board.test.tsx` and `bun run typecheck`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(web): Touren planner view`

### Task 8: E2E for slice 1

**Model:** standard

**Files:**
- Modify:
  - `tools/invoices/browser_setup.py` (set `feature_flag.enabled = true` for `delivery.tours`, revision + 1, before the board proof)
  - `tests/e2e/delivery-board.spec.mjs` (new test after the existing one)
- Test: same file

**Interfaces:**
- Consumes: test ids from Tasks 6 and 7. `KLARA_BOARD_SESSION`, `ANNA_DRIVER_SESSION`.

- [ ] **Step 1: Write the failing test** `"managers plan a tour; the driver reorders, delivers and sees a later stop as neu"`:
  - Klara opens `/admin/delivery?action=…&view=tours`, picks the seeded day (index 0), assigns two stops to Anna, moves the second up, and saves. She expects "Reihenfolge gespeichert."
  - Anna opens `/app/delivery?action=…`, sees heading "Meine Tour", and the large card shows Klara's first stop. She uses "Reihenfolge ändern", moves one stop down, presses "Fertig", ticks "Zugestellt", and sees the next card. She uses "Rückgängig" and ticks again.
  - Klara reloads, sees the banner "Fahrer hat eigene Reihenfolge", and assigns a third stop to Anna.
  - Anna reloads. The third stop is last and shows "neu".
  - `expectAccessible` on both pages, and fidelity screenshots `delivery-tours-{1440,390}-{light,dark}.png`.
- [ ] **Step 2: Run** `./leonaid test-e2e invoices`. Expected: FAIL before Tasks 6–7 are merged in the branch, PASS after.
- [ ] **Step 3: Fix** whatever the run shows. No new leaf and no `select_suites` change beyond Task 3.
- [ ] **Step 4: Run** `./leonaid test-e2e invoices`, then `./leonaid test-env-stop`. Expected: PASS.
- [ ] **Step 5: Commit** `test(e2e): delivery tours journey`

---

# Slice 2: map, geocoding, start point (Stage 1b)

Demo after Task 11: pins, start point and straight lines in both views. Geocoding runs against the public Nominatim on the dev instance.

### Task 9: `delivery_geo`, configuration and the geocoding job

**Model:** capable

**Files:**
- Create:
  - `migrations/versions/0059_delivery_geo.py`
  - `src/leonaid/domain/delivery_geo.py`
  - `src/leonaid/application/delivery_geo.py`
  - `src/leonaid/adapters/postgres/delivery_geo.py`
  - `src/leonaid/adapters/nominatim.py`
  - `tools/delivery/geocoding.py` (proof plus a real Nominatim-compatible HTTP server on `127.0.0.1:0`, built on `http.server.ThreadingHTTPServer`, with canned JSON per postal code, a 2 s delay for postal code `99999`, and a request log)
- Modify:
  - `src/leonaid/configuration.py` (`MapSettings` + `load_map_settings()`)
  - `src/leonaid/entrypoints/worker/platform.py` (a `geocoding` loop, interval `LEONAID_GEOCODING_INTERVAL_SECONDS`, default 60, with its health stall like the retention loop)
  - `src/leonaid/bootstrap/worker.py`
  - `src/leonaid/adapters/postgres/privacy.py:452-456` (erasure deletes `delivery_geo` rows; the access report reads lat/lon)
  - `src/leonaid/domain/privacy.py:157` (`PrivacyOrderDelivery.coordinates: GeoPoint | None = None`)
  - `tools/delivery/privacy.py` (assert the row is gone after erasure)
  - `infra/compose/compose.yml`, `infra/pilot/compose.yml`, `infra/pilot/production.env.example` (the five env vars for core and worker)
- Test: `tests/unit/test_delivery_geo.py`, `tests/unit/test_configuration.py`, `tools/delivery/geocoding.py`

**Interfaces:**
- Produces, schema:
  - `delivery_geo(commitment_id uuid PK, action_id uuid NOT NULL, FK (action_id, commitment_id) → commitment ON DELETE CASCADE, lat numeric(9,6), lon numeric(9,6), source text CHECK IN ('geocoder','manual'), outcome text CHECK IN ('found','not_found','failed'), address_hash text NOT NULL, geocoded_at timestamptz NOT NULL, geocoder text NOT NULL, attempts integer NOT NULL DEFAULT 1)`
  - Checks: `(outcome = 'found') = (lat IS NOT NULL AND lon IS NOT NULL)`, the lat/lon ranges, and `source = 'geocoder' OR outcome = 'found'`.
  - The same migration adds `action_delivery_configuration.start_label text CHECK (length <= 80)`, `start_address text CHECK (length <= 200)`, `start_lat numeric(9,6)`, `start_lon numeric(9,6)`, and `CHECK ((start_lat IS NULL) = (start_lon IS NULL))`.
- Produces, domain:
  - `GeoPoint(lat: Decimal, lon: Decimal)`: validated, quantised to 6 places.
  - `GeocodeQuery(street: str, postal_code: str, city: str, country_code: str)`
  - `address_hash(query: GeocodeQuery) -> str`: sha256 hex of the casefolded, whitespace-collapsed fields joined by `\x1f`.
  - `GeocodeOutcome = Found(point, importance) | NotFound | Failed(code)`
  - `accept(result_postcode: str | None, importance: float | None, query) -> bool`: the postcode must match exactly and `importance >= MIN_IMPORTANCE` (`MIN_IMPORTANCE = 0.05`, to be calibrated on the dev instance).
  - `retry_due(outcome, attempts, geocoded_at, now) -> bool`: `failed` with attempts < 3 and older than 1 h. `not_found` is never retried for the same hash.
- Produces, application:
  - `Geocoder` protocol `lookup(query) -> GeocodeOutcome`, plus `provider_id: str`.
  - `DeliveryGeoRepository` protocol with `pending(*, today, limit) -> list[PendingGeocode]`, `record(pending, outcome, *, geocoder, at) -> bool` (writes only while the stored address still has `pending.address_hash`), and `set_pin(*, action_id, commitment_id, point, at)`.
  - `GeocodingJob.run_once(*, now, limit=30) -> int`. It returns 0 without any request while `delivery.tours` is off. It holds `pg_try_advisory_lock(hashtext('leonaid.geocoding'))`.
- Produces, adapter: `NominatimGeocoder(url, user_agent, *, min_interval=1.0, timeout=10.0)`. It uses the structured query `street=&postalcode=&city=&countrycodes=&format=jsonv2&addressdetails=1&limit=1`, with an asyncio lock plus a monotonic gap for the throttle.
- Pending rule: deliverable orders with `delivery_recipient_snapshot`, window `delivery_on >= today`, in actions with delivery enabled. A stop is pending when it has no row, when its row's `address_hash` differs (a manual pin included), or when `retry_due`. This covers the spec's "on new address" and "nightly catch-up" with one loop; see the report.
- `MapSettings`: `tile_url`, `tile_origin`, `attribution`, `geocoder_url`, `geocoder_user_agent` (default `"LeonAid (" + LEONAID_PUBLIC_BASE_URL + ")"`). Validation:
  - `tile_url` is `https://…` or starts with `/`, and contains `{z}`, `{x}` and `{y}`.
  - An absolute `tile_url` has the origin `tile_origin`, else `ConfigurationError("LEONAID_MAP_TILE_ORIGIN:mismatch")`.

- [ ] **Step 1: Write failing unit tests:**
  - `test_address_hash_ignores_case_and_spacing_only`
  - `test_accept_requires_matching_postcode_and_importance`
  - `test_retry_due_only_for_failed_under_three_attempts`
  - `test_map_settings_defaults_and_origin_mismatch`
- [ ] **Step 2: Write the failing proof** `prove_geocoding(pool, action_id, admin_id)` with these sections:
  - `prove_geocoding_respects_flag_and_scope`: with the flag off, nothing is pending and the server sees 0 requests. Past-day orders are never queried. Server requests contain only the four query keys (no name or phone). No row in `audit_event` or `outbox_event` contains the street.
  - `found / not_found / timeout (failed) rows`
  - `throttle: 3 lookups take >= 2 s`
  - `changed address makes the row stale and re-geocodes; manual pin survives until the hash changes`
  - `two concurrent run_once calls: one gets the advisory lock`
  - `privacy erasure deletes delivery_geo`
- [ ] **Step 3: Run** `./leonaid test-unit -k "delivery_geo or configuration"` and `./leonaid test-delivery`. Expected: FAIL.
- [ ] **Step 4: Implement** everything listed under Interfaces and wire the worker loop.
- [ ] **Step 5: Run** the same commands. Expected: PASS.
- [ ] **Step 6: Commit** `feat(delivery): delivery_geo and throttled geocoding job`

### Task 10: Pins, start point and coordinates in the API

**Model:** standard

**Files:**
- Modify:
  - `src/leonaid/domain/delivery.py:138` (`DeliveryConfiguration.start: DeliveryStartPoint | None = None`)
  - `src/leonaid/adapters/postgres/delivery.py` (read and write the start columns)
  - `src/leonaid/application/delivery.py` (on save: when `start.address` changed and no point was given, call `Geocoder.lookup` once and store the point or none)
  - `src/leonaid/adapters/postgres/delivery_tours.py` (join `delivery_geo` where `outcome = 'found'` and the hash is current; add the start point)
  - `src/leonaid/domain/delivery_tours.py` (`TourStopView.point: GeoPoint | None`, `DayTours.start` and `MyTour.start: DeliveryStartPoint | None`)
  - `schemas.py` and `routes.py` (`DeliveryConfigurationRequest.start_point`, `DeliveryConfigurationResponse.start_point`, `DeliveryTourStopResponse.lat/lon`, `start_point` and `map: MapTilesResponse{tile_url, attribution}` on `DeliveryDayToursResponse` and `MyTourResponse`)
  - `packages/features/src/action-admin/delivery-section.tsx` (fields "Startpunkt" with label and address, plus the hint "Startpunkt nicht gefunden – Pin auf der Karte setzen")
  - the generated client
- Test: `tests/unit/test_delivery_domain.py`, `tools/delivery/geocoding.py`, `apps/web/src/manage-action.test.tsx`

**Interfaces:**
- Produces:
  - `DeliveryStartPoint(label: str, address: str, point: GeoPoint | None)` with label 1–80 and address 1–200, single line.
  - `DeliveryStartPointRequest{label, address, lat: float | None, lon: float | None}`.
  - Operation `setDeliveryPin`: PUT `/api/v1/actions/{action_id}/delivery-geo/{commitment_id}`, body `DeliveryPinRequest{lat: float (-90..90), lon: float (-180..180)}`, manager only, flag `web`, returns `DeliveryTourStopResponse`.
  - Tile settings reach the clients only in the two tour responses (`map`). There is no global runtime config endpoint; see the report.
  - `start_point` absent in the request keeps the stored value (`"start_point" not in body.model_fields_set`). An explicit `null` clears it.

- [ ] **Step 1: Write failing tests:**
  - `test_absent_start_point_keeps_stored_one`
  - `test_start_point_rejects_multiline_and_long_values`
  - proof `pin sets manual row and appears as lat/lon in my_tour and day_tours`
  - proof `pin on a foreign action's commitment: 404`
  - component `start point fields round-trip`
- [ ] **Step 2: Run** `./leonaid test-unit -k delivery_domain`, `./leonaid test-delivery` and `bun run --filter @leonaid/web test:components -- src/manage-action.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes and regenerate the client.
- [ ] **Step 4: Run** the same commands and `./leonaid test-api-contract`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(delivery): start point, manual pin, coordinates in tours`

### Task 11: Leaflet map, CSP and map views

**Model:** capable

**Files:**
- Create: `packages/features/src/delivery/tour-map.tsx`, `tools/proxy/caddyfiles_test.py`
- Modify:
  - `packages/features/package.json` (`"leaflet": "1.9.4"`, dev `"@types/leaflet"` pinned) and `bun.lock`
  - `tools/proxy/caddyfiles.py:404,417` (`img-src 'self' data: blob: {$LEONAID_MAP_TILE_ORIGIN:https://tile.openstreetmap.org}`; dev target only: `handle /e2e-tiles/*` with `header Content-Type image/svg+xml` and `respond` returning a 256×256 SVG)
  - the regenerated `infra/proxy/Caddyfile*` and `infra/pilot/Caddyfile*` (`python3 tools/proxy/caddyfiles.py`)
  - `infra/compose/compose.yml` and `infra/pilot/compose.yml` (proxy gets `LEONAID_MAP_TILE_ORIGIN`)
  - `tools/testing/shared-runtime.yml` (`LEONAID_MAP_TILE_URL=/e2e-tiles/{z}/{x}/{y}.svg`)
  - `my-tour.tsx` (the "Karte" toggle, a full-height map, a bottom sheet on pin tap, opt-in device location via `navigator.geolocation.watchPosition` that is never sent)
  - `tour-planner.tsx` (a map on the right; list and pin selection highlight each other; unassigned pins are grey; a draft line is dashed; "Pin setzen" for stops without coordinates calls `setDeliveryPin` on map click; "Vorschlag sortieren" is enabled through `canSuggestOrder`)
  - `tests/e2e/delivery-board.spec.mjs`
- Test: `apps/web/src/tour-map.test.tsx`, `tools/proxy/caddyfiles_test.py`, E2E

**Interfaces:**
- Consumes: `map`, `start_point` and `lat`/`lon` from Task 10. Task 5 `nearestNextOrder`.
- Produces: `TourMap(props: { tiles: { url: string; attribution: string }; start: { lat: number; lon: number; label: string } | null; pins: readonly { id: string; lat: number; lon: number; rank: number; tone: "driver-0" … "driver-7" | "unassigned" | "done"; selected: boolean }[]; line: { ids: readonly string[]; dashed: boolean } | null; onSelect: (id: string) => void; onPlace?: (lat: number, lon: number) => void; showLocation?: boolean })`.
  - Pins are `L.divIcon` with class names only: `tour-pin tour-pin--<tone>`, and the number as text. No `style` attributes, no `L.Icon.Default`.
  - Leaflet CSS is imported from `leaflet/dist/leaflet.css` in `tours.css`.
  - `fitBounds` on data change. `whenReady` sets `data-ready="true"` for tests.

- [ ] **Step 1: Write failing tests:**
  - `caddyfiles_test.py::test_img_src_names_tile_origin_and_connect_src_stays_self`, for every rendered file.
  - `caddyfiles_test.py::test_e2e_tiles_only_in_dev`
  - `tour-map.test.tsx`: `renders numbered divIcon pins in rank order`, `no element has a style attribute set by markup`, `attribution text visible`, `click on pin calls onSelect`.
  - E2E: in the tours test, Klara's map shows `.tour-pin` count equal to the stops with coordinates (seed two pins via `setDeliveryPin` in the test through the UI "Pin setzen"). Anna's "Karte" toggle shows the same numbered pins, and the response CSP header of `/app/delivery` contains `img-src 'self' data: blob: https://tile.openstreetmap.org`. `csp-guard` reports nothing.
- [ ] **Step 2: Run** `python3 -m pytest tools/proxy/caddyfiles_test.py`, `bun run --filter @leonaid/web test:components -- src/tour-map.test.tsx` and `./leonaid test-e2e invoices`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes and regenerate the Caddyfiles. Then `tools/proxy/validate-caddyfiles.sh` must pass.
- [ ] **Step 4: Run** the same commands, `./leonaid check-fast` and `./leonaid test-env-stop`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(delivery): Leaflet tour map with configurable tiles`

---

# Slice 3: driver note

### Task 12: "Hinweis für den Fahrer" through all layers

**Model:** standard

**Files:**
- Modify:
  - `src/leonaid/domain/delivery.py:16-61` (`DeliveryContactSnapshot.driver_note`, max 200, single line; `empty` includes it; `payload()` adds `"driver_note"` only when not None; `from_payload` reads it)
  - `schemas.py:1068` (`DeliveryContactRequest.driver_note: str | None = Field(default=None, max_length=200)`)
  - `schemas.py:2636` (`DeliveryDropContactResponse.driver_note`) and the privacy access response
  - `routes.py` (the mappers at lines 1482, 1909, 2240, 3981 pass it through)
  - `src/leonaid/domain/delivery_board.py` (`DropContact.driver_note`)
  - `src/leonaid/adapters/postgres/delivery_board.py` (`_drops` reads it)
  - `apps/public/src/actions/index.ts:98-210` (`deliveryDriverNote: optionalText(200)`, sent inside `deliveryContact`)
  - `apps/public/src/components/PublicOrder.astro` (the field, after the delivery contact)
  - `apps/public/src/lib/order-redisplay.ts`
  - `packages/features/src/commitments/delivery-fields.tsx`, `delivery-completion.tsx`, `commitment-admin.tsx` (input, and display in the order detail)
  - `my-tour.tsx` and `tour-planner.tsx` (show the note on the card and in the stop detail)
  - the generated client
- Test:
  - `tests/unit/test_delivery_domain.py`, `tests/unit/test_public_orders.py`, `tests/unit/test_privacy.py`, `tests/unit/test_public_order_mail_legs.py`
  - `tools/delivery/legacy_replay.py` (unchanged, must still pass)
  - `apps/web/src/commitment-admin.test.tsx`, `apps/web/src/my-tour.test.tsx`
  - `./leonaid test-emdash` (the campaign site reuses `PublicOrder.astro`)

**Interfaces:**
- Produces: `DeliveryContactSnapshot(name: str | None = None, phone: str | None = None, driver_note: str | None = None)`. Error code `delivery_contact_too_long`, with the existing message pattern for limit 200.

- [ ] **Step 1: Write failing tests:**
  - `test_contact_payload_without_note_is_unchanged`: `payload() == {"name": "X", "phone": "1"}`.
  - `test_driver_note_rejects_newline_and_201_chars`
  - `test_request_hash_changes_with_driver_note_only_when_present`
  - `test_privacy_report_contains_driver_note` and `test_erasure_clears_it`
  - `test_order_mails_never_render_driver_note`: render the confirmation mail with a note and assert the note text is absent.
  - component `driver note shows on the next-stop card`
  - component `completion form round-trips the note`
- [ ] **Step 2: Run** `./leonaid test-unit -k "delivery_domain or public_orders or privacy or mail_legs"` and the component tests. Expected: FAIL.
- [ ] **Step 3: Implement** all of the changes above and regenerate the client.
- [ ] **Step 4: Run** the same commands, `./leonaid test-delivery` (legacy replay and privacy), `./leonaid test-emdash` and `./leonaid test-api-contract`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(orders): driver note on delivery orders`

---

# Slice 4: offline tour (Stage 2)

Active only while both `pwa.offline_queue` and `delivery.tours` are on; the device store exists only with the first.

### Task 13: Offline tour cache, purge and read audit sync

**Model:** capable

**Files:**
- Create: `packages/features/src/offline/tour-cache.ts`
- Modify:
  - `packages/features/src/offline/device-store.ts:25` (`CacheKind = "board" | "capture" | "tour"`)
  - `packages/features/src/offline/runtime.tsx` (purge on flag off, `delivery.tours` too)
  - `packages/features/src/offline/sign-out.tsx` (existing wipe, assert it covers `tour`)
  - `packages/features/src/offline/index.ts`
  - `my-tour.tsx` (online fetch writes the cache; offline renders it with the banner "Offline – Stand HH:MM")
  - `apps/pwa/src/app.tsx` (pass `cached`)
  - server: `routes.py` and `schemas.py` (operation `recordMyTourReads`: POST `/api/v1/actions/{action_id}/my-tour/reads`, body `MyTourReadsRequest{reads: list[{window_id: UUID, read_at: datetime}] (max 50)}`, 204)
  - `src/leonaid/application/delivery_tours.py` (`record_reads`, which accepts `read_at` within the last 14 days and not in the future, for windows of the driver's own stops only, and reuses `record_read_audit`)
- Test: `apps/pwa/src/tour-cache.test.ts` (node), `tools/delivery/tours.py` (section `offline reads`)

**Interfaces:**
- Produces:
  - `CachedTour = { tour: MyTourResponse; fetchedAt: string; reads: { windowId: string; readAt: string }[] }`
  - `minimizeTour(response: MyTourResponse): MyTourResponse`, which drops the `days` list. Stops keep only the fields "Meine Tour" renders.
  - `purgeTour(cached: CachedTour, now: Date): CachedTour | null`. It removes a window's stops when the window is `closed` or `now > ends_at + 12 h`, and returns null when no window is left (§9).
  - `noteOfflineRead(cached, windowIds, now): CachedTour`, which keeps one read per window and local day.
  - `tourCacheKey(actionId)`.

- [ ] **Step 1: Write failing tests:**
  - `purge drops a closed window and keeps the open one`
  - `purge drops a window 12 h after its end`
  - `purge returns null when nothing is left`
  - `flag off deletes the tour cache`
  - `sign-out deletes the tour cache`
  - `offline read is recorded once per window and day`
  - proof `recordMyTourReads writes viewed_on from read_at; foreign window ignored; future read_at 422`
- [ ] **Step 2: Run** `bun run --filter @leonaid/pwa test -- src/tour-cache.test.ts` and `./leonaid test-delivery`. Expected: FAIL.
- [ ] **Step 3: Implement** the cache, the purge, the read sync on reconnect (through the existing sync loop in `offline/sync.ts`), and the endpoint. Regenerate the client.
- [ ] **Step 4: Run** the same commands and `bun run typecheck`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(pwa): offline tour cache with purge rules`

### Task 14: Queue kinds `delivery-state` and `tour-order`

**Model:** capable

**Files:**
- Modify:
  - `packages/features/src/offline/queue.ts:95-125` (two entry types)
  - `packages/features/src/offline/sync.ts` (send them)
  - `packages/features/src/offline/conflicts.ts` (codes)
  - `packages/features/src/offline/labels.ts` ("Zustellung", "Tour-Reihenfolge")
  - `packages/features/src/offline/queue-sheet.tsx` (conflict copy)
  - `my-tour.tsx` (offline actions enqueue and update the cached tour optimistically)
- Test: `apps/pwa/src/offline-queue.test.ts`, `apps/web/src/my-tour.test.tsx`

**Interfaces:**
- Produces:
  - `DeliveryStateEntry extends EntryCommon { kind: "delivery-state"; commitmentId: string; request: DeliveryStateRequest }`
  - `TourOrderEntry extends EntryCommon { kind: "tour-order"; request: DeliveryTourOrderRequest }`
  - Replacement rule: a new `delivery-state` entry for the same `commitmentId` replaces a pending one that was not sent yet (`everSent !== true`). An undo that returns to the server state deletes it. A new `tour-order` for the same action and day replaces the pending one.
  - Conflict mapping: `delivery_state_conflict`, `tour_revision_conflict` and `tour_order_stale` show "Vom Planer geändert". `delivery_window_closed` shows "Fenster geschlossen". Each is shown in "Du" like the other entries (§9).

- [ ] **Step 1: Write failing tests:**
  - `delivered offline then undone offline leaves no entry`
  - `two tour-order entries collapse to the last`
  - `tour-order conflict after an appended stop shows Vom Planer geändert and keeps the server order`
  - `window closed while offline shows Fenster geschlossen`
  - `entries replay in sequence after reconnect`
- [ ] **Step 2: Run** `bun run --filter @leonaid/pwa test -- src/offline-queue.test.ts` and `bun run --filter @leonaid/web test:components -- src/my-tour.test.tsx`. Expected: FAIL.
- [ ] **Step 3: Implement** the two entry kinds, the replacement rule, the conflict mapping and the optimistic cache update.
- [ ] **Step 4: Run** the same commands and `bun run typecheck`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(pwa): offline delivery-state and tour-order queue kinds`

---

# Docs

### Task 15: Documentation and pilot boundary

**Model:** cheap

**Files:**
- Create: `apps/docs/src/content/docs/{de,en}/user/how-to/plan-delivery-tours.md` and `.../drive-my-tour.md`
- Modify:
  - `apps/docs/src/content/docs/{de,en}/known-limits.md:21` (replace "Route and tour planning is outside the current scope" with the limits from §3: no road routing, no live tracking, one tour per driver and day, public Nominatim and OSM tiles subject to their usage policies)
  - `.../user/reference/roles.md` (driver: "Meine Tour"; charity admin: "Touren planen")
  - `.../user/how-to/work-delivery-board.md` (link)
  - `infra/pilot/LEGAL-CONFIGURATION-RUNBOOK.md` (the two privacy paragraphs required before the flag goes on: tiles for members per §8.1, geocoding for customers per §8.2; a self-hosted geocoder is not a transfer)
  - `specs/leonaid-pilot/PLAN.md` (§Nicht enthalten: point to this spec)
- Test: `./leonaid docs-check`, `./leonaid docs-build`

- [ ] **Step 1: Write** the pages. Both languages carry the same facts. Use the UI labels exactly as in Tasks 6, 7 and 11.
- [ ] **Step 2: Run** `./leonaid docs-check && ./leonaid docs-build`. Expected: PASS.
- [ ] **Step 3: Commit** `docs: delivery tours, Meine Tour, privacy runbook`

---

## Self-Review

- **Spec coverage:**

  | Spec | Task |
  |---|---|
  | §5 ranks | 1, 2, 3 |
  | §5 `delivery_geo`, config, env | 9, 10 |
  | §5 retention | 9 |
  | §5.1 driver note | 12 |
  | §6.1–6.3 | 7, 11 |
  | §6.4 | 9, 10, 11 |
  | §7, 7.1, 7.3, 7.4 | 5, 6 |
  | §7.2 | 11 |
  | §8.1 | 11 |
  | §8.2 | 9 |
  | §9 | 13, 14 |
  | §10 | 3, 4, 9, 13 |
  | §11 | 4, 10, 13 |
  | §12 | 2, 3, 6, 9, 11, 13, 14 |
  | §13 docs | 15 |

  The spec's "policy negative contract" moves to the delivery proof (Task 3), and its E2E leaf folds into `invoices` (Task 8).
- **Type consistency:**
  - `expected_revision` is `str` for tours and `int` for drops, kept apart.
  - `DeliveryTourOrderRequest` is used by both PUTs and by `TourOrderEntry`.
  - `record_read_audit` is defined in Task 3 and reused in Task 13.
  - `GeoPoint` is defined in Task 9 and used in Tasks 10 and 12 (privacy).
- **Proportion:** The plan holds signatures, test names and values, with no bodies.
