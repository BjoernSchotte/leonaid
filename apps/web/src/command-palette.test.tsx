import { act, fireEvent, render, screen, within } from "@testing-library/react";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import type {
  CurrentIdentityResponse,
  LeonAidApiClient,
  NavigationItemResponse,
  SearchResponse,
} from "@leonaid/api-client";
import {
  CommandPalette,
  enabledSearchModules,
  requestedUnlistedAction,
  resetCommandPaletteState,
  searchPalette,
  useCommandPalette,
  useContextCommands,
  type UiModule,
} from "@leonaid/features";
import { HotkeyProvider } from "@leonaid/ui";

import { webModules } from "./modules";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
});

beforeEach(() => resetCommandPaletteState());
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const nav = (
  key: string,
  label: string,
  surface: "web" | "pwa" = "web",
): NavigationItemResponse => ({
  key,
  label,
  href: surface === "web" ? `/admin/${key}` : `/app/${key}`,
  surface,
});

// LEONAID_DISABLED_MODULES=tasks,inbox: the server lists neither module.
const navigationWithoutTasksAndInbox: NavigationItemResponse[] = [
  nav("overview-web", "Übersicht"),
  nav("invoices", "Rechnungen"),
  nav("orders", "Bestellungen"),
  nav("knowledge", "Wissen"),
  nav("materials", "Materialien"),
  nav("tasks", "Aufgaben", "pwa"),
];

function identity(
  navigation: NavigationItemResponse[],
): CurrentIdentityResponse {
  return {
    actionMemberships: [],
    displayName: "Klara Admin",
    email: "klara@example.org",
    freshLoginAt: "2026-11-03T10:00:00Z",
    installation: { clubName: "Lions Club Musterstadt" },
    freshUntil: "2026-11-03T10:10:00Z",
    globalRoles: [],
    navigation,
    roleLabels: [],
    sessionExpiresAt: "2026-11-04T10:00:00Z",
    sessionLastSeenAt: "2026-11-03T10:00:00Z",
    landingPath: "/admin/",
    userId: "10000000-0000-4000-8000-000000000002",
  };
}

interface Pending {
  readonly query: string;
  readonly signal: AbortSignal;
  readonly resolve: (response: SearchResponse) => void;
}

function fakeClient() {
  const pending: Pending[] = [];
  const searchCore = vi.fn(
    (
      parameters: { readonly q: string },
      options: { readonly signal?: AbortSignal } = {},
    ) =>
      new Promise<SearchResponse>((resolve, reject) => {
        options.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
        pending.push({ query: parameters.q, signal: options.signal!, resolve });
      }),
  );
  const empty = vi.fn(async () => ({ items: [] }));
  const client = {
    searchCore,
    listTasks: empty,
    listKnowledgePages: empty,
    listMaterials: empty,
    listInboxCases: empty,
  } as unknown as LeonAidApiClient;
  return { client, pending, searchCore, empty };
}

function OpenButton() {
  const palette = useCommandPalette();
  return (
    <button onClick={() => palette.setOpen(true)} type="button">
      Suche öffnen
    </button>
  );
}

function MaterialCreateInPlace() {
  useContextCommands([
    {
      id: "create:material",
      label: "Material hier hochladen",
      group: "Material",
      run: () => {},
    },
  ]);
  return null;
}

function PageCommands() {
  useContextCommands([
    {
      id: "invite",
      label: "Mitglied einladen",
      group: "Mitglieder",
      keys: "c",
      run: () => {},
    },
  ]);
  return null;
}

function renderPalette(
  client: LeonAidApiClient,
  navigation: NavigationItemResponse[],
  modules: readonly UiModule[] = webModules,
) {
  return render(
    <HotkeyProvider>
      <OpenButton />
      <PageCommands />
      <CommandPalette
        context={{ client, identity: identity(navigation) }}
        modules={modules}
        surface="web"
      />
    </HotkeyProvider>,
  );
}

function dialog() {
  return document.querySelector<HTMLDialogElement>("dialog.palette")!;
}

function type(text: string) {
  fireEvent.change(screen.getByRole("combobox"), { target: { value: text } });
}

describe("command palette sources", () => {
  it("drops modules the server does not list for this surface", () => {
    expect(
      enabledSearchModules(
        webModules,
        navigationWithoutTasksAndInbox,
        "web",
      ).map((module) => module.id),
    ).toEqual(["materials", "knowledge"]);
  });

  it("never asks a switched-off module and keeps server results as returned", async () => {
    const tasks = vi.fn(async () => []);
    const knowledge = vi.fn(async () => [
      {
        id: "k1",
        type: "knowledge-page" as const,
        title: "Rechnungslauf",
        context: "Wissen",
        href: "/admin/knowledge/k1",
      },
    ]);
    const modules: UiModule[] = [
      {
        id: "tasks",
        label: "Aufgaben",
        surfaces: ["web"],
        routes: [],
        search: { label: "Aufgaben", find: tasks },
      },
      {
        id: "knowledge",
        label: "Wissen",
        surfaces: ["web"],
        routes: [],
        search: { label: "Wissen", find: knowledge },
      },
    ];
    const client = {
      searchCore: vi.fn(async () => ({
        results: [
          {
            id: "m1",
            type: "member",
            title: "Rita Rechner",
            context: "rita@example.org",
            href: "/admin/members",
          },
          {
            id: "i1",
            type: "invoice",
            title: "KT26-0001",
            context: "Sophie · Krapfentaxi",
            href: "/admin/invoices?action=a",
          },
        ],
      })),
    } as unknown as LeonAidApiClient;
    const outcome = await searchPalette(
      { client, identity: identity(navigationWithoutTasksAndInbox) },
      modules,
      "web",
      "  rech  ",
      new AbortController().signal,
    );
    expect(tasks).not.toHaveBeenCalled();
    expect(knowledge).toHaveBeenCalledWith(
      expect.anything(),
      "rech",
      "web",
      expect.any(AbortSignal),
    );
    expect(client.searchCore).toHaveBeenCalledWith(
      { q: "rech", limit: 8 },
      { signal: expect.any(AbortSignal) },
    );
    expect(
      outcome.groups.map((group) => [
        group.label,
        group.hits.map((hit) => hit.id),
      ]),
    ).toEqual([
      ["Rechnungen", ["i1"]],
      ["Mitglieder", ["m1"]],
      ["Wissen", ["k1"]],
    ]);
    expect(outcome.failed).toEqual([]);
  });

  it("reports a failed source and keeps the others", async () => {
    const client = {
      searchCore: vi.fn(async () => {
        throw new Error("503");
      }),
    } as unknown as LeonAidApiClient;
    const modules: UiModule[] = [
      {
        id: "knowledge",
        label: "Wissen",
        surfaces: ["web"],
        routes: [],
        search: { label: "Wissen", find: async () => [] },
      },
    ];
    const outcome = await searchPalette(
      { client, identity: identity(navigationWithoutTasksAndInbox) },
      modules,
      "web",
      "rech",
      new AbortController().signal,
    );
    expect(outcome.allFailed).toBe(false);
    expect(outcome.failed).toEqual([
      "Aktionen, Bestellungen, Rechnungen, Sponsoren und Mitglieder",
    ]);
  });
});

describe("CommandPalette", () => {
  it("opens with Strg+K, lists only server navigation and page commands", () => {
    const { client } = fakeClient();
    renderPalette(client, navigationWithoutTasksAndInbox);
    act(() => {
      fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    });
    expect(dialog().open).toBe(true);
    const list = screen.getByRole("listbox");
    expect(within(list).getByText("Rechnungen")).toBeTruthy();
    expect(within(list).getByText("Wissen")).toBeTruthy();
    expect(within(list).queryByText("Aufgaben")).toBeNull();
    expect(within(list).queryByText("Eingang")).toBeNull();
    expect(within(list).queryByText("Eingänge")).toBeNull();
    // Approved zone order, not server order.
    expect(
      [...list.querySelectorAll("[data-zone] .palette-label")].map(
        (label) => label.textContent,
      ),
    ).toEqual([
      "Übersicht",
      "Bestellungen",
      "Rechnungen",
      "Material",
      "Wissen",
    ]);
    expect(
      within(list).getByText("Auf dieser Seite · Mitglieder"),
    ).toBeTruthy();
    expect(within(list).getByText("Mitglied einladen")).toBeTruthy();
    // Footer coverage names only enabled module searches.
    expect(document.querySelector(".palette-footer")?.textContent).not.toMatch(
      /Aufgaben|Eingänge/,
    );
  });

  it("debounces, aborts the previous request per keystroke and shows only server hits", async () => {
    vi.useFakeTimers();
    const { client, pending, searchCore, empty } = fakeClient();
    renderPalette(client, navigationWithoutTasksAndInbox);
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    act(() => type("re"));
    expect(searchCore).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(150));
    expect(searchCore).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toContain("Wird gesucht");
    const first = pending[0]!;
    act(() => type("rec"));
    expect(first.signal.aborted).toBe(true);
    act(() => type("rech"));
    act(() => vi.advanceTimersByTime(150));
    // "rec" never left the debounce window; "rech" is the only other request.
    expect(searchCore.mock.calls.map(([parameters]) => parameters.q)).toEqual([
      "re",
      "rech",
    ]);
    const listsTasks = (client as unknown as { listTasks: unknown }).listTasks;
    expect(listsTasks).toBe(empty);
    // Restricted role: the server returns no invoice, so none shows.
    await act(async () => {
      pending[1]!.resolve({
        results: [
          {
            id: "a1",
            type: "action",
            title: "Krapfentaxi Nord",
            context: "Aktiv",
            href: "/admin/actions/a1",
          },
        ],
      });
      await vi.runAllTimersAsync();
    });
    const list = screen.getByRole("listbox");
    expect(within(list).getByText("Krapfentaxi Nord")).toBeTruthy();
    expect(list.querySelector("[data-hit-type='invoice']")).toBeNull();
    expect(
      within(list).queryByText("Rechnungen", {
        selector: "[cmdk-group-heading]",
      }),
    ).toBeNull();
  });

  it("offers only creates the account can reach, page creates first", () => {
    const { client } = fakeClient();
    const full = [
      ...navigationWithoutTasksAndInbox,
      nav("actions", "Charity-Aktionen"),
      nav("members", "Mitglieder"),
      nav("tasks", "Aufgaben"),
    ];
    const { unmount } = renderPalette(client, full);
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    const creates = () =>
      [
        ...(screen
          .getByRole("group", { name: "Anlegen" })
          .querySelectorAll(".palette-label") ?? []),
      ].map((label) => label.textContent);
    expect(creates()).toEqual([
      "Aktion anlegen",
      "Aufgabe anlegen",
      "Material hochladen",
      "Wissensseite anlegen",
      "Mitglied einladen",
    ]);
    act(() => {
      fireEvent(dialog(), new Event("cancel", { cancelable: true }));
    });
    unmount();
    resetCommandPaletteState();

    // Switched-off tasks, no core areas, and a page that creates in place.
    render(
      <HotkeyProvider>
        <OpenButton />
        <MaterialCreateInPlace />
        <CommandPalette
          context={{
            client,
            identity: identity(navigationWithoutTasksAndInbox),
          }}
          modules={webModules}
          surface="web"
        />
      </HotkeyProvider>,
    );
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    expect(creates()).toEqual(["Wissensseite anlegen"]);
    expect(
      screen.getByRole("group", { name: "Auf dieser Seite · Material" }),
    ).toBeTruthy();
  });

  it("puts the section with the best match first, as cmdk does", () => {
    const { client } = fakeClient();
    renderPalette(client, navigationWithoutTasksAndInbox);
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    const headings = () =>
      [...document.querySelectorAll("[cmdk-group-heading]")].map(
        (heading) => heading.textContent,
      );
    // Empty query: prototype order.
    expect(headings().slice(0, 3)).toEqual([
      "Auf dieser Seite · Mitglieder",
      "Anlegen",
      "Gehe zu",
    ]);
    act(() => type("rech"));
    expect(headings()[0]).toBe("Gehe zu");
    expect(
      document.querySelector("[cmdk-item][data-selected='true'] .palette-label")
        ?.textContent,
    ).toBe("Rechnungen");
  });

  it("keeps the user's selection when hits arrive and dims stale hits", async () => {
    vi.useFakeTimers();
    const { client, pending } = fakeClient();
    renderPalette(client, navigationWithoutTasksAndInbox, []);
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    act(() => type("re"));
    const selectedLabel = () =>
      document.querySelector("[cmdk-item][data-selected='true'] .palette-label")
        ?.textContent;
    const firstSelected = selectedLabel();
    act(() => {
      fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    });
    const moved = selectedLabel();
    expect(moved).not.toBe(firstSelected);
    act(() => vi.advanceTimersByTime(150));
    await act(async () => {
      pending[0]!.resolve({
        results: [
          {
            id: "a1",
            type: "action",
            title: "Rettung 2026",
            context: "Aktiv",
            href: "/admin/actions/a1",
          },
        ],
      });
      await vi.runAllTimersAsync();
    });
    expect(screen.getByText("Rettung 2026")).toBeTruthy();
    expect(selectedLabel()).toBe(moved);

    // The next query keeps the old hits dimmed and unselectable …
    act(() => type("ret"));
    const staleHit = screen
      .getByText("Rettung 2026")
      .closest<HTMLElement>("[cmdk-item]")!;
    expect(staleHit.getAttribute("aria-disabled")).toBe("true");
    expect(staleHit.closest("[data-stale='true']")).not.toBeNull();
    // … until its own answer replaces them.
    act(() => vi.advanceTimersByTime(150));
    await act(async () => {
      pending[1]!.resolve({ results: [] });
      await vi.runAllTimersAsync();
    });
    expect(screen.queryByText("Rettung 2026")).toBeNull();
  });

  it("shows the empty state when nothing matches", async () => {
    vi.useFakeTimers();
    const { client, pending } = fakeClient();
    renderPalette(client, navigationWithoutTasksAndInbox, []);
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    act(() => type("zzqx"));
    expect(document.querySelector(".palette-empty")).toBeNull();
    act(() => vi.advanceTimersByTime(150));
    await act(async () => {
      pending[0]!.resolve({ results: [] });
      await vi.runAllTimersAsync();
    });
    expect(document.querySelector(".palette-empty")?.textContent).toContain(
      "Keine Treffer für „zzqx“",
    );
  });

  it("shows the error state with a retry", async () => {
    vi.useFakeTimers();
    const searchCore = vi
      .fn()
      .mockRejectedValueOnce(new Error("503"))
      .mockResolvedValueOnce({ results: [] });
    const client = { searchCore } as unknown as LeonAidApiClient;
    renderPalette(client, navigationWithoutTasksAndInbox, []);
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    act(() => type("rech"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(screen.getByRole("status").textContent).toContain(
      "nicht erreichbar",
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
      await vi.advanceTimersByTimeAsync(150);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(searchCore).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status", { hidden: true }).hidden).toBe(true);
  });

  it("closes on Escape, returns focus and adds no <style> element", () => {
    const { client } = fakeClient();
    const styles = document.querySelectorAll("style").length;
    renderPalette(client, navigationWithoutTasksAndInbox);
    const opener = screen.getByText("Suche öffnen");
    opener.focus();
    act(() => {
      fireEvent.click(opener);
    });
    expect(dialog().open).toBe(true);
    act(() => {
      fireEvent(dialog(), new Event("cancel", { cancelable: true }));
    });
    expect(dialog().open).toBe(false);
    expect(document.activeElement).toBe(opener);
    expect(document.querySelectorAll("style").length).toBe(styles);
    expect(document.querySelector("[style]")).toBeNull();
  });

  it("keeps page Escape bindings from running behind the palette", () => {
    const { client } = fakeClient();
    renderPalette(client, navigationWithoutTasksAndInbox);
    act(() => {
      fireEvent.click(screen.getByText("Suche öffnen"));
    });
    const behind = vi.fn();
    window.addEventListener("keydown", behind);
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(behind).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("combobox"), {
      key: "k",
      ctrlKey: true,
    });
    expect(behind).toHaveBeenCalledTimes(1);
    window.removeEventListener("keydown", behind);
    expect(dialog().open).toBe(false);
  });
});

describe("requestedUnlistedAction", () => {
  const id = "20000000-0000-4000-8000-000000000003";
  const memberships = [{ actionId: "20000000-0000-4000-8000-000000000001" }];

  it("keeps a search link's action for roles that read every action", () => {
    expect(requestedUnlistedAction(memberships, true, `?action=${id}`)).toBe(
      id,
    );
  });

  it("ignores it for membership-scoped roles, listed and malformed ids", () => {
    expect(
      requestedUnlistedAction(memberships, false, `?action=${id}`),
    ).toBeNull();
    expect(
      requestedUnlistedAction(
        memberships,
        true,
        `?action=${memberships[0]!.actionId}`,
      ),
    ).toBeNull();
    expect(
      requestedUnlistedAction(memberships, true, "?action=../x"),
    ).toBeNull();
    expect(requestedUnlistedAction(memberships, true, "")).toBeNull();
  });
});
