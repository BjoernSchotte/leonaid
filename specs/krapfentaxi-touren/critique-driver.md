# Critique: driver view "Meine Tour" and planner "Touren"

Date: 2026-11-09. Method: impeccable critique, dual-agent (A: design review,
B: detector and browser evidence), synthesized here. Instance: dev LAN
instance `https://ms-s1-max.local:28081`, action "Krapfentaxi 2026",
Sa 05.12., driver `dora.fahrer@`, planner `klara.kern@` (charity admin;
`carla.club@` is only an acquirer on this instance and cannot open
`/admin/delivery`).

This file is the template for the next rebuild of the driver view (D16-D18).
Section 3 is the target layout. Section 4 is the planner list.

## Screenshots

Directory: `/tmp/claude-1000/-home-bjoern-code-leonaid/9bbddd1d-64ab-4104-9149-df8574e34743/scratchpad/critique/`
(temporary; copy what you need).

| File | State |
|---|---|
| `00-driver-landing.png` | Driver after login on `/app/` |
| `00b-driver-more-menu.png` | "Mehr" sheet, "Meine Tour" is the last tile |
| `01-light-start.png`, `01-light-start-full.png`, `02-dark-start.png` | Start, 2 of 7 delivered, 390×844 |
| `03-light-after-delivered.png`, `03-dark-after-delivered.png` | Right after "Zugestellt" on stop 2 |
| `04-light-done-expanded.png`, `04-dark-done-expanded.png` | Delivered stop 2 tapped open |
| `05-light-edit-mode.png` | Current "Reihenfolge ändern" mode (goes away, D16) |
| `10-planner-1440.png`, `10-planner-1440-full.png`, `11-planner-1440-dark.png` | Planner, Sa 05.12., 1440 px |

The test "Zugestellt" on Maria Obermaier was undone right after (state back
to 2 of 7, checked after reload).

## 1. Verdict

The page is on-brand (Barlow, Lions-blue bar, delivery zone teal, number
chips) but it is office card grammar scaled down to a phone. It breaks
`.impeccable.md` principle 3 ("rearranged for usage context, not scaled
down"). Nothing in it answers the real scene: phone in a car mount or in one
hand, gloves, glare, a customer at the door, constant interruptions.

Health score (Nielsen, 0-4): **20/40, Acceptable** (lower edge).

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of status | 3 | Progress is clear; the driver loses their place after every action |
| 2 | Match real world | 2 | "Keine aktive Akquise-Aktion", "Reihenfolge der Planung", "Lieferkontakt ohne Telefon" |
| 3 | Control and freedom | 3 | Undo toast with the customer's name, "Rückgängig" in the done card |
| 4 | Consistency | 2 | Planner "0 Boxen" vs driver "6 Stück"; dark primary weaker than secondary |
| 5 | Error prevention | 2 | "Zugestellt" and "Nicht angetroffen" side by side, 44 px, 8 px gap |
| 6 | Recognition vs recall | 2 | The page sits in "Mehr"; driver matches window times to the clock |
| 7 | Flexibility, efficiency | 1 | No auto-advance, no fixed action, reordering needs a mode |
| 8 | Minimalist design | 2 | Progress shown 3×, window time 2×, three nested frames |
| 9 | Error recovery | 3 | Fast undo; stale/sync errors only as toast |
| 10 | Help | 2 | Address link (OSM) vs "Navigation" is unexplained |

Cognitive load: 5 of 8 checks fail (single focus, grouping, hierarchy, one
thing at a time, working memory). The first viewport offers 8+ targets.

Detector: the source scan is clean (it cannot see class-based styling). The
live scan, run with the page CSP bypassed in the test browser only (the CSP
blocks the injected script and its WebAssembly), found 2 issues on the driver
page and none on the planner:

- `nested-cards`: the next-stop card (`article.tour-card.is-next`) sits in a
  teal band inside the window panel (`section.tour-window`). Agrees with the
  review (finding P1-3).
- `flat-type-hierarchy` (advisory): h1 "Meine Tour" 17 px, h2 "08–10 Uhr"
  15 px, body 16 px, h3 stop name 21 px. The page title and the window heads
  are no larger than body text. The large stop name is right; the window
  heads should become small sticky labels, not h2 panels (section 3).

What works, and stays:

- D15: done stops stay in place as a grey line and open on tap, with
  "Rückgängig" inside. Nothing jumps.
- The undo toast names the customer ("Maria Obermaier: zugestellt.
  Rückgängig").
- Every target is at least 44 px; keyboard ordering exists
  (`TaskOrdering`, space + arrows); the aria-live region announces moves.

## 2. Findings, by severity

### P0-1 The next stop leaves the screen after every "Zugestellt"

Screenshot `03-light-after-delivered.png`. At start the action row of the
next card sits at y=610–706. After one "Zugestellt" the new next card's
action row is at y=794–890: under the bottom nav (from y=779) and below the
fold. The page does not scroll. The screen is filled by three grey done rows.
The toast covers the new card's quantity. The driver must scroll one-handed
after every stop, 7 times per tour. This breaks the core loop and D18.

Fix: the next stop lives in a fixed dock at the bottom (section 3, block C).
Its content swaps on "Zugestellt"; the list scrolls behind it. Interim, if
the dock slips: after a mark, `scrollIntoView({ block: "end" })` the new
`.tour-next` (instant under reduced motion) and move focus to its heading.

### P0-2 The driver does not land on the tour, and the bar says the wrong thing

Screenshots `00-driver-landing.png`, `00b-driver-more-menu.png`, every
driver shot. After login a driver-only user sees the acquirer start page
("Noch keine passende Charity-Aktion … als Akquisiteur"). The top bar reads
"Keine aktive Akquise-Aktion" on "Meine Tour" too. The bottom nav has only
"Start"; "Meine Tour" is the last tile in "Mehr". A volunteer will think the
account is broken.

Fix (`apps/pwa/src/navigation.ts`, start route): for a user whose only role
in the action is driver, `/app/` redirects to `/app/delivery`; "Tour" (truck
icon) is the first bottom tab when `delivery.tours` is on and the user has
stops; the top bar shows the action name ("Krapfentaxi 2026"), never the
acquirer empty text.

### P1-1 Chrome eats 45 % of the viewport, progress shows 3 times

Screenshot `01-light-start.png`. About 350 of 779 usable px come before the
next card: wrong bar title, "Meine Tour Sa 05.12.", "2 von 7 zugestellt ·
Reihenfolge der Planung", the meter, "Reihenfolge ändern", the window head
"08–10 Uhr · 2 von 3 zugestellt", a done row. The eyebrow repeats the window
time ("Nächster Stopp · 08–10 Uhr").

Fix: one header line, a 4 px meter, sticky 32 px window labels, no
"Reihenfolge der Planung" (show a chip "Eigene Reihenfolge" only when the
driver's order differs), no "Reihenfolge ändern" (D16), no window time in the
card.

### P1-2 Buttons are the wrong size and weight for gloves and glare

Screenshots `01-light-start.png`, `02-dark-start.png`. 44 px
(`--control-h-lg`) is the floor, not the size for a car mount. "Zugestellt"
and "Nicht angetroffen" share one row with an 8 px gap: a slip records the
wrong outcome. "Nicht angetroffen" touches its border at 390 px and clips at
360 px. In dark mode the primary is a pastel fill with dark text and reads
weaker than the outlined "Navigation".

Fix: "Zugestellt" full width, 64 px, saturated fill with white text in both
themes. "Nicht angetroffen" 48 px, secondary, in a different row, at least
16 px away.

### P1-3 Three nested frames, contact block says nothing

Screenshots `01-light-start.png`, detector `nested-cards`. Card inside a teal
band inside the window panel. The grey contact panel shows "Lieferkontakt /
Lieferkontakt ohne Telefon / Keine Nummer": three phrases for "no phone".
The quantity "6 Stück", the number the driver needs at the trunk, is a loose
15 px line.

Fix: one surface for the next stop (the dock). Quantity as a mono chip next
to the name, 21 px. Phone as a 48 px icon button only when a number exists;
without one, nothing (or one muted "Kein Telefon" line).

### P1-4 The map is an external link; two "go there" actions

Screenshot `01-light-start.png`. The address is a link to OpenStreetMap and
"Navigation" opens the map app. Both leave the app; neither shows which house
it is. D17 wants the map inline.

Fix: inline Leaflet map in the dock (section 3, C3). The address text stays
plain text; a small "In OpenStreetMap öffnen" link sits under the map.
"Navigation" stays the turn-by-turn button.

### P2-1 The expanded done stop duplicates itself and pushes the work away

Screenshot `04-light-done-expanded.png`. The name and "Zugestellt" appear
twice (row and card); the full card with Navigation and contact opens for a
finished stop and pushes the next stop out of view.

Fix: a done stop expands to a compact panel: address, quantity, time of the
mark, one "Rückgängig" button (48 px). No Navigation, no contact block.

### P2-2 Rows are tall and uneven

Screenshot `01-light-start-full.png`. Open rows are 112 px (name, then a
44 px address link, then quantity). Done rows wrap long names to 2 lines
(61–64 px). The chevron follows the name, so its x position changes per row.

Fix: open rows 56 px, one line name + one line street, quantity right. Done
rows 48 px, one line with ellipsis. Status icon at the right edge; no
chevron (the whole row is the toggle).

### P2-3 Edit mode (removed by D16) shows why it must go

Screenshot `05-light-edit-mode.png`. A 130 px banner, "Fertig" and
"Abbrechen", 4 controls per row, a dead gutter between handle and number, and
done stops can be dragged too.

Fix: section 3, B (handles always there, save on drop, undo toast, done stops
fixed).

### P3

- Copy: "Zugestellt." with a period reads like a log line; "Reihenfolge der
  Planung" is planner language.
- A fully done window keeps its full panel and head; collapse it to one line
  "08–10 Uhr · alle 3 zugestellt".
- The last delivery has no closing moment beyond a status line.

## 3. Target: mobile driver view (390×844)

One task per screen: deliver the next stop. The list is context; the dock is
the work.

```
┌──────────────────────────────────┐ y=0
│ A  Krapfentaxi 2026      2/7   ⋮ │ 56 px top bar, 4 px meter on its lower edge
├──────────────────────────────────┤
│ B  08–10 Uhr · 2/3     (sticky)  │ 32 px window label
│ ⠿ ① Autohaus Isarwinkel…     ✓  │ 48 px done row (no handle)
│ ⠿ ② Maria Obermaier  Marktstr.  6│ 56 px open row, current: 4 px zone line left
│ ⠿ ③ Kanzlei Huber…  Am Schloß. 12│
│ 10–12 Uhr · 0/2                  │   (list scrolls behind the dock)
├══════════════════════════════════┤ y≈420
│ C  ② Maria Obermaier     [6 Stk]│ 48 px
│    Marktstraße 48                │ 24 px, 17 px text
│ ┌──────────────────────────────┐ │
│ │        inline OSM map        │ │ 140 px
│ └──────────────────────────────┘ │
│    In OpenStreetMap öffnen ↗     │ 24 px small link
│ [Navigation]  [☎]  [Nicht da]    │ 48 px row
│ [        ✓ Zugestellt        ]   │ 64 px, y≈700–764
├──────────────────────────────────┤ y≈779
│ D  Tour  ·  Mehr                 │ bottom nav
└──────────────────────────────────┘ y=844
```

### A. Top bar (56 px)

- Left: action name ("Krapfentaxi 2026"). Below or after it, small: "Meine
  Tour · Sa 05.12." Day picker only when there are several days: tapping the
  day opens a native `<select>`.
- Right: "2/7" in JetBrains Mono, then a ⋮ menu: "Zurück zur Planung" (only
  when the driver order differs, D16), day, action switch (several actions).
- The meter is the 4 px lower edge of the bar (`--zone`, `--ok` when all
  done).
- Goes away: page H1 block, "Reihenfolge der Planung", "Reihenfolge ändern",
  the separate meter row.

### B. Stop list (scrolls; bottom padding = dock height)

- Window label: sticky, 32 px, `--fs-sm` semibold, "08–10 Uhr · 2/3", plus
  "noch 35 min" or "Fenster vorbei" (warn) as today. No panel border, no h2
  card; a hairline above. A fully done window collapses to one label line
  "08–10 Uhr · alle 3 zugestellt", tap opens it.
- Open row, 56 px: drag handle at the left edge (44×56 hit area, grip icon
  `--text-3`), position chip 28 px, name (16 px semibold, one line, ellipsis)
  over street (13 px, `--text-2`, one line), quantity right (mono, 15 px).
  Tapping an open row shows that stop in the dock (heading "Stopp 4"), with a
  "Zum nächsten Stopp" link to go back. The row of the stop shown in the dock has a 4 px `--zone-line`
  left border.
- Done row, 48 px: no handle, chip in `--surface-3`, name one line in
  `--text-3`, StatusIcon at the right edge (shape + sr label, no "Zugestellt"
  text). Tap expands in place to address, quantity, mark time and one 48 px
  "Rückgängig" (P2-1).
- Cancelled row: as done, name struck through, no handle.

Drag handles (D16):

- Always visible on open rows of open windows. No mode, no "Fertig".
- Touch: drag starts on the handle without the 220 ms long press
  (`TouchSensor` delay 0, small distance tolerance) because only the handle is
  draggable; set `touch-action: none` on the handle only, so the list still
  scrolls by the row body.
- Keyboard: the handle is the keyboard target (space, arrows, space, Escape),
  as `TaskOrdering` does today. The ↑/↓ buttons go away visually; keep them
  only if a test shows the keyboard path is not enough, and then show them on
  `:focus-within` only.
- Drop only inside the same window (as today); done and cancelled stops are
  not draggable and are not drop targets between them.
- Each drop saves at once: `saveMyTourOrder` with the revision, short debounce
  (~600 ms) for chained moves, toast "Reihenfolge gespeichert. Rückgängig"
  (10 s, restores the previous order with a new save). A revision conflict
  reloads and says "Die Tour wurde inzwischen geändert."
- If a drop changes which stop is next, the dock follows.

### C. Next-stop dock (fixed, ~360 px, above the bottom nav)

Surface: `--surface`, top radius 16 px, `--shadow-2`, 16 px side padding. No
outer card, no teal band. In order:

1. Head, 48 px: position chip (filled `--zone`), name 21 px bold, one line,
   ellipsis; right a quantity chip in mono 21 px on `--zone-soft` ("6 Stk",
   or "2 Kisten · 12 Stk" for mixed units). "für {buyer}" only when it
   differs, 13 px, under the name. Badges "neu" / "Fenster vorbei" after the
   name.
2. Address, one line, 17 px, plain text (not a link). Postal code and town
   only when the town differs from the action's town; else they go to the
   accessible name.
3. Inline map (D17): Leaflet, raster OSM, full dock width minus gutters,
   140 px high, radius 8 px, one pin, zoom 17, no drag and no zoom by default
   (so it does not fight the dock's scroll). Tap opens the map at 60 vh with
   pan and zoom, a close button 48 px. Under the map: a small link "In
   OpenStreetMap öffnen" (`osmHref`, new tab). Without coordinates: no map
   box, a muted line "Adresse ohne Kartenpunkt" plus the OSM search link.
   Tiles under CSP `img-src` (slice 2, D17).
4. Secondary row, 48 px, gaps 8 px: "Navigation" (secondary, `navigationHref`
   as today), phone icon button 48×48 (only with a number; `tel:`),
   "Nicht da" (secondary; accessible name "Nicht angetroffen").
5. Primary: "Zugestellt", full width, 64 px, `--accent` fill with white text
   in both themes (fix the dark pastel), check icon. At least 16 px from the
   secondary row. y≈700–764: thumb zone.

Behaviour:

- On "Zugestellt": the row in the list turns into a done row in place, the
  dock swaps to the next open stop (instant under reduced motion, else a
  150 ms cross-fade), focus moves to the dock's name, the toast "{name}:
  zugestellt. Rückgängig" shows above the dock (not over it).
- Collapse: a 24 px grip at the dock top; drag down or tap collapses it to
  96 px (name, quantity, "Zugestellt") for scanning the list. State per
  session only.
- Closed window or cancelled order: the dock shows the reason line instead of
  the buttons, as today's copy.
- All done: the dock shows "Alle 7 zugestellt. Danke!" with "Gib der
  Aktionsleitung Bescheid" as text; the meter turns `--ok`.
- Offline: unchanged rule (no stops shown), the dock is not rendered.

### D. Bottom nav

- "Tour" (truck) first and active. A driver-only user gets "Tour" and "Mehr".

### Goes away

Edit mode with banner, "Fertig", "Abbrechen"; the grey contact panel; the
page H1 block; "Reihenfolge der Planung"; the window time in the eyebrow; the
window panel borders and the teal band; the "Zugestellt" text on done rows;
the address as link; the chevron.

### Sizes and tokens

Primary 64 px, secondary 48 px, list rows 56/48 px, labels 32 px. Text at
least 13 px, address 17 px, name in dock 21 px, quantity 21 px mono. Colours
from `leitsystem.css` only (`--zone`, `--zone-soft`, `--zone-line`,
`--accent`, `--ok`, `--warn`, `--surface*`, `--text-*`). Check both themes
and 360 px width.

## 4. Planner "Touren" (1440)

Screenshot `10-planner-1440.png`.

1. **Bug**: every stop shows "0 Boxen" while the driver sees "6 Stück" /
   "24 Stück". `tour-planner.tsx:1176` uses `drop.totalBoxes`; the driver uses
   `quantities(drop)`. Use `quantities(drop)` in both.
2. "Strecke –" in every lane is noise until coordinates exist; hide it.
3. "Vorschlag sortieren" and "Reihenfolge speichern" have equal weight. If
   the planner also saves on drop (parity with D16, a decision for the lead),
   drop "Reihenfolge speichern"; else make it primary only while the lane is
   dirty.
4. Delivered stops only get a green check; dim them like the driver view and
   keep them in place.
5. Disabled ↑/↓ at list ends look almost like enabled ones; hide them or show
   them without a border.
6. Replace the "Erster: … · Letzter: …" line with the load per window
   ("08–10: 3 Stopps, 42 Stk").
7. Empty "Nicht zugeordnet" lane: "Alle Stopps zugeordnet".
8. Two hint lines over the lanes (intro and "Wählen Sie Stopps aus …"): keep
   one.

## 5. Open questions (options for the lead)

1. Dock vs list-first: (a) fixed dock as above (recommended), (b) next stop
   only, list one swipe away, (c) interim scroll-into-view only.
2. Planner save: (a) save on drop with undo like the driver (recommended for
   consistency), (b) keep explicit "Reihenfolge speichern".
3. Driver role routing: (a) redirect `/app/` for driver-only users
   (recommended), (b) only add the bottom tab.

## Run notes

- Assessments: two isolated sub-agents; A worked from screenshots and code,
  B ran the detector.
- CLI detector: `my-tour.tsx`, `tour-planner.tsx`, `delivery/`: 0 findings.
- Browser overlay: blocked by CSP (`script-src 'self'`, no
  `wasm-unsafe-eval`); ran with `Page.setBypassCSP` in the test browser only,
  live server stopped with `--keep-inject`, pages reloaded.
- Snapshot in `.impeccable/critique/` not written: this file is the record.
