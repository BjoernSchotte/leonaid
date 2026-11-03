/**
 * List view state that outlives a render: the URL query (filters, active
 * view, grouping, sort, search, open row) and the saved views a person keeps
 * in this browser (localStorage). Pure functions, so they are easy to test.
 */

export interface ListFilter {
  /** A property id. */
  readonly prop: string;
  /** Matches when the row's value is one of these. */
  readonly values: readonly string[];
}

export interface ListViewDefinition {
  readonly id: string;
  readonly label: string;
  readonly filters: readonly ListFilter[];
  /** A groupable property id, or null for a flat list. */
  readonly groupBy: string | null;
  /** A sort id. */
  readonly sort: string;
  /** Saved by the person in this browser; can be removed. */
  readonly custom?: boolean;
}

/** The part of the list state that the URL carries. */
export interface ListState {
  readonly viewId: string;
  readonly filters: readonly ListFilter[];
  readonly groupBy: string | null;
  readonly sort: string;
  readonly query: string;
  /** The row shown in the detail pane. */
  readonly openId: string | null;
}

export const URL_KEYS = {
  view: "view",
  query: "q",
  group: "group",
  sort: "sort",
  open: "open",
  /** `f.<prop>=<value>`, repeated for several values. */
  filterPrefix: "f.",
  /** `f=none`: the view's filters were removed. */
  filtersCleared: "f",
} as const;

const NO_GROUP = "none";
const CLEARED = "none";

export const STORAGE_PREFIX = "leonaid.views.";

/** What the list knows about its properties and sorts, for validation. */
export interface ListSchema {
  readonly views: readonly ListViewDefinition[];
  readonly filterable: ReadonlySet<string>;
  readonly groupable: ReadonlySet<string>;
  readonly sorts: ReadonlySet<string>;
}

export function sameFilters(
  a: readonly ListFilter[],
  b: readonly ListFilter[],
): boolean {
  if (a.length !== b.length) return false;
  return a.every((filter, index) => {
    const other = b[index];
    return (
      other !== undefined &&
      other.prop === filter.prop &&
      other.values.length === filter.values.length &&
      other.values.every((value, at) => value === filter.values[at])
    );
  });
}

/** The state a view stands for, before any change. */
export function stateForView(
  view: ListViewDefinition,
  openId: string | null = null,
): ListState {
  return {
    viewId: view.id,
    filters: view.filters,
    groupBy: view.groupBy,
    sort: view.sort,
    query: "",
    openId,
  };
}

/** True when filters, grouping or sort differ from the view (the dirty dot). */
export function isDirty(state: ListState, view: ListViewDefinition): boolean {
  return (
    !sameFilters(state.filters, view.filters) ||
    state.groupBy !== view.groupBy ||
    state.sort !== view.sort
  );
}

/**
 * Reads the list state from a query string. Unknown views, properties and
 * sorts fall back to the view's values, so a stale or edited link still
 * opens a working list.
 */
export function parseListState(search: string, schema: ListSchema): ListState {
  const params = new URLSearchParams(search);
  const fallback = schema.views[0];
  if (!fallback) throw new Error("A list view needs at least one view.");
  const view =
    schema.views.find((item) => item.id === params.get(URL_KEYS.view)) ??
    fallback;

  const filters: ListFilter[] = [];
  let hasFilterParams = params.get(URL_KEYS.filtersCleared) === CLEARED;
  for (const key of new Set(params.keys())) {
    if (!key.startsWith(URL_KEYS.filterPrefix)) continue;
    hasFilterParams = true;
    const prop = key.slice(URL_KEYS.filterPrefix.length);
    if (!schema.filterable.has(prop)) continue;
    const values = [...new Set(params.getAll(key).filter(Boolean))];
    if (values.length > 0) filters.push({ prop, values });
  }

  const groupParam = params.get(URL_KEYS.group);
  const groupBy =
    groupParam === null
      ? view.groupBy
      : groupParam === NO_GROUP
        ? null
        : schema.groupable.has(groupParam)
          ? groupParam
          : view.groupBy;

  const sortParam = params.get(URL_KEYS.sort);
  const sort =
    sortParam !== null && schema.sorts.has(sortParam) ? sortParam : view.sort;

  return {
    viewId: view.id,
    filters: hasFilterParams ? filters : view.filters,
    groupBy,
    sort,
    query: params.get(URL_KEYS.query) ?? "",
    openId: params.get(URL_KEYS.open) || null,
  };
}

function isListKey(key: string): boolean {
  return (
    key === URL_KEYS.view ||
    key === URL_KEYS.query ||
    key === URL_KEYS.group ||
    key === URL_KEYS.sort ||
    key === URL_KEYS.open ||
    key === URL_KEYS.filtersCleared ||
    key.startsWith(URL_KEYS.filterPrefix)
  );
}

/**
 * Writes the state into a query string, keeping parameters that are not the
 * list's. Only what differs from the view is written, so the default list
 * keeps a clean URL. Returns the search string with a leading "?" or "".
 */
export function serializeListState(
  search: string,
  state: ListState,
  schema: ListSchema,
): string {
  const params = new URLSearchParams(search);
  for (const key of [...new Set(params.keys())]) {
    if (isListKey(key)) params.delete(key);
  }
  const first = schema.views[0];
  const view =
    schema.views.find((item) => item.id === state.viewId) ?? first ?? null;
  if (view && view !== first) params.set(URL_KEYS.view, view.id);
  if (!view || !sameFilters(state.filters, view.filters)) {
    if (state.filters.length === 0) {
      params.set(URL_KEYS.filtersCleared, CLEARED);
    }
    for (const filter of state.filters) {
      for (const value of filter.values) {
        params.append(`${URL_KEYS.filterPrefix}${filter.prop}`, value);
      }
    }
  }
  if (!view || state.groupBy !== view.groupBy) {
    params.set(URL_KEYS.group, state.groupBy ?? NO_GROUP);
  }
  if (!view || state.sort !== view.sort) params.set(URL_KEYS.sort, state.sort);
  if (state.query) params.set(URL_KEYS.query, state.query);
  if (state.openId) params.set(URL_KEYS.open, state.openId);
  const text = params.toString();
  return text ? `?${text}` : "";
}

function isFilter(value: unknown): value is ListFilter {
  if (!value || typeof value !== "object") return false;
  const filter = value as Record<string, unknown>;
  return (
    typeof filter.prop === "string" &&
    Array.isArray(filter.values) &&
    filter.values.every((item) => typeof item === "string")
  );
}

function isViewDefinition(value: unknown): value is ListViewDefinition {
  if (!value || typeof value !== "object") return false;
  const view = value as Record<string, unknown>;
  return (
    typeof view.id === "string" &&
    view.id !== "" &&
    typeof view.label === "string" &&
    Array.isArray(view.filters) &&
    view.filters.every(isFilter) &&
    (view.groupBy === null || typeof view.groupBy === "string") &&
    typeof view.sort === "string"
  );
}

/** The browser's localStorage, or null where reading it throws. */
function storage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Saved views of a list. Storage may be missing, full or blocked (private
 * mode, policy); every failure reads as "no saved views".
 */
export function readSavedViews(listId: string): ListViewDefinition[] {
  let raw: string | null = null;
  try {
    raw = storage()?.getItem(STORAGE_PREFIX + listId) ?? null;
  } catch {
    return [];
  }
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(isViewDefinition)
      .map((view) => ({ ...view, custom: true }));
  } catch {
    return [];
  }
}

/** Stores the saved views; false when the browser refused. */
export function writeSavedViews(
  listId: string,
  views: readonly ListViewDefinition[],
): boolean {
  try {
    const target = storage();
    if (!target) return false;
    if (views.length === 0) target.removeItem(STORAGE_PREFIX + listId);
    else target.setItem(STORAGE_PREFIX + listId, JSON.stringify(views));
    return true;
  } catch {
    return false;
  }
}
