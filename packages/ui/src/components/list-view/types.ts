import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import type { OptionMenuOption } from "../option-menu";
import type { ListViewDefinition } from "./saved-views";

/**
 * A record property: filter chip, group header, row chip and inline edit in
 * one definition (Linear's "display property").
 */
export interface ListProperty<T> {
  readonly id: string;
  /** German label, e.g. "Status". */
  readonly label: string;
  readonly icon: LucideIcon;
  /** The row's value(s); option values, not labels. */
  readonly get: (row: T) => string | readonly string[];
  /** In display order; the group order follows it. */
  readonly options: readonly OptionMenuOption<string>[];
  /** Offered in the filter menu (default true). */
  readonly filterable?: boolean;
  /** Offered in "Gruppieren nach" (default true). */
  readonly groupable?: boolean;
  /**
   * Inline edit: `key` opens the option menu on the focused row (and is
   * listed in the shortcut help), a chip click does the same. `apply` gets
   * every checked row when the edited row is checked, otherwise just that
   * row. A rejected promise shows an error toast. Leave `edit` out for
   * people who may not change the property; the server decides anyway.
   */
  readonly edit?: {
    readonly key: string;
    readonly apply: (
      ids: readonly string[],
      value: string,
    ) => void | Promise<void>;
  };
  /** Chip in the row; leave it out to hide the property in rows. */
  readonly chip?: (row: T) => ReactNode;
}

export interface ListSort<T> {
  readonly id: string;
  readonly label: string;
  readonly compare: (a: T, b: T) => number;
}

/** The fixed row anatomy, left to right. */
export interface ListColumns<T> {
  /** A 14 px flag or icon before the name (keep its width stable). */
  readonly leading?: (row: T) => ReactNode;
  /** The name, weight 500. A mono number goes first (`.mono`). */
  readonly primary: (row: T) => ReactNode;
  /** text-3 meta; dropped when the list is narrower than 860 px. */
  readonly secondary?: (row: T) => ReactNode;
  /** Right-aligned tabular amount or date. */
  readonly trailing?: (row: T) => ReactNode;
}

export type ListStatus = "ready" | "loading" | "error";

export interface ListViewProps<T> {
  /** Stable list id: localStorage key `leonaid.views.<id>` and DOM ids. */
  readonly id: string;
  /** Page title (h1) and search placeholder ("<title> durchsuchen"). */
  readonly title: string;
  readonly entityLabel: { readonly one: string; readonly many: string };
  /** The rows the server returned for this account; nothing else is shown. */
  readonly rows: readonly T[];
  readonly getId: (row: T) => string;
  readonly columns: ListColumns<T>;
  readonly properties: readonly ListProperty<T>[];
  /** At least one; the first is the default. */
  readonly sorts: readonly ListSort<T>[];
  /** Built-in views as tabs; the first is the default. At least one. */
  readonly views: readonly ListViewDefinition[];
  /** Text the search box matches (case-insensitive substring). */
  readonly searchText: (row: T) => string;
  /** Pane heading and accessible names ("<title> auswählen"). */
  readonly detailTitle: (row: T) => string;
  /**
   * Pane body below the editable property rows. Without it, opening a row
   * only calls `onOpen` (e.g. to navigate to a separate page).
   */
  readonly renderDetail?: (row: T) => ReactNode;
  /** Called when a row opens (row) or the pane closes (null). */
  readonly onOpen?: (row: T | null) => void;
  /**
   * The row link's href (open in new tab, copy link). Default: this page
   * with `?open=<id>`.
   */
  readonly rowHref?: (row: T) => string;
  /** Extra buttons in the bulk bar; `clear` empties the selection. */
  readonly bulkActions?: (
    ids: readonly string[],
    clear: () => void,
  ) => ReactNode;
  /** Primary header action with keycap C. */
  readonly onCreate?: () => void;
  readonly createLabel?: string;
  /** Icon of the "Noch keine …" empty state. */
  readonly emptyIcon: LucideIcon;
  /** Header actions before the create button. */
  readonly headerExtra?: ReactNode;
  /** Content between toolbar and rows (quick add, callouts). */
  readonly beforeList?: ReactNode;
  readonly className?: string;
  /** "loading" shows skeleton rows, "error" the error state. */
  readonly status?: ListStatus;
  /** Shown with the error state as "Erneut versuchen". */
  readonly onRetry?: () => void;
  /**
   * Publishes the list's palette commands (views, filters, grouping,
   * selection, create). Pass the palette's `useContextCommands`; it is
   * called as a hook on every render, so it must never change.
   */
  readonly useCommands?: (commands: readonly ListCommand[]) => void;
}

/** A palette command; structurally the palette's `PaletteCommand`. */
export interface ListCommand {
  readonly id: string;
  readonly label: string;
  /** Palette section: the list title. */
  readonly group: string;
  readonly icon?: LucideIcon;
  /** Binding shown as keycaps. */
  readonly keys?: string;
  readonly keywords?: readonly string[];
  readonly run: () => void;
}
