import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type Case,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import { resetCommandPaletteState } from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

import { InboxPage } from "../../../packages/features/src/inbox/inbox";
import {
  managesCase,
  shortDay,
} from "../../../packages/features/src/inbox/inbox-model";
import { installDialogPolyfill } from "../../../packages/ui/src/test-utils/dialog-polyfill";

const me = "10000000-0000-4000-8000-000000000001";
const actionId = "20000000-0000-4000-8000-000000000001";

beforeAll(() => {
  installDialogPolyfill();
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
  resetCommandPaletteState();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/admin/inbox");
  vi.restoreAllMocks();
});

function inboxCase(id: string, overrides: Partial<Case> = {}): Case {
  return {
    actionId: null,
    assigneeUserId: null,
    closedAt: null,
    closureNote: null,
    contactErrorCode: null,
    contactRevision: 1,
    contactStatus: "pending",
    email: "mara@example.org",
    familyName: "Muster",
    givenName: "Mara",
    id,
    message: "Guten Tag,\nkönnen wir einen Termin abstimmen?",
    phone: null,
    publicReference: `E-${id.slice(-4)}`,
    receivedAt: "2026-10-28T09:14:00Z",
    revision: 3,
    status: "new",
    subject: `Anfrage ${id.slice(-4)}`,
    twentyPersonId: null,
    updatedAt: "2026-10-28T09:14:00Z",
    ...overrides,
  };
}

const caseId = (n: number) =>
  `30000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

function identity(
  overrides: Partial<CurrentIdentityResponse> = {},
): CurrentIdentityResponse {
  return {
    actionMemberships: [],
    displayName: "Klara Admin",
    email: "klara@example.org",
    freshLoginAt: "2026-11-03T08:00:00Z",
    freshUntil: "2026-11-03T09:00:00Z",
    globalRoles: ["system_admin"],
    installation: { clubName: "Lions Club Beispielstadt" },
    navigation: [],
    roleLabels: [],
    sessionExpiresAt: "2026-11-04T08:00:00Z",
    sessionLastSeenAt: "2026-11-03T08:00:00Z",
    userId: me,
    ...overrides,
  };
}

function client(cases: Case[], extra: Partial<LeonAidApiClient> = {}) {
  const state = new Map(cases.map((item) => [item.id, item]));
  const api = {
    listInboxCases: vi.fn(
      async ({
        offset = 0,
        limit = 50,
      }: {
        offset?: number;
        limit?: number;
      }) => {
        const all = [...state.values()];
        const items = all.slice(offset, offset + limit);
        return {
          items,
          nextOffset: offset + limit < all.length ? offset + limit : null,
        };
      },
    ),
    getInboxCase: vi.fn(async (id: string) => {
      const item = state.get(id);
      if (!item)
        throw new ApiError(404, {
          code: "not_found",
          message: "Fall nicht gefunden.",
        } as never);
      return item;
    }),
    updateInboxCase: vi.fn(
      async (
        id: string,
        body: {
          status: Case["status"];
          assigneeUserId: string | null;
          closureNote?: string | null;
        },
      ) => {
        const current = state.get(id)!;
        const next = {
          ...current,
          status: body.status,
          assigneeUserId: body.assigneeUserId,
          closureNote: body.closureNote ?? null,
          revision: current.revision + 1,
        };
        state.set(id, next);
        return next;
      },
    ),
    getInboxCasePermissions: vi.fn(async () => ({ canManage: true })),
    listInboxAssignees: vi.fn(async () => ({
      items: [
        { userId: me, displayName: "Klara Admin" },
        {
          userId: "10000000-0000-4000-8000-000000000002",
          displayName: "Jonas Weber",
        },
      ],
      nextOffset: null,
    })),
    listTaskActionContexts: vi.fn(async () => ({
      items: [{ actionId, name: "Adventskalender 2026", canCreateLists: true }],
      nextOffset: null,
    })),
    listInboxComments: vi.fn(async () => ({ items: [], nextOffset: null })),
    addInboxComment: vi.fn(),
    listInboxTaskReferences: vi.fn(async () => ({ items: [] })),
    listInboxMaterialReferences: vi.fn(async () => ({ items: [] })),
    ...extra,
  };
  return api as unknown as LeonAidApiClient & typeof api;
}

function renderPage(
  api: LeonAidApiClient,
  options: {
    readonly identity?: CurrentIdentityResponse;
    readonly caseId?: string;
    readonly surface?: "web" | "pwa";
    readonly providers?: boolean;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const page = (
    <InboxPage
      basePath={options.surface === "pwa" ? "/app/inbox" : "/admin/inbox"}
      caseId={options.caseId}
      client={api}
      identity={options.identity ?? identity()}
      surface={options.surface ?? "web"}
    />
  );
  return render(
    <QueryClientProvider client={queryClient}>
      {options.providers === false ? (
        page
      ) : (
        <HotkeyProvider>
          <ToastProvider>{page}</ToastProvider>
        </HotkeyProvider>
      )}
    </QueryClientProvider>,
  );
}

describe("inbox model", () => {
  it("mirrors the server's management rule", () => {
    const admin = identity();
    const charityAdmin = identity({
      globalRoles: [],
      actionMemberships: [
        {
          actionId,
          actionName: "Adventskalender",
          role: "charity_admin",
          roleLabel: "Charity-Admin",
        },
      ],
    });
    const acquirer = identity({
      globalRoles: [],
      actionMemberships: [
        {
          actionId,
          actionName: "Adventskalender",
          role: "acquirer",
          roleLabel: "Akquise",
        },
      ],
    });
    expect(managesCase(admin, { actionId: null })).toBe(true);
    expect(managesCase(charityAdmin, { actionId })).toBe(true);
    expect(managesCase(charityAdmin, { actionId: null })).toBe(false);
    expect(managesCase(acquirer, { actionId })).toBe(false);
  });

  it("formats the row day as in the prototype", () => {
    const now = new Date("2026-11-03T12:00:00");
    expect(shortDay("2026-10-28T09:14:00", now)).toBe("28.10.");
    expect(shortDay("2025-10-28T09:14:00", now)).toBe("28.10.2025");
  });
});

describe("inbox list", () => {
  it("loads every page and shows open cases in the default view", async () => {
    const cases = Array.from({ length: 130 }, (_, index) =>
      inboxCase(caseId(index + 1), {
        status: index === 0 ? "closed" : "new",
        closureNote: index === 0 ? "Termin vereinbart." : null,
      }),
    );
    const api = client(cases);
    renderPage(api);
    expect(
      await screen.findByText("Anfrage 0130", { exact: false }),
    ).toBeTruthy();
    expect(api.listInboxCases).toHaveBeenCalledTimes(2);
    expect(api.listInboxCases).toHaveBeenLastCalledWith(
      { offset: 100, limit: 100 },
      expect.anything(),
    );
    // "Offen" hides the closed case.
    expect(screen.queryByText("Anfrage 0001", { exact: false })).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Eingang" }));
  });

  it("turns the old case path into the pane", async () => {
    const id = caseId(7);
    window.history.replaceState(null, "", `/admin/inbox/${id}`);
    const api = client([inboxCase(id)]);
    renderPage(api, { caseId: id });
    const pane = await screen.findByRole("complementary", {
      name: /Details: Anfrage 0007/,
    });
    expect(window.location.pathname).toBe("/admin/inbox");
    const params = new URLSearchParams(window.location.search);
    expect(params.get("open")).toBe(id);
    expect(within(pane).getByText(/können wir einen Termin/)).toBeTruthy();
    expect(within(pane).getByText(/mit Einwilligung/)).toBeTruthy();
  });

  it("explains a case the account cannot open", async () => {
    window.history.replaceState(null, "", "/app/inbox");
    const api = client([inboxCase(caseId(1))]);
    renderPage(api, { caseId: caseId(99), surface: "pwa", providers: false });
    expect(
      await screen.findByText(
        "Dieser Eingang ist nicht mehr verfügbar oder du hast keinen Zugriff.",
      ),
    ).toBeTruthy();
    expect(api.getInboxCase).toHaveBeenCalledWith(caseId(99));
  });
});

describe("closing requires a note", () => {
  async function openPane(api: LeonAidApiClient, id: string) {
    window.history.replaceState(null, "", `/admin/inbox?open=${id}`);
    renderPage(api);
    return screen.findByRole("complementary", { name: /Details/ });
  }

  it("closes from the pane only with a note of 10 characters", async () => {
    const id = caseId(1);
    const api = client([inboxCase(id)]);
    const pane = await openPane(api, id);
    fireEvent.click(
      within(pane).getByRole("button", { name: "Abschließen …" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Anfrage abschließen",
    });
    const note = within(dialog).getByLabelText(/Abschlussnotiz/);
    fireEvent.change(note, { target: { value: "kurz" } });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Abschließen" }),
    );
    expect(
      await within(dialog).findByText(/mindestens 10 Zeichen/),
    ).toBeTruthy();
    expect(api.updateInboxCase).not.toHaveBeenCalled();

    fireEvent.change(note, {
      target: { value: "  Termin am Donnerstag vereinbart.  " },
    });
    await act(async () => {
      fireEvent.click(
        within(dialog).getByRole("button", { name: "Abschließen" }),
      );
    });
    await waitFor(() => expect(api.updateInboxCase).toHaveBeenCalledTimes(1));
    expect(api.updateInboxCase).toHaveBeenCalledWith(
      id,
      expect.objectContaining({
        status: "closed",
        closureNote: "Termin am Donnerstag vereinbart.",
        expectedRevision: 3,
        assigneeUserId: null,
      }),
    );
    expect(await screen.findByText("E-0001 abgeschlossen.")).toBeTruthy();
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Anfrage abschließen" }),
      ).toBeNull(),
    );
  });

  it("asks for the note when Status is set to Abgeschlossen; cancel changes nothing", async () => {
    const id = caseId(2);
    const api = client([inboxCase(id, { status: "in_progress" })]);
    const pane = await openPane(api, id);
    fireEvent.click(
      within(within(pane).getByRole("group", { name: "Eigenschaften" }))
        .getAllByRole("button")
        .find((button) => button.textContent?.includes("Status"))!,
    );
    fireEvent.click(
      await screen.findByRole("option", { name: /Abgeschlossen/ }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Anfrage abschließen",
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Abbrechen" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Anfrage abschließen" }),
      ).toBeNull(),
    );
    expect(api.updateInboxCase).not.toHaveBeenCalled();
    expect(screen.queryByText(/Status: Abgeschlossen/)).toBeNull();
    expect(screen.queryByText(/wurde nicht geändert/)).toBeNull();
  });

  it("reopens without a closing note", async () => {
    const id = caseId(3);
    const api = client([
      inboxCase(id, { status: "closed", closureNote: "Erledigt per Telefon." }),
    ]);
    const pane = await openPane(api, id);
    expect(
      await within(pane).findByText("Abschlussnotiz: Erledigt per Telefon."),
    ).toBeTruthy();
    fireEvent.click(
      within(within(pane).getByRole("group", { name: "Eigenschaften" }))
        .getAllByRole("button")
        .find((button) => button.textContent?.includes("Status"))!,
    );
    await act(async () => {
      fireEvent.click(
        await screen.findByRole("option", { name: /In Bearbeitung/ }),
      );
    });
    await waitFor(() =>
      expect(api.updateInboxCase).toHaveBeenCalledWith(
        id,
        expect.objectContaining({ status: "in_progress", closureNote: null }),
      ),
    );
  });
});

describe("assignment", () => {
  it("offers the eligible people to the case management", async () => {
    const id = caseId(4);
    const api = client([inboxCase(id)]);
    window.history.replaceState(null, "", `/admin/inbox?open=${id}`);
    renderPage(api);
    const pane = await screen.findByRole("complementary", { name: /Details/ });
    await waitFor(() => expect(api.listInboxAssignees).toHaveBeenCalled());
    fireEvent.click(
      within(within(pane).getByRole("group", { name: "Eigenschaften" }))
        .getAllByRole("button")
        .find((button) => button.textContent?.includes("Zuständigkeit"))!,
    );
    await act(async () => {
      fireEvent.click(
        await screen.findByRole("option", { name: /Jonas Weber/ }),
      );
    });
    await waitFor(() =>
      expect(api.updateInboxCase).toHaveBeenCalledWith(
        id,
        expect.objectContaining({
          assigneeUserId: "10000000-0000-4000-8000-000000000002",
          status: "new",
          closureNote: null,
        }),
      ),
    );
  });

  it("gives an assignee without management rights no assignment control", async () => {
    const id = caseId(5);
    const api = client([inboxCase(id, { actionId, assigneeUserId: me })]);
    window.history.replaceState(null, "", `/admin/inbox?open=${id}`);
    renderPage(api, {
      identity: identity({
        globalRoles: [],
        actionMemberships: [
          {
            actionId,
            actionName: "Adventskalender 2026",
            role: "acquirer",
            roleLabel: "Akquise",
          },
        ],
      }),
    });
    const pane = await screen.findByRole("complementary", { name: /Details/ });
    const props = within(pane).getByRole("group", { name: "Eigenschaften" });
    expect(within(props).queryByText("Zuständigkeit")).toBeNull();
    expect(within(props).getByText("Status")).toBeTruthy();
    expect(api.listInboxAssignees).not.toHaveBeenCalled();
    expect(within(pane).getAllByText("Adventskalender 2026").length).toBe(1);
  });

  it("takes a new case over: in progress and assigned to me", async () => {
    const id = caseId(6);
    const api = client([inboxCase(id)]);
    window.history.replaceState(null, "", `/admin/inbox?open=${id}`);
    renderPage(api);
    const pane = await screen.findByRole("complementary", { name: /Details/ });
    await act(async () => {
      fireEvent.click(within(pane).getByRole("button", { name: "Übernehmen" }));
    });
    await waitFor(() =>
      expect(api.updateInboxCase).toHaveBeenCalledWith(
        id,
        expect.objectContaining({ status: "in_progress", assigneeUserId: me }),
      ),
    );
    expect(await screen.findByText("Anfrage übernommen.")).toBeTruthy();
  });
});
