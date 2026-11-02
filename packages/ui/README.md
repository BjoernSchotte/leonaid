# `@leonaid/ui`

Shared, host-neutral open-code components for web and PWA. The shadcn/ui
configuration is fixed to Base UI and only the free Hugeicons packages.

`src/styles/tokens.css` separates two layers:

- unchanged Lions International brand primitives from the official
  [Brand Guidelines](https://www.lionsclubs.org/en/resources-for-members/brand-guidelines),
  including Blue `#00338D`, Yellow `#EBB700`, Purple `#7A2582` and Navy
  `#0D2240`;
- semantic LeonAid tokens such as `--background`, `--surface`, `--primary`,
  `--focus`, `--success` and `--sidebar`.

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
