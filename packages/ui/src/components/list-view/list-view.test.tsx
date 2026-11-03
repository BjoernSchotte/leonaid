// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { CircleDot, Globe, ShoppingBasket } from "lucide-react";
import { useState } from "react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { HotkeyProvider } from "../../keyboard/use-hotkeys";
import { installDialogPolyfill } from "../../test-utils/dialog-polyfill";
import { ToastProvider } from "../toast";
import { ListView } from "./list-view";
import { STORAGE_PREFIX, type ListViewDefinition } from "./saved-views";
import type {
  ListCommand,
  ListEditOutcome,
  ListProperty,
  ListSort,
} from "./types";

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeAll(() => {
  globalThis.ResizeObserver =
    TestResizeObserver as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  installDialogPolyfill();
});

interface Order {
  readonly id: string;
  readonly number: string;
  readonly sponsor: string;
  status: string;
  readonly source: string;
  readonly cents: number;
}

const STATUSES = ["Eingegangen", "Bestätigt", "Geliefert"];

function fixture(): Order[] {
  return [
    {
      id: "o1",
      number: "B-001",
      sponsor: "Bäckerei Kern",
      status: "Eingegangen",
      source: "Akquise",
      cents: 4200,
    },
    {
      id: "o2",
      number: "B-002",
      sponsor: "Autohaus Nord",
      status: "Bestätigt",
      source: "Öffentlich",
      cents: 9900,
    },
    {
      id: "o3",
      number: "B-003",
      sponsor: "Café Mitte",
      status: "Eingegangen",
      source: "Öffentlich",
      cents: 1500,
    },
    {
      id: "o4",
      number: "B-004",
      sponsor: "Druckerei Süd",
      status: "Geliefert",
      source: "Akquise",
      cents: 7000,
    },
  ];
}

const views: ListViewDefinition[] = [
  { id: "all", label: "Alle", filters: [], groupBy: null, sort: "number" },
  {
    id: "new",
    label: "Neu",
    filters: [{ prop: "status", values: ["Eingegangen"] }],
    groupBy: "status",
    sort: "number",
  },
];

const sorts: ListSort<Order>[] = [
  {
    id: "number",
    label: "Nummer",
    compare: (a, b) => a.number.localeCompare(b.number),
  },
  { id: "amount", label: "Betrag", compare: (a, b) => b.cents - a.cents },
];

let published: readonly ListCommand[] = [];
function useCaptureCommands(commands: readonly ListCommand[]) {
  published = commands;
}
function runCommand(label: string) {
  const command = published.find((item) => item.label === label);
  if (!command) throw new Error(`No command "${label}"`);
  act(() => command.run());
}

function Harness({
  apply,
  createCommandId,
  editOptions,
  onCreate,
  onOpen,
}: {
  createCommandId?: string;
  onCreate?: () => void;
  apply?: (
    ids: readonly string[],
    value: string,
  ) => ListEditOutcome | Promise<ListEditOutcome>;
  editOptions?: (rows: readonly Order[]) => { value: string; label: string }[];
  onOpen?: (row: Order | null) => void;
}) {
  const [rows, setRows] = useState(fixture);
  const properties: ListProperty<Order>[] = [
    {
      id: "status",
      label: "Status",
      icon: CircleDot,
      get: (row) => row.status,
      options: STATUSES.map((status) => ({ value: status, label: status })),
      chip: (row) => <span>{row.status}</span>,
      edit: {
        key: "s",
        options: editOptions,
        apply:
          apply ??
          ((ids, value) =>
            setRows((current) =>
              current.map((row) =>
                ids.includes(row.id) ? { ...row, status: value } : row,
              ),
            )),
      },
    },
    {
      id: "source",
      label: "Herkunft",
      icon: Globe,
      get: (row) => row.source,
      options: [
        { value: "Akquise", label: "Akquise" },
        { value: "Öffentlich", label: "Öffentliches Formular" },
      ],
      groupable: false,
    },
  ];
  return (
    <ToastProvider>
      <HotkeyProvider>
        <ListView<Order>
          columns={{
            primary: (row) => `${row.number} ${row.sponsor}`,
            trailing: (row) => `${row.cents / 100} €`,
          }}
          detailTitle={(row) => `${row.number} · ${row.sponsor}`}
          emptyIcon={ShoppingBasket}
          entityLabel={{ one: "Bestellung", many: "Bestellungen" }}
          getId={(row) => row.id}
          createCommandId={createCommandId}
          id="orders"
          onCreate={onCreate}
          onOpen={onOpen}
          properties={properties}
          renderDetail={(row) => <p>Detail {row.number}</p>}
          rows={rows}
          searchText={(row) => `${row.number} ${row.sponsor}`}
          sorts={sorts}
          title="Bestellungen"
          useCommands={useCaptureCommands}
          views={views}
        />
      </HotkeyProvider>
    </ToastProvider>
  );
}

function press(key: string, target: Element | null = document.activeElement) {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
  });
  act(() => {
    (target ?? document.body).dispatchEvent(event);
  });
  return event;
}

function rowLinks() {
  return [...document.querySelectorAll<HTMLAnchorElement>(".row-link")];
}

function focusedRowText() {
  return document.querySelector(".row.is-focused .row-primary")?.textContent;
}

function setUrl(search: string) {
  window.history.replaceState(null, "", `/admin/orders${search}`);
}

beforeEach(() => {
  setUrl("");
  window.localStorage.clear();
  vi.useRealTimers();
});

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(window, "matchMedia");
  vi.restoreAllMocks();
  document.body.focus();
});

describe("ListView rendering", () => {
  it("renders only the given rows with a live count", () => {
    render(<Harness />);
    expect(rowLinks()).toHaveLength(4);
    expect(screen.getByText("4 Bestellungen").getAttribute("aria-live")).toBe(
      "polite",
    );
  });

  it("filters by search text and shows 'x von y'", () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "café" },
    });
    expect(rowLinks().map((link) => link.textContent)).toEqual([
      "B-003 Café Mitte",
    ]);
    expect(screen.getByText("1 von 4")).toBeTruthy();
    expect(window.location.search).toBe("?q=caf%C3%A9");
  });

  it("shows the no-match empty state with a reset", () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "zzz" },
    });
    expect(
      screen.getByRole("heading", {
        name: "Keine Bestellungen passen zu dieser Ansicht",
      }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Filter und Suche zurücksetzen" }),
    );
    expect(rowLinks()).toHaveLength(4);
  });
});

describe("URL round-trip", () => {
  it("restores view, filters and grouping after a reload", () => {
    const first = render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Neu" }));
    expect(window.location.search).toBe("?view=new");
    expect(rowLinks()).toHaveLength(2);
    // Add "Bestätigt" to the status chip's values.
    fireEvent.click(screen.getByRole("button", { name: /Status\s*ist/ }));
    fireEvent.click(screen.getByRole("option", { name: /Bestätigt/ }));
    expect(window.location.search).toBe(
      "?view=new&f.status=Eingegangen&f.status=Best%C3%A4tigt",
    );
    expect(rowLinks()).toHaveLength(3);
    // The view tab shows the unsaved change.
    expect(
      screen.getByRole("button", { name: /Neu\s*\(geändert\)/ }),
    ).toBeTruthy();
    const url = window.location.search;
    first.unmount();

    setUrl(url);
    render(<Harness />);
    expect(rowLinks()).toHaveLength(3);
    expect(
      screen.getByRole("button", { name: /Neu/, pressed: true }),
    ).toBeTruthy();
    expect(screen.getByText("ist eins von")).toBeTruthy();
    expect(
      screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent),
    ).toEqual(expect.arrayContaining([expect.stringContaining("Eingegangen")]));
  });

  it("restores the open row from ?open= and follows back/forward", () => {
    setUrl("?open=o2");
    render(<Harness />);
    expect(
      screen.getByRole("complementary", {
        name: "Details: B-002 · Autohaus Nord",
      }),
    ).toBeTruthy();
    act(() => {
      window.history.pushState(null, "", "/admin/orders");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("removing a filter chip updates the URL", () => {
    setUrl("?f.source=%C3%96ffentlich");
    render(<Harness />);
    expect(rowLinks()).toHaveLength(2);
    fireEvent.click(
      screen.getByRole("button", { name: "Filter Herkunft entfernen" }),
    );
    expect(rowLinks()).toHaveLength(4);
    expect(window.location.search).toBe("");
  });
});

describe("keyboard", () => {
  it("j/k move, Enter opens, Esc closes and returns focus", () => {
    const onOpen = vi.fn();
    render(<Harness onOpen={onOpen} />);
    press("j");
    expect(focusedRowText()).toBe("B-001 Bäckerei Kern");
    expect(document.activeElement).toBe(rowLinks()[0]);
    press("j");
    press("j");
    press("k");
    expect(focusedRowText()).toBe("B-002 Autohaus Nord");

    // Enter on the focused row link activates it natively (a click).
    fireEvent.click(rowLinks()[1]!);
    expect(window.location.search).toBe("?open=o2");
    expect(onOpen).toHaveBeenLastCalledWith(
      expect.objectContaining({ id: "o2" }),
    );
    const pane = screen.getByRole("complementary", { name: /B-002/ });
    expect(within(pane).getByText("Detail B-002")).toBeTruthy();

    // j keeps working with the pane open and moves the pane along.
    press("j");
    expect(window.location.search).toBe("?open=o3");

    vi.useFakeTimers();
    press("Escape");
    act(() => vi.runAllTimers());
    vi.useRealTimers();
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(onOpen).toHaveBeenLastCalledWith(null);
    expect(document.activeElement).toBe(rowLinks()[2]);
  });

  it("Enter opens the focused row when focus is not on a link", () => {
    render(<Harness />);
    press("j");
    press("j");
    act(() => document.body.focus());
    press("Enter", document.body);
    expect(window.location.search).toBe("?open=o2");
  });

  it("x checks rows, shows the bulk bar and Esc clears it", () => {
    render(<Harness />);
    press("j");
    press("x");
    press("j");
    press("x");
    const bar = screen.getByRole("region", { name: "Auswahl" });
    expect(within(bar).getByText("2 ausgewählt")).toBeTruthy();
    press("Escape");
    expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull();
  });

  it("f opens the filter menu and / focuses the search", () => {
    render(<Harness />);
    press("f");
    expect(screen.getByRole("dialog", { name: "Filter wählen" })).toBeTruthy();
    press("Escape");
    press("/");
    expect(document.activeElement).toBe(screen.getByRole("searchbox"));
  });

  it("is inert while typing in the search box", () => {
    render(<Harness />);
    const search = screen.getByRole("searchbox");
    act(() => search.focus());
    for (const key of ["j", "k", "x", "f", "/", "s"]) {
      const event = press(key, search);
      expect(event.defaultPrevented).toBe(false);
    }
    expect(document.querySelector(".row.is-focused")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    // Esc leaves the field and lands on the first row.
    press("Escape", search);
    expect(document.activeElement).toBe(rowLinks()[0]);
  });

  it("is inert while a modal dialog is open", () => {
    render(
      <>
        <Harness />
        <dialog open>
          <button type="button">Im Dialog</button>
        </dialog>
      </>,
    );
    press("j", document.body);
    expect(document.querySelector(".row.is-focused")).toBeNull();
  });

  it("lists its keys in the 'Liste' help group", async () => {
    const { HotkeyRegistry } = await import("../../keyboard/hotkeys");
    const registry = new HotkeyRegistry();
    render(
      <HotkeyProvider registry={registry}>
        <ListView<Order>
          columns={{ primary: (row) => row.number }}
          detailTitle={(row) => row.number}
          emptyIcon={ShoppingBasket}
          entityLabel={{ one: "Bestellung", many: "Bestellungen" }}
          getId={(row) => row.id}
          id="orders"
          properties={[]}
          rowHref={(row) => `/admin/orders/${row.id}`}
          rows={fixture()}
          searchText={(row) => row.number}
          sorts={sorts}
          title="Bestellungen"
          views={views}
        />
      </HotkeyProvider>,
    );
    const keys = registry
      .getVisible()
      .filter((binding) => binding.group === "Liste")
      .map((binding) => binding.keys);
    expect(keys).toEqual(
      expect.arrayContaining(["j", "k", "enter", "x", "/", "f"]),
    );
  });
});

describe("inline edits", () => {
  it("s edits the focused row; with checked rows it edits all of them", async () => {
    const apply = vi.fn();
    render(<Harness apply={apply} />);
    press("j");
    press("s");
    fireEvent.click(screen.getByRole("option", { name: /Geliefert/ }));
    expect(apply).toHaveBeenLastCalledWith(["o1"], "Geliefert");
    // The row stays busy until the edit has settled.
    await act(async () => {});

    press("x");
    press("j");
    press("x");
    press("s");
    fireEvent.click(screen.getByRole("option", { name: /Bestätigt/ }));
    expect(apply).toHaveBeenLastCalledWith(["o1", "o2"], "Bestätigt");
    await act(async () => {});
    expect(
      await screen.findByText("Status bei 2 Einträgen: Bestätigt"),
    ).toBeTruthy();
  });

  it("asks for a row first when none is focused", async () => {
    render(<Harness />);
    press("s");
    expect(
      await screen.findByText("Erst eine Zeile mit J/K auswählen."),
    ).toBeTruthy();
  });

  it("reports a failed edit", async () => {
    render(<Harness apply={() => Promise.reject(new Error("403"))} />);
    press("j");
    press("s");
    fireEvent.click(screen.getByRole("option", { name: /Geliefert/ }));
    expect(
      await screen.findByText("Status wurde nicht geändert."),
    ).toBeTruthy();
  });
});

describe("saved views", () => {
  it("saves the current filters under leonaid.views.<id>", async () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox", { name: "Sortieren" }), {
      target: { value: "amount" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ansicht speichern" }));
    fireEvent.change(screen.getByLabelText("Name der Ansicht"), {
      target: { value: "Teuer" },
    });
    fireEvent.submit(
      screen.getByLabelText("Name der Ansicht").closest("form")!,
    );
    expect(
      screen.getByRole("button", { name: "Teuer", pressed: true }),
    ).toBeTruthy();
    const stored = JSON.parse(
      window.localStorage.getItem(`${STORAGE_PREFIX}orders`) ?? "[]",
    ) as ListViewDefinition[];
    expect(stored).toEqual([
      expect.objectContaining({ label: "Teuer", sort: "amount" }),
    ]);
    expect(window.location.search).toMatch(/^\?view=c/);

    fireEvent.click(
      screen.getByRole("button", { name: "Ansicht Teuer löschen" }),
    );
    expect(screen.queryByRole("button", { name: "Teuer" })).toBeNull();
    expect(window.localStorage.getItem(`${STORAGE_PREFIX}orders`)).toBeNull();
  });

  it("keeps working when storage throws", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    render(<Harness />);
    expect(rowLinks()).toHaveLength(4);
    fireEvent.change(screen.getByRole("combobox", { name: "Sortieren" }), {
      target: { value: "amount" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ansicht speichern" }));
    fireEvent.change(screen.getByLabelText("Name der Ansicht"), {
      target: { value: "Teuer" },
    });
    fireEvent.submit(
      screen.getByLabelText("Name der Ansicht").closest("form")!,
    );
    expect(
      screen.getByRole("button", { name: "Teuer", pressed: true }),
    ).toBeTruthy();
    expect(
      await screen.findByText("Ansicht „Teuer“ gilt nur bis zum Neuladen."),
    ).toBeTruthy();
  });
});

describe("detail pane on phones", () => {
  it("opens as a full-screen modal sheet at 390 px and closes with Esc", () => {
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: (query: string) =>
        ({
          matches: query === "(max-width: 720px)",
          media: query,
          addEventListener: () => {},
          removeEventListener: () => {},
        }) as unknown as MediaQueryList,
    });
    setUrl("?open=o1");
    render(<Harness />);
    const sheet = document.querySelector("dialog.pane-sheet");
    expect(sheet).not.toBeNull();
    expect(sheet?.hasAttribute("open")).toBe(true);
    expect(sheet?.getAttribute("aria-label")).toBe(
      "Details: B-001 · Bäckerei Kern",
    );
    expect(screen.queryByRole("complementary")).toBeNull();
    // List keys are inert behind the modal sheet.
    press("j", document.body);
    expect(window.location.search).toBe("?open=o1");
    press("Escape", sheet);
    expect(document.querySelector("dialog.pane-sheet")).toBeNull();
    expect(window.location.search).toBe("");
  });
});

describe("palette commands", () => {
  it("switches views, filters, groups and selects through the palette", () => {
    vi.useFakeTimers();
    render(<Harness />);
    const labels = () => published.map((command) => command.label);
    expect(labels()).toEqual(
      expect.arrayContaining([
        "Ansicht: Alle",
        "Ansicht: Neu",
        "Filter hinzufügen",
        "Filtern nach Status",
        "Filtern nach Herkunft",
        "Gruppieren nach Status",
        "Alle Bestellungen auswählen",
      ]),
    );
    // Not groupable, nothing to clear or unselect yet.
    expect(labels()).not.toContain("Gruppieren nach Herkunft");
    expect(labels()).not.toContain("Filter zurücksetzen");
    expect(labels()).not.toContain("Auswahl aufheben");
    expect(published.every((command) => command.group === "Bestellungen")).toBe(
      true,
    );

    runCommand("Ansicht: Neu");
    expect(window.location.search).toBe("?view=new");
    expect(rowLinks()).toHaveLength(2);

    runCommand("Filter zurücksetzen");
    expect(rowLinks()).toHaveLength(4);
    expect(window.location.search).toBe("?view=new&f=none");

    runCommand("Alle Bestellungen auswählen");
    expect(screen.getByText("4 ausgewählt")).toBeTruthy();
    runCommand("Auswahl aufheben");
    expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull();

    runCommand("Filter hinzufügen");
    act(() => vi.advanceTimersByTime(20));
    expect(screen.getByRole("dialog", { name: "Filter wählen" })).toBeTruthy();
    press("Escape", screen.getByRole("dialog", { name: "Filter wählen" }));

    runCommand("Filtern nach Herkunft");
    act(() => vi.advanceTimersByTime(20));
    expect(
      screen.getByRole("dialog", { name: "Filter Herkunft" }),
    ).toBeTruthy();
    vi.useRealTimers();
  });
});

describe("create command", () => {
  it("publishes the create action under the list id or the given id", () => {
    const onCreate = vi.fn();
    const { unmount } = render(<Harness onCreate={onCreate} />);
    expect(
      published.find((command) => command.label === "Neu anlegen")?.id,
    ).toBe("list:orders:create");
    unmount();
    render(<Harness createCommandId="create:order" onCreate={onCreate} />);
    const create = published.find((command) => command.label === "Neu anlegen");
    expect(create?.id).toBe("create:order");
    expect(create?.keys).toBe("c");
    act(() => create?.run());
    expect(onCreate).toHaveBeenCalledTimes(1);
  });
});

describe("review fixes", () => {
  it("requires a way to open rows at the type level", () => {
    const check = () => (
      // @ts-expect-error renderDetail, onOpen or rowHref is required
      <ListView<Order>
        columns={{ primary: (row) => row.number }}
        detailTitle={(row) => row.number}
        emptyIcon={ShoppingBasket}
        entityLabel={{ one: "Bestellung", many: "Bestellungen" }}
        getId={(row) => row.id}
        id="orders"
        properties={[]}
        rows={[]}
        searchText={(row) => row.number}
        sorts={sorts}
        title="Bestellungen"
        views={views}
      />
    );
    expect(typeof check).toBe("function");
  });

  it("closes the pane without adding a history entry", () => {
    render(<Harness />);
    fireEvent.click(rowLinks()[0]!);
    const afterOpen = window.history.length;
    press("Escape", document.body);
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(window.history.length).toBe(afterOpen);
    expect(window.location.search).toBe("");
  });

  it("keeps row links stable while typing a search", () => {
    render(<Harness />);
    const before = rowLinks()[0]!.getAttribute("href");
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "B-00" },
    });
    expect(rowLinks()[0]!.getAttribute("href")).toBe(before);
    expect(before).toBe("/admin/orders?open=o1");
  });

  it("acts only on checked rows that are visible, not in collapsed groups", () => {
    const apply = vi.fn();
    setUrl("?group=status");
    render(<Harness apply={apply} />);
    press("j");
    press("x"); // o1, Eingegangen
    press("j");
    press("j");
    press("x"); // o2, Bestätigt (groups: Eingegangen o1 o3, Bestätigt o2)
    expect(screen.getByText(/2 ausgewählt/)).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: /Bestätigt/, expanded: true }),
    );
    expect(screen.getByText("1 ausgewählt · 1 ausgeblendet")).toBeTruthy();
    fireEvent.click(
      within(screen.getByRole("region", { name: "Auswahl" })).getByRole(
        "button",
        { name: /Status/ },
      ),
    );
    fireEvent.click(screen.getByRole("option", { name: /Geliefert/ }));
    expect(apply).toHaveBeenLastCalledWith(["o1"], "Geliefert");
  });

  it("a cancelled edit shows no toast", async () => {
    render(<Harness apply={() => Promise.resolve("cancelled" as const)} />);
    press("j");
    press("s");
    fireEvent.click(screen.getByRole("option", { name: /Geliefert/ }));
    await act(async () => {});
    expect(screen.queryByText(/Status: Geliefert/)).toBeNull();
    expect(screen.queryByText(/nicht geändert/)).toBeNull();
  });

  it("offers only the options allowed for the edited rows", async () => {
    render(
      <Harness
        editOptions={(rows) =>
          rows.every((row) => row.status === "Eingegangen")
            ? [{ value: "Bestätigt", label: "Bestätigt" }]
            : []
        }
      />,
    );
    press("j"); // o1 Eingegangen
    press("s");
    expect(
      within(screen.getByRole("dialog", { name: "Status ändern" }))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual([expect.stringContaining("Bestätigt")]);
    press("Escape", screen.getByRole("dialog", { name: "Status ändern" }));
    press("j"); // o2 Bestätigt: no transition allowed
    press("s");
    expect(screen.queryByRole("dialog", { name: "Status ändern" })).toBeNull();
    expect(
      await screen.findByText("Status lässt sich hier nicht ändern."),
    ).toBeTruthy();
  });

  it("marks rows busy and ignores a second edit while saving", async () => {
    let finish: () => void = () => {};
    const apply = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    render(<Harness apply={apply} />);
    press("j");
    press("s");
    fireEvent.click(screen.getByRole("option", { name: /Geliefert/ }));
    const row = document.querySelector(".row.is-focused")!;
    expect(row.getAttribute("aria-busy")).toBe("true");
    press("s");
    expect(screen.queryByRole("dialog", { name: "Status ändern" })).toBeNull();
    expect(apply).toHaveBeenCalledTimes(1);
    await act(async () => finish());
    expect(row.getAttribute("aria-busy")).toBeNull();
  });

  it("Esc after clicking a row checkbox clears the selection", () => {
    render(<Harness />);
    const box = screen.getByRole("checkbox", { name: /B-001/ });
    act(() => box.focus());
    fireEvent.click(box);
    expect(screen.getByRole("region", { name: "Auswahl" })).toBeTruthy();
    press("Escape", box);
    expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull();
  });

  it("leaves Esc alone in fields outside the list", () => {
    render(
      <>
        <input aria-label="Woanders" />
        <Harness />
      </>,
    );
    const field = screen.getByRole("textbox", { name: "Woanders" });
    act(() => field.focus());
    const event = press("Escape", field);
    expect(event.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(field);
  });

  it("drops saved-view filters on properties that no longer exist", () => {
    window.localStorage.setItem(
      `${STORAGE_PREFIX}orders`,
      JSON.stringify([
        {
          id: "c1",
          label: "Alt",
          filters: [{ prop: "removed", values: ["x"] }],
          groupBy: "removed",
          sort: "gone",
        },
      ]),
    );
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Alt" }));
    expect(rowLinks()).toHaveLength(4);
    expect(screen.queryByRole("button", { name: "Zurücksetzen" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "Alt", pressed: true }),
    ).toBeTruthy();
  });
});

describe("options that arrive after mount", () => {
  function Late({
    names,
    pending,
    status,
    useCommands,
  }: {
    names: readonly string[];
    pending?: boolean;
    status?: "ready" | "loading";
    useCommands?: (commands: readonly ListCommand[]) => void;
  }) {
    const assignee = (row: Order) =>
      row.id === "o1" || row.id === "o3" ? "x" : "y";
    const properties: ListProperty<Order>[] = [
      {
        id: "assignee",
        label: "Zuständig",
        icon: Globe,
        get: assignee,
        options: names.map((name) => ({ value: name, label: name })),
        optionsPending: pending,
      },
    ];
    return (
      <HotkeyProvider>
        <ListView<Order>
          columns={{ primary: (row) => row.number }}
          detailTitle={(row) => row.number}
          emptyIcon={ShoppingBasket}
          entityLabel={{ one: "Bestellung", many: "Bestellungen" }}
          getId={(row) => row.id}
          id="late"
          properties={properties}
          renderDetail={(row) => <p>Detail {row.number}</p>}
          rows={fixture()}
          searchText={(row) => row.number}
          sorts={sorts}
          status={status}
          title="Bestellungen"
          useCommands={useCommands}
          views={[views[0]!]}
        />
      </HotkeyProvider>
    );
  }

  it("keeps a URL filter until the options arrive, then applies it", () => {
    setUrl("?f.assignee=x");
    const { rerender } = render(<Late names={[]} pending />);
    expect(window.location.search).toBe("?f.assignee=x");
    rerender(<Late names={["x", "y"]} />);
    expect(window.location.search).toBe("?f.assignee=x");
    expect(rowLinks()).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Filter Zuständig entfernen" }),
    ).toBeTruthy();
  });

  it("drops the value when the arrived options do not offer it", () => {
    setUrl("?f.assignee=x");
    const { rerender } = render(<Late names={[]} pending />);
    rerender(<Late names={["y"]} />);
    expect(rowLinks()).toHaveLength(4);
    expect(window.location.search).toBe("");
  });

  it("does not validate or rewrite while the list is loading", () => {
    setUrl("?f.assignee=x");
    const { rerender } = render(<Late names={["y"]} status="loading" />);
    expect(window.location.search).toBe("?f.assignee=x");
    // Other params are still written while loading; the value stays.
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "B" },
    });
    expect(window.location.search).toBe("?f.assignee=x&q=B");
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "" },
    });
    rerender(<Late names={["x", "y"]} status="ready" />);
    expect(window.location.search).toBe("?f.assignee=x");
    expect(rowLinks()).toHaveLength(2);
  });

  it("treats empty options on a ready list as real data", () => {
    setUrl("?f.assignee=x");
    render(<Late names={[]} />);
    // No assignees exist: the value cannot match and is dropped.
    expect(window.location.search).toBe("");
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "B-00" },
    });
    expect(window.location.search).toBe("?q=B-00");
    const before = window.history.length;
    fireEvent.click(rowLinks()[0]!);
    expect(window.location.search).toBe("?q=B-00&open=o1");
    expect(window.history.length).toBe(before + 1);
  });

  it("does not re-read the URL for a new but equal properties object", () => {
    setUrl("?f.assignee=x");
    const { rerender } = render(<Late names={["x", "y"]} />);
    expect(rowLinks()).toHaveLength(2);
    // Someone else changes the URL without a popstate; an equal schema
    // must not make the untouched list pick it up.
    window.history.replaceState(null, "", "/admin/orders?f.assignee=y");
    rerender(<Late names={["x", "y"]} />);
    expect(rowLinks().map((link) => link.textContent)).toEqual([
      "B-001",
      "B-003",
    ]);
  });

  it("reads useCommands once and warns when it changes", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<Late names={["x"]} useCommands={first} />);
    rerender(<Late names={["x"]} useCommands={second} />);
    expect(second).not.toHaveBeenCalled();
    expect(first).toHaveBeenCalled();
    expect(warn).toHaveBeenCalledTimes(1);
  });
});

describe("hidden checked rows", () => {
  it("Esc and the palette clear checked rows that are all hidden", () => {
    setUrl("?group=status");
    render(<Harness />);
    press("j");
    press("j");
    press("j");
    press("x"); // o2 in "Bestätigt"
    fireEvent.click(
      screen.getByRole("button", { name: /Bestätigt/, expanded: true }),
    );
    expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull();
    expect(published.map((command) => command.label)).toContain(
      "Auswahl aufheben",
    );
    act(() => document.body.focus());
    press("Escape", document.body);
    fireEvent.click(
      screen.getByRole("button", { name: /Bestätigt/, expanded: false }),
    );
    expect(screen.queryByRole("region", { name: "Auswahl" })).toBeNull();
    expect(
      (screen.getByRole("checkbox", { name: /B-002/ }) as HTMLInputElement)
        .checked,
    ).toBe(false);
  });
});
