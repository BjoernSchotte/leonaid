import {
  Bookmark,
  BookmarkPlus,
  CheckSquare,
  ChevronDown,
  FilterX,
  Layers,
  ListFilter as ListFilterIcon,
  Plus,
  SearchX,
  SquareX,
  X,
} from "lucide-react";
import {
  memo,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import { useHotkeys } from "../../keyboard/use-hotkeys";
import { isTypingTarget, type HotkeyBinding } from "../../keyboard/hotkeys";
import { cn } from "../../lib/utils";
import { Button } from "../button";
import { EmptyState } from "../empty-state";
import { Kbd } from "../kbd";
import { OptionMenu } from "../option-menu";
import { Popover } from "../popover";
import { SkeletonRows } from "../skeleton-rows";
import { ErrorState } from "../status-message";
import { useOptionalToast } from "../toast";
import { DetailPane } from "./detail-pane";
import { FilterBar } from "./filter-bar";
import {
  isDirty,
  parseListState,
  withoutListParams,
  sanitizeFilters,
  sanitizeView,
  readSavedViews,
  serializeListState,
  stateForView,
  URL_KEYS,
  writeSavedViews,
  type ListFilter,
  type ListSchema,
  type ListState,
  type ListViewDefinition,
} from "./saved-views";
import type {
  ListColumns,
  ListCommand,
  ListProperty,
  ListViewProps,
} from "./types";

/** Help overlay section of every list binding. */
export const LIST_HOTKEY_GROUP = "Liste";

type Menu =
  | { readonly kind: "filter-prop" }
  | { readonly kind: "filter-values"; readonly prop: string }
  | {
      readonly kind: "edit";
      readonly prop: string;
      readonly rowId: string;
      /** The rows the edit applies to, fixed when the menu opens. */
      readonly ids: readonly string[];
    }
  | { readonly kind: "save" };

interface Group<T> {
  readonly key: string;
  readonly label: string;
  readonly icon: ReactNode;
  readonly rows: readonly T[];
}

const ALL_GROUP = "__all";

/** Without a palette the list publishes no commands. */
function useNoCommands(_commands: readonly ListCommand[]): void {}

/* The palette closes and hands focus back first; open menus after that. */
const AFTER_PALETTE_MS = 10;

function valuesOf<T>(prop: ListProperty<T>, row: T): readonly string[] {
  const value = prop.get(row);
  return typeof value === "string" ? [value] : value;
}

function optionLabel<T>(prop: ListProperty<T>, value: string): string {
  return prop.options.find((option) => option.value === value)?.label ?? value;
}

/** Calls the latest function without changing identity (row memo). */
function useStableCallback<A extends unknown[], R>(
  fn: (...args: A) => R,
): (...args: A) => R {
  const ref = useRef(fn);
  useLayoutEffect(() => {
    ref.current = fn;
  });
  return useCallback((...args: A) => ref.current(...args), []);
}

/* ---------- row ---------- */

interface RowContext<T> {
  readonly columns: ListColumns<T>;
  readonly chips: readonly ListProperty<T>[];
  readonly detailTitle: (row: T) => string;
  readonly onToggle: (id: string) => void;
  readonly onFocusRow: (id: string) => void;
  readonly onLinkClick: (
    id: string,
    event: MouseEvent<HTMLAnchorElement>,
  ) => void;
  readonly onChip: (
    propId: string,
    id: string,
    chip: HTMLButtonElement,
  ) => void;
  readonly registerRow: (id: string, element: HTMLAnchorElement | null) => void;
}

interface RowProps<T> {
  readonly row: T;
  readonly id: string;
  readonly href: string;
  readonly focused: boolean;
  readonly open: boolean;
  readonly checked: boolean;
  /** An edit on this row is being saved. */
  readonly busy: boolean;
  readonly tabbable: boolean;
  readonly groupBy: string | null;
  readonly context: RowContext<T>;
}

function ListRowInner<T>({
  busy,
  checked,
  context,
  focused,
  groupBy,
  href,
  id,
  open,
  row,
  tabbable,
}: RowProps<T>) {
  const { columns } = context;
  return (
    <li
      aria-busy={busy || undefined}
      className={cn(
        "row",
        focused && "is-focused",
        open && "is-selected",
        checked && "is-checked",
        busy && "is-busy",
      )}
    >
      <input
        aria-label={`${context.detailTitle(row)} auswählen`}
        checked={checked}
        className="row-check"
        onChange={() => context.onToggle(id)}
        tabIndex={-1}
        type="checkbox"
      />
      {columns.leading ? (
        <span className="row-leading">{columns.leading(row)}</span>
      ) : null}
      <a
        aria-current={open ? "true" : undefined}
        className="row-link"
        href={href}
        onClick={(event) => context.onLinkClick(id, event)}
        onFocus={() => context.onFocusRow(id)}
        ref={(element) => context.registerRow(id, element)}
        tabIndex={tabbable ? 0 : -1}
      >
        <span className="row-primary">{columns.primary(row)}</span>
        {columns.secondary ? (
          <span className="row-secondary">{columns.secondary(row)}</span>
        ) : null}
      </a>
      <span className="row-chips">
        {context.chips.map((prop) =>
          prop.edit ? (
            <button
              className={cn(
                "prop-chip",
                "is-editable",
                groupBy === prop.id && "is-grouped",
              )}
              data-chip={prop.id}
              key={prop.id}
              onClick={(event) =>
                context.onChip(prop.id, id, event.currentTarget)
              }
              tabIndex={-1}
              title={`${prop.label} ändern (${prop.edit.key.toUpperCase()})`}
              type="button"
            >
              {prop.chip?.(row)}
              <span className="sr-only">{`: ${prop.label} ändern`}</span>
            </button>
          ) : (
            <span
              className={cn("prop-chip", groupBy === prop.id && "is-grouped")}
              key={prop.id}
            >
              {prop.chip?.(row)}
            </span>
          ),
        )}
      </span>
      {columns.trailing ? (
        <span className="row-trailing">{columns.trailing(row)}</span>
      ) : null}
    </li>
  );
}

/** Re-renders only when its row, its state or the list setup changes. */
const ListRow = memo(ListRowInner) as typeof ListRowInner;

/* ---------- list view ---------- */

/**
 * Linear-style record list: saved views, filter chips, grouping, sort,
 * keyboard (j/k, Enter, Esc, x, f, /, property letters), inline edits, bulk
 * selection and a detail pane (a full-screen sheet on phones). Filters and
 * the active view live in the URL query; saved views in localStorage.
 *
 * It only shows the rows it is given: authorization stays on the server.
 * Needs a HotkeyProvider above it; toasts appear when a ToastProvider is
 * there.
 *
 * Contract:
 * - One list per page: the URL keys (view, f.*, group, sort, q, open) and
 *   the list keys (j/k/x/…) are page-wide.
 * - Keep `columns`, `properties`, `sorts`, `views`, `getId`, `detailTitle`
 *   and `searchText` stable (module constants or useMemo/useCallback). They
 *   are memo inputs: a new identity re-renders or re-derives every row.
 * - Grouping by a property whose `get` returns several values files each
 *   row under its first value; filtering matches any value.
 */
export function ListView<T>(props: ListViewProps<T>) {
  const {
    columns,
    detailTitle,
    entityLabel,
    getId,
    properties,
    renderDetail,
    rows,
    searchText,
    sorts,
    title,
  } = props;
  const toast = useOptionalToast();
  const headingId = useId();
  const viewNameId = useId();

  /* ----- schema and views ----- */
  const [savedViews, setSavedViews] = useState<ListViewDefinition[]>(() =>
    readSavedViews(props.id).filter(
      (saved) => !props.views.some((view) => view.id === saved.id),
    ),
  );
  const propertyById = useMemo(
    () => new Map(properties.map((prop) => [prop.id, prop])),
    [properties],
  );
  const filterable = useMemo(
    () => properties.filter((prop) => prop.filterable !== false),
    [properties],
  );
  const groupable = useMemo(
    () => properties.filter((prop) => prop.groupable !== false),
    [properties],
  );
  const editable = useMemo(
    () => properties.filter((prop) => prop.edit),
    [properties],
  );
  const chipProps = useMemo(
    () => properties.filter((prop) => prop.chip),
    [properties],
  );
  /*
   * Options that come from the server may still be loading: every property
   * while `status` is "loading", or one marked `optionsPending`. Filter
   * values on pending properties are kept as given (and written back to the
   * URL unchanged); an empty option list on a ready list is real data.
   * The schema is rebuilt only when ids, option values or pending flags
   * change, not for every new `properties` object.
   */
  const loading = props.status === "loading";
  const schemaSignature = JSON.stringify([
    filterable.map((prop) => [
      prop.id,
      loading || prop.optionsPending === true,
      prop.options.map((option) => option.value),
    ]),
    groupable.map((prop) => prop.id),
    sorts.map((sort) => sort.id),
  ]);
  const fieldSchema = useMemo<Omit<ListSchema, "views">>(
    () => ({
      filterable: new Map(
        filterable.map((prop) => [
          prop.id,
          new Set(prop.options.map((option) => option.value)),
        ]),
      ),
      pending: new Set(
        filterable
          .filter((prop) => loading || prop.optionsPending === true)
          .map((prop) => prop.id),
      ),
      groupable: new Set(groupable.map((prop) => prop.id)),
      sorts: new Set(sorts.map((sort) => sort.id)),
    }),
    // The signature covers everything the schema is built from.
    [schemaSignature],
  );
  /* Saved views are checked against today's properties and sorts. */
  const allViews = useMemo(
    () => [
      ...props.views,
      ...savedViews.map((view) =>
        sanitizeView(view, fieldSchema, sorts[0]?.id ?? view.sort),
      ),
    ],
    [props.views, savedViews, fieldSchema, sorts],
  );
  const schema = useMemo<ListSchema>(
    () => ({ ...fieldSchema, views: allViews }),
    [fieldSchema, allViews],
  );

  /* ----- state (mirrored in the URL) ----- */
  const [state, setState] = useState<ListState>(() =>
    parseListState(window.location.search, schema),
  );
  const pushNext = useRef(false);
  const update = useCallback((patch: Partial<ListState>, push = false) => {
    if (push) pushNext.current = true;
    setState((current) => ({ ...current, ...patch }));
  }, []);

  /*
   * Once options arrive (or change): an untouched list re-reads the URL,
   * which still holds the pending values as given, so stale-only filters
   * fall back to the view. A list the person changed drops the values the
   * options do not offer.
   */
  const untouched = useRef<ListState | null>(state);
  useEffect(() => {
    setState((current) => {
      if (current === untouched.current) {
        const reparsed = parseListState(window.location.search, schema);
        if (JSON.stringify(reparsed) === JSON.stringify(current)) {
          return current;
        }
        untouched.current = reparsed;
        return reparsed;
      }
      const filters = sanitizeFilters(current.filters, fieldSchema);
      return filters === current.filters ? current : { ...current, filters };
    });
    // Only the options matter here; schema follows fieldSchema.
  }, [fieldSchema]);

  useEffect(() => {
    const next = serializeListState(window.location.search, state, schema);
    const push = pushNext.current;
    pushNext.current = false;
    if (next === window.location.search) return;
    const url = `${window.location.pathname}${next}${window.location.hash}`;
    if (push) window.history.pushState(window.history.state, "", url);
    else window.history.replaceState(window.history.state, "", url);
  }, [state, schema]);

  const schemaRef = useRef(schema);
  schemaRef.current = schema;
  useEffect(() => {
    const onPopState = () =>
      setState(parseListState(window.location.search, schemaRef.current));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const baseView =
    allViews.find((view) => view.id === state.viewId) ?? allViews[0]!;
  const dirty = isDirty(state, baseView);

  /* ----- local UI state ----- */
  const [compact, setCompact] = useState(false);
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  /* Synchronous twin of `busy` for the double-submit guard. */
  const busyRef = useRef(new Set<string>());
  const rootRef = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(state.openId);
  const [menu, setMenu] = useState<Menu | null>(null);

  const searchRef = useRef<HTMLInputElement>(null);
  const filterButton = useRef<HTMLButtonElement>(null);
  const saveButton = useRef<HTMLButtonElement>(null);
  const filterAnchor = useRef<HTMLElement | null>(null);
  const editAnchor = useRef<HTMLElement | null>(null);
  const rowRefs = useRef(new Map<string, HTMLAnchorElement>());
  const paneProps = useRef(new Map<string, HTMLButtonElement>());

  /* ----- derive ----- */
  const visible = useMemo(() => {
    const needle = state.query.trim().toLowerCase();
    const sort = sorts.find((item) => item.id === state.sort) ?? sorts[0];
    const result = rows.filter(
      (row) =>
        state.filters.every((filter) => {
          const prop = propertyById.get(filter.prop);
          if (!prop || filter.values.length === 0) return true;
          return valuesOf(prop, row).some((value) =>
            filter.values.includes(value),
          );
        }) &&
        (!needle || searchText(row).toLowerCase().includes(needle)),
    );
    return sort ? result.sort(sort.compare) : result;
  }, [
    rows,
    sorts,
    searchText,
    state.filters,
    state.query,
    state.sort,
    propertyById,
  ]);

  const groups = useMemo<Group<T>[]>(() => {
    const prop = state.groupBy ? propertyById.get(state.groupBy) : undefined;
    if (!prop)
      return [{ key: ALL_GROUP, label: "", icon: null, rows: visible }];
    const byKey = new Map<string, T[]>();
    for (const row of visible) {
      const key = valuesOf(prop, row)[0] ?? "–";
      const list = byKey.get(key);
      if (list) list.push(row);
      else byKey.set(key, [row]);
    }
    const order = new Map(
      prop.options.map((option, index) => [option.value, index]),
    );
    return [...byKey.entries()]
      .sort(
        ([a], [b]) =>
          (order.get(a) ?? Number.MAX_SAFE_INTEGER) -
          (order.get(b) ?? Number.MAX_SAFE_INTEGER),
      )
      .map(([key, groupRows]) => {
        const option = prop.options.find((item) => item.value === key);
        return {
          key,
          label: option?.label ?? key,
          icon: option?.icon ?? null,
          rows: groupRows,
        };
      });
  }, [visible, state.groupBy, propertyById]);

  /* Collapsed state belongs to one grouping, not to equal option values. */
  const collapseKey = (key: string) => `${state.groupBy ?? ""}:${key}`;
  const flatIds = useMemo(
    () =>
      groups
        .filter(
          (group) => !collapsed.has(`${state.groupBy ?? ""}:${group.key}`),
        )
        .flatMap((group) => group.rows.map(getId)),
    [groups, collapsed, getId, state.groupBy],
  );
  const rowById = useMemo(
    () => new Map(rows.map((row) => [getId(row), row])),
    [rows, getId],
  );
  /*
   * Selection acts only on rows the person can see: checked rows hidden by
   * a filter, the search or a collapsed group are left alone (and counted
   * as hidden in the bulk bar).
   */
  const checkedIds = useMemo(
    () => flatIds.filter((id) => checked.has(id)),
    [checked, flatIds],
  );
  const hiddenChecked = checked.size - checkedIds.length;
  /* Rows that are gone (deleted, no longer returned) drop out. */
  useEffect(() => {
    setChecked((current) => {
      const next = [...current].filter((id) => rowById.has(id));
      return next.length === current.size ? current : new Set(next);
    });
  }, [rowById]);
  const openRow =
    renderDetail && state.openId ? (rowById.get(state.openId) ?? null) : null;

  /* ----- open / close ----- */
  const onOpenRef = useRef(props.onOpen);
  onOpenRef.current = props.onOpen;
  const lastOpen = useRef<string | null>(null);
  useEffect(() => {
    const id = openRow ? state.openId : null;
    if (id === lastOpen.current) return;
    lastOpen.current = id;
    onOpenRef.current?.(openRow);
  }, [openRow, state.openId]);

  const focusRow = useCallback((id: string | null) => {
    if (!id) return;
    setFocusedId(id);
    const element = rowRefs.current.get(id);
    element?.focus();
    element?.scrollIntoView?.({ block: "nearest" });
  }, []);

  const openById = (id: string) => {
    setFocusedId(id);
    if (!renderDetail) {
      const row = rowById.get(id);
      if (row) props.onOpen?.(row);
      return;
    }
    update({ openId: id }, state.openId === null);
  };

  const closePane = () => {
    const previous = state.openId;
    // Replace, not push: opening pushed the entry, so Back after a close
    // leaves the list instead of reopening the pane.
    update({ openId: null });
    // Return focus to the row unless something else took it meanwhile.
    window.setTimeout(() => {
      const active = document.activeElement;
      if (
        !active ||
        active === document.body ||
        active.id === "main" ||
        active.closest(".pane")
      ) {
        focusRow(previous);
      }
    }, 0);
  };

  const move = (delta: number) => {
    if (flatIds.length === 0) return;
    const index = focusedId ? flatIds.indexOf(focusedId) : -1;
    const next =
      flatIds[
        index === -1
          ? 0
          : Math.max(0, Math.min(flatIds.length - 1, index + delta))
      ]!;
    focusRow(next);
    if (openRow) update({ openId: next });
  };

  const toggleChecked = useCallback((id: string) => {
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);
  const clearChecked = useCallback(() => setChecked(new Set()), []);

  /* ----- edits ----- */
  const editTargets = (rowId: string) =>
    checkedIds.includes(rowId) ? checkedIds : [rowId];

  const editOptions = (prop: ListProperty<T>, ids: readonly string[]) =>
    prop.edit?.options
      ? prop.edit.options(
          ids.flatMap((id) => {
            const row = rowById.get(id);
            return row === undefined ? [] : [row];
          }),
        )
      : prop.options;

  const openEdit = (
    propId: string,
    rowId: string | null,
    anchor?: HTMLElement,
  ) => {
    const prop = propertyById.get(propId);
    if (!prop?.edit) return;
    if (!rowId || !rowById.has(rowId)) {
      toast?.show({
        title: "Erst eine Zeile mit J/K auswählen.",
        tone: "info",
      });
      return;
    }
    const ids = editTargets(rowId);
    if (ids.some((id) => busy.has(id))) {
      toast?.show({
        title: "Die letzte Änderung wird noch gespeichert.",
        tone: "info",
      });
      return;
    }
    if (editOptions(prop, ids).length === 0) {
      toast?.show({
        title: `${prop.label} lässt sich hier nicht ändern.`,
        tone: "info",
      });
      return;
    }
    const rowChip = [
      ...(rowRefs.current
        .get(rowId)
        ?.closest(".row")
        ?.querySelectorAll<HTMLElement>("[data-chip]") ?? []),
    ].find((chip) => chip.dataset.chip === propId);
    editAnchor.current =
      anchor ??
      rowChip ??
      rowRefs.current.get(rowId) ??
      paneProps.current.get(propId) ??
      null;
    setMenu({ kind: "edit", prop: propId, rowId, ids });
  };

  const setRowsBusy = (ids: readonly string[], on: boolean) =>
    setBusy((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });

  const applyEdit = async (
    prop: ListProperty<T>,
    ids: readonly string[],
    value: string,
  ) => {
    setMenu(null);
    // A second pick while the first is saving is ignored, not sent twice.
    if (!prop.edit || ids.some((id) => busyRef.current.has(id))) return;
    for (const id of ids) busyRef.current.add(id);
    setRowsBusy(ids, true);
    const label = optionLabel(prop, value);
    try {
      const outcome = await prop.edit.apply(ids, value);
      if (outcome === "cancelled") return;
      toast?.show({
        title:
          ids.length > 1
            ? `${prop.label} bei ${ids.length} Einträgen: ${label}`
            : `${prop.label}: ${label}`,
        tone: "success",
      });
    } catch {
      toast?.show({
        title: `${prop.label} wurde nicht geändert.`,
        description: "Bitte versuchen Sie es erneut.",
        tone: "error",
      });
    } finally {
      for (const id of ids) busyRef.current.delete(id);
      setRowsBusy(ids, false);
    }
  };

  /* ----- views and filters ----- */
  const applyView = (view: ListViewDefinition) =>
    setState((current) => stateForView(view, current.openId));

  const setFilters = (filters: readonly ListFilter[]) => update({ filters });

  const toggleFilterValue = (propId: string, value: string) => {
    const existing = state.filters.find((filter) => filter.prop === propId);
    if (!existing) {
      setFilters([...state.filters, { prop: propId, values: [value] }]);
      return;
    }
    const values = existing.values.includes(value)
      ? existing.values.filter((item) => item !== value)
      : [...existing.values, value];
    setFilters(
      values.length
        ? state.filters.map((filter) =>
            filter.prop === propId ? { ...filter, values } : filter,
          )
        : state.filters.filter((filter) => filter.prop !== propId),
    );
  };

  const saveView = (label: string) => {
    const view: ListViewDefinition = {
      id: `c${Date.now().toString(36)}`,
      label,
      filters: state.filters,
      groupBy: state.groupBy,
      sort: state.sort,
      custom: true,
    };
    const next = [...savedViews, view];
    setSavedViews(next);
    setState((current) => ({ ...current, viewId: view.id }));
    if (writeSavedViews(props.id, next)) {
      toast?.show({
        title: `Ansicht „${label}“ gespeichert.`,
        tone: "success",
      });
    } else {
      toast?.show({
        title: `Ansicht „${label}“ gilt nur bis zum Neuladen.`,
        description:
          "Der Browser erlaubt keine Speicherung. Prüfen Sie die Einstellungen für Website-Daten.",
        tone: "error",
      });
    }
  };

  const deleteView = (id: string) => {
    const next = savedViews.filter((view) => view.id !== id);
    setSavedViews(next);
    writeSavedViews(props.id, next);
    if (state.viewId === id) applyView(props.views[0]!);
  };

  /* ----- keyboard ----- */
  /* Esc leaves fields of this list only; other fields keep their Esc. */
  const listField = (): HTMLElement | null => {
    const active = document.activeElement;
    return active instanceof HTMLElement &&
      isTypingTarget(active) &&
      rootRef.current?.contains(active)
      ? active
      : null;
  };
  const bindings: HotkeyBinding[] = [
    {
      keys: "j",
      label: "Nächste Zeile",
      group: LIST_HOTKEY_GROUP,
      run: () => move(1),
    },
    {
      keys: "k",
      label: "Vorherige Zeile",
      group: LIST_HOTKEY_GROUP,
      run: () => move(-1),
    },
    {
      keys: "arrowdown",
      label: "Nächste Zeile",
      group: LIST_HOTKEY_GROUP,
      hidden: true,
      run: () => move(1),
    },
    {
      keys: "arrowup",
      label: "Vorherige Zeile",
      group: LIST_HOTKEY_GROUP,
      hidden: true,
      run: () => move(-1),
    },
    {
      keys: "enter",
      label: "Zeile öffnen",
      group: LIST_HOTKEY_GROUP,
      run: () => {
        if (focusedId && rowById.has(focusedId)) openById(focusedId);
      },
    },
    {
      keys: "x",
      label: "Zeile auswählen",
      group: LIST_HOTKEY_GROUP,
      run: () =>
        focusedId && rowById.has(focusedId) && toggleChecked(focusedId),
    },
    {
      keys: "/",
      label: "In der Liste suchen",
      group: LIST_HOTKEY_GROUP,
      run: () => searchRef.current?.focus(),
    },
    {
      keys: "f",
      label: "Filter hinzufügen",
      group: LIST_HOTKEY_GROUP,
      run: () => setMenu({ kind: "filter-prop" }),
    },
    {
      keys: "escape",
      label: "Detail schließen / Auswahl aufheben",
      group: LIST_HOTKEY_GROUP,
      // Also clears checked rows that are all hidden (no bulk bar shown).
      when: () => listField() !== null || openRow !== null || checked.size > 0,
      run: () => {
        const active = document.activeElement;
        if (active === searchRef.current) {
          searchRef.current?.blur();
          focusRow(focusedId ?? flatIds[0] ?? null);
          return;
        }
        // Esc in another field of the list only leaves the field.
        const field = listField();
        if (field) {
          field.blur();
          return;
        }
        if (openRow) closePane();
        else clearChecked();
      },
    },
    ...editable.map(
      (prop): HotkeyBinding => ({
        keys: prop.edit!.key,
        label: `${prop.label} ändern`,
        group: LIST_HOTKEY_GROUP,
        run: () => openEdit(prop.id, focusedId),
      }),
    ),
    ...(props.onCreate
      ? [
          {
            keys: "c",
            label: props.createLabel ?? "Neu anlegen",
            group: LIST_HOTKEY_GROUP,
            run: () => props.onCreate?.(),
          },
        ]
      : []),
  ];
  useHotkeys(bindings);

  /* ----- palette ----- */
  const openMenuSoon = (next: Menu) =>
    window.setTimeout(() => setMenu(next), AFTER_PALETTE_MS);
  const commands: ListCommand[] = [
    ...allViews.map(
      (view): ListCommand => ({
        id: `list:${props.id}:view:${view.id}`,
        label: `Ansicht: ${view.label}`,
        group: title,
        icon: Bookmark,
        run: () => applyView(view),
      }),
    ),
    {
      id: `list:${props.id}:filter`,
      label: "Filter hinzufügen",
      group: title,
      icon: ListFilterIcon,
      keys: "f",
      run: () => openMenuSoon({ kind: "filter-prop" }),
    },
    ...filterable.map(
      (prop): ListCommand => ({
        id: `list:${props.id}:filter:${prop.id}`,
        label: `Filtern nach ${prop.label}`,
        group: title,
        icon: ListFilterIcon,
        run: () => {
          filterAnchor.current = filterButton.current;
          openMenuSoon({ kind: "filter-values", prop: prop.id });
        },
      }),
    ),
    ...(state.filters.length > 0
      ? [
          {
            id: `list:${props.id}:filter-clear`,
            label: "Filter zurücksetzen",
            group: title,
            icon: FilterX,
            run: () => setFilters([]),
          },
        ]
      : []),
    ...groupable.map(
      (prop): ListCommand => ({
        id: `list:${props.id}:group:${prop.id}`,
        label: `Gruppieren nach ${prop.label}`,
        group: title,
        icon: Layers,
        run: () => update({ groupBy: prop.id }),
      }),
    ),
    ...(flatIds.length > 0
      ? [
          {
            id: `list:${props.id}:select-all`,
            label: `Alle ${entityLabel.many} auswählen`,
            group: title,
            icon: CheckSquare,
            run: () => setChecked(new Set(flatIds)),
          },
        ]
      : []),
    ...(checked.size > 0
      ? [
          {
            id: `list:${props.id}:select-none`,
            label: "Auswahl aufheben",
            group: title,
            icon: SquareX,
            run: clearChecked,
          },
        ]
      : []),
    ...(props.onCreate
      ? [
          {
            id: `list:${props.id}:create`,
            label: props.createLabel ?? "Neu anlegen",
            group: title,
            icon: Plus,
            keys: "c",
            run: () => props.onCreate?.(),
          },
        ]
      : []),
  ];
  // A hook passed as a prop: fixed at mount, so the hook order never changes.
  const [useCommands] = useState(() => props.useCommands ?? useNoCommands);
  const warnedCommands = useRef(false);
  if (
    (props.useCommands ?? useNoCommands) !== useCommands &&
    !warnedCommands.current
  ) {
    warnedCommands.current = true;
    console.warn(
      "ListView: useCommands changed after mount; the first one stays in use.",
    );
  }
  useCommands(commands);

  /* ----- rows ----- */
  const onLinkClick = useStableCallback(
    (id: string, event: MouseEvent<HTMLAnchorElement>) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey)
        return;
      if (!renderDetail && !props.onOpen) return;
      event.preventDefault();
      openById(id);
    },
  );
  const onChip = useStableCallback(
    (propId: string, id: string, chip: HTMLButtonElement) => {
      setFocusedId(id);
      openEdit(propId, id, chip);
    },
  );
  const registerRow = useCallback(
    (id: string, element: HTMLAnchorElement | null) => {
      if (element) rowRefs.current.set(id, element);
      else if (rowRefs.current.get(id)?.isConnected === false) {
        rowRefs.current.delete(id);
      }
    },
    [],
  );
  const rowContext = useMemo<RowContext<T>>(
    () => ({
      columns,
      chips: chipProps,
      detailTitle,
      onToggle: toggleChecked,
      onFocusRow: setFocusedId,
      onLinkClick,
      onChip,
      registerRow,
    }),
    [
      columns,
      chipProps,
      detailTitle,
      toggleChecked,
      onLinkClick,
      onChip,
      registerRow,
    ],
  );

  /*
   * The default href names the record only (page params plus ?open=<id>),
   * not the search or filters: it stays the same string while typing, so
   * the memoised rows do not re-render per keystroke. A plain click keeps
   * the current filters because it is handled in place.
   */
  const pageSearch = withoutListParams(window.location.search);
  const hrefBase = `${window.location.pathname}${pageSearch}${pageSearch ? "&" : "?"}${URL_KEYS.open}=`;
  const hrefFor = props.rowHref
    ? props.rowHref
    : (row: T) => `${hrefBase}${encodeURIComponent(getId(row))}`;
  const tabbableId =
    focusedId && flatIds.includes(focusedId) ? focusedId : (flatIds[0] ?? null);

  /* ----- render ----- */
  const status = props.status ?? "ready";
  const count = visible.length;
  const total = rows.length;
  const filterProp =
    menu?.kind === "filter-values" ? propertyById.get(menu.prop) : undefined;
  const editProp =
    menu?.kind === "edit" ? propertyById.get(menu.prop) : undefined;
  const editRow = menu?.kind === "edit" ? rowById.get(menu.rowId) : undefined;
  const closeMenu = useCallback(() => setMenu(null), []);

  let body: ReactNode;
  if (status === "error") {
    body = (
      <ErrorState
        onRetry={props.onRetry}
        title="Die Liste konnte nicht geladen werden"
      >
        Der Server hat nicht geantwortet. Ihre Filter bleiben erhalten. Prüfen
        Sie die Verbindung und versuchen Sie es erneut.
      </ErrorState>
    );
  } else if (status === "loading") {
    body = <SkeletonRows rows={8} />;
  } else if (count === 0) {
    body = (
      <EmptyState
        action={
          total === 0 && props.onCreate ? (
            <Button icon={Plus} onClick={props.onCreate} variant="primary">
              {props.createLabel ?? "Neu anlegen"}
            </Button>
          ) : total > 0 ? (
            <Button
              onClick={() => update({ filters: [], query: "" })}
              variant="secondary"
            >
              Filter und Suche zurücksetzen
            </Button>
          ) : undefined
        }
        description={
          total === 0
            ? "Sobald die ersten Einträge da sind, erscheinen sie hier."
            : "Entfernen Sie einen Filter oder ändern Sie den Suchbegriff."
        }
        headingLevel={2}
        icon={total === 0 ? props.emptyIcon : SearchX}
        title={
          total === 0
            ? `Noch keine ${entityLabel.many}`
            : `Keine ${entityLabel.many} passen zu dieser Ansicht`
        }
      />
    );
  } else {
    body = groups.map((group) => {
      const groupKey = collapseKey(group.key);
      const isCollapsed = collapsed.has(groupKey);
      return (
        <section
          aria-label={group.label || title}
          className="group"
          key={group.key}
        >
          {group.label ? (
            <h2 className="group-header">
              <button
                aria-expanded={!isCollapsed}
                onClick={() =>
                  setCollapsed((current) => {
                    const next = new Set(current);
                    if (next.has(groupKey)) next.delete(groupKey);
                    else next.add(groupKey);
                    return next;
                  })
                }
                type="button"
              >
                <ChevronDown
                  aria-hidden="true"
                  className="group-chevron"
                  size={14}
                />
                {group.icon ? (
                  <span className="group-icon">{group.icon}</span>
                ) : null}
                <span>{group.label}</span>
                <span className="group-count num">{group.rows.length}</span>
              </button>
            </h2>
          ) : null}
          {!isCollapsed ? (
            <ul className="rows">
              {group.rows.map((row) => {
                const id = getId(row);
                return (
                  <ListRow<T>
                    busy={busy.has(id)}
                    checked={checked.has(id)}
                    context={rowContext}
                    focused={id === focusedId}
                    groupBy={state.groupBy}
                    href={hrefFor(row)}
                    id={id}
                    key={id}
                    open={id === state.openId && openRow !== null}
                    row={row}
                    tabbable={id === tabbableId}
                  />
                );
              })}
            </ul>
          ) : null}
        </section>
      );
    });
  }

  return (
    <div
      ref={rootRef}
      className={cn(
        "listview",
        openRow && "has-pane",
        compact && "is-compact",
        props.className,
      )}
    >
      <div className="listview-main">
        <header className="page-header">
          <div className="page-heading">
            <h1 id={headingId}>{title}</h1>
            <span aria-live="polite" className="page-count num">
              {count === total
                ? `${total} ${total === 1 ? entityLabel.one : entityLabel.many}`
                : `${count} von ${total}`}
            </span>
          </div>
          <div className="page-actions">
            {props.headerExtra}
            {props.onCreate ? (
              <Button
                icon={Plus}
                onClick={props.onCreate}
                shortcut="c"
                variant={openRow ? "secondary" : "primary"}
              >
                {props.createLabel ?? "Neu"}
              </Button>
            ) : null}
          </div>
        </header>

        <nav aria-label="Gespeicherte Ansichten" className="views">
          {allViews.map((view) => {
            const active = view.id === baseView.id;
            return (
              <span
                className={cn("view-tab", active && "is-active")}
                key={view.id}
              >
                <button
                  aria-pressed={active}
                  onClick={() => applyView(view)}
                  type="button"
                >
                  {view.custom ? (
                    <Bookmark aria-hidden="true" size={13} />
                  ) : null}
                  {view.label}
                  {active && dirty ? (
                    <>
                      <span aria-hidden="true" className="view-dirty" />
                      <span className="sr-only"> (geändert)</span>
                    </>
                  ) : null}
                </button>
                {view.custom ? (
                  <button
                    aria-label={`Ansicht ${view.label} löschen`}
                    className="view-remove"
                    onClick={() => deleteView(view.id)}
                    type="button"
                  >
                    <X aria-hidden="true" size={12} />
                  </button>
                ) : null}
              </span>
            );
          })}
          <button
            className="view-save"
            disabled={!dirty}
            onClick={() => setMenu({ kind: "save" })}
            ref={saveButton}
            type="button"
          >
            <BookmarkPlus aria-hidden="true" size={14} />
            Ansicht speichern
          </button>
        </nav>

        <FilterBar<T>
          compact={compact}
          filterButtonRef={filterButton}
          filters={state.filters}
          groupBy={state.groupBy}
          groupable={groupable}
          onAddFilter={() => setMenu({ kind: "filter-prop" })}
          onCompactChange={setCompact}
          onEditFilter={(prop, chip) => {
            filterAnchor.current = chip;
            setMenu({ kind: "filter-values", prop });
          }}
          onGroupByChange={(groupBy) => update({ groupBy })}
          onLeaveSearch={() => focusRow(flatIds[0] ?? null)}
          onQueryChange={(query) => update({ query })}
          onRemoveFilter={(prop) =>
            setFilters(state.filters.filter((filter) => filter.prop !== prop))
          }
          onResetFilters={() => setFilters([])}
          onSortChange={(sort) => update({ sort })}
          propertyById={propertyById}
          query={state.query}
          searchRef={searchRef}
          sort={state.sort}
          sorts={sorts}
          title={title}
        />

        {checkedIds.length > 0 ? (
          <div aria-label="Auswahl" className="bulkbar" role="region">
            <span className="num">
              {checkedIds.length} ausgewählt
              {hiddenChecked > 0 ? ` · ${hiddenChecked} ausgeblendet` : ""}
            </span>
            {editable.map((prop) => (
              <Button
                icon={prop.icon}
                key={prop.id}
                onClick={(event) =>
                  openEdit(prop.id, checkedIds[0] ?? null, event.currentTarget)
                }
                shortcut={prop.edit!.key}
                size="sm"
                variant="secondary"
              >
                {prop.label}
              </Button>
            ))}
            {props.bulkActions?.(checkedIds, clearChecked)}
            <Button
              onClick={clearChecked}
              shortcut="escape"
              size="sm"
              variant="ghost"
            >
              Auswahl aufheben
            </Button>
          </div>
        ) : null}

        {props.beforeList}
        <div
          aria-busy={status === "loading" || undefined}
          aria-labelledby={headingId}
          className="list"
          role="region"
        >
          {body}
        </div>
        <p aria-hidden="true" className="list-hint">
          <Kbd announce={false} keys="j" /> <Kbd announce={false} keys="k" />{" "}
          bewegen · <Kbd announce={false} keys="enter" /> öffnen ·{" "}
          <Kbd announce={false} keys="x" /> auswählen
          {editable.map((prop) => (
            <span key={prop.id}>
              {" "}
              · <Kbd announce={false} keys={prop.edit!.key} /> {prop.label}
            </span>
          ))}{" "}
          · <Kbd announce={false} keys="?" /> alle Kürzel
        </p>
      </div>

      {openRow && renderDetail ? (
        <DetailPane
          onClose={closePane}
          onNext={() => move(1)}
          onPrevious={() => move(-1)}
          title={detailTitle(openRow)}
        >
          {editable.length ? (
            <div aria-label="Eigenschaften" className="pane-props" role="group">
              {editable.map((prop) => {
                const PropIcon = prop.icon;
                return (
                  <button
                    className="pane-prop"
                    key={prop.id}
                    onClick={(event) =>
                      openEdit(prop.id, getId(openRow), event.currentTarget)
                    }
                    ref={(element) => {
                      if (element) paneProps.current.set(prop.id, element);
                      else paneProps.current.delete(prop.id);
                    }}
                    type="button"
                  >
                    <span className="pane-prop-label">
                      <PropIcon aria-hidden="true" size={14} />
                      {prop.label}
                    </span>
                    <span className="pane-prop-value">
                      {prop.chip
                        ? prop.chip(openRow)
                        : valuesOf(prop, openRow)
                            .map((value) => optionLabel(prop, value))
                            .join(", ")}
                    </span>
                    <Kbd announce={false} keys={prop.edit!.key} subtle />
                  </button>
                );
              })}
            </div>
          ) : null}
          {renderDetail(openRow)}
        </DetailPane>
      ) : null}

      {/* ----- layers ----- */}
      <Popover
        anchor={filterButton}
        label="Filter wählen"
        onClose={closeMenu}
        open={menu?.kind === "filter-prop"}
      >
        <OptionMenu<string>
          onSelect={(value) => {
            filterAnchor.current = filterButton.current;
            setMenu({ kind: "filter-values", prop: value });
          }}
          options={filterable.map((prop) => {
            const PropIcon = prop.icon;
            return {
              value: prop.id,
              label: prop.label,
              icon: <PropIcon aria-hidden="true" size={14} />,
            };
          })}
          placeholder="Filtern nach …"
          value={[]}
        />
      </Popover>
      <Popover
        anchor={filterAnchor}
        label={filterProp ? `Filter ${filterProp.label}` : "Filter"}
        onClose={closeMenu}
        open={filterProp !== undefined}
      >
        {filterProp ? (
          <OptionMenu<string>
            multiple
            onSelect={(value) => toggleFilterValue(filterProp.id, value)}
            options={filterProp.options}
            placeholder={`${filterProp.label} …`}
            value={
              state.filters.find((filter) => filter.prop === filterProp.id)
                ?.values ?? []
            }
          />
        ) : null}
      </Popover>
      <Popover
        anchor={editAnchor}
        label={editProp ? `${editProp.label} ändern` : "Ändern"}
        onClose={closeMenu}
        open={editProp !== undefined && editRow !== undefined}
      >
        {editProp && editRow !== undefined ? (
          <OptionMenu<string>
            onSelect={(value) => {
              if (menu?.kind === "edit")
                void applyEdit(editProp, menu.ids, value);
            }}
            options={editOptions(
              editProp,
              menu?.kind === "edit" ? menu.ids : [],
            )}
            placeholder={`${editProp.label} ändern …`}
            value={valuesOf(editProp, editRow)}
          />
        ) : null}
      </Popover>
      <Popover
        anchor={saveButton}
        label="Ansicht speichern"
        onClose={closeMenu}
        open={menu?.kind === "save"}
      >
        <form
          className="save-view"
          onSubmit={(event: FormEvent<HTMLFormElement>) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const label = String(data.get("label") ?? "").trim();
            if (!label) return;
            saveView(label);
            setMenu(null);
          }}
        >
          <label className="field-label" htmlFor={viewNameId}>
            Name der Ansicht
          </label>
          <input
            className="input"
            id={viewNameId}
            maxLength={40}
            name="label"
            placeholder="z. B. Heute liefern"
            required
          />
          <p className="field-hint">
            Speichert Filter, Gruppierung und Sortierung in diesem Browser.
          </p>
          <Button size="sm" type="submit" variant="primary">
            Speichern
          </Button>
        </form>
      </Popover>
    </div>
  );
}
