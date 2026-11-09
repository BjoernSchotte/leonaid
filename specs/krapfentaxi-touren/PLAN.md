# Krapfentaxi: delivery tours for drivers

Status: 2026-11-09, approved as the base. Implementation runs in the real
app behind the feature flag `delivery-tours`, and discussion continues on
the dev instance (D12).
Reference only: [prototype.html](prototype.html), an early click
prototype that is not maintained.

## 1. Context

Krapfentaxi already has a delivery workflow:

- **Delivery board.** Migration 0046, `src/leonaid/domain/delivery_board.py`
  and `packages/features/src/delivery/delivery-board.tsx`. The web admin
  (`/delivery`) and the PWA (`delivery`) share this one component.
- **Driver role.** The action role `driver` exists (`domain/identity.py`).
  Managers (charity admin, system admin) assign each order to one driver
  (`commitment_delivery.driver_user_id`).
- **What a driver sees.** Only the orders assigned to them, with name,
  address, contact and quantities. No amounts, no e-mail, no history
  (`DeliveryDrop`). The first read per driver, window and day is audited
  for 90 days.
- **What a driver can do.** Mark a drop as delivered or missed. After the
  closure, a manager closes the window.

What is missing is the tour:

- There is no order of stops. Drops are sorted by buyer name.
- There are no coordinates and no map.
- There is no way for a driver to plan the round.
- The board stays online-only on purpose: `specs/pwa-offline-queue/PLAN.md`
  D2 keeps addresses off the device.

The pilot boundary (`specs/leonaid-pilot/PLAN.md` §Nicht enthalten) and the
known limits in the docs exclude tour planning today. This spec lifts that
boundary for Krapfentaxi.

## 2. Goals

- **G1.** A manager plans the tours of one delivery day in the web admin:
  - assign the orders to drivers,
  - set a base order of stops per driver,
  - see all stops on a map.
- **G2.** A driver sees their tour for today or the next delivery day in the
  acquisition app, in the base order.
- **G3.** A driver can reorder their own stops. Their order wins on their
  device and is visible to the manager. The base order stays untouched.
- **G4.** A map with OpenStreetMap tiles in both apps:
  - all stops of a tour as numbered pins,
  - the start point,
  - a straight line in stop order.
- **G5.** From each stop, one tap starts navigation in the phone's map app,
  and one tap calls the delivery contact if a phone number exists.
- **G6.** Delivered and missed work as today, from the tour, without
  leaving it.
- **G7.** Stage 2: the driver's own tour works without network for the
  delivery day (§9).

## 3. Non-goals

- **Algorithmic route optimization** with road distances, time windows or
  vehicle capacity. Section 6.3 has one simple sort helper. Nothing more.
- **Live tracking** of drivers, or ETA messages to customers.
- **Push notifications, SMS.**
- **Several tours per driver per day.** A tour is driver × delivery day
  (§4): one pickup in the morning, then all stops.
- **Drivers seeing other drivers' stops,** or amounts.
- **Self-hosted tile server or geocoder** in Stage 1. The providers are
  configurable (§8), so a later switch needs no code.

## 4. Terms

| Term | Meaning |
|---|---|
| Delivery window | Existing: a time slot of an action (`action_delivery_window`). |
| Stop | One order with a delivery address in a window. Today's `DeliveryDrop`. |
| Delivery day | The date of a window (`delivery_on`). One day has one or more windows. |
| Tour | All stops one driver holds on one delivery day, across all windows of that day. No own table: driver × day. The driver collects all Krapfen at the start point in the morning (D11). |
| Start point | Where every tour starts, for example the bakery or the club house. One per action, optional. |
| Base order | The manager's order of the stops in a tour. |
| Driver order | The driver's own order of their tour. Empty until they reorder. |
| Effective order | The driver order where set, else the base order. |

## 5. Data model

Changes stay inside the delivery tables. Commitments are not touched.

- **`commitment_delivery`:**
  - `base_position integer NULL`: the manager's order within driver × day.
  - `driver_position integer NULL`: written only by the assigned driver.
  - Both reset to `NULL` when the driver assignment changes.
- **New `delivery_geo`,** one row per commitment:
  - `commitment_id`, `lat numeric(9,6)`, `lon numeric(9,6)`,
  - `source text check in ('geocoder','manual')`,
  - `address_hash text`: hash of the address snapshot fields the geocoder
    saw,
  - `geocoded_at`, `geocoder text`: provider id for the audit trail.
  - A changed delivery address (delivery completion) has a different hash.
    The row is then stale and is geocoded again. A `manual` pin survives
    only while the hash matches.
- **`action_delivery_configuration`:**
  - `start_label`, `start_address` as one line, and `start_lat`, `start_lon`.
  - All are optional. Without a start point the map simply has none.
- **Installation configuration** (env, not per action):
  - `LEONAID_MAP_TILE_URL`, `LEONAID_MAP_ATTRIBUTION`, `LEONAID_GEOCODER_URL`
    and `LEONAID_GEOCODER_USER_AGENT`.
  - Defaults: OSM standard tiles and the public Nominatim (§8).
- **Retention:** `delivery_geo` follows the order. Privacy erasure
  (`PrivacyOrderDelivery`) deletes the row with the delivery data, and the
  privacy proof (`tools/delivery/privacy.py`) is extended for it.

Ordering rules (domain, `delivery_board.py`):

- **Windows come first.** The effective order is sorted by window start,
  then by position within the window. Base and driver order rank stops only
  inside their window, so a customer's promised slot is never broken by
  sorting. A stop cannot be moved into another window by reordering; that
  stays a change of the order's window (delivery completion).
- Positions are dense ranks `1..n` per driver × day and window. A write replaces the
  whole order of one tour in one command, with the tour's `revision`. That
  makes it idempotent and conflict-safe, like today's state changes.
- A stop newly assigned to a tour gets the next base position at the end.
  It is appended to an existing driver order at the end, so the driver sees
  it last and marked "neu".
- A stop that leaves a tour (reassignment, cancellation) drops out of both
  orders. The remaining ranks close up.
- A manager can reset a driver order ("Fahrerreihenfolge verwerfen"). A
  driver can reset to the base order.

### 5.1 Driver note on the order (D10)

- **New field:** "Hinweis für den Fahrer (optional)", one line, max 200
  characters. Examples: bell, back yard, delivery entrance.
- **Where it is entered:**
  - the public order form (`PublicOrder.astro`, so also the EmDash
    microsite),
  - Anna's capture (`delivery-fields.tsx`),
  - manager completion (`delivery-completion.tsx`).
- **Storage:** part of the delivery snapshot of the order, beside the
  delivery contact (`delivery_contact_snapshot` gains `driver_note`). It is
  not copied to the CRM.
- **Shown to:**
  - the assigned driver (stop card),
  - managers (order detail, tour view).
  It does not appear in mails, invoices, audit events or telemetry.
- **Privacy:** the field is covered by access and erasure like the
  delivery contact (`PrivacyOrderDelivery`).
- **Request hash:** the public idempotency hash includes the field.

## 6. Manager: tour planning (web admin)

Place: the existing delivery board `/delivery`, as a new view "Touren" next
to today's list. A day picker instead of the window picker. The driver
columns show their stops grouped by window ("08–10", "10–12", …), and
reordering works inside each window group. Same rights as today: charity
admin and system admin (D9).

### 6.1 Layout

- **Left:** "Nicht zugeordnet", the stops without a driver. Then one column
  per driver of the action, each with a count, the first and last stop, and
  the straight-line length.
- **Right:** the map. All stops of the window, coloured by driver, numbered
  by effective order. Unassigned stops are grey.
- Selecting a stop in the list highlights its pin, and the other way round.
- Pin numbers always follow the effective order. An unsaved draft order is
  drawn as a dashed line until "Reihenfolge speichern".

### 6.2 Assign and order

- **Assign:** select one or more stops (list or map), then "Fahrer
  zuordnen" → driver. Drag a stop onto a driver column. Both use today's
  `assign_driver`.
- **Order:** drag within a driver column, plus keyboard and "nach oben"/"nach
  unten" buttons, as in the Leitsystem lists. Saving is explicit
  ("Reihenfolge speichern"), one command per tour.
- If a driver has their own order, the column says "Fahrer hat eigene
  Reihenfolge (seit 08:12)" and offers "anzeigen" and "verwerfen".

### 6.3 Sort helper

"Vorschlag sortieren" on a driver column. Within each window group it
orders by nearest next stop, by straight-line distance, with no road data
and no external service. The first window starts at the start point, and
each later window starts at the last stop of the window before. It is a suggestion: the list changes, and saving stays
explicit. Without a start point it starts at the stop furthest from the
centre.

### 6.4 Addresses without a pin

- Geocoding runs on the server when an order gets a delivery address and in
  a nightly catch-up (§8.2).
- A stop without coordinates shows "Adresse nicht gefunden – Pin setzen".
  The manager places the pin on the map, and that writes a `manual` row.
- Stops without a pin can still be assigned and ordered. They are only
  missing on the map.

## 7. Driver: my tour (acquisition app)

Place: the existing PWA route `delivery`, renamed "Meine Tour" for users
with the role `driver`.

- **Day choice:** today, else the next delivery day with stops for this
  driver. Other days are available through a small picker. Only days where
  the driver holds stops are offered.
- **Window groups:** the list is grouped by window. A group whose window has
  started gets a time hint: "08–10 · noch 35 min". Once a window has ended,
  its open stops show "Fenster vorbei" in the warning tone.

### 7.1 List (default)

- **Header:**
  - the day ("Sa 05.12."),
  - progress "3 von 9 zugestellt",
  - a "Karte" toggle.
- **The next open stop** is a large card:
  - recipient,
  - full address,
  - delivery contact with a phone button,
  - quantities ("12 Krapfen, 2 Kisten"),
  - the driver note, if there is one.
  - Buttons: "Navigation", "Zugestellt", "Nicht angetroffen".
- **The other stops** are rows in effective order, inside their window
  group: number, name, street, quantity, status icon.
- **Done stops stay in place** (Björn, 2026-11-09, D15). A delivered or
  missed stop does not move and does not disappear. It shrinks to one
  greyed-out line (number, name, status) and expands on tap to the full
  card, so "Rückgängig" and the details stay reachable.
- **The address is a link to OpenStreetMap** (D15). Tapping the address
  (card and row) opens `https://www.openstreetmap.org/?mlat=<lat>&mlon=<lon>#map=18/<lat>/<lon>`
  in a new tab. Without coordinates (slice 1) it opens the OSM search
  `https://www.openstreetmap.org/search?query=<address>`. "Navigation"
  stays the button for turn-by-turn in the phone's map app.
- **"Reihenfolge ändern"** switches the list to edit mode:
  - drag handles,
  - up and down buttons (44 px touch targets, keyboard-accessible),
  - "Fertig" saves the driver order,
  - "Zurück zur Planung" resets it to the base order.

### 7.2 Map

- Full-height map with:
  - numbered pins in effective order,
  - the start point,
  - a straight line through the open stops,
  - the device location only if the driver allows it. The location stays
    in the browser and is never sent.
- Tapping a pin opens the stop card as a bottom sheet with the same
  buttons.

### 7.3 Navigation and calls

- **"Navigation"** opens the phone's map app:
  - `geo:lat,lon?q=<address>` on Android,
  - `maps://?daddr=` on iOS,
  - an OSM directions link as fallback.
  - Without coordinates, the link passes the address as text.
- **"Anrufen"** is a `tel:` link to the delivery contact, else the order
  contact (the rule from the Krapfentaxi delivery spec §1).

### 7.4 Status

- "Zugestellt" and "Nicht angetroffen" are today's commands. The card moves
  to "Erledigt", and the next open stop becomes the large card.
- An undo toast ("Rückgängig", 10 s) uses today's withdrawal rule in
  `decide_state_change`.

## 8. Map, tiles and geocoding

### 8.1 Tiles

- **Library:** Leaflet 1.9, bundled into both apps with no CDN.
  `script-src 'self'` stays.
- **Tile URL and attribution** come from the installation configuration and
  reach the apps through the existing runtime config endpoint.
- **CSP change** (Caddyfile, pilot Caddyfiles, `csp-guard.mjs`):
  `img-src` gains the tile host from the configuration, nothing else.
  `connect-src` stays `'self'`.
- **Default:** `https://tile.openstreetmap.org/{z}/{x}/{y}.png` with
  "© OpenStreetMap-Mitwirkende". This is fine for a club's volume under the
  OSM tile usage policy (attribution, no bulk prefetch, a valid referer).
  For a busy installation the configuration can name a provider with a key,
  or a self-hosted server, with no code change.
- **Privacy:** tile requests tell the provider the viewed area and the
  driver's IP address. They do not include addresses or names. This goes
  into the member privacy notice (`member_privacy_notice_text`, the D8 path
  with four-eyes approval).

### 8.2 Geocoding

- **Server-side only.** The browser never geocodes.
- **What is sent:** only street line, postal code, city and country. Never
  names, contacts or order data.
- **Provider:** default is the public Nominatim at 1 request/s with an
  installation User-Agent. A queue job throttles it, and the result is
  cached in `delivery_geo`.
- **Configurable:** a self-hosted Nominatim or a commercial geocoder only
  needs a new URL, as long as it uses the Nominatim JSON API.
- **Failure:** "not found", too unsure (`importance` below a threshold) or
  timeout leaves no row, and the manager sets the pin (§6.4).
- **Privacy:** sending delivery addresses to the geocoding provider is a new
  transfer to a third party. It goes into the privacy notice for customers
  (public order form and order confirmation). With a self-hosted geocoder
  it is not a transfer.

## 9. Offline (Stage 2)

Björn, 2026-11-09: "es ist okay, wenn die vollständige adresse dem fahrer
bekannt ist – das braucht er ja für die durchführung". On that basis
(D4), this replaces `pwa-offline-queue` D2 for one narrow case:

- **What is stored:** the driver's own tour for today or the next delivery day
  (stops, addresses, contacts, quantities, the effective order). It is
  stored in the existing per-user device store (`device-store.ts`). That
  store is sealed with the non-exportable key from `crypto.ts`. Björn would
  also allow it unencrypted (D4), but reusing the store is less work.
- **Purge:**
  - when the window is closed,
  - 12 hours after the window ends,
  - when the driver signs out,
  - when the flag is switched off.
  The first of these wins.
- **Map tiles are not cached** beyond the browser's normal HTTP cache. An
  offline map shows what it already loaded, and the list works without it.
- **The offline queue gains two kinds:**
  - `delivery-state` (delivered/missed),
  - `tour-order` (the driver order).
  Both are already idempotent on the server through target state plus
  revision. A conflict ("vom Planer geändert", "Fenster geschlossen")
  shows in "Du" as for other entries.
- **Nothing else becomes offline:** the manager's tour planning and other
  drivers stay online-only.

## 10. Rights and audit

- Driver:
  - reads only their own tour,
  - writes only the `driver_position` of their own stops, plus the existing
    state change.
- Manager: reads and writes everything in an action they manage.
- The existing first-read audit also covers "Meine Tour" and the map view.
  An offline read is logged when the driver next syncs (its read time as
  the event time).
- Coordinates are personal data, like the address. They never go into
  audit events, URLs or telemetry (rule from the Krapfentaxi delivery spec
  §145).

## 11. API sketch

All endpoints live in `routes.py` next to the delivery board.

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/actions/{id}/delivery-board/tours?day=` | manager | All tours of a delivery day, grouped by window, with positions and coordinates |
| PUT | `/actions/{id}/delivery-board/tours/{driver}/order` | manager | Base order of one tour (`revision`, ordered commitment ids) |
| DELETE | `/actions/{id}/delivery-board/tours/{driver}/driver-order` | manager | Discard the driver order |
| GET | `/actions/{id}/my-tour?day=` | driver | Own tour of a day, effective order |
| PUT | `/actions/{id}/my-tour/order` | driver | Driver order (`revision`, ids), empty list = reset |
| PUT | `/actions/{id}/delivery-geo/{commitment}` | manager | Manual pin |
| PUT | `/actions/{id}/delivery-configuration` | manager | Existing, gains the start point fields |

OpenAPI changes go through the existing breaking check and approval file.

## 12. Tests

- **Domain:** rank rules (append, close up, reset on reassignment), revision
  conflicts, driver writes only own stops.
- **Integration:**
  - geocoder queue against a stub Nominatim (throttle, failure, stale hash),
  - privacy erasure removes `delivery_geo`,
  - the policy negative contract for `my-tour` with a foreign driver.
- **Component:** tour list reorder by keyboard and buttons, next-stop card,
  undo.
- **E2E,** one leaf (`delivery-tours`): the manager assigns and orders, the
  driver reorders, delivers and sees the manager's later stop appended
  ("neu"). The map uses a stub tile server under `'self'` in tests. The CSP
  guard checks the configured tile host.
- **Stage 2:** offline queue kinds (component), purge rules (unit).

## 13. Stages and effort (estimate)

| Stage | Content | Effort |
|---|---|---|
| 1a | Data model, ranks, API, driver list with reorder, navigation and call links | 2–3 days |
| 1b | Leaflet in both apps, CSP, geocoding queue, manual pin, manager tours view with map | 3–4 days |
| 2 | Offline tour (device store, two queue kinds, purge) | 2 days |
| — | Docs: known limits, user guide "Touren planen" / "Meine Tour", privacy notices | 1 day |

## 14. Decisions

| # | Decision | Who | Date |
|---|---|---|---|
| D1 | A tour is driver × delivery day, with no own entity. Stops are grouped by window, and reordering only works inside a window. This follows from D11 (one pickup in the morning). | Lead | 2026-11-09 |
| D2 | The base order is the manager's. The driver order is per driver and does not change the base order. New stops are appended at the end and marked "neu". | Lead | 2026-11-09 |
| D3 | External tiles (OSM by default, configurable). The CSP opens `img-src` for exactly that host. | Björn | 2026-11-09 |
| D4 | The driver knows the full address. Stage 2 stores the driver's own tour on the device, with purge rules (§9). This replaces pwa-offline-queue D2 for this case. Björn allows it unencrypted. The lead reuses the existing sealed device store anyway, because it costs nothing extra. | Björn / Lead | 2026-11-09 |
| D8 | The public Nominatim is enough for the pilot. | Björn | 2026-11-09 |
| D9 | Only charity admins (and system admins) plan tours. No new role. | Björn | 2026-11-09 |
| D10 | New order field "Hinweis für den Fahrer" (§5.1). | Björn | 2026-11-09 |
| D11 | One start point per action. The driver collects all Krapfen there in the morning and then drives the tour over all their stops. No start point per window. | Björn | 2026-11-09 |
| D12 | No separate prototype. Build it directly in the real app (web admin + PWA), behind the feature flag `delivery-tours`, in slices that can be shown early. Discuss on the dev instance. | Björn | 2026-11-09 |
| D13 | The driver may mark a stop "Nicht angetroffen" (`missed`) during the day. Today `missed` only appears at window closure. The same withdrawal rule as "Zugestellt" applies. The manager sees it at once and can reassign. | Lead | 2026-11-09 |
| D14 | Plan review rulings: (a) The feature flag key is `delivery.tours` (repo convention). (b) Tile URL and attribution come in the tour responses, because there is no runtime config endpoint. (c) Writes carry `day` in the body. (d) There is a new `POST /actions/{id}/my-tour/reads` for offline read audit. (e) Geocoding failures are stored as `not_found`/`failed` rows so the geocoder is not asked again and again (this replaces "no row" in §8.2). A result counts when it is house level, the postal code matches and the house number matches (calibrated on real Bad Tölz addresses: Nominatim's `importance` is ~6e-5 even for exact hits, so no importance threshold). (f) A window change via delivery completion resets the stop's positions. (g) The offline tour needs both flags, `pwa.offline_queue` and `delivery.tours`. | Lead | 2026-11-09 |
| D15 | Driver view: done stops stay in place, greyed and collapsed, expandable on tap. The address links to OpenStreetMap. | Björn | 2026-11-09 |
| D16 | Driver view: no "Reihenfolge ändern" mode. Drag handles (and up/down for keyboard) are always there; every move inside a window saves at once (revision-checked, short debounce, undo toast). "Fertig" disappears; "Zurück zur Planung" moves to a small menu. | Björn | 2026-11-09 |
| D17 | Driver view: the OpenStreetMap map is inline in the stop card (and in the map view), not a new window. An extra small link "In OpenStreetMap öffnen" opens it externally. This pulls slice 2 (coordinates, Leaflet, CSP img-src, geocoding) ahead of further driver UI work. | Björn | 2026-11-09 |
| D18 | Driver view on mobile must be much simpler and faster to use: one-hand, few taps, the next stop's address, map and "Zugestellt" within thumb reach. The layout follows an impeccable critique of the real page (specs/krapfentaxi-touren/critique-*.md). | Björn | 2026-11-09 |
| D19 | All points of critique-driver.md are implemented (Björn: "alle Punkte verbessern"). Open questions there: fixed "Nächster Stopp" dock (1a); the planner saves on drop with undo, so "Reihenfolge speichern" goes (2a); driver-only users land on the tour at `/app/` and "Tour" is the first nav item (3a). | Björn / Lead | 2026-11-09 |
| D5 | Geocoding on the server via Nominatim API, with no names. Manual pin as fallback. | Lead | 2026-11-09 |
| D6 | Optimization is only the straight-line "nearest next" suggestion. No routing service. | Lead | 2026-11-09 |
| D7 | Leaflet, bundled. No MapLibre or vector tiles. Fewer dependencies, and raster OSM is enough. | Lead | 2026-11-09 |

## 15. Open questions for Björn

None at the moment.
