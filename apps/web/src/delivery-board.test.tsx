import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DeliveryBoardResponse,
  DeliveryDropResponse,
  LeonAidApiClient,
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

async function renderBoard(
  client: LeonAidApiClient,
  surface: "web" | "pwa" = "web",
) {
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <ToastProvider>
        <HotkeyProvider>
          <DeliveryBoardPage
            actionId={actionId}
            client={client}
            surface={surface}
          />
        </HotkeyProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findAllByTestId("delivery-drop");
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
      "bleiben auf dieser Tafel unter „Nachliefern“",
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
});
