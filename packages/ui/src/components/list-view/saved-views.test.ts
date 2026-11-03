// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  isDirty,
  parseListState,
  readSavedViews,
  serializeListState,
  stateForView,
  STORAGE_PREFIX,
  writeSavedViews,
  type ListSchema,
  type ListViewDefinition,
} from "./saved-views";

const views: ListViewDefinition[] = [
  {
    id: "todo",
    label: "Zu prüfen",
    filters: [{ prop: "status", values: ["Eingegangen", "Prüfbereit"] }],
    groupBy: "status",
    sort: "new",
  },
  { id: "all", label: "Alle", filters: [], groupBy: null, sort: "new" },
];

const schema: ListSchema = {
  views,
  filterable: new Set(["status", "source"]),
  groupable: new Set(["status"]),
  sorts: new Set(["new", "amount"]),
};

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("URL state", () => {
  it("keeps the default view out of the URL", () => {
    expect(serializeListState("", stateForView(views[0]!), schema)).toBe("");
  });

  it("round-trips view, filters, grouping, sort, search and open row", () => {
    const state = {
      viewId: "all",
      filters: [
        { prop: "status", values: ["Offen", "Überfällig"] },
        { prop: "source", values: ["Öffentlich"] },
      ],
      groupBy: "status",
      sort: "amount",
      query: "Bäckerei & Söhne",
      openId: "o-7",
    };
    const search = serializeListState("?tab=x", state, schema);
    expect(search).toContain("view=all");
    expect(search).toContain("f.status=Offen&f.status=%C3%9Cberf%C3%A4llig");
    expect(search).toContain("tab=x");
    expect(parseListState(search, schema)).toEqual(state);
  });

  it("marks removed view filters with f=none", () => {
    const state = { ...stateForView(views[0]!), filters: [] };
    const search = serializeListState("", state, schema);
    expect(search).toBe("?f=none");
    expect(parseListState(search, schema).filters).toEqual([]);
  });

  it("writes group=none when grouping is switched off", () => {
    const state = { ...stateForView(views[0]!), groupBy: null };
    const search = serializeListState("", state, schema);
    expect(search).toBe("?group=none");
    expect(parseListState(search, schema).groupBy).toBeNull();
  });

  it("falls back to the view for unknown views, properties and sorts", () => {
    const state = parseListState(
      "?view=gone&f.secret=1&group=secret&sort=evil&f.status=Offen",
      schema,
    );
    expect(state.viewId).toBe("todo");
    expect(state.filters).toEqual([{ prop: "status", values: ["Offen"] }]);
    expect(state.groupBy).toBe("status");
    expect(state.sort).toBe("new");
  });

  it("drops the list's old parameters but keeps foreign ones", () => {
    const search = serializeListState(
      "?f.status=Offen&open=1&page=2",
      stateForView(views[1]!),
      schema,
    );
    expect(search).toBe("?page=2&view=all");
  });

  it("reports changes against the view as dirty", () => {
    expect(isDirty(stateForView(views[0]!), views[0]!)).toBe(false);
    expect(
      isDirty({ ...stateForView(views[0]!), sort: "amount" }, views[0]!),
    ).toBe(true);
    // Search and the open row are not part of a view.
    expect(
      isDirty(
        { ...stateForView(views[0]!), query: "x", openId: "1" },
        views[0]!,
      ),
    ).toBe(false);
  });
});

describe("saved views in localStorage", () => {
  const saved: ListViewDefinition = {
    id: "c1",
    label: "Meine",
    filters: [{ prop: "status", values: ["Offen"] }],
    groupBy: null,
    sort: "new",
  };

  it("stores under leonaid.views.<listId>", () => {
    expect(writeSavedViews("orders", [saved])).toBe(true);
    expect(window.localStorage.getItem(`${STORAGE_PREFIX}orders`)).toContain(
      "Meine",
    );
    expect(readSavedViews("orders")).toEqual([{ ...saved, custom: true }]);
  });

  it("ignores broken or foreign data", () => {
    window.localStorage.setItem(`${STORAGE_PREFIX}orders`, "{not json");
    expect(readSavedViews("orders")).toEqual([]);
    window.localStorage.setItem(
      `${STORAGE_PREFIX}orders`,
      JSON.stringify([{ id: 1 }, saved, { ...saved, filters: "x" }]),
    );
    expect(readSavedViews("orders")).toEqual([{ ...saved, custom: true }]);
  });

  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    expect(readSavedViews("orders")).toEqual([]);
    expect(writeSavedViews("orders", [saved])).toBe(false);
  });

  it("survives a localStorage getter that throws", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(readSavedViews("orders")).toEqual([]);
    expect(writeSavedViews("orders", [saved])).toBe(false);
  });
});
