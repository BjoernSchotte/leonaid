# `@leonaid/ui`

Shared, host-neutral open-code components for web and PWA. The shadcn/ui
configuration is fixed to Base UI and only the free Hugeicons packages.

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
- aliases in `tokens.css` that keep the older names (`--background`,
  `--primary`, `--muted`, `--sidebar`, ...) pointing at Leitsystem tokens until
  each component moves to the new names.

`src/styles/contrast.test.ts` (`bun run test:ui`) checks every text and control
pair, in light and dark and for every zone, against its WCAG target.

Components use only the semantic layer. This lets light and dark mode evolve
without rewriting business components or brand primitives. The switcher
supports `system`, `light` and `dark`, stores only this preference locally and,
in system mode, follows live changes of the operating system.

## Required patterns

New interfaces use the exported components from `@leonaid/ui` and no locally
rebuilt variants:

| Situation                  | Component/pattern            | Contract                                                                                                   |
| -------------------------- | ---------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Main and secondary actions | `Button`                     | at most one dominant primary action per page; danger always as text and color                              |
| Field with explanation     | `FormField`                  | visible label, short description, error directly at the field and via `aria-describedby`                   |
| Non-blocking result        | `ToastProvider` / `useToast` | success, notice or error; errors are announced urgently, a toast never replaces a persistent error message |
| Blocking confirmation      | `ConfirmDialog`              | concrete effect in the text, focus trap and focus return by Base UI                                        |
| Business status            | `StatusMessage`              | icon and text in addition to color                                                                         |
| No results                 | `EmptyState`                 | explains the state and a sensible next step                                                                |
| Tabular data               | `DataTable`                  | native table with caption; focusable horizontal scroll area on small displays                              |
| Signed-in application      | `AppShell`                   | role and current work context visible; desktop sidebar, mobile drawer or PWA tab bar                       |

All interactive targets are at least `44px` high. The global `:focus-visible`
ring stays in place. Pages start with a unique `h1`; dialogs have a title and a
description. Status must never be conveyed only through color or position.

## Component catalog

System admins reach the production-like catalog under `/admin/system/ui`. It
runs inside the real app shell, shows real identity and assignment data from
the running API and contains the states for actions, feedback, form fields,
table and empty state. This makes it the stable surface for accessibility and
visual regression tests as well.

## Dependencies and license boundary

The exact versions stay pinned in `package.json` and `bun.lock`. License and
origin notices are in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
Product code may use only icons from `@hugeicons/core-free-icons`. Hugeicons
Pro, copied web SVGs or other asset packages need their own license decision
before they are added.
