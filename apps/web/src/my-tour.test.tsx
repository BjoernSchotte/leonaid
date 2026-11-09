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
  type DeliveryDropResponse,
  type DeliveryTourResponse,
  type DeliveryTourStopResponse,
  type DeliveryTourWindowResponse,
  type LeonAidApiClient,
  type MyTourResponse,
} from "@leonaid/api-client";
import { MyTourPage } from "@leonaid/features";
import { ToastProvider } from "@leonaid/ui";

const actionId = "20000000-0000-4000-8000-000000000001";
const DAY = "2099-12-05";

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Element.prototype.scrollIntoView ??= () => {};
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function drop(
  id: string,
  buyerName: string,
  windowId: string,
  extra: Partial<DeliveryDropResponse> = {},
): DeliveryDropResponse {
  return {
    address: {
      city: "Augsburg",
      postalCode: "86150",
      recipientName: buyerName,
      streetLine1: `${buyerName.split(" ")[0]}weg 2`,
    },
    buyerName,
    commitmentId: id,
    contact: { name: "Empfang", phone: "+49 821 123" },
    driverName: "Fahrerin Anna",
    driverUserId: "anna",
    missedAtClosure: false,
    orderStatus: "review_ready",
    quantities: [
      { quantity: 3, unit: "box" },
      { quantity: 12, unit: "piece" },
    ],
    revision: 0,
    state: "open",
    stateChangedAt: null,
    stateChangedByName: null,
    totalBoxes: 3,
    windowId,
    ...extra,
  };
}

function stop(
  value: DeliveryDropResponse,
  rank: number,
  extra: Partial<DeliveryTourStopResponse> = {},
): DeliveryTourStopResponse {
  return {
    baseRank: rank,
    driverRank: null,
    drop: value,
    effectiveRank: rank,
    newForDriver: false,
    ...extra,
  };
}

function window(
  windowId: string,
  startsAt: string,
  endsAt: string,
  stops: DeliveryTourStopResponse[],
): DeliveryTourWindowResponse {
  return { closed: false, endsAt, startsAt, stops, windowId };
}

/** Two windows: 08–10 (Bäckerei Kern, Autohaus Nord), 10–12 (Praxis Süd). */
function myTour(
  extra: {
    day?: string;
    driverOrderedAt?: string | null;
    windows?: DeliveryTourWindowResponse[];
  } = {},
): MyTourResponse {
  const day = extra.day ?? DAY;
  return {
    actionId,
    actionName: "Krapfentaxi",
    days: [day],
    timezone: "Europe/Berlin",
    tour: {
      day,
      driverName: "Fahrerin Anna",
      driverOrderedAt: extra.driverOrderedAt ?? null,
      driverUserId: "anna",
      revision: "r1",
      windows: extra.windows ?? [
        window("w1", `${day}T07:00:00Z`, `${day}T09:00:00Z`, [
          stop(drop("c1", "Bäckerei Kern", "w1"), 1),
          stop(drop("c2", "Autohaus Nord", "w1", { revision: 2 }), 2),
        ]),
        window("w2", `${day}T09:00:00Z`, `${day}T11:00:00Z`, [
          stop(drop("c3", "Praxis Süd", "w2"), 1),
        ]),
      ],
    },
  };
}

function fakeClient(initial: MyTourResponse) {
  let response = initial;
  let revision = 1;
  const mapTour = (
    change: (tour: DeliveryTourResponse) => DeliveryTourResponse,
  ) => {
    if (!response.tour) throw new Error("no tour");
    response = { ...response, tour: change(response.tour) };
    return response.tour!;
  };
  return {
    getMyTour: vi.fn(async () => response),
    setDeliveryState: vi.fn(
      async (
        _action: string,
        id: string,
        body: { delivered: boolean; missed?: boolean },
      ) => {
        let updated: DeliveryDropResponse | undefined;
        mapTour((tour) => ({
          ...tour,
          windows: tour.windows.map((item) => ({
            ...item,
            stops: item.stops.map((entry) => {
              if (entry.drop.commitmentId !== id) return entry;
              updated = {
                ...entry.drop,
                revision: entry.drop.revision + 1,
                state: body.delivered
                  ? "delivered"
                  : body.missed
                    ? "missed"
                    : "open",
              };
              return { ...entry, drop: updated };
            }),
          })),
        }));
        return updated!;
      },
    ),
    saveMyTourOrder: vi.fn(
      async (_action: string, body: { commitmentIds: string[] }) => {
        revision += 1;
        return mapTour((tour) => ({
          ...tour,
          driverOrderedAt: body.commitmentIds.length
            ? "2099-12-05T06:30:00Z"
            : null,
          revision: `r${revision}`,
          windows: tour.windows.map((item) => {
            const rankOf = (entry: DeliveryTourStopResponse) =>
              body.commitmentIds.length
                ? body.commitmentIds.indexOf(entry.drop.commitmentId)
                : entry.baseRank;
            const stops = [...item.stops]
              .sort((a, b) => rankOf(a) - rankOf(b))
              .map((entry, index) => ({
                ...entry,
                driverRank: body.commitmentIds.length ? index + 1 : null,
                effectiveRank: index + 1,
                newForDriver: false,
              }));
            return { ...item, stops };
          }),
        }));
      },
    ),
  } as unknown as LeonAidApiClient & Record<string, ReturnType<typeof vi.fn>>;
}

function tree(client: LeonAidApiClient, queries: QueryClient, offline = false) {
  return (
    <QueryClientProvider client={queries}>
      <ToastProvider>
        <MyTourPage actionId={actionId} client={client} offline={offline} />
      </ToastProvider>
    </QueryClientProvider>
  );
}

async function renderTour(client: LeonAidApiClient) {
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(tree(client, queries));
  await screen.findByTestId("tour-next-stop");
  return {
    queries,
    rerender: (offline: boolean) =>
      view.rerender(tree(client, queries, offline)),
  };
}

const card = () => screen.getByTestId("tour-next-stop");

describe("Meine Tour", () => {
  it("shows the first open stop as the large card with navigation and tel links", async () => {
    await renderTour(fakeClient(myTour()));
    expect(screen.getByRole("heading", { name: "Meine Tour" })).toBeTruthy();
    expect(screen.getByTestId("tour-day").textContent).toContain("Sa 05.12.");
    expect(screen.getByText("0 von 3 zugestellt")).toBeTruthy();
    expect(screen.getByText("Reihenfolge der Planung")).toBeTruthy();
    const next = within(card());
    expect(next.getByRole("heading", { name: "Bäckerei Kern" })).toBeTruthy();
    expect(card().textContent).toContain("3 Boxen, 12 Stück");
    expect(card().textContent).toContain("Empfang");
    expect(
      next.getByRole("link", { name: "Navigation" }).getAttribute("href"),
    ).toBe(
      "https://www.openstreetmap.org/search?query=B%C3%A4ckereiweg%202%2C%2086150%20Augsburg",
    );
    expect(
      next.getByRole("link", { name: "Empfang anrufen" }).getAttribute("href"),
    ).toBe("tel:+49821123");
    expect(next.getByRole("button", { name: "Zugestellt" })).toBeTruthy();
    expect(
      next.getByRole("button", { name: "Nicht angetroffen" }),
    ).toBeTruthy();
    const rows = screen.getAllByTestId("tour-stop");
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Autohaus Nord"),
      expect.stringContaining("Praxis Süd"),
    ]);
    expect(rows[0]!.textContent).toContain("Autohausweg 2");
    expect(rows[0]!.textContent).toContain("3 Boxen, 12 Stück");
    // The Karte toggle comes with the map (Task 11).
    expect(screen.queryByRole("button", { name: /Karte/ })).toBeNull();
  });

  it("address links to OpenStreetMap", async () => {
    await renderTour(fakeClient(myTour()));
    const address = within(card()).getByRole("link", {
      name: /Bäckereiweg 2/,
    });
    expect(address.getAttribute("href")).toBe(
      "https://www.openstreetmap.org/search?query=B%C3%A4ckereiweg%202%2C%2086150%20Augsburg",
    );
    expect(address.getAttribute("target")).toBe("_blank");
    expect(address.getAttribute("rel")).toBe("noopener");
    const row = within(screen.getAllByTestId("tour-stop")[0]!).getByRole(
      "link",
      { name: /Autohausweg 2/ },
    );
    expect(row.getAttribute("href")).toBe(
      "https://www.openstreetmap.org/search?query=Autohausweg%202%2C%2086150%20Augsburg",
    );
    expect(row.getAttribute("target")).toBe("_blank");
  });

  it("delivered stop stays in place greyed and collapsed; the next open stop becomes the large card; tapping the done line expands it", async () => {
    const client = fakeClient(myTour());
    await renderTour(client);
    fireEvent.click(within(card()).getByRole("button", { name: "Zugestellt" }));
    const done = await screen.findByTestId("tour-stop-done");
    expect(client.setDeliveryState).toHaveBeenCalledWith(actionId, "c1", {
      delivered: true,
      expectedRevision: 0,
      missed: false,
    });
    expect(done.textContent).toContain("Bäckerei Kern");
    expect(done.textContent).toContain("1");
    // Collapsed: one line, no address.
    expect(done.textContent).not.toContain("Bäckereiweg");
    await waitFor(() =>
      expect(
        within(card()).getByRole("heading", { name: "Autohaus Nord" }),
      ).toBeTruthy(),
    );
    expect(screen.getByText("1 von 3 zugestellt")).toBeTruthy();
    // In place: the done line stays above the next stop, in its window.
    expect(
      done.compareDocumentPosition(card()) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const toggle = within(done).getByRole("button", { name: /Bäckerei Kern/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const expanded = screen.getByTestId("tour-stop-done");
    expect(expanded.textContent).toContain("Bäckereiweg 2");
    expect(
      within(expanded).getByRole("button", { name: "Rückgängig" }),
    ).toBeTruthy();
  });

  it("Nicht angetroffen marks the stop missed on the server", async () => {
    const client = fakeClient(myTour());
    await renderTour(client);
    fireEvent.click(
      within(card()).getByRole("button", { name: "Nicht angetroffen" }),
    );
    await screen.findByText("Bäckerei Kern: nicht angetroffen.");
    expect(client.setDeliveryState).toHaveBeenCalledWith(actionId, "c1", {
      delivered: false,
      expectedRevision: 0,
      missed: true,
    });
    expect(screen.getByTestId("tour-stop-done").textContent).toContain(
      "Nicht angetroffen",
    );
  });

  it("undo within 10 s restores the stop", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const client = fakeClient(myTour());
    await renderTour(client);
    fireEvent.click(within(card()).getByRole("button", { name: "Zugestellt" }));
    await screen.findByText("Bäckerei Kern: zugestellt.");
    await act(() => vi.advanceTimersByTimeAsync(9_000));
    const undo = screen.getByRole("button", { name: "Rückgängig" });
    fireEvent.click(undo);
    await waitFor(() =>
      expect(client.setDeliveryState).toHaveBeenLastCalledWith(actionId, "c1", {
        delivered: false,
        expectedRevision: 1,
        missed: false,
      }),
    );
    await waitFor(() =>
      expect(
        within(card()).getByRole("heading", { name: "Bäckerei Kern" }),
      ).toBeTruthy(),
    );
    expect(screen.queryByTestId("tour-stop-done")).toBeNull();
  });

  it("reorder by buttons then Fertig sends the full order with the revision", async () => {
    const client = fakeClient(myTour());
    await renderTour(client);
    fireEvent.click(screen.getByTestId("tour-reorder"));
    // Moves stay inside a window: the first stop of 10–12 cannot go up.
    expect(
      screen
        .getByRole("button", { name: "Praxis Süd nach oben" })
        .getAttribute("aria-disabled"),
    ).toBe("true");
    fireEvent.click(
      screen.getByRole("button", { name: "Autohaus Nord nach oben" }),
    );
    expect(
      screen.getAllByTestId("tour-stop").map((row) => row.textContent),
    ).toEqual([
      expect.stringContaining("Autohaus Nord"),
      expect.stringContaining("Bäckerei Kern"),
      expect.stringContaining("Praxis Süd"),
    ]);
    fireEvent.click(screen.getByTestId("tour-reorder-done"));
    await screen.findByText(
      "Deine Reihenfolge ist gespeichert. Die Planung sieht sie.",
    );
    expect(client.saveMyTourOrder).toHaveBeenCalledWith(actionId, {
      commitmentIds: ["c2", "c1", "c3"],
      day: DAY,
      expectedRevision: "r1",
    });
    await waitFor(() =>
      expect(
        within(card()).getByRole("heading", { name: "Autohaus Nord" }),
      ).toBeTruthy(),
    );
    expect(screen.getByText("Eigene Reihenfolge")).toBeTruthy();
  });

  it("reorder by keyboard (space, arrow, space) moves within the window only", async () => {
    // jsdom has no layout: stack the rows 60 px apart for dnd-kit.
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(
      function (this: Element) {
        const rows = [...document.querySelectorAll(".tour-row")];
        const index = rows.indexOf(this.closest(".tour-row") as Element);
        const top = Math.max(0, index) * 60;
        return {
          bottom: top + 56,
          height: 56,
          left: 0,
          right: 320,
          top,
          width: 320,
          x: 0,
          y: top,
          toJSON: () => ({}),
        } as DOMRect;
      },
    );
    const client = fakeClient(myTour());
    await renderTour(client);
    fireEvent.click(screen.getByTestId("tour-reorder"));
    // dnd-kit starts listening for the arrow keys on a timer.
    const press = async (key: string, code: string) => {
      await act(async () => {
        fireEvent.keyDown(document.activeElement!, { code, key });
        await new Promise((resolve) => setTimeout(resolve, 20));
      });
    };
    const keyboardMove = async (name: string, key: string) => {
      screen
        .getByRole("button", { name: `Stopp verschieben: ${name}` })
        .focus();
      await press(" ", "Space");
      await press(key, key);
      await press(" ", "Space");
    };
    const names = () =>
      screen
        .getAllByTestId("tour-stop")
        .map((row) => within(row).getByTestId("tour-stop-name").textContent);
    await keyboardMove("Bäckerei Kern", "ArrowDown");
    await waitFor(() =>
      expect(names()).toEqual(["Autohaus Nord", "Bäckerei Kern", "Praxis Süd"]),
    );
    // The last stop of 08–10 does not cross into 10–12.
    await keyboardMove("Bäckerei Kern", "ArrowDown");
    expect(names()).toEqual(["Autohaus Nord", "Bäckerei Kern", "Praxis Süd"]);
    fireEvent.click(screen.getByTestId("tour-reorder-done"));
    await waitFor(() =>
      expect(client.saveMyTourOrder).toHaveBeenCalledWith(actionId, {
        commitmentIds: ["c2", "c1", "c3"],
        day: DAY,
        expectedRevision: "r1",
      }),
    );
  });

  it("Zurück zur Planung sends an empty list", async () => {
    const client = fakeClient(
      myTour({ driverOrderedAt: "2099-12-05T06:00:00Z" }),
    );
    await renderTour(client);
    expect(screen.getByText("Eigene Reihenfolge")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tour-reorder"));
    fireEvent.click(screen.getByTestId("tour-reset-order"));
    await screen.findByText("Es gilt wieder die Reihenfolge der Planung.");
    expect(client.saveMyTourOrder).toHaveBeenCalledWith(actionId, {
      commitmentIds: [],
      day: DAY,
      expectedRevision: "r1",
    });
    expect(screen.getByText("Reihenfolge der Planung")).toBeTruthy();
    expect(screen.queryByTestId("tour-reorder-done")).toBeNull();
  });

  it("appended stop shows neu", async () => {
    const tour = myTour({ driverOrderedAt: "2099-12-05T06:00:00Z" });
    const windows = tour.tour!.windows;
    await renderTour(
      fakeClient(
        myTour({
          driverOrderedAt: "2099-12-05T06:00:00Z",
          windows: [
            windows[0]!,
            {
              ...windows[1]!,
              stops: [
                ...windows[1]!.stops,
                stop(drop("c4", "Kanzlei West", "w2"), 2, {
                  newForDriver: true,
                }),
              ],
            },
          ],
        }),
      ),
    );
    const rows = screen.getAllByTestId("tour-stop");
    const appended = rows.find((row) =>
      row.textContent?.includes("Kanzlei West"),
    )!;
    expect(within(appended).getByText("neu")).toBeTruthy();
    expect(rows.filter((row) => row.textContent?.includes("neu"))).toHaveLength(
      1,
    );
  });

  it("ended window shows Fenster vorbei", async () => {
    const day = "2020-12-05";
    await renderTour(
      fakeClient(
        myTour({
          day,
          windows: [
            window("w1", `${day}T07:00:00Z`, `${day}T09:00:00Z`, [
              stop(drop("c1", "Bäckerei Kern", "w1"), 1),
              stop(drop("c2", "Autohaus Nord", "w1"), 2),
              stop(
                drop("c5", "Hotel Ost", "w1", {
                  revision: 1,
                  state: "delivered",
                }),
                3,
              ),
            ]),
          ],
        }),
      ),
    );
    expect(within(card()).getByText("Fenster vorbei")).toBeTruthy();
    expect(
      within(screen.getByTestId("tour-stop")).getByText("Fenster vorbei"),
    ).toBeTruthy();
    expect(
      within(screen.getByTestId("tour-stop-done")).queryByText(
        "Fenster vorbei",
      ),
    ).toBeNull();
  });

  it('conflict 409 shows "Die Tour wurde inzwischen geändert." and refetches', async () => {
    const client = fakeClient(myTour());
    vi.mocked(client.saveMyTourOrder).mockRejectedValueOnce(
      new ApiError(409, {
        code: "tour_revision_conflict",
        message: "Die Tour wurde inzwischen geändert.",
        requestId: "req-1",
      }),
    );
    await renderTour(client);
    const loads = vi.mocked(client.getMyTour).mock.calls.length;
    fireEvent.click(screen.getByTestId("tour-reorder"));
    fireEvent.click(
      screen.getByRole("button", { name: "Autohaus Nord nach oben" }),
    );
    fireEvent.click(screen.getByTestId("tour-reorder-done"));
    await screen.findByText("Die Tour wurde inzwischen geändert.");
    await waitFor(() =>
      expect(vi.mocked(client.getMyTour).mock.calls.length).toBeGreaterThan(
        loads,
      ),
    );
    expect(screen.queryByTestId("tour-reorder-done")).toBeNull();
  });

  it("shows nothing offline and drops the cached tour", async () => {
    const client = fakeClient(myTour());
    const view = await renderTour(client);
    view.rerender(true);
    await screen.findByText(/Ohne Verbindung zeigen wir deine Tour nicht/);
    expect(screen.queryByTestId("tour-next-stop")).toBeNull();
    expect(
      view.queries.getQueryCache().findAll({ queryKey: ["my-tour"] }),
    ).toHaveLength(0);
  });
});
