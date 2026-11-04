import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type DeliveryBoardResponse,
  type DeliveryDropResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  DeliveryBoardPage,
  deliveryWindowLabel,
  resetCommandPaletteState,
} from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

const actionId = "20000000-0000-4000-8000-000000000001";
const windowId = "98000000-0000-4000-8000-000000000001";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    if (!this.open) return;
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

beforeEach(() => resetCommandPaletteState());

function drop(
  id: string,
  buyerName: string,
  extra: Partial<DeliveryDropResponse> = {},
): DeliveryDropResponse {
  return {
    address: {
      city: "Augsburg",
      postalCode: "86150",
      recipientName: buyerName,
      streetLine1: "Lieferweg 2",
    },
    buyerName,
    commitmentId: id,
    contact: { name: "Empfang", phone: "+49 30 123" },
    driverName: null,
    driverUserId: null,
    missedAtClosure: false,
    orderStatus: "review_ready",
    quantities: [{ quantity: 3, unit: "box" }],
    revision: 0,
    state: "open",
    stateChangedAt: null,
    stateChangedByName: null,
    totalBoxes: 3,
    windowId,
    ...extra,
  };
}

function board(
  extra: Partial<DeliveryBoardResponse> = {},
): DeliveryBoardResponse {
  return {
    actionId,
    actionName: "Krapfentaxi",
    day: "2026-11-11",
    days: ["2026-11-11"],
    drivers: [{ displayName: "Fahrerin Anna", userId: "anna" }],
    followUpTasks: true,
    manager: true,
    timezone: "Europe/Berlin",
    windows: [
      {
        closure: null,
        drops: [
          drop("c1", "Bäckerei Kern", {
            driverName: "Fahrerin Anna",
            driverUserId: "anna",
          }),
          drop("c2", "Autohaus Nord", { revision: 2 }),
        ],
        endsAt: "2026-11-11T08:00:00Z",
        id: windowId,
        retired: false,
        startsAt: "2026-11-11T06:00:00Z",
      },
    ],
    ...extra,
  };
}

function fakeClient(initial: DeliveryBoardResponse) {
  let response = initial;
  return {
    getDeliveryBoard: vi.fn(async () => response),
    setDeliveryState: vi.fn(
      async (_a: string, id: string, body: { delivered: boolean }) => {
        let updated: DeliveryDropResponse | undefined;
        response = {
          ...response,
          windows: response.windows.map((window) => ({
            ...window,
            drops: window.drops.map((item) => {
              if (item.commitmentId !== id) return item;
              updated = {
                ...item,
                revision: item.revision + 1,
                state: body.delivered ? "delivered" : "open",
              };
              return updated;
            }),
          })),
        };
        return updated!;
      },
    ),
    closeDeliveryWindow: vi.fn(async () => ({
      followUp: "tasks",
      missedCount: 1,
    })),
    reopenDeliveryWindow: vi.fn(async () => ({ reopenedCount: 1 })),
    assignDeliveryDriver: vi.fn(async () => ({ changed: 1 })),
  } as unknown as LeonAidApiClient & Record<string, ReturnType<typeof vi.fn>>;
}

interface RenderOptions {
  readonly offline?: boolean;
  readonly actions?: readonly { actionId: string; actionName: string }[];
  readonly queries?: QueryClient;
}

function boardTree(
  client: LeonAidApiClient,
  surface: "web" | "pwa",
  {
    offline = false,
    actions,
    queries,
  }: RenderOptions & {
    queries: QueryClient;
  },
) {
  return (
    <QueryClientProvider client={queries}>
      <ToastProvider>
        <HotkeyProvider>
          <DeliveryBoardPage
            actionId={actionId}
            actions={actions}
            client={client}
            offline={offline}
            surface={surface}
          />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}

async function renderBoard(
  client: LeonAidApiClient,
  surface: "web" | "pwa" = "web",
  options: RenderOptions = {},
) {
  const queries =
    options.queries ??
    new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(boardTree(client, surface, { ...options, queries }));
  await screen.findAllByTestId("delivery-drop");
  return {
    queries,
    rerender: (next: RenderOptions) =>
      view.rerender(boardTree(client, surface, { ...next, queries })),
  };
}

describe("delivery board", () => {
  it("labels windows like the prototype", () => {
    expect(
      deliveryWindowLabel(
        { startsAt: "2026-11-11T06:00:00Z", endsAt: "2026-11-11T08:00:00Z" },
        "Europe/Berlin",
      ),
    ).toBe("Mi 11.11. · 07–09 Uhr");
  });

  it("shows the manager board with drivers, progress and the next step", async () => {
    const client = fakeClient(board());
    await renderBoard(client);
    expect(screen.getByRole("heading", { name: "Auslieferung" })).toBeTruthy();
    expect(screen.getByText("Mittwoch, 11. November")).toBeTruthy();
    const section = screen.getByTestId("delivery-window");
    expect(section.textContent).toContain(
      "0 von 2 geliefert · 6 Boxen · Fahrerin Anna",
    );
    expect(
      screen.getByRole("meter", { name: /0 von 2 geliefert/ }),
    ).toBeTruthy();
    expect(screen.getByText(/1 Lieferung hat noch keinen Fahrer/)).toBeTruthy();
    expect(screen.getByTestId("delivery-driver-filter")).toBeTruthy();
  });

  it("ticks a drop with its revision and offers undo", async () => {
    const client = fakeClient(board());
    await renderBoard(client);
    fireEvent.click(
      screen.getByRole("button", {
        name: /Autohaus Nord, 3 Boxen: als geliefert/,
      }),
    );
    await screen.findByText("Autohaus Nord: geliefert.");
    expect(client.setDeliveryState).toHaveBeenCalledWith(actionId, "c2", {
      delivered: true,
      expectedRevision: 2,
    });
    fireEvent.click(screen.getByRole("button", { name: "Rückgängig" }));
    // Undo sends the revision the server returned after the tick.
    await waitFor(() =>
      expect(client.setDeliveryState).toHaveBeenLastCalledWith(actionId, "c2", {
        delivered: false,
        expectedRevision: 3,
      }),
    );
  });

  it("filters by driver", async () => {
    await renderBoard(fakeClient(board()));
    fireEvent.change(screen.getByTestId("delivery-driver-filter"), {
      target: { value: "anna" },
    });
    expect(screen.getAllByTestId("delivery-drop")).toHaveLength(1);
    fireEvent.change(screen.getByTestId("delivery-driver-filter"), {
      target: { value: "none" },
    });
    expect(screen.getAllByTestId("delivery-drop")[0]!.textContent).toContain(
      "Autohaus Nord",
    );
  });

  it("closes a window after naming the open drops and the follow-up", async () => {
    const client = fakeClient(board());
    await renderBoard(client);
    fireEvent.click(screen.getByTestId("delivery-close-window"));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain(
      "2 Lieferungen sind noch nicht abgehakt.",
    );
    expect(dialog.textContent).toContain("als Aufgabe „Nachliefern“ für Sie");
    fireEvent.click(within(dialog).getByTestId("delivery-close-confirm"));
    await screen.findByText(/1 offene Lieferungen als Aufgabe angelegt/);
    expect(client.closeDeliveryWindow).toHaveBeenCalledWith(actionId, windowId);
  });

  it("says where open drops stay when tasks are switched off", async () => {
    await renderBoard(fakeClient(board({ followUpTasks: false })));
    fireEvent.click(screen.getByTestId("delivery-close-window"));
    expect((await screen.findByRole("dialog")).textContent).toContain(
      "bleiben mit dem Hinweis „Nachliefern“ auf dieser Tafel",
    );
  });

  it("gives drivers only ticking, in Du", async () => {
    await renderBoard(
      fakeClient(board({ manager: false, drivers: [] })),
      "pwa",
    );
    expect(screen.getByText(/Du siehst nur deine Lieferungen/)).toBeTruthy();
    expect(screen.queryByTestId("delivery-driver-filter")).toBeNull();
    expect(screen.queryByTestId("delivery-close-window")).toBeNull();
    expect(screen.queryByRole("button", { name: /Fahrer/ })).toBeNull();
    expect(screen.getAllByRole("link", { name: "+49 30 123" })).toHaveLength(2);
  });

  it("tells a closed window apart and lets managers deliver missed drops later", async () => {
    const client = fakeClient(
      board({
        windows: [
          {
            ...board().windows[0]!,
            closure: {
              closedAt: "2026-11-11T09:00:00Z",
              closedByName: "Klara Kern",
              missedCount: 1,
            },
            drops: [
              drop("c2", "Autohaus Nord", { state: "missed", revision: 3 }),
            ],
          },
        ],
      }),
    );
    await renderBoard(client);
    expect(screen.getByText("Abgeschlossen")).toBeTruthy();
    expect(screen.getByText("Nachliefern")).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", {
        name: /nicht geliefert, jetzt als geliefert/,
      }),
    );
    await screen.findByText("Autohaus Nord: geliefert.");
    expect(client.setDeliveryState).toHaveBeenCalledWith(actionId, "c2", {
      delivered: true,
      expectedRevision: 3,
    });
  });

  it("in a closed window takes back only a later delivery of a missed drop", async () => {
    const closed = {
      ...board().windows[0]!,
      closure: {
        closedAt: "2026-11-11T09:00:00Z",
        closedByName: "Klara Kern",
        missedCount: 1,
      },
      drops: [
        drop("c1", "Bäckerei Kern", { state: "delivered", revision: 1 }),
        drop("c2", "Autohaus Nord", {
          missedAtClosure: true,
          revision: 5,
          state: "delivered",
        }),
        drop("c3", "Neu Gebucht GmbH", { revision: 0 }),
      ],
    };
    const client = fakeClient(board({ windows: [closed] }));
    await renderBoard(client);
    // A regular delivery stays: undo needs the window reopened.
    const regular = screen.getByRole("button", {
      name: /Bäckerei Kern, 3 Boxen: geliefert, Fenster abgeschlossen/,
    }) as HTMLButtonElement;
    expect(regular.disabled).toBe(true);
    // The later delivery of a drop missed at closure can be taken back.
    const later = screen.getByRole("button", {
      name: /Autohaus Nord, 3 Boxen: geliefert, zurücknehmen/,
    }) as HTMLButtonElement;
    expect(later.disabled).toBe(false);
    // An open drop booked after the closure can still be ticked, once.
    fireEvent.click(
      screen.getByRole("button", {
        name: /Neu Gebucht GmbH, 3 Boxen: als geliefert/,
      }),
    );
    await screen.findByText("Neu Gebucht GmbH: geliefert.");
    expect(screen.queryByRole("button", { name: "Rückgängig" })).toBeNull();
  });

  it("shows no drops offline in the PWA and drops the cached board", async () => {
    const client = fakeClient(board({ manager: false, drivers: [] }));
    const view = await renderBoard(client, "pwa");
    expect(view.queries.getQueryCache().findAll()).not.toHaveLength(0);
    view.rerender({ offline: true });
    await screen.findByText(/Ohne Verbindung zeigen wir keine Lieferungen/);
    expect(screen.queryAllByTestId("delivery-drop")).toHaveLength(0);
    expect(
      view.queries.getQueryCache().findAll({ queryKey: ["delivery-board"] }),
    ).toHaveLength(0);
  });

  it("answers drivers in Du when the server refuses", async () => {
    const client = fakeClient(board({ manager: false, drivers: [] }));
    vi.mocked(client.setDeliveryState).mockRejectedValueOnce(
      new ApiError(403, {
        code: "delivery_not_assigned",
        message: "Diese Lieferung ist Ihnen nicht zugewiesen.",
        requestId: "req-1",
      }),
    );
    await renderBoard(client, "pwa");
    fireEvent.click(
      screen.getByRole("button", {
        name: /Autohaus Nord, 3 Boxen: als geliefert/,
      }),
    );
    await screen.findByText("Diese Lieferung ist dir nicht zugewiesen.");
    expect(screen.queryByText(/Ihnen/)).toBeNull();
  });

  it("names a failed reopen", async () => {
    const client = fakeClient(
      board({
        windows: [
          {
            ...board().windows[0]!,
            closure: {
              closedAt: "2026-11-11T09:00:00Z",
              closedByName: "Klara Kern",
              missedCount: 0,
            },
          },
        ],
      }),
    );
    vi.mocked(client.reopenDeliveryWindow).mockRejectedValueOnce(
      new Error("offline"),
    );
    await renderBoard(client);
    fireEvent.click(screen.getByRole("button", { name: "Wieder öffnen" }));
    await screen.findByText(/Bitte versuchen Sie es erneut/);
  });

  it("points to inviting drivers when the action has none", async () => {
    await renderBoard(fakeClient(board({ drivers: [] })));
    const invite = screen.getByTestId("delivery-next-invite");
    expect(invite.getAttribute("href")).toBe(
      `/admin/members/invitations?action=${actionId}`,
    );
    expect(screen.getByText(/noch keine Ausfahrer/)).toBeTruthy();
  });

  it("offers closing a past window once everything is delivered", async () => {
    const client = fakeClient(
      board({
        windows: [
          {
            ...board().windows[0]!,
            endsAt: "2020-01-01T08:00:00Z",
            startsAt: "2020-01-01T06:00:00Z",
            drops: [
              drop("c1", "Bäckerei Kern", {
                driverUserId: "anna",
                driverName: "Fahrerin Anna",
                state: "delivered",
              }),
              drop("c9", "Storno AG", { orderStatus: "cancelled" }),
            ],
          },
        ],
      }),
    );
    await renderBoard(client);
    // The cancelled drop neither needs a driver nor blocks the close.
    expect(screen.queryByTestId("delivery-next-assign")).toBeNull();
    fireEvent.click(screen.getByTestId("delivery-next-close"));
    expect((await screen.findByRole("dialog")).textContent).toContain(
      "Alle Lieferungen dieses Fensters sind abgehakt.",
    );
  });

  it("repeats the recipient only when it differs from the buyer", async () => {
    await renderBoard(
      fakeClient(
        board({
          windows: [
            {
              ...board().windows[0]!,
              drops: [
                drop("c1", "Bäckerei Kern"),
                drop("c2", "Autohaus Nord", {
                  address: {
                    city: "Augsburg",
                    postalCode: "86150",
                    recipientName: "Werkstatt Süd",
                    streetLine1: "Hofweg 1",
                  },
                }),
              ],
            },
          ],
        }),
      ),
    );
    const [first, second] = screen.getAllByTestId("delivery-drop");
    expect(first!.textContent).toContain("Lieferweg 2, 86150 Augsburg");
    expect(first!.textContent).not.toContain("Bäckerei Kern, Lieferweg");
    expect(second!.textContent).toContain("Werkstatt Süd, Hofweg 1");
  });

  it("drops finished commands from memory when the PWA goes offline", async () => {
    const client = fakeClient(board({ manager: false, drivers: [] }));
    const view = await renderBoard(client, "pwa");
    fireEvent.click(
      screen.getByRole("button", {
        name: /Autohaus Nord, 3 Boxen: als geliefert/,
      }),
    );
    await screen.findByText("Autohaus Nord: geliefert.");
    view.rerender({ offline: true });
    await screen.findByText(/Ohne Verbindung zeigen wir keine Lieferungen/);
    await waitFor(() =>
      expect(
        view.queries
          .getMutationCache()
          .findAll({ mutationKey: ["delivery-board"] }),
      ).toHaveLength(0),
    );
  });

  it("reminds of orders booked into a closed window", async () => {
    await renderBoard(
      fakeClient(
        board({
          windows: [
            {
              ...board().windows[0]!,
              closure: {
                closedAt: "2026-11-11T09:00:00Z",
                closedByName: "Klara Kern",
                missedCount: 0,
              },
              drops: [
                drop("c1", "Bäckerei Kern", { state: "delivered" }),
                drop("c3", "Neu Gebucht GmbH"),
              ],
            },
          ],
        }),
      ),
    );
    expect(
      screen.getByText(/1 Lieferung wurde nach dem Abschluss/),
    ).toBeTruthy();
    expect(screen.getByText("nach Abschluss gebucht")).toBeTruthy();
    fireEvent.click(screen.getByTestId("delivery-next-late"));
    await waitFor(() =>
      expect(document.activeElement?.getAttribute("aria-label")).toMatch(
        /^Neu Gebucht GmbH/,
      ),
    );
  });

  it("asks for drivers only for open drops", async () => {
    await renderBoard(
      fakeClient(
        board({
          windows: [
            {
              ...board().windows[0]!,
              drops: [
                drop("c1", "Bäckerei Kern", { state: "delivered" }),
                drop("c2", "Autohaus Nord"),
              ],
            },
          ],
        }),
      ),
    );
    expect(
      screen.getByText(/^1 Lieferung hat noch keinen Fahrer/),
    ).toBeTruthy();
  });

  it("says where open drops stay after closing without tasks", async () => {
    const client = fakeClient(board({ followUpTasks: false }));
    vi.mocked(client.closeDeliveryWindow).mockResolvedValueOnce({
      followUp: "board",
      missedCount: 2,
    });
    await renderBoard(client);
    fireEvent.click(screen.getByTestId("delivery-close-window"));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByTestId(
        "delivery-close-confirm",
      ),
    );
    await screen.findByText(
      "Fenster abgeschlossen. 2 offene Lieferungen bleiben mit dem Hinweis „Nachliefern“ auf dieser Tafel.",
    );
  });

  it("lets a driver with several actions switch between them", async () => {
    const other = "20000000-0000-4000-8000-000000000002";
    await renderBoard(
      fakeClient(board({ manager: false, drivers: [] })),
      "pwa",
      {
        actions: [
          { actionId, actionName: "Krapfentaxi" },
          { actionId: other, actionName: "Martinsgans" },
        ],
      },
    );
    const changed = vi.fn();
    window.addEventListener("leonaid:action-changed", changed);
    fireEvent.change(screen.getByTestId("delivery-action"), {
      target: { value: other },
    });
    expect(new URLSearchParams(window.location.search).get("action")).toBe(
      other,
    );
    expect(changed).toHaveBeenCalled();
    window.removeEventListener("leonaid:action-changed", changed);
  });
});
