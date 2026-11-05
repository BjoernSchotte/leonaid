# `@leonaid/ui`

Shared, host-neutral open-code components for web and PWA. The shadcn/ui
configuration is fixed to Base UI and Lucide icons.

The tokens have three layers:

- unchanged Lions International brand primitives from the official
  [Brand Guidelines](https://www.lionsclubs.org/en/resources-for-members/brand-guidelines),
  including Yellow `#EBB700`, Purple `#7A2582` and Navy `#0D2240`, in
  `src/styles/tokens.css`;
- the "Leitsystem" semantic tokens in `src/styles/leitsystem.css`: surfaces
  (`--bg`, `--surface`, `--surface-2`), text (`--text`, `--text-2`,
  `--text-3`), `--accent`, status (`--ok`, `--warn`, `--danger`, `--info`),
  the rail (`--rail-*`), type, space, shape and motion scales, and the zone
  hues. `[data-zone="<navigation key>"]` on an area root sets `--zone-h`;
  `--zone`, `--zone-soft`, `--zone-line` and `--zone-ink` derive from it;
- `tokens.css` with the Lions brand primitives and a few component metrics.
  The pre-Leitsystem alias names are gone; `tools/ci/legacy_ui.py` in
  `./leonaid check` rejects them and Hugeicons or Base UI imports.

`src/styles/contrast.test.ts` (`bun run test:ui`) checks every text and control
pair, in light and dark and for every zone, against its WCAG target.

Components use only the semantic layer. This lets light and dark mode evolve
without rewriting business components or brand primitives. The switcher
supports `system`, `light` and `dark`, stores only this preference locally and,
in system mode, follows live changes of the operating system.

## Required patterns

New interfaces use the exported components from `@leonaid/ui` and no locally
rebuilt variants:

| Situation                  | Component/pattern                                            | Contract                                                                                                                                                                                                                                                                                                                                     |
| -------------------------- | ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Main and secondary actions | `Button`, `IconButton`                                       | at most one dominant primary action per page; danger always as text and color                                                                                                                                                                                                                                                                |
| Record status              | `StatusIcon`, `StatusLabel`                                  | shape carries the status, tone repeats it; `statusShape` is the only domain-status → shape map                                                                                                                                                                                                                                               |
| Secondary fact             | `Badge`                                                      | never the main record status                                                                                                                                                                                                                                                                                                                 |
| Progress                   | `Meter`                                                      | `role="meter"` with value, max and label; fill via CSSOM, never `style=`                                                                                                                                                                                                                                                                     |
| Person                     | `Avatar`                                                     | initials and a hue class bucket from the name; decorative unless labelled                                                                                                                                                                                                                                                                    |
| Keyboard hint              | `Kbd`                                                        | `aria-hidden`; ⌘/Strg per platform; subtle hints hide on touch-only devices                                                                                                                                                                                                                                                                  |
| Field with explanation     | `Field` (`FormField`), `Input`, `Textarea`, `Select`         | visible label, hint or error below the control (an error replaces the hint), linked via `aria-describedby`; `aria-invalid` on error                                                                                                                                                                                                          |
| On/off setting             | `Switch`                                                     | native checkbox with `role="switch"`; label, focus and keyboard stay native                                                                                                                                                                                                                                                                  |
| Views of one list          | `Tabs`, `TabPanel`                                           | roving tab stop on the selected tab: ←/→, Home/End move focus and select; set `idPrefix` on both to link tab and panel                                                                                                                                                                                                                       |
| Non-blocking result        | `ToastProvider` / `useToast`                                 | success, notice or error with an optional action; info/success polite, errors assertive; 5.2 s, paused on hover, focus and hidden page (a toast shown in a background tab is inserted at once, only its timer waits); F6 jumps to the newest toast; shown inside the topmost open `Modal`; a toast never replaces a persistent error message |
| Dialog                     | `Modal`                                                      | native `<dialog>` with `showModal()`: focus trap, inert background, Esc and backdrop close, focus returns to the opener                                                                                                                                                                                                                      |
| Blocking confirmation      | `ConfirmDialog`                                              | `Modal` as `alertdialog`; concrete effect in the description, ghost "Abbrechen" first                                                                                                                                                                                                                                                        |
| Business status            | `StatusMessage`                                              | callout with icon and text in addition to color; errors as `role="alert"`                                                                                                                                                                                                                                                                    |
| Failed load                | `ErrorState`                                                 | `role="alert"`, what failed and "Erneut versuchen" when a retry exists                                                                                                                                                                                                                                                                       |
| Loading                    | `SkeletonRows`                                               | `aria-hidden`; set `aria-busy` on the loading region                                                                                                                                                                                                                                                                                         |
| No results                 | `EmptyState`                                                 | explains the state and a sensible next step; `headingLevel={2}` when it replaces a page                                                                                                                                                                                                                                                      |
| Tabular data               | `DataTable` (renders the prototype `.table-wrap` / `.table`) | native table with caption; labelled, focusable scroll region because scrollbars are hidden; hand-written tables use the same `.table-wrap` (`role="region"`, `tabIndex={0}`, `aria-label`) and `.table` classes                                                                                                                              |
| Record list                | `ListView`                                                   | the prototype list: saved views, filter bar, keyboard rows (`j`/`k`, `x`, Enter), bulk bar and detail pane                                                                                                                                                                                                                                   |
| What to do next            | `NextStep`                                                   | zone-soft block with the consequence and exactly one primary action; only for roles that may act                                                                                                                                                                                                                                             |
| Read-only role             | `ReadOnlyNotice`                                             | "Nur lesen." callout with `role="note"` saying what the role can see; never rebuilt by hand                                                                                                                                                                                                                                                  |
| Dropping unsaved work      | `useDiscardDialog`                                           | one "Entwurf verwerfen?" question before a pane, edit mode or version change drops edits; `Sie` or `du` per surface                                                                                                                                                                                                                          |
| Charts                     | `ChartCanvas`, `ChartLegend`, `ChartTable`                   | Chart.js on a canvas with a legend that carries every value and the data as a table behind a disclosure                                                                                                                                                                                                                                      |
| Signed-in application      | `RailShell` (admin), `MobileShell` (PWA)                     | zone band and area name; rail, collapsed rail or bottom nav with "Mehr" sheet (admin); app bar and tab bar (PWA)                                                                                                                                                                                                                             |

Buttons follow the Leitsystem heights (`sm` 28, `md` 32, `lg` 44 px); on
the mobile layout (≤ 800 px) every interactive target is at least `44px` high. The global `:focus-visible`
ring stays in place. Pages start with a unique `h1`; dialogs have a title and a
description. Status must never be conveyed only through color or position.

## Component catalog

System admins reach the production-like catalog under `/admin/system/ui`. It
runs inside the real app shell, shows real identity and assignment data from
the running API and contains the states for actions, feedback, form fields,
table and empty state. This makes it the stable surface for accessibility and
visual regression tests as well.

## Icons

New code renders icons from [`lucide-react`](https://lucide.dev) through the
`Icon` adapter: `<Icon icon={Plus} />` at 14, 16 (default) or 20 px. Without
`label` the icon is `aria-hidden`; with `label` it becomes `role="img"` with
that accessible name. An icon never stands alone: an icon-only control is an
`IconButton`, whose required `label` becomes `aria-label` and `title`.
`Button`, `IconButton` and `Badge` take a Lucide icon component directly and
size it themselves.

Hugeicons and Base UI are gone; `./leonaid check` (tools/ci/legacy_ui.py)
rejects them and the old token aliases.

## Dependencies and license boundary

The exact versions stay pinned in `package.json` and `bun.lock`. License and
origin notices are in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
Product code may use only icons from `lucide-react`. Copied web SVGs or other
asset packages need their own license decision before they are added.
