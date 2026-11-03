import {
  Bookmark,
  BookmarkPlus,
  ChevronDown,
  Plus,
  SearchX,
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
import type { HotkeyBinding } from "../../keyboard/hotkeys";
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
import type { ListColumns, ListProperty, ListViewProps } from "./types";

/** Help overlay section of every list binding. */
export const LIST_HOTKEY_GROUP = "Liste";

type Menu =
  | { readonly kind: "filter-prop" }
  | { readonly kind: "filter-values"; readonly prop: string }
  | { readonly kind: "edit"; readonly prop: string; readonly rowId: string }
  | { readonly kind: "save" };

interface Group<T> {
  readonly key: string;
  readonly label: string;
  readonly icon: ReactNode;
  readonly rows: readonly T[];
}

const ALL_GROUP = "__all";

function valuesOf<T>(prop: ListProperty<T>, row: T): readonly string[] {
  const value = prop.get(row);
  return typeof value === "string" ? [value] : value;
}

function optionLabel<T>(prop: ListProperty<T>, value: string): string {
  return prop.options.find((option) => option.value === value)?.label ?? value;
}

function isFieldElement(element: Element | null): element is HTMLElement {
  return (
    element instanceof HTMLElement &&
    (element.tagName === "INPUT" ||
      element.tagName === "TEXTAREA" ||
      element.tagName === "SELECT" ||
      element.isContentEditable)
  );
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
  readonly tabbable: boolean;
  readonly groupBy: string | null;
  readonly context: RowContext<T>;
}

function ListRowInner<T>({
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
      className={cn(
        "row",
        focused && "is-focused",
        open && "is-selected",
        checked && "is-checked",
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
  const allViews = useMemo(
    () => [...props.views, ...savedViews],
    [props.views, savedViews],
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
  const schema = useMemo<ListSchema>(
    () => ({
      views: allViews,
      filterable: new Set(filterable.map((prop) => prop.id)),
      groupable: new Set(groupable.map((prop) => prop.id)),
      sorts: new Set(sorts.map((sort) => sort.id)),
    }),
    [allViews, filterable, groupable, sorts],
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

  const flatIds = useMemo(
    () =>
      groups
        .filter((group) => !collapsed.has(group.key))
        .flatMap((group) => group.rows.map(getId)),
    [groups, collapsed, getId],
  );
  const rowById = useMemo(
    () => new Map(rows.map((row) => [getId(row), row])),
    [rows, getId],
  );
  const visibleIds = useMemo(
    () => new Set(visible.map(getId)),
    [visible, getId],
  );
  /* Checked rows that a filter hides are not acted on. */
  const checkedIds = useMemo(
    () => [...checked].filter((id) => visibleIds.has(id)),
    [checked, visibleIds],
  );
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
    update({ openId: null }, true);
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
  const openEdit = (
    propId: string,
    rowId: string | null,
    anchor?: HTMLElement,
  ) => {
    if (!rowId || !rowById.has(rowId)) {
      toast?.show({
        title: "Erst eine Zeile mit J/K auswählen.",
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
    setMenu({ kind: "edit", prop: propId, rowId });
  };

  const applyEdit = async (
    prop: ListProperty<T>,
    rowId: string,
    value: string,
  ) => {
    const ids = checkedIds.includes(rowId) ? checkedIds : [rowId];
    setMenu(null);
    const label = optionLabel(prop, value);
    try {
      await prop.edit?.apply(ids, value);
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
  const inField = () => isFieldElement(document.activeElement);
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
      when: () => inField() || openRow !== null || checkedIds.length > 0,
      run: () => {
        const active = document.activeElement;
        if (active === searchRef.current) {
          searchRef.current?.blur();
          focusRow(focusedId ?? flatIds[0] ?? null);
          return;
        }
        // Esc in any other field only leaves the field.
        if (isFieldElement(active)) {
          active.blur();
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

  /* The open param goes last, so one base serves every row. */
  const hrefBase = useMemo(() => {
    const search = serializeListState(
      window.location.search,
      { ...state, openId: null },
      schema,
    );
    return `${window.location.pathname}${search}${search ? "&" : "?"}${URL_KEYS.open}=`;
  }, [state, schema]);
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
      const isCollapsed = collapsed.has(group.key);
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
                    if (next.has(group.key)) next.delete(group.key);
                    else next.add(group.key);
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
            <span className="num">{checkedIds.length} ausgewählt</span>
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
            onSelect={(value) =>
              void applyEdit(editProp, getId(editRow), value)
            }
            options={editProp.options}
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
