import {
  onlineManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { TypedInMemoryProvider } from "@openfeature/react-sdk";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type DeliveryDropResponse,
  type DeliveryTourResponse,
  type DeliveryTourStopResponse,
  type DeliveryTourWindowResponse,
  type CurrentIdentityResponse,
  type LeonAidApiClient,
  type MyTourResponse,
} from "@leonaid/api-client";
import {
  FEATURE_FLAGS,
  FeatureFlagProvider,
  driverStanding,
  MyTourPage,
  PwaDeliveryPage,
  PwaDriverStart,
  useLeonAidSettledFlag,
} from "@leonaid/features";
import { ToastProvider } from "@leonaid/ui";

import { QueueController } from "../../../packages/features/src/offline/controller";
import type {
  CacheEntryInfo,
  CacheKind,
  CachedValue,
} from "../../../packages/features/src/offline/device-store";
import {
  MemoryQueueStore,
  type QueueEntry,
} from "../../../packages/features/src/offline/queue";
import {
  OfflineRuntimeContext,
  type OfflineRuntime,
} from "../../../packages/features/src/offline/runtime";
import { sendEntry } from "../../../packages/features/src/offline/sync";
import {
  saveTour,
  type TourCacheStore,
} from "../../../packages/features/src/offline/tour-cache";

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
    contact: { driverNote: null, name: "Empfang", phone: "+49 821 123" },
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
    lat: null,
    lon: null,
    newForDriver: false,
    ...extra,
  };
}

function tourWindow(
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
    map: {
      attribution: "© OpenStreetMap-Mitwirkende",
      tileUrl: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    },
    startPoint: null,
    timezone: "Europe/Berlin",
    tour: {
      day,
      driverName: "Fahrerin Anna",
      driverOrderedAt: extra.driverOrderedAt ?? null,
      driverUserId: "anna",
      revision: "r1",
      windows: extra.windows ?? [
        tourWindow("w1", `${day}T07:00:00Z`, `${day}T09:00:00Z`, [
          stop(drop("c1", "Bäckerei Kern", "w1"), 1),
          stop(drop("c2", "Autohaus Nord", "w1", { revision: 2 }), 2),
        ]),
        tourWindow("w2", `${day}T09:00:00Z`, `${day}T11:00:00Z`, [
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

async function renderTour(client: LeonAidApiClient, ready = "tour-next-stop") {
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = render(tree(client, queries));
  await screen.findByTestId(ready);
  return {
    queries,
    rerender: (offline: boolean) =>
      view.rerender(tree(client, queries, offline)),
  };
}

const card = () => screen.getByTestId("tour-next-stop");
const dock = () => screen.getByTestId("tour-dock");
const names = () =>
  screen
    .getAllByTestId("tour-stop")
    .map((row) => within(row).getByTestId("tour-stop-name").textContent);

/** jsdom has no layout: stack the rows 60 px apart for dnd-kit. */
function stackRows() {
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
}

/** Space, arrow, space on a grip (dnd-kit listens for keys on a timer). */
async function keyboardMove(name: string, key: string) {
  const press = async (value: string, code: string) => {
    await act(async () => {
      fireEvent.keyDown(document.activeElement!, { code, key: value });
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  };
  screen.getByRole("button", { name: `Stopp verschieben: ${name}` }).focus();
  await press(" ", "Space");
  await press(key, key);
  await press(" ", "Space");
}

describe("Meine Tour", () => {
  it("docks the next stop with quantity, map slot, navigation, call and both outcomes", async () => {
    await renderTour(fakeClient(myTour()));
    expect(
      screen.getByRole("heading", { name: "Meine Tour", level: 1 }),
    ).toBeTruthy();
    expect(screen.getByTestId("tour-bar-sub").textContent).toBe(
      "Meine Tour · Sa 05.12.",
    );
    expect(screen.getByTestId("tour-progress").textContent).toBe("0/3");
    expect(
      screen.getByRole("meter", { name: "0 von 3 zugestellt" }),
    ).toBeTruthy();
    // No edit mode and no planner language (D16, critique P1-1).
    expect(screen.queryByText("Reihenfolge ändern")).toBeNull();
    expect(screen.queryByText("Fertig")).toBeNull();
    expect(screen.queryByText("Reihenfolge der Planung")).toBeNull();

    const next = within(card());
    expect(next.getByRole("heading", { name: "Bäckerei Kern" })).toBeTruthy();
    expect(screen.getByTestId("tour-dock-qty").textContent).toBe(
      "3 Boxen · 12 Stk",
    );
    // The address is plain text; the town shows only when it differs.
    expect(card().querySelector(".tour-dock-address")?.textContent).toBe(
      "Bäckereiweg 2, 86150 Augsburg",
    );
    expect(next.queryByRole("link", { name: /Bäckereiweg/ })).toBeNull();
    // No pin yet: no map box, one muted line and the OSM search.
    expect(next.getByTestId("tour-map").textContent).toBe(
      "Adresse ohne Kartenpunkt",
    );
    const osm = next.getByRole("link", { name: "In OpenStreetMap öffnen" });
    expect(osm.getAttribute("href")).toBe(
      "https://www.openstreetmap.org/search?query=B%C3%A4ckereiweg%202%2C%2086150%20Augsburg",
    );
    expect(osm.getAttribute("target")).toBe("_blank");
    expect(osm.getAttribute("rel")).toBe("noopener");
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
      next.getByRole("button", { name: "Nicht da (nicht angetroffen)" })
        .textContent,
    ).toBe("Nicht da");
    // No contact panel: the phone is the call button.
    expect(screen.queryByText("Lieferkontakt")).toBeNull();

    // The list: every stop in order, the docked one marked; street and
    // quantity in the row, no link.
    expect(names()).toEqual(["Bäckerei Kern", "Autohaus Nord", "Praxis Süd"]);
    const rows = screen.getAllByTestId("tour-stop");
    expect(rows[0]!.classList.contains("is-current")).toBe(true);
    expect(rows[1]!.textContent).toContain("Autohausweg 2");
    expect(rows[1]!.textContent).toContain("3 Boxen · 12 Stk");
    expect(within(rows[1]!).queryByRole("link")).toBeNull();
    // Grips are always there where a window has two open stops.
    expect(
      within(rows[1]!).getByRole("button", {
        name: "Stopp verschieben: Autohaus Nord",
      }),
    ).toBeTruthy();
    expect(
      within(rows[2]!).queryByRole("button", { name: /Stopp verschieben/ }),
    ).toBeNull();
    // Window labels are headings with the window's count.
    expect(
      screen.getByRole("heading", { name: /08–10 Uhr · 0\/2/ }),
    ).toBeTruthy();
  });

  it("Zugestellt keeps the stop in place and moves the dock on to the next stop", async () => {
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
    // Collapsed: one line, no address, no grip.
    expect(done.textContent).not.toContain("Bäckereiweg");
    expect(
      within(done).queryByRole("button", { name: /verschieben/ }),
    ).toBeNull();
    expect(within(done).getByRole("img", { name: "Zugestellt" })).toBeTruthy();
    const heading = await within(card()).findByRole("heading", {
      name: "Autohaus Nord",
    });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(screen.getByTestId("tour-progress").textContent).toBe("1/3");
    // In place: the done line stays first in its window.
    const rows = [...document.querySelectorAll("ol.tour-rows > li")];
    expect(rows[0]).toBe(done);
    expect(await screen.findByText("Bäckerei Kern: zugestellt.")).toBeTruthy();

    const toggle = within(done).getByRole("button", { name: /Bäckerei Kern/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const expanded = screen.getByTestId("tour-stop-done");
    expect(expanded.textContent).toContain("Bäckereiweg 2, 86150 Augsburg");
    expect(expanded.textContent).toContain("3 Boxen, 12 Stück");
    expect(
      within(expanded).getByRole("button", { name: "Rückgängig" }),
    ).toBeTruthy();
    // A finished stop opens a compact panel, never a second card.
    expect(
      within(expanded).queryByRole("link", { name: "Navigation" }),
    ).toBeNull();
  });

  it("Nicht angetroffen marks the stop missed on the server", async () => {
    const client = fakeClient(myTour());
    await renderTour(client);
    fireEvent.click(
      within(card()).getByRole("button", { name: /Nicht angetroffen/i }),
    );
    await screen.findByText("Bäckerei Kern: nicht angetroffen.");
    expect(client.setDeliveryState).toHaveBeenCalledWith(actionId, "c1", {
      delivered: false,
      expectedRevision: 0,
      missed: true,
    });
    expect(
      within(screen.getByTestId("tour-stop-done")).getByRole("img", {
        name: "Nicht angetroffen",
      }),
    ).toBeTruthy();
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

  it("driver note shows on the next-stop card and on the stop row", async () => {
    const note = {
      name: "Empfang",
      phone: null,
      driverNote: "Hintereingang im Hof",
    };
    await renderTour(
      fakeClient(
        myTour({
          windows: [
            tourWindow("w1", `${DAY}T07:00:00Z`, `${DAY}T09:00:00Z`, [
              stop(drop("c1", "Bäckerei Kern", "w1", { contact: note }), 1),
              stop(drop("c2", "Autohaus Nord", "w1"), 2),
            ]),
          ],
        }),
      ),
    );
    expect(within(card()).getByTestId("driver-note").textContent).toContain(
      "Hintereingang im Hof",
    );
    const rows = screen.getAllByTestId("tour-stop");
    expect(within(rows[0]!).getByTestId("driver-note")).toBeTruthy();
    expect(within(rows[1]!).queryByTestId("driver-note")).toBeNull();
  });

  it("a long driver note folds in the dock behind mehr", async () => {
    const long = "Hinterhof, zweite Tür links, dann klingeln. "
      .repeat(4)
      .trim();
    await renderTour(
      fakeClient(
        myTour({
          windows: [
            tourWindow("w1", `${DAY}T07:00:00Z`, `${DAY}T09:00:00Z`, [
              stop(
                drop("c1", "Bäckerei Kern", "w1", {
                  contact: { name: null, phone: null, driverNote: long },
                }),
                1,
              ),
            ]),
          ],
        }),
      ),
    );
    const note = within(card()).getByTestId("driver-note");
    expect(note.textContent).toContain(long);
    expect(note.querySelector(".is-folded")).toBeTruthy();
    fireEvent.click(within(note).getByRole("button", { name: "mehr" }));
    expect(note.querySelector(".is-folded")).toBeNull();
    fireEvent.click(within(note).getByRole("button", { name: "weniger" }));
    expect(note.querySelector(".is-folded")).toBeTruthy();
  });

  it("a tapped open stop shows in the dock until the driver goes back", async () => {
    await renderTour(fakeClient(myTour()));
    fireEvent.click(screen.getByRole("button", { name: /Praxis Süd/ }));
    expect(
      within(card()).getByRole("heading", { name: "Praxis Süd" }),
    ).toBeTruthy();
    expect(card().textContent).toContain("Stopp 3");
    const rows = screen.getAllByTestId("tour-stop");
    expect(rows[2]!.classList.contains("is-current")).toBe(true);
    fireEvent.click(
      within(card()).getByRole("button", { name: "Zum nächsten Stopp" }),
    );
    expect(
      within(card()).getByRole("heading", { name: "Bäckerei Kern" }),
    ).toBeTruthy();
  });

  it("a move by keyboard saves at once with the revision, inside the window only, with undo", async () => {
    stackRows();
    const client = fakeClient(myTour());
    await renderTour(client);
    await keyboardMove("Bäckerei Kern", "ArrowDown");
    await waitFor(() =>
      expect(names()).toEqual(["Autohaus Nord", "Bäckerei Kern", "Praxis Süd"]),
    );
    // The dock follows: the new first stop is next.
    expect(
      within(card()).getByRole("heading", { name: "Autohaus Nord" }),
    ).toBeTruthy();
    // The last stop of 08–10 does not cross into 10–12.
    await keyboardMove("Bäckerei Kern", "ArrowDown");
    expect(names()).toEqual(["Autohaus Nord", "Bäckerei Kern", "Praxis Süd"]);
    await screen.findByText("Reihenfolge gespeichert.", undefined, {
      timeout: 3_000,
    });
    expect(client.saveMyTourOrder).toHaveBeenCalledTimes(1);
    expect(client.saveMyTourOrder).toHaveBeenCalledWith(actionId, {
      commitmentIds: ["c2", "c1", "c3"],
      day: DAY,
      expectedRevision: "r1",
    });
    expect(screen.getByTestId("tour-bar-sub").textContent).toContain(
      "Eigene Reihenfolge",
    );
    // "Rückgängig" saves the order from before, with the new revision.
    fireEvent.click(screen.getByRole("button", { name: "Rückgängig" }));
    await screen.findByText(
      "Vorherige Reihenfolge wiederhergestellt.",
      undefined,
      {
        timeout: 3_000,
      },
    );
    expect(client.saveMyTourOrder).toHaveBeenLastCalledWith(actionId, {
      commitmentIds: ["c1", "c2", "c3"],
      day: DAY,
      expectedRevision: "r2",
    });
    expect(names()).toEqual(["Bäckerei Kern", "Autohaus Nord", "Praxis Süd"]);
  });

  it("a move right before a day switch saves for its own day and leaves the new day's tour alone", async () => {
    stackRows();
    const DAY2 = "2099-12-06";
    const first = myTour();
    const client = fakeClient({ ...first, days: [DAY, DAY2] });
    const second: MyTourResponse = {
      ...myTour({
        day: DAY2,
        windows: [
          tourWindow("w9", `${DAY2}T07:00:00Z`, `${DAY2}T09:00:00Z`, [
            stop(drop("c8", "Hotel Ost", "w9"), 1),
            stop(drop("c9", "Kanzlei West", "w9"), 2),
          ]),
        ],
      }),
      days: [DAY, DAY2],
    };
    const loadFirst = vi.mocked(client.getMyTour).getMockImplementation()!;
    vi.mocked(client.getMyTour).mockImplementation(
      async (action: string, query?: { day?: string | null }) =>
        query?.day === DAY2 ? second : loadFirst(action, query),
    );
    const { queries } = await renderTour(client);
    await keyboardMove("Bäckerei Kern", "ArrowDown");
    expect(names()).toEqual(["Autohaus Nord", "Bäckerei Kern", "Praxis Süd"]);
    // Switch the day before the pause is over.
    fireEvent.click(screen.getByRole("button", { name: "Tour-Menü" }));
    fireEvent.change(await screen.findByTestId("tour-day-select"), {
      target: { value: DAY2 },
    });
    await waitFor(() =>
      expect(client.saveMyTourOrder).toHaveBeenCalledWith(actionId, {
        commitmentIds: ["c2", "c1", "c3"],
        day: DAY,
        expectedRevision: "r1",
      }),
    );
    await waitFor(() => expect(names()).toEqual(["Hotel Ost", "Kanzlei West"]));
    await screen.findByText("Reihenfolge gespeichert.");
    expect(
      queries.getQueryData<MyTourResponse>(["my-tour", actionId, DAY2])?.tour,
    ).toEqual(second.tour);
    expect(names()).toEqual(["Hotel Ost", "Kanzlei West"]);
    // The switch carried no undo for a tour no longer on screen.
    expect(screen.queryByRole("button", { name: "Rückgängig" })).toBeNull();
    window.history.replaceState({}, "", "/");
  });

  it("chained moves go out as one save", async () => {
    stackRows();
    const client = fakeClient(
      myTour({
        windows: [
          tourWindow("w1", `${DAY}T07:00:00Z`, `${DAY}T09:00:00Z`, [
            stop(drop("c1", "Bäckerei Kern", "w1"), 1),
            stop(drop("c2", "Autohaus Nord", "w1"), 2),
            stop(drop("c3", "Praxis Süd", "w1"), 3),
          ]),
        ],
      }),
    );
    await renderTour(client);
    await keyboardMove("Praxis Süd", "ArrowUp");
    await keyboardMove("Praxis Süd", "ArrowUp");
    expect(names()).toEqual(["Praxis Süd", "Bäckerei Kern", "Autohaus Nord"]);
    await screen.findByText("Reihenfolge gespeichert.", undefined, {
      timeout: 3_000,
    });
    expect(client.saveMyTourOrder).toHaveBeenCalledTimes(1);
    expect(client.saveMyTourOrder).toHaveBeenCalledWith(actionId, {
      commitmentIds: ["c3", "c1", "c2"],
      day: DAY,
      expectedRevision: "r1",
    });
  });

  it('conflict 409 shows "Die Tour wurde inzwischen geändert." and refetches', async () => {
    stackRows();
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
    await keyboardMove("Bäckerei Kern", "ArrowDown");
    await screen.findByText("Die Tour wurde inzwischen geändert.", undefined, {
      timeout: 3_000,
    });
    await waitFor(() =>
      expect(vi.mocked(client.getMyTour).mock.calls.length).toBeGreaterThan(
        loads,
      ),
    );
    // The server's order shows again.
    expect(names()).toEqual(["Bäckerei Kern", "Autohaus Nord", "Praxis Süd"]);
  });

  it("Zurück zur Planung sits in the menu and sends an empty list", async () => {
    const client = fakeClient(
      myTour({ driverOrderedAt: "2099-12-05T06:00:00Z" }),
    );
    await renderTour(client);
    expect(screen.getByTestId("tour-bar-sub").textContent).toContain(
      "Eigene Reihenfolge",
    );
    fireEvent.click(screen.getByRole("button", { name: "Tour-Menü" }));
    fireEvent.click(await screen.findByTestId("tour-reset-order"));
    await screen.findByText("Es gilt wieder die Reihenfolge der Planung.");
    expect(client.saveMyTourOrder).toHaveBeenCalledWith(actionId, {
      commitmentIds: [],
      day: DAY,
      expectedRevision: "r1",
    });
    expect(screen.getByTestId("tour-bar-sub").textContent).not.toContain(
      "Eigene Reihenfolge",
    );
  });

  it("without an own order and with one day there is no menu", async () => {
    await renderTour(fakeClient(myTour()));
    expect(screen.queryByRole("button", { name: "Tour-Menü" })).toBeNull();
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
            tourWindow("w1", `${day}T07:00:00Z`, `${day}T09:00:00Z`, [
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
    // The window label says it once; the rows stay short.
    expect(
      screen.getByRole("heading", { name: /08–10 Uhr.*Fenster vorbei/ }),
    ).toBeTruthy();
    expect(
      within(screen.getAllByTestId("tour-stop")[1]!).queryByText(
        "Fenster vorbei",
      ),
    ).toBeNull();
    expect(
      within(screen.getByTestId("tour-stop-done")).queryByText(
        "Fenster vorbei",
      ),
    ).toBeNull();
  });

  it("all done: the dock thanks the driver and done windows fold to one line", async () => {
    const delivered = { revision: 1, state: "delivered" as const };
    await renderTour(
      fakeClient(
        myTour({
          windows: [
            tourWindow("w1", `${DAY}T07:00:00Z`, `${DAY}T09:00:00Z`, [
              stop(drop("c1", "Bäckerei Kern", "w1", delivered), 1),
              stop(drop("c2", "Autohaus Nord", "w1", delivered), 2),
            ]),
          ],
        }),
      ),
      "tour-dock",
    );
    await screen.findByText("Alle 2 zugestellt. Danke!");
    expect(dock().textContent).toContain("Gib der Aktionsleitung Bescheid");
    const toggle = screen.getByRole("button", {
      name: /08–10 Uhr · alle 2 zugestellt/,
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("meter").className).toContain("tone-ok");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByTestId("tour-stop-done")).toHaveLength(2);
  });

  it("shows nothing offline and drops the cached tour", async () => {
    const client = fakeClient(myTour());
    const view = await renderTour(client);
    view.rerender(true);
    await screen.findByText(/Ohne Verbindung zeigen wir deine Tour nicht/);
    expect(screen.queryByTestId("tour-next-stop")).toBeNull();
    expect(screen.queryByTestId("tour-dock")).toBeNull();
    expect(
      view.queries.getQueryCache().findAll({ queryKey: ["my-tour"] }),
    ).toHaveLength(0);
  });

  describe("offline queue (§9)", () => {
    /** The device store's cache in memory, as IndexedDB keeps it. */
    class MemoryTourStore implements TourCacheStore {
      readonly records = new Map<
        string,
        { kind: CacheKind; actionId: string; value: unknown; fetchedAt: string }
      >();
      async listCache(): Promise<CacheEntryInfo[]> {
        return [...this.records.values()].map(
          ({ actionId, fetchedAt, kind }) => ({ actionId, fetchedAt, kind }),
        );
      }
      async getCache<T>(
        kind: CacheKind,
        id: string,
      ): Promise<CachedValue<T> | undefined> {
        const record = this.records.get(`${kind}:${id}`);
        return record
          ? {
              fetchedAt: record.fetchedAt,
              value: structuredClone(record.value) as T,
            }
          : undefined;
      }
      async putCache(
        kind: CacheKind,
        id: string,
        value: unknown,
        fetchedAt: string,
      ) {
        this.records.set(`${kind}:${id}`, {
          actionId: id,
          fetchedAt,
          kind,
          value: structuredClone(value),
        });
      }
      async deleteCache(kind: CacheKind, id: string) {
        this.records.delete(`${kind}:${id}`);
      }
    }

    const stopQueues: (() => void)[] = [];
    afterEach(() => {
      for (const stop of stopQueues.splice(0)) stop();
    });

    /** Started offline from the device copy, with the queue of §9. */
    async function renderOffline(client: LeonAidApiClient) {
      const online = vi
        .spyOn(navigator, "onLine", "get")
        .mockReturnValue(false);
      const device = new MemoryTourStore();
      await saveTour(device, actionId, myTour(), new Date());
      const store = new MemoryQueueStore();
      const queue = new QueueController({
        send: (entry) => sendEntry(client, entry),
        store,
        userId: "anna",
      });
      stopQueues.push(queue.start());
      const runtime: OfflineRuntime = {
        enabled: true,
        queue,
        store: device as unknown as OfflineRuntime["store"],
      };
      const queries = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const page = (offline: boolean) => (
        <QueryClientProvider client={queries}>
          <ToastProvider>
            <OfflineRuntimeContext.Provider value={runtime}>
              <MyTourPage
                actionId={actionId}
                client={client}
                offline={offline}
              />
            </OfflineRuntimeContext.Provider>
          </ToastProvider>
        </QueryClientProvider>
      );
      const view = render(page(true));
      await screen.findByTestId("tour-next-stop");
      return {
        entries: () => store.list(),
        reconnect: async () => {
          online.mockReturnValue(true);
          view.rerender(page(false));
          await act(async () => {
            window.dispatchEvent(new Event("online"));
          });
        },
      };
    }

    /** The dock remounts per stop: read it fresh on every try. */
    const dockShows = (name: string) =>
      waitFor(() =>
        expect(
          within(card()).getByRole("heading", { level: 2 }).textContent,
        ).toBe(name),
      );

    const kinds = (entries: QueueEntry[]) => entries.map((entry) => entry.kind);

    it("Zugestellt offline is queued and shows at once; Rückgängig leaves no entry", async () => {
      const client = fakeClient(myTour());
      const device = await renderOffline(client);
      expect(screen.getByTestId("tour-offline").textContent).toContain(
        "speichert LeonAid auf diesem Gerät",
      );
      fireEvent.click(
        within(card()).getByRole("button", { name: "Zugestellt" }),
      );
      expect(
        await screen.findByText(
          "Bäckerei Kern: zugestellt. Wird gesendet, sobald du online bist.",
        ),
      ).toBeTruthy();
      // The dock moves on; the stop shows done and the count follows.
      await dockShows("Autohaus Nord");
      expect(screen.getByTestId("tour-stop-done").textContent).toContain(
        "Bäckerei Kern",
      );
      expect(screen.getByTestId("tour-progress").textContent).toBe("1/3");
      const [entry] = await device.entries();
      expect(entry?.kind === "delivery-state" && entry.request).toEqual({
        delivered: true,
        expectedRevision: 0,
        missed: false,
      });
      // "Nicht da" on the next stop goes the same way.
      fireEvent.click(
        within(card()).getByRole("button", { name: /^Nicht da/ }),
      );
      await dockShows("Praxis Süd");
      expect(kinds(await device.entries())).toEqual([
        "delivery-state",
        "delivery-state",
      ]);
      // Undo of the first mark: the unsent entry goes, the stop is open.
      fireEvent.click(
        within(
          screen
            .getByText(
              "Bäckerei Kern: zugestellt. Wird gesendet, sobald du online bist.",
            )
            .closest("[role=status], li, div")! as HTMLElement,
        ).getByRole("button", { name: "Rückgängig" }),
      );
      await dockShows("Bäckerei Kern");
      const left = await device.entries();
      expect(
        left.map((item) => item.kind === "delivery-state" && item.commitmentId),
      ).toEqual(["c2"]);
      expect(client.setDeliveryState).not.toHaveBeenCalled();
    });

    it("a move offline is queued, never shown as saved, and replays after reconnect", async () => {
      stackRows();
      const client = fakeClient(myTour());
      const device = await renderOffline(client);
      await keyboardMove("Bäckerei Kern", "ArrowDown");
      await waitFor(() =>
        expect(names()).toEqual([
          "Autohaus Nord",
          "Bäckerei Kern",
          "Praxis Süd",
        ]),
      );
      expect(
        await screen.findByText(
          "Reihenfolge gemerkt. Sie wird gesendet, sobald du online bist.",
        ),
      ).toBeTruthy();
      expect(screen.queryByText("Reihenfolge gespeichert.")).toBeNull();
      const [entry] = await device.entries();
      expect(entry?.kind === "tour-order" && entry.request).toEqual({
        commitmentIds: ["c2", "c1", "c3"],
        day: DAY,
        expectedRevision: "r1",
      });
      // Zugestellt for the new first stop, still offline.
      fireEvent.click(
        within(card()).getByRole("button", { name: "Zugestellt" }),
      );
      await dockShows("Bäckerei Kern");
      expect(client.saveMyTourOrder).not.toHaveBeenCalled();

      await device.reconnect();
      await waitFor(async () => expect(await device.entries()).toEqual([]));
      expect(client.saveMyTourOrder).toHaveBeenCalledWith(
        actionId,
        { commitmentIds: ["c2", "c1", "c3"], day: DAY, expectedRevision: "r1" },
        expect.anything(),
      );
      expect(client.setDeliveryState).toHaveBeenCalledWith(
        actionId,
        "c2",
        { delivered: true, expectedRevision: 2, missed: false },
        expect.anything(),
      );
      // Core's tour now holds both; the page shows it, online.
      await waitFor(() =>
        expect(screen.queryByTestId("tour-offline")).toBeNull(),
      );
      expect(names()).toEqual(["Bäckerei Kern", "Praxis Süd"]);
      expect(screen.getByTestId("tour-progress").textContent).toBe("1/3");
    });
  });

  describe("map (§7.2, D17)", () => {
    /** Bäckerei Kern and Praxis Süd have pins; Autohaus Nord has none. */
    function located() {
      const tour = myTour({
        windows: [
          tourWindow("w1", `${DAY}T07:00:00Z`, `${DAY}T09:00:00Z`, [
            stop(drop("c1", "Bäckerei Kern", "w1"), 1, {
              lat: 47.76,
              lon: 11.56,
            }),
            stop(drop("c2", "Autohaus Nord", "w1", { revision: 2 }), 2),
          ]),
          tourWindow("w2", `${DAY}T09:00:00Z`, `${DAY}T11:00:00Z`, [
            stop(drop("c3", "Praxis Süd", "w2"), 1, {
              lat: 47.77,
              lon: 11.57,
            }),
          ]),
        ],
      });
      return {
        ...tour,
        startPoint: {
          address: "Marktstraße 1, 83646 Bad Tölz",
          label: "Lions-Halle",
          lat: 47.75,
          lon: 11.55,
          locating: false,
        },
      };
    }
    /** Leaflet loads on the first map: wait for the pins. */
    const pinsOf = async (element: Element) => {
      await waitFor(() =>
        expect(element.querySelector(".tour-pin[data-pin-id]")).toBeTruthy(),
      );
      return pinsIn(element);
    };
    const pinsIn = (element: Element) =>
      [...element.querySelectorAll<HTMLElement>(".tour-pin[data-pin-id]")]
        .map((pin) => [pin.dataset.pinId, pin.textContent])
        .sort();

    afterEach(() => {
      window.history.replaceState(null, "", "/");
    });

    it("the dock shows only the stop's pin on a still map (Ruling 17); navigation uses the pin", async () => {
      await renderTour(fakeClient(located()));
      const map = within(card()).getByTestId("tour-map");
      expect(await pinsOf(map)).toEqual([["stop", "1"]]);
      // Street level at the house: the start point stays out of the dock.
      expect(map.querySelector(".tour-pin--start")).toBeNull();
      expect(map.querySelector(".leaflet-control-zoom")).toBeNull();
      expect(map.textContent).toContain("© OpenStreetMap-Mitwirkende");
      expect(
        within(card())
          .getByRole("link", { name: "In OpenStreetMap öffnen" })
          .getAttribute("href"),
      ).toBe(
        "https://www.openstreetmap.org/?mlat=47.76&mlon=11.56#map=18/47.76/11.56",
      );
      expect(
        within(card())
          .getByRole("link", { name: "Navigation" })
          .getAttribute("href"),
      ).toBe("https://www.openstreetmap.org/directions?to=47.76,11.56");
    });

    it("Karte shows numbered pins in effective order, the start and a line through the open stops", async () => {
      const client = fakeClient(located());
      await renderTour(client);
      const toggle = screen.getByRole("button", { name: "Karte" });
      expect(toggle.getAttribute("aria-pressed")).toBe("false");
      fireEvent.click(toggle);
      const view = await screen.findByTestId("tour-mapview");
      expect(toggle.getAttribute("aria-pressed")).toBe("true");
      expect(window.location.search).toBe("?view=map");
      // Autohaus Nord has no pin; numbers follow the list (1, 2, 3).
      expect(await pinsOf(view)).toEqual([
        ["c1", "1"],
        ["c3", "3"],
      ]);
      expect(view.querySelector(".tour-pin--start")).toBeTruthy();
      expect(view.querySelector("path.tour-line")).toBeTruthy();
      expect(
        view
          .querySelector('[data-pin-id="c1"]')
          ?.classList.contains("is-selected"),
      ).toBe(true);
      // No list and no dock until a pin is tapped.
      expect(screen.queryByTestId("tour-stop")).toBeNull();
      expect(screen.queryByTestId("tour-dock")).toBeNull();

      fireEvent.click(view.querySelector('[data-pin-id="c3"]')!);
      expect(
        within(card()).getByRole("heading", { name: "Praxis Süd" }),
      ).toBeTruthy();
      // The sheet has the same buttons, but no second map.
      expect(
        within(card()).getByRole("button", { name: "Zugestellt" }),
      ).toBeTruthy();
      expect(within(card()).queryByTestId("tour-map")).toBeNull();
      fireEvent.click(
        within(dock()).getByRole("button", { name: "Stoppkarte schließen" }),
      );
      expect(screen.queryByTestId("tour-dock")).toBeNull();

      fireEvent.click(toggle);
      expect(await screen.findAllByTestId("tour-stop")).toHaveLength(3);
      expect(window.location.search).toBe("");
    });

    it("a tap on the dock map opens the map view with that stop in the sheet", async () => {
      await renderTour(fakeClient(located()));
      fireEvent.click(
        within(card()).getByRole("button", { name: "Karte groß öffnen" }),
      );
      expect(await screen.findByTestId("tour-mapview")).toBeTruthy();
      expect(
        within(card()).getByRole("heading", { name: "Bäckerei Kern" }),
      ).toBeTruthy();
    });

    it("a done stop's pin opens a sheet with Rückgängig", async () => {
      const tour = located();
      const client = fakeClient({
        ...tour,
        tour: {
          ...tour.tour!,
          windows: tour.tour!.windows.map((item) => ({
            ...item,
            stops: item.stops.map((entry) =>
              entry.drop.commitmentId === "c1"
                ? { ...entry, drop: { ...entry.drop, state: "delivered" } }
                : entry,
            ),
          })),
        },
      });
      await renderTour(client);
      fireEvent.click(screen.getByRole("button", { name: "Karte" }));
      const view = await screen.findByTestId("tour-mapview");
      await pinsOf(view);
      const done = view.querySelector('[data-pin-id="c1"]')!;
      expect(done.classList.contains("tour-pin--done")).toBe(true);
      fireEvent.click(done);
      const sheet = screen.getByTestId("tour-done-sheet");
      fireEvent.click(
        within(sheet).getByRole("button", { name: "Rückgängig" }),
      );
      await waitFor(() =>
        expect(client.setDeliveryState).toHaveBeenCalledWith(actionId, "c1", {
          delivered: false,
          expectedRevision: 0,
          missed: false,
        }),
      );
    });

    it("the device location is opt-in and stays in the browser", async () => {
      const watchPosition = vi.fn(() => 3);
      const clearWatch = vi.fn();
      Object.defineProperty(navigator, "geolocation", {
        configurable: true,
        value: { clearWatch, watchPosition },
      });
      await renderTour(fakeClient(located()));
      fireEvent.click(screen.getByRole("button", { name: "Karte" }));
      await pinsOf(await screen.findByTestId("tour-mapview"));
      expect(watchPosition).not.toHaveBeenCalled();
      const locate = screen.getByRole("button", { name: "Mein Standort" });
      fireEvent.click(locate);
      expect(locate.getAttribute("aria-pressed")).toBe("true");
      expect(watchPosition).toHaveBeenCalledTimes(1);
      fireEvent.click(locate);
      expect(clearWatch).toHaveBeenCalledWith(3);
    });
  });
});

describe("PWA delivery route", () => {
  const identity = {
    actionMemberships: [],
    globalRoles: [],
    userId: "anna",
  } as unknown as CurrentIdentityResponse;

  it("waits for the flag: with delivery.tours on the board never loads", async () => {
    let answer: (value: unknown) => void = () => {};
    const client = fakeClient(myTour());
    const getDeliveryBoard = vi.fn();
    Object.assign(client, {
      getDeliveryBoard,
      getFeatureFlagEvaluations: vi.fn(
        () => new Promise((resolve) => (answer = resolve)),
      ),
    });
    const seen: (boolean | null)[] = [];
    function Probe() {
      seen.push(useLeonAidSettledFlag(FEATURE_FLAGS.deliveryTours));
      return null;
    }
    const queries = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queries}>
        <ToastProvider>
          <FeatureFlagProvider
            client={client}
            identity={identity}
            surface="pwa"
          >
            <Probe />
            <PwaDeliveryPage
              actionId={actionId}
              client={client}
              offline={false}
            />
          </FeatureFlagProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.queryByTestId("tour-next-stop")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Auslieferung" })).toBeNull();
    await act(async () => {
      answer({ flags: [{ enabled: true, key: "delivery.tours" }] });
    });
    await screen.findByTestId("tour-next-stop");
    expect(getDeliveryBoard).not.toHaveBeenCalled();
    // The nav label reads the same value: unknown, then on, never off.
    expect(seen[0]).toBeNull();
    expect(seen.at(-1)).toBe(true);
    expect(seen).not.toContain(false);
  });

  it("a driver-only user lands on the tour at /app/ with the flag on", async () => {
    window.history.replaceState({}, "", `/app/?action=${actionId}`);
    const client = fakeClient(myTour());
    const flags = (enabled: boolean) =>
      Object.assign(client, {
        getFeatureFlagEvaluations: vi.fn(async () => ({
          flags: enabled ? [{ enabled: true, key: "delivery.tours" }] : [],
        })),
      });
    const start = () => (
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ToastProvider>
          <FeatureFlagProvider
            client={client}
            identity={identity}
            surface="pwa"
          >
            <PwaDriverStart
              delivery={<p>Tour page</p>}
              fallback={<p>Start page</p>}
            />
          </FeatureFlagProvider>
        </ToastProvider>
      </QueryClientProvider>
    );
    flags(true);
    const view = render(start());
    // Never the acquirer start page while the flag loads.
    expect(screen.queryByText("Start page")).toBeNull();
    await screen.findByText("Tour page");
    expect(`${window.location.pathname}${window.location.search}`).toBe(
      `/app/delivery?action=${actionId}`,
    );
    view.unmount();

    window.history.replaceState({}, "", "/app/");
    flags(false);
    render(start());
    await screen.findByText("Start page");
    expect(window.location.pathname).toBe("/app/");
  });

  it("driver standing follows the roles in the selected action", () => {
    const memberships = [
      { actionId: "a1", role: "driver" },
      { actionId: "a2", role: "driver" },
      { actionId: "a2", role: "acquirer" },
    ];
    expect(driverStanding(memberships, "a1")).toEqual({
      driver: true,
      driverOnly: true,
    });
    expect(driverStanding(memberships, "a2")).toEqual({
      driver: true,
      driverOnly: false,
    });
    // No ?action=: the first membership.
    expect(driverStanding(memberships, "")).toEqual({
      driver: true,
      driverOnly: true,
    });
    expect(driverStanding([{ actionId: "a3", role: "acquirer" }], "")).toEqual({
      driver: false,
      driverOnly: false,
    });
    expect(driverStanding([], "")).toEqual({
      driver: false,
      driverOnly: false,
    });
  });

  it("shows the board when the flag is off", async () => {
    const client = fakeClient(myTour());
    const getDeliveryBoard = vi.fn(async () => ({
      actionId,
      actionName: "Krapfentaxi",
      day: null,
      days: [],
      drivers: [],
      followUpTasks: false,
      manager: false,
      timezone: "Europe/Berlin",
      windows: [],
    }));
    Object.assign(client, {
      getDeliveryBoard,
      getFeatureFlagEvaluations: vi.fn(async () => ({ flags: [] })),
    });
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ToastProvider>
          <FeatureFlagProvider
            client={client}
            identity={identity}
            surface="pwa"
          >
            <PwaDeliveryPage
              actionId={actionId}
              client={client}
              offline={false}
            />
          </FeatureFlagProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
    await screen.findByRole("heading", { name: "Auslieferung" });
    await waitFor(() => expect(getDeliveryBoard).toHaveBeenCalled());
    expect(client.getMyTour).not.toHaveBeenCalled();
  });

  function renderRoute(client: LeonAidApiClient, offline = false) {
    const queries = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queries}>
        <ToastProvider>
          <FeatureFlagProvider
            client={client}
            identity={identity}
            surface="pwa"
          >
            <PwaDeliveryPage
              actionId={actionId}
              client={client}
              offline={offline}
            />
          </FeatureFlagProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
    return queries;
  }

  it("settles all flags off when the app opens offline without flags", async () => {
    onlineManager.setOnline(false);
    try {
      const client = fakeClient(myTour());
      Object.assign(client, {
        getDeliveryBoard: vi.fn(),
        // What fetch does without a network.
        getFeatureFlagEvaluations: vi.fn(async () => {
          throw new TypeError("Failed to fetch");
        }),
      });
      renderRoute(client, true);
      // Flag off: the board's offline notice, not an endless skeleton.
      await screen.findByText(/Ohne Verbindung zeigen wir keine Lieferungen/);
      expect(client.getMyTour).not.toHaveBeenCalled();
    } finally {
      onlineManager.setOnline(true);
    }
  });

  it("settles all flags off when OpenFeature refuses the values", async () => {
    vi.spyOn(
      TypedInMemoryProvider.prototype,
      "putConfiguration",
    ).mockRejectedValue(new Error("refused"));
    const client = fakeClient(myTour());
    const getDeliveryBoard = vi.fn(async () => ({
      actionId,
      actionName: "Krapfentaxi",
      day: null,
      days: [],
      drivers: [],
      followUpTasks: false,
      manager: false,
      timezone: "Europe/Berlin",
      windows: [],
    }));
    Object.assign(client, {
      getDeliveryBoard,
      getFeatureFlagEvaluations: vi.fn(async () => ({
        flags: [{ enabled: true, key: "delivery.tours" }],
      })),
    });
    renderRoute(client);
    // Flag off: the board, not an endless skeleton and not the tour.
    await screen.findByRole("heading", { name: "Auslieferung" });
    await waitFor(() => expect(getDeliveryBoard).toHaveBeenCalled());
    expect(client.getMyTour).not.toHaveBeenCalled();
  });

  it("keeps the page mounted while the flags reload", async () => {
    const client = fakeClient(myTour());
    const evaluations = vi.fn(async () => ({
      flags: [{ enabled: true, key: "delivery.tours" }],
    }));
    Object.assign(client, {
      getDeliveryBoard: vi.fn(),
      getFeatureFlagEvaluations: evaluations,
    });
    const queries = renderRoute(client);
    await screen.findByTestId("tour-next-stop");
    const loads = vi.mocked(client.getMyTour).mock.calls.length;
    const reload = async () => {
      const before = evaluations.mock.calls.length;
      await act(() =>
        queries.invalidateQueries({ queryKey: ["feature-flags"] }),
      );
      await waitFor(() =>
        expect(evaluations.mock.calls.length).toBeGreaterThan(before),
      );
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 20));
      });
    };
    // Same result, then a changed one: the tour stays, nothing reloads it.
    await reload();
    evaluations.mockResolvedValue({
      flags: [
        { enabled: true, key: "delivery.tours" },
        { enabled: true, key: "admin.preview_notice" },
      ],
    });
    await reload();
    expect(screen.getByTestId("tour-next-stop")).toBeTruthy();
    expect(vi.mocked(client.getMyTour).mock.calls.length).toBe(loads);
    expect(client.getDeliveryBoard).not.toHaveBeenCalled();
  });
});
