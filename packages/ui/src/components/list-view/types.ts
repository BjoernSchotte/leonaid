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
  /**
   * Offered in "Gruppieren nach" (default true). A multi-valued property
   * groups each row under its first value only; consider `false`.
   */
  readonly groupable?: boolean;
  /**
   * Inline edit; leave it out for a read-only property (e.g. an invoice
   * status that only changes through explicit commands in the pane or the
   * bulk bar). People who may not change it get no `edit` either; the
   * server decides anyway.
   */
  readonly edit?: ListPropertyEdit<T>;
  /** Chip in the row; leave it out to hide the property in rows. */
  readonly chip?: (row: T) => ReactNode;
}

/** What `apply` reports: "cancelled" means nothing changed and no toast. */
export type ListEditOutcome = void | "cancelled";

export interface ListPropertyEdit<T> {
  /** Opens the option menu on the focused row; listed in the help. */
  readonly key: string;
  /**
   * The values that may be set on these rows (allowed transitions, rights).
   * Default: every option. An empty result shows a hint instead of a menu.
   */
  readonly options?: (
    rows: readonly T[],
  ) => readonly OptionMenuOption<string>[];
  /**
   * Applies the value to every checked row when the edited row is checked,
   * otherwise to that row. It may first ask for more (a note, a fresh
   * sign-in) and resolve "cancelled" when the person backs out: no toast.
   * Resolving otherwise shows a success toast, rejecting an error toast.
   * The rows are busy (`aria-busy`, no second edit) until it settles.
   */
  readonly apply: (
    ids: readonly string[],
    value: string,
  ) => ListEditOutcome | Promise<ListEditOutcome>;
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

export interface ListViewBaseProps<T> {
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

/**
 * How a row opens. At least one is required, so a row link always leads
 * somewhere:
 * - `renderDetail`: the pane (desktop) or sheet (phone), `?open=<id>`;
 * - `onOpen` alone: the page handles it (e.g. navigates);
 * - `rowHref` alone: a plain link to the record's page.
 */
export type ListOpenProps<T> =
  | {
      /** Pane body below the editable property rows. */
      readonly renderDetail: (row: T) => ReactNode;
      /** Called when a row opens (row) or the pane closes (null). */
      readonly onOpen?: (row: T | null) => void;
      /** Link target for new tab / copy; default this page + `?open=<id>`. */
      readonly rowHref?: (row: T) => string;
    }
  | {
      readonly renderDetail?: undefined;
      readonly onOpen: (row: T | null) => void;
      readonly rowHref?: (row: T) => string;
    }
  | {
      readonly renderDetail?: undefined;
      readonly onOpen?: (row: T | null) => void;
      readonly rowHref: (row: T) => string;
    };

export type ListViewProps<T> = ListViewBaseProps<T> & ListOpenProps<T>;

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
