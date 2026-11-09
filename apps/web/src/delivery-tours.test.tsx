import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  type CurrentIdentityResponse,
  type DeliveryDayToursResponse,
  type DeliveryDropResponse,
  type DeliveryTourResponse,
  type DeliveryTourStopResponse,
  type DeliveryTourWindowResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  BOARD_POLL_MS,
  DeliveryBoardPage,
  FeatureFlagProvider,
  TourPlanner,
} from "@leonaid/features";
import { HotkeyProvider, ToastProvider } from "@leonaid/ui";

const actionId = "20000000-0000-4000-8000-000000000001";
const DAY = "2099-12-05";

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

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

function drop(
  id: string,
  buyerName: string,
  windowId: string,
  driver: string | null,
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
    contact: null,
    driverName:
      driver === "anna" ? "Fahrerin Anna" : driver ? "Fahrer Ben" : null,
    driverUserId: driver,
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

const TILES = {
  attribution: "© OpenStreetMap-Mitwirkende",
  tileUrl: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
};

const W1 = { start: `${DAY}T07:00:00Z`, end: `${DAY}T09:00:00Z` };
const W2 = { start: `${DAY}T09:00:00Z`, end: `${DAY}T11:00:00Z` };

function win(
  windowId: "w1" | "w2",
  stops: DeliveryTourStopResponse[],
): DeliveryTourWindowResponse {
  const times = windowId === "w1" ? W1 : W2;
  return {
    closed: false,
    endsAt: times.end,
    startsAt: times.start,
    stops,
    windowId,
  };
}

/**
 * Anna: 08–10 Bäckerei Kern, Autohaus Nord; 10–12 Praxis Süd.
 * Ben: no stops. Unassigned: 08–10 Café Mitte, 10–12 Kita Ost.
 */
function dayTours(
  extra: { anna?: Partial<DeliveryTourResponse>; days?: string[] } = {},
): DeliveryDayToursResponse {
  return {
    actionId,
    actionName: "Krapfentaxi",
    day: DAY,
    days: extra.days ?? [DAY],
    drivers: [
      { displayName: "Fahrerin Anna", userId: "anna" },
      { displayName: "Fahrer Ben", userId: "ben" },
    ],
    map: TILES,
    startPoint: null,
    timezone: "Europe/Berlin",
    tours: [
      {
        day: DAY,
        driverName: "Fahrerin Anna",
        driverOrderedAt: null,
        driverUserId: "anna",
        revision: "r1",
        windows: [
          win("w1", [
            stop(drop("c1", "Bäckerei Kern", "w1", "anna"), 1),
            stop(drop("c2", "Autohaus Nord", "w1", "anna"), 2),
          ]),
          win("w2", [stop(drop("c3", "Praxis Süd", "w2", "anna"), 1)]),
        ],
        ...extra.anna,
      },
      {
        day: DAY,
        driverName: "Fahrer Ben",
        driverOrderedAt: null,
        driverUserId: "ben",
        revision: "r0",
        windows: [],
      },
    ],
    unassigned: [
      win("w1", [stop(drop("c4", "Café Mitte", "w1", null), 1)]),
      win("w2", [stop(drop("c5", "Kita Ost", "w2", null), 1)]),
    ],
  };
}

function fakeClient(initial: DeliveryDayToursResponse) {
  let response = initial;
  const changeTour = (
    driver: string,
    change: (tour: DeliveryTourResponse) => DeliveryTourResponse,
  ) => {
    response = {
      ...response,
      tours: response.tours.map((tour) =>
        tour.driverUserId === driver ? change(tour) : tour,
      ),
    };
    return response.tours.find((tour) => tour.driverUserId === driver)!;
  };
  return {
    getDeliveryTours: vi.fn(async () => response),
    // Unassigned stops join the end of their window in the driver's tour.
    assignDeliveryDriver: vi.fn(
      async (
        _action: string,
        body: { commitmentIds: string[]; driverUserId: string | null },
      ) => {
        const moving = response.unassigned
          .flatMap((item) => item.stops)
          .filter((entry) =>
            body.commitmentIds.includes(entry.drop.commitmentId),
          );
        const driver = body.driverUserId;
        if (!driver || !moving.length) return { changed: 0 };
        response = {
          ...response,
          unassigned: response.unassigned
            .map((item) => ({
              ...item,
              stops: item.stops.filter((entry) => !moving.includes(entry)),
            }))
            .filter((item) => item.stops.length),
        };
        changeTour(driver, (tour) => {
          let windows = [...tour.windows];
          for (const entry of moving) {
            const id = entry.drop.windowId as "w1" | "w2";
            const existing = windows.find((item) => item.windowId === id);
            const joined = {
              ...entry,
              baseRank: (existing?.stops.length ?? 0) + 1,
              effectiveRank: (existing?.stops.length ?? 0) + 1,
              drop: { ...entry.drop, driverUserId: driver },
            };
            windows = existing
              ? windows.map((item) =>
                  item === existing
                    ? { ...item, stops: [...item.stops, joined] }
                    : item,
                )
              : [...windows, win(id, [joined])].sort((a, b) =>
                  a.windowId.localeCompare(b.windowId),
                );
          }
          return { ...tour, revision: `${tour.revision}+`, windows };
        });
        return { changed: moving.length };
      },
    ),
    saveDeliveryTourOrder: vi.fn(
      async (
        _action: string,
        driver: string,
        body: { commitmentIds: string[] },
      ) =>
        changeTour(driver, (tour) => ({
          ...tour,
          revision: "r2",
          windows: tour.windows.map((item) => ({
            ...item,
            stops: [...item.stops]
              .sort(
                (a, b) =>
                  body.commitmentIds.indexOf(a.drop.commitmentId) -
                  body.commitmentIds.indexOf(b.drop.commitmentId),
              )
              .map((entry, index) => ({ ...entry, baseRank: index + 1 })),
          })),
        })),
    ),
    setDeliveryPin: vi.fn(
      async (
        _action: string,
        id: string,
        body: { lat: number; lon: number },
      ) => {
        const place = (item: DeliveryTourWindowResponse) => ({
          ...item,
          stops: item.stops.map((entry) =>
            entry.drop.commitmentId === id ? { ...entry, ...body } : entry,
          ),
        });
        response = {
          ...response,
          unassigned: response.unassigned.map(place),
          tours: response.tours.map((tour) => ({
            ...tour,
            windows: tour.windows.map(place),
          })),
        };
        return { ...body };
      },
    ),
    discardDeliveryDriverOrder: vi.fn(async (_action: string, driver: string) =>
      changeTour(driver, (tour) => ({
        ...tour,
        driverOrderedAt: null,
        revision: "r3",
        windows: tour.windows.map((item) => ({
          ...item,
          stops: item.stops.map((entry) => ({
            ...entry,
            driverRank: null,
            effectiveRank: entry.baseRank,
          })),
        })),
      })),
    ),
  } as unknown as LeonAidApiClient & Record<string, ReturnType<typeof vi.fn>>;
}

function newQueries() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

async function renderPlanner(
  client: LeonAidApiClient,
  onDayChange: (day: string) => void = () => {},
) {
  render(
    <QueryClientProvider client={newQueries()}>
      <ToastProvider>
        <TourPlanner
          actionId={actionId}
          client={client}
          day={DAY}
          onDayChange={onDayChange}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
  await screen.findAllByTestId("tour-column");
}

const column = (driver: string) =>
  screen
    .getAllByTestId("tour-column")
    .find((element) => element.dataset.driver === driver)!;

const names = (element: HTMLElement) =>
  within(element)
    .queryAllByTestId("tour-stop-name")
    .map((item) => item.textContent);

/** jsdom has no layout: columns 400 px apart, rows 60 px apart. */
function stackLayout() {
  vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(
    function (this: Element) {
      const lanes = [...document.querySelectorAll("[data-lane]")];
      const rect = (left: number, top: number, height: number) =>
        ({
          bottom: top + height,
          height,
          left,
          right: left + 360,
          top,
          width: 360,
          x: left,
          y: top,
          toJSON: () => ({}),
        }) as DOMRect;
      const lane = this.closest("[data-lane]");
      const left = Math.max(0, lanes.indexOf(lane as Element)) * 400;
      const row = this.closest(".tour-stop");
      if (row && lane) {
        const rows = [...lane.querySelectorAll(".tour-stop")];
        return rect(left, 100 + rows.indexOf(row) * 60, 56);
      }
      return lane ? rect(left, 0, 1000) : rect(0, 0, 0);
    },
  );
}

/** dnd-kit starts listening for the arrow keys on a timer. */
async function press(key: string, code: string) {
  await act(async () => {
    fireEvent.keyDown(document.activeElement!, { code, key });
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

async function keyboardMove(lane: HTMLElement, name: string, key: string) {
  within(lane)
    .getByRole("button", { name: `Stopp verschieben: ${name}` })
    .focus();
  await press(" ", "Space");
  await press(key, key);
  await press(" ", "Space");
}

describe("Touren planner", () => {
  it("columns per driver grouped by window with counts", async () => {
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    expect(client.getDeliveryTours).toHaveBeenCalledWith(actionId, {
      day: DAY,
    });

    const unassigned = screen.getByTestId("tour-unassigned");
    const columns = screen.getAllByTestId("tour-column");
    expect(columns.map((item) => item.dataset.driver)).toEqual(["anna", "ben"]);
    // "Nicht zugeordnet" comes first.
    expect(
      unassigned.compareDocumentPosition(columns[0]!) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      within(unassigned).getByRole("heading", { name: /Nicht zugeordnet/ }),
    ).toBeTruthy();
    expect(within(unassigned).getByTestId("tour-count").textContent).toBe("2");

    const anna = column("anna");
    expect(within(anna).getByTestId("tour-count").textContent).toBe("3");
    expect(
      within(anna)
        .getAllByTestId("tour-window")
        .map((group) => within(group).getByRole("heading").textContent),
    ).toEqual(["08–10 Uhr", "10–12 Uhr"]);
    const [early, late] = within(anna).getAllByTestId("tour-window");
    expect(names(early!)).toEqual(["Bäckerei Kern", "Autohaus Nord"]);
    expect(names(late!)).toEqual(["Praxis Süd"]);
    // The load per window instead of first and last stop.
    expect(
      within(within(anna).getByTestId("tour-load"))
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["08–10: 2 Stopps, 6 Boxen", "10–12: 1 Stopp, 3 Boxen"]);
    // No coordinates yet: no length at all.
    expect(within(anna).queryByTestId("tour-length")).toBeNull();
    // One hint line; no save button (every move saves).
    expect(screen.getByTestId("tour-plan-hint").textContent).toContain(
      "Wählen Sie Stopps aus",
    );
    expect(within(anna).queryByTestId("tour-save-order")).toBeNull();

    const ben = column("ben");
    expect(within(ben).getByTestId("tour-count").textContent).toBe("0");
    expect(within(ben).getByText(/Noch keine Stopps/)).toBeTruthy();
  });

  it("shows the quantities the driver sees and dims delivered stops in place", async () => {
    const client = fakeClient(
      dayTours({
        anna: {
          windows: [
            win("w1", [
              stop(
                drop("c1", "Bäckerei Kern", "w1", "anna", {
                  quantities: [{ quantity: 6, unit: "piece" }],
                  revision: 1,
                  state: "delivered",
                  totalBoxes: 0,
                }),
                1,
              ),
              stop(
                drop("c2", "Autohaus Nord", "w1", "anna", {
                  quantities: [{ quantity: 24, unit: "piece" }],
                  totalBoxes: 0,
                }),
                2,
              ),
            ]),
          ],
        },
      }),
    );
    await renderPlanner(client);
    const rows = within(column("anna")).getAllByTestId("tour-stop");
    // Not "0 Boxen": the same source as "Meine Tour".
    expect(rows[0]!.textContent).toContain("6 Stück");
    expect(rows[1]!.textContent).toContain("24 Stück");
    expect(rows.map((row) => row.textContent)).not.toContainEqual(
      expect.stringContaining("0 Boxen"),
    );
    expect(rows[0]!.classList.contains("is-done")).toBe(true);
    expect(rows[1]!.classList.contains("is-done")).toBe(false);
    expect(
      within(within(column("anna")).getByTestId("tour-load")).getByRole(
        "listitem",
      ).textContent,
    ).toBe("08–10: 2 Stopps, 30 Stk");
  });

  it("an empty Nicht zugeordnet says all stops are assigned", async () => {
    const tours = dayTours();
    const client = fakeClient({ ...tours, unassigned: [] });
    await renderPlanner(client);
    expect(
      within(screen.getByTestId("tour-unassigned")).getByText(
        "Alle Stopps zugeordnet.",
      ),
    ).toBeTruthy();
    expect(screen.getByTestId("tour-plan-hint").textContent).toContain(
      "Sortiert wird nur innerhalb eines Lieferfensters",
    );
  });

  it("assign selected stops to a driver calls assignDeliveryDriver", async () => {
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    const assignButton = () =>
      screen.getByRole("button", { name: "Fahrer zuordnen" });
    expect(
      screen.queryByRole("button", { name: "Fahrer zuordnen" }),
    ).toBeNull();

    fireEvent.click(
      screen.getByRole("checkbox", { name: "Café Mitte auswählen" }),
    );
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Kita Ost auswählen" }),
    );
    expect(screen.getByText("2 ausgewählt")).toBeTruthy();
    fireEvent.click(assignButton());
    fireEvent.click(await screen.findByRole("option", { name: /Fahrer Ben/ }));

    await waitFor(() =>
      expect(client.assignDeliveryDriver).toHaveBeenCalledWith(actionId, {
        commitmentIds: ["c4", "c5"],
        driverUserId: "ben",
      }),
    );
    // The selection is gone and the tours reload.
    await waitFor(() => expect(screen.queryByText("2 ausgewählt")).toBeNull());
    await waitFor(() =>
      expect(client.getDeliveryTours).toHaveBeenCalledTimes(2),
    );
  });

  it("a move saves on its own with revision and day; Rückgängig restores the order", async () => {
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    const anna = column("anna");
    fireEvent.click(
      within(anna).getByRole("button", { name: "Bäckerei Kern nach unten" }),
    );
    expect(names(anna)).toEqual([
      "Autohaus Nord",
      "Bäckerei Kern",
      "Praxis Süd",
    ]);
    // The last stop of 08–10 has no way down into 10–12: no arrow.
    expect(
      within(anna).queryByRole("button", { name: "Bäckerei Kern nach unten" }),
    ).toBeNull();

    await screen.findByText(
      "Reihenfolge für Fahrerin Anna gespeichert.",
      undefined,
      { timeout: 3_000 },
    );
    expect(client.saveDeliveryTourOrder).toHaveBeenCalledTimes(1);
    expect(client.saveDeliveryTourOrder).toHaveBeenCalledWith(
      actionId,
      "anna",
      {
        commitmentIds: ["c2", "c1", "c3"],
        day: DAY,
        expectedRevision: "r1",
      },
    );
    expect(names(anna)).toEqual([
      "Autohaus Nord",
      "Bäckerei Kern",
      "Praxis Süd",
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Rückgängig" }));
    await screen.findByText(
      "Vorherige Reihenfolge für Fahrerin Anna wiederhergestellt.",
      undefined,
      { timeout: 3_000 },
    );
    expect(client.saveDeliveryTourOrder).toHaveBeenLastCalledWith(
      actionId,
      "anna",
      {
        commitmentIds: ["c1", "c2", "c3"],
        day: DAY,
        expectedRevision: "r2",
      },
    );
    expect(names(anna)).toEqual([
      "Bäckerei Kern",
      "Autohaus Nord",
      "Praxis Süd",
    ]);
  });

  it("a stop joining a column goes to the end of its own window and moves from there", async () => {
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    const anna = column("anna");
    fireEvent.click(
      within(anna).getByRole("button", { name: "Bäckerei Kern nach unten" }),
    );
    await waitFor(
      () => expect(client.saveDeliveryTourOrder).toHaveBeenCalledTimes(1),
      { timeout: 3_000 },
    );

    // Café Mitte (08–10) joins Anna.
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Café Mitte auswählen" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Fahrer zuordnen" }));
    fireEvent.click(
      await screen.findByRole("option", { name: /Fahrerin Anna/ }),
    );
    await waitFor(() => expect(names(anna)).toHaveLength(4));
    expect(names(anna)).toEqual([
      "Autohaus Nord",
      "Bäckerei Kern",
      "Café Mitte",
      "Praxis Süd",
    ]);
    const [early, late] = within(anna).getAllByTestId("tour-window");
    expect(names(early!)).toEqual([
      "Autohaus Nord",
      "Bäckerei Kern",
      "Café Mitte",
    ]);
    expect(names(late!)).toEqual(["Praxis Süd"]);
    expect(
      within(anna)
        .getAllByTestId("tour-stop")
        .map((row) => row.querySelector(".tour-pos")?.textContent),
    ).toEqual(["1", "2", "3", "4"]);

    // Up works for the new stop inside its window, on the new revision.
    fireEvent.click(
      within(anna).getByRole("button", { name: "Café Mitte nach oben" }),
    );
    expect(names(anna)).toEqual([
      "Autohaus Nord",
      "Café Mitte",
      "Bäckerei Kern",
      "Praxis Süd",
    ]);
    await waitFor(
      () =>
        expect(client.saveDeliveryTourOrder).toHaveBeenLastCalledWith(
          actionId,
          "anna",
          {
            commitmentIds: ["c2", "c4", "c1", "c3"],
            day: DAY,
            expectedRevision: "r2+",
          },
        ),
      { timeout: 3_000 },
    );
  });

  it("drag across windows is ignored", async () => {
    stackLayout();
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    const anna = column("anna");
    // Autohaus Nord is the last stop of 08–10: down would cross into 10–12.
    await keyboardMove(anna, "Autohaus Nord", "ArrowDown");
    expect(names(anna)).toEqual([
      "Bäckerei Kern",
      "Autohaus Nord",
      "Praxis Süd",
    ]);
    expect(client.assignDeliveryDriver).not.toHaveBeenCalled();

    // Inside the window the keyboard move works.
    await keyboardMove(anna, "Bäckerei Kern", "ArrowDown");
    await waitFor(() =>
      expect(names(anna)).toEqual([
        "Autohaus Nord",
        "Bäckerei Kern",
        "Praxis Süd",
      ]),
    );
    // Only the move inside the window saved.
    await waitFor(
      () => expect(client.saveDeliveryTourOrder).toHaveBeenCalledTimes(1),
      { timeout: 3_000 },
    );
    expect(client.saveDeliveryTourOrder).toHaveBeenCalledWith(
      actionId,
      "anna",
      { commitmentIds: ["c2", "c1", "c3"], day: DAY, expectedRevision: "r1" },
    );
  });

  it("dragging a stop onto another column assigns it", async () => {
    stackLayout();
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    // Café Mitte (unassigned, 08–10) to the right: onto Anna's column.
    await keyboardMove(
      screen.getByTestId("tour-unassigned"),
      "Café Mitte",
      "ArrowRight",
    );
    await waitFor(() =>
      expect(client.assignDeliveryDriver).toHaveBeenCalledWith(actionId, {
        commitmentIds: ["c4"],
        driverUserId: "anna",
      }),
    );
    expect(client.saveDeliveryTourOrder).not.toHaveBeenCalled();
  });

  it("driver order banner shows time; verwerfen calls discard", async () => {
    const client = fakeClient(
      dayTours({
        anna: {
          driverOrderedAt: `${DAY}T07:12:00Z`,
          windows: [
            win("w1", [
              stop(drop("c1", "Bäckerei Kern", "w1", "anna"), 1, {
                driverRank: 2,
                effectiveRank: 2,
              }),
              stop(drop("c2", "Autohaus Nord", "w1", "anna"), 2, {
                driverRank: 1,
                effectiveRank: 1,
              }),
            ]),
            win("w2", [
              stop(drop("c3", "Praxis Süd", "w2", "anna"), 1, {
                driverRank: 1,
              }),
            ]),
          ],
        },
      }),
    );
    await renderPlanner(client);
    const anna = column("anna");
    const banner = within(anna).getByTestId("tour-driver-order-banner");
    expect(banner.textContent).toContain(
      "Fahrer hat eigene Reihenfolge (seit 08:12)",
    );
    expect(
      within(column("ben")).queryByTestId("tour-driver-order-banner"),
    ).toBeNull();

    // The column shows the base order; "anzeigen" shows the driver's, read-only.
    expect(names(anna)).toEqual([
      "Bäckerei Kern",
      "Autohaus Nord",
      "Praxis Süd",
    ]);
    fireEvent.click(within(anna).getByTestId("tour-show-driver-order"));
    expect(names(anna)).toEqual([
      "Autohaus Nord",
      "Bäckerei Kern",
      "Praxis Süd",
    ]);
    expect(
      within(anna).queryByRole("button", { name: /nach unten/ }),
    ).toBeNull();
    fireEvent.click(within(anna).getByTestId("tour-show-driver-order"));
    expect(names(anna)).toEqual([
      "Bäckerei Kern",
      "Autohaus Nord",
      "Praxis Süd",
    ]);

    fireEvent.click(within(anna).getByTestId("tour-discard-driver-order"));
    const dialog = await screen.findByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Verwerfen" }));
    await waitFor(() =>
      expect(client.discardDeliveryDriverOrder).toHaveBeenCalledWith(
        actionId,
        "anna",
        { day: DAY },
      ),
    );
    await waitFor(() =>
      expect(within(anna).queryByTestId("tour-driver-order-banner")).toBeNull(),
    );
  });

  it("Vorschlag sortieren disabled without coordinates", async () => {
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    const suggest = within(column("anna")).getByTestId("tour-suggest-order");
    expect(suggest.getAttribute("aria-disabled")).toBe("true");
    expect(suggest.getAttribute("title")).toBe(
      "Für den Vorschlag fehlen Koordinaten.",
    );
    fireEvent.click(suggest);
    expect(client.saveDeliveryTourOrder).not.toHaveBeenCalled();
  });

  describe("map (§6.1, §6.3, §6.4)", () => {
    /** Anna's 08–10 stops and Café Mitte (unassigned) have pins. */
    function located() {
      const tours = dayTours();
      const at: Record<string, { lat: number; lon: number }> = {
        c1: { lat: 47.77, lon: 11.57 },
        c2: { lat: 47.76, lon: 11.56 },
        c4: { lat: 47.765, lon: 11.565 },
      };
      const place = (item: DeliveryTourWindowResponse) => ({
        ...item,
        stops: item.stops.map((entry) => ({
          ...entry,
          ...(at[entry.drop.commitmentId] ?? {}),
        })),
      });
      return {
        ...tours,
        startPoint: {
          address: "Marktstraße 1, 86150 Augsburg",
          label: "Lions-Halle",
          lat: 47.755,
          lon: 11.555,
          locating: false,
        },
        tours: tours.tours.map((tour) => ({
          ...tour,
          windows: tour.windows.map(place),
        })),
        unassigned: tours.unassigned.map(place),
      };
    }
    const map = () => screen.getByTestId("tour-plan-map");
    /** Leaflet loads on the first map: wait for its pins. */
    const mapReady = () =>
      waitFor(() =>
        expect(map().querySelector(".tour-pin[data-pin-id]")).toBeTruthy(),
      );
    const pin = (id: string) =>
      map().querySelector<HTMLElement>(`[data-pin-id="${id}"]`);

    it("pins coloured by driver and numbered by effective order; unassigned grey", async () => {
      await renderPlanner(fakeClient(located()));
      await mapReady();
      expect(pin("c1")?.textContent).toBe("1");
      expect(pin("c2")?.textContent).toBe("2");
      expect(pin("c1")?.classList.contains("tour-pin--driver-0")).toBe(true);
      expect(pin("c4")?.classList.contains("tour-pin--unassigned")).toBe(true);
      expect(pin("c4")?.textContent).toBe("");
      // Praxis Süd has no pin: no marker, but "Pin setzen" in its row.
      expect(pin("c3")).toBeNull();
      expect(map().querySelector(".tour-pin--start")).toBeTruthy();
      expect(
        within(column("anna")).getAllByTestId("tour-stop-no-pin"),
      ).toHaveLength(1);
    });

    it("list and pins select each other; one lane's order is drawn", async () => {
      await renderPlanner(fakeClient(located()));
      await mapReady();
      expect(map().querySelector("path.tour-line")).toBeNull();
      fireEvent.click(pin("c2")!);
      const row = within(column("anna"))
        .getAllByTestId("tour-stop")
        .find((item) => item.dataset.commitmentId === "c2")!;
      expect(within(row).getByRole<HTMLInputElement>("checkbox").checked).toBe(
        true,
      );
      expect(pin("c2")?.classList.contains("is-selected")).toBe(true);
      const line = map().querySelector("path.tour-line");
      expect(line).toBeTruthy();
      expect(line?.classList.contains("is-dashed")).toBe(false);
      // And back: the list choice clears the pin's highlight.
      fireEvent.click(within(row).getByRole("checkbox"));
      expect(pin("c2")?.classList.contains("is-selected")).toBe(false);
    });

    it("a move still saving draws the draft as a dashed line", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const client = fakeClient(located());
      await renderPlanner(client);
      await mapReady();
      fireEvent.click(
        within(column("anna")).getByRole("button", {
          name: "Autohaus Nord nach oben",
        }),
      );
      expect(
        map().querySelector("path.tour-line")?.classList.contains("is-dashed"),
      ).toBe(true);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      await waitFor(() =>
        expect(client.saveDeliveryTourOrder).toHaveBeenCalled(),
      );
      await waitFor(() =>
        expect(map().querySelector("path.tour-line.is-dashed")).toBeNull(),
      );
    });

    it("Vorschlag sortieren starts at the start point and saves the nearest-next order", async () => {
      const client = fakeClient(located());
      await renderPlanner(client);
      await mapReady();
      const suggest = within(column("anna")).getByTestId("tour-suggest-order");
      expect(suggest.getAttribute("aria-disabled")).not.toBe("true");
      fireEvent.click(suggest);
      // Autohaus Nord is nearer to the start than Bäckerei Kern.
      await waitFor(() =>
        expect(client.saveDeliveryTourOrder).toHaveBeenCalledWith(
          actionId,
          "anna",
          {
            commitmentIds: ["c2", "c1", "c3"],
            day: DAY,
            expectedRevision: "r1",
          },
        ),
      );
    });

    it("Pin setzen: a map click sets the stop's pin", async () => {
      const client = fakeClient(located());
      await renderPlanner(client);
      await mapReady();
      const setPin = within(column("anna")).getByRole("button", {
        name: "Pin setzen: Praxis Süd",
      });
      fireEvent.click(setPin);
      expect(setPin.getAttribute("aria-pressed")).toBe("true");
      expect(within(map()).getByRole("status").textContent).toContain(
        "Praxis Süd",
      );
      fireEvent.click(map().querySelector(".leaflet-container")!, {
        clientX: 20,
        clientY: 20,
      });
      await waitFor(() =>
        expect(client.setDeliveryPin).toHaveBeenCalledWith(
          actionId,
          "c3",
          expect.objectContaining({
            lat: expect.any(Number),
            lon: expect.any(Number),
          }),
        ),
      );
      expect(
        await screen.findByText("Pin für Praxis Süd gesetzt."),
      ).toBeTruthy();
      await waitFor(() => expect(pin("c3")?.textContent).toBe("3"));
      expect(
        within(column("anna")).queryByTestId("tour-stop-no-pin"),
      ).toBeNull();
    });

    it("Pin versetzen: an existing pin moves to the clicked place (Ruling 18)", async () => {
      const client = fakeClient(located());
      await renderPlanner(client);
      await mapReady();
      const move = within(column("anna")).getByRole("button", {
        name: "Pin versetzen: Bäckerei Kern",
      });
      fireEvent.click(move);
      expect(move.getAttribute("aria-pressed")).toBe("true");
      fireEvent.click(map().querySelector(".leaflet-container")!, {
        clientX: 5,
        clientY: 5,
      });
      await waitFor(() =>
        expect(client.setDeliveryPin).toHaveBeenCalledTimes(1),
      );
      const [, id, body] = vi.mocked(client.setDeliveryPin).mock.calls[0]!;
      expect(id).toBe("c1");
      // New coordinates, not the old pin's.
      expect(body).not.toEqual({ lat: 47.77, lon: 11.57 });
      expect(Number.isFinite(body.lat) && Number.isFinite(body.lon)).toBe(true);
      await waitFor(() =>
        expect(
          vi.mocked(client.getDeliveryTours).mock.calls.length,
        ).toBeGreaterThan(1),
      );
    });

    it("the centre button places the pin for keyboard users", async () => {
      const client = fakeClient(located());
      await renderPlanner(client);
      await mapReady();
      fireEvent.click(
        within(column("anna")).getByRole("button", {
          name: "Pin setzen: Praxis Süd",
        }),
      );
      fireEvent.click(
        within(map()).getByRole("button", {
          name: "Pin in Kartenmitte setzen",
        }),
      );
      await waitFor(() =>
        expect(client.setDeliveryPin).toHaveBeenCalledTimes(1),
      );
    });
  });

  it("a move right before a day switch saves for its own day and leaves the new day's columns alone", async () => {
    const DAY2 = "2099-12-06";
    const client = fakeClient(dayTours({ days: [DAY, DAY2] }));
    const second: DeliveryDayToursResponse = {
      ...dayTours({ days: [DAY, DAY2] }),
      day: DAY2,
      tours: [
        {
          day: DAY2,
          driverName: "Fahrerin Anna",
          driverOrderedAt: null,
          driverUserId: "anna",
          revision: "d2",
          windows: [
            win("w1", [stop(drop("c7", "Hotel Ost", "w1", "anna"), 1)]),
          ],
        },
      ],
      unassigned: [],
    };
    const loadFirst = vi
      .mocked(client.getDeliveryTours)
      .getMockImplementation()!;
    vi.mocked(client.getDeliveryTours).mockImplementation(
      async (action: string, query?: { day?: string | null }) =>
        query?.day === DAY2 ? second : loadFirst(action, query),
    );
    const queries = newQueries();
    function Switching() {
      const [day, setDay] = useState(DAY);
      return (
        <TourPlanner
          actionId={actionId}
          client={client}
          day={day}
          onDayChange={setDay}
        />
      );
    }
    render(
      <QueryClientProvider client={queries}>
        <ToastProvider>
          <Switching />
        </ToastProvider>
      </QueryClientProvider>,
    );
    await screen.findAllByTestId("tour-column");
    fireEvent.click(
      within(column("anna")).getByRole("button", {
        name: "Bäckerei Kern nach unten",
      }),
    );
    fireEvent.change(screen.getByTestId("tour-day"), {
      target: { value: DAY2 },
    });
    await waitFor(() =>
      expect(client.saveDeliveryTourOrder).toHaveBeenCalledWith(
        actionId,
        "anna",
        { commitmentIds: ["c2", "c1", "c3"], day: DAY, expectedRevision: "r1" },
      ),
    );
    await waitFor(() => expect(names(column("anna"))).toEqual(["Hotel Ost"]));
    await screen.findByText("Reihenfolge für Fahrerin Anna gespeichert.");
    expect(
      queries.getQueryData<DeliveryDayToursResponse>([
        "delivery-tours",
        actionId,
        DAY2,
      ]),
    ).toEqual(second);
    expect(names(column("anna"))).toEqual(["Hotel Ost"]);
  });

  it("an arrow that would leave the window is not there to focus; focus stays in the row", async () => {
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    const anna = column("anna");
    expect(
      within(anna).queryByRole("button", { name: "Bäckerei Kern nach oben" }),
    ).toBeNull();
    expect(
      within(anna).queryByRole("button", { name: "Autohaus Nord nach unten" }),
    ).toBeNull();
    const down = within(anna).getByRole("button", {
      name: "Bäckerei Kern nach unten",
    });
    down.focus();
    fireEvent.click(down);
    // Bäckerei Kern is now last in 08–10: its down arrow is gone, focus
    // moved to its up arrow.
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(anna).getByRole("button", { name: "Bäckerei Kern nach oben" }),
      ),
    );
  });

  it("polling pauses while a move saves", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const client = fakeClient(dayTours());
    await renderPlanner(client);
    const calls = () => vi.mocked(client.getDeliveryTours).mock.calls.length;

    let before = calls();
    await act(() => vi.advanceTimersByTimeAsync(BOARD_POLL_MS + 50));
    expect(calls() - before).toBe(1);

    // A move just before the poll: the poll waits for the save.
    await act(() => vi.advanceTimersByTimeAsync(BOARD_POLL_MS - 300));
    fireEvent.click(
      within(column("anna")).getByRole("button", {
        name: "Bäckerei Kern nach unten",
      }),
    );
    before = calls();
    await act(() => vi.advanceTimersByTimeAsync(400));
    expect(calls() - before).toBe(0);
    await act(() => vi.advanceTimersByTimeAsync(400));
    expect(client.saveDeliveryTourOrder).toHaveBeenCalledTimes(1);

    // Saved: polling runs again.
    before = calls();
    await act(() => vi.advanceTimersByTimeAsync(BOARD_POLL_MS + 50));
    expect(calls() - before).toBeGreaterThanOrEqual(1);
  });

  it("changing the day sends a waiting move first, without asking", async () => {
    const client = fakeClient(dayTours({ days: [DAY, "2099-12-06"] }));
    const onDayChange = vi.fn();
    await renderPlanner(client, onDayChange);
    fireEvent.click(
      within(column("anna")).getByRole("button", {
        name: "Bäckerei Kern nach unten",
      }),
    );
    fireEvent.change(screen.getByTestId("tour-day"), {
      target: { value: "2099-12-06" },
    });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(onDayChange).toHaveBeenCalledWith("2099-12-06");
    await waitFor(() =>
      expect(client.saveDeliveryTourOrder).toHaveBeenCalledWith(
        actionId,
        "anna",
        { commitmentIds: ["c2", "c1", "c3"], day: DAY, expectedRevision: "r1" },
      ),
    );
  });

  it("a stale order on save shows the current tour again", async () => {
    const client = fakeClient(dayTours());
    vi.mocked(client.saveDeliveryTourOrder).mockRejectedValueOnce(
      new ApiError(409, {
        code: "tour_revision_conflict",
        message: "Die Tour wurde inzwischen geändert.",
      } as never),
    );
    await renderPlanner(client);
    const anna = column("anna");
    fireEvent.click(
      within(anna).getByRole("button", { name: "Bäckerei Kern nach unten" }),
    );
    await screen.findByText(
      "Die Tour wurde inzwischen geändert. Die Touren zeigen jetzt den aktuellen Stand.",
      undefined,
      { timeout: 3_000 },
    );
    expect(names(anna)).toEqual([
      "Bäckerei Kern",
      "Autohaus Nord",
      "Praxis Süd",
    ]);
    await waitFor(() =>
      expect(client.getDeliveryTours).toHaveBeenCalledTimes(2),
    );
  });
});

describe("delivery view switch (web)", () => {
  const identity = {
    actionMemberships: [],
    globalRoles: ["charity_admin"],
    userId: "maria",
  } as unknown as CurrentIdentityResponse;

  function renderPage(client: LeonAidApiClient) {
    render(
      <QueryClientProvider client={newQueries()}>
        <ToastProvider>
          <HotkeyProvider>
            <FeatureFlagProvider
              client={client}
              identity={identity}
              surface="web"
            >
              <DeliveryBoardPage
                actionId={actionId}
                client={client}
                surface="web"
              />
            </FeatureFlagProvider>
          </HotkeyProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );
  }

  function pageClient(enabled: boolean) {
    const client = fakeClient(dayTours());
    Object.assign(client, {
      getDeliveryBoard: vi.fn(async () => ({
        actionId,
        actionName: "Krapfentaxi",
        day: DAY,
        days: [DAY],
        drivers: [],
        followUpTasks: false,
        manager: true,
        timezone: "Europe/Berlin",
        windows: [],
      })),
      getFeatureFlagEvaluations: vi.fn(async () => ({
        flags: [{ enabled, key: "delivery.tours" }],
      })),
    });
    return client;
  }

  it("flag on: Touren in ?view=tours shows the planner, Liste goes back", async () => {
    const client = pageClient(true);
    renderPage(client);
    fireEvent.click(await screen.findByRole("link", { name: "Touren" }));
    await screen.findAllByTestId("tour-column");
    expect(new URL(window.location.href).searchParams.get("view")).toBe(
      "tours",
    );
    expect(client.getDeliveryTours).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("link", { name: "Liste" }));
    await waitFor(() =>
      expect(screen.queryAllByTestId("tour-column")).toHaveLength(0),
    );
    expect(new URL(window.location.href).searchParams.get("view")).toBeNull();
  });

  it("?view=tours waits for the flag and never loads the planner without it", async () => {
    window.history.replaceState(null, "", "/?view=tours");
    const client = pageClient(false);
    renderPage(client);
    await screen.findByRole("heading", { name: "Auslieferung" });
    await waitFor(() => expect(client.getDeliveryBoard).toHaveBeenCalled());
    expect(client.getDeliveryTours).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Touren" })).toBeNull();
  });

  it("?view=tours with the flag opens the planner directly", async () => {
    window.history.replaceState(null, "", `/?view=tours&day=${DAY}`);
    const client = pageClient(true);
    renderPage(client);
    await screen.findAllByTestId("tour-column");
    expect(client.getDeliveryBoard).not.toHaveBeenCalled();
    expect(client.getDeliveryTours).toHaveBeenCalledWith(actionId, {
      day: DAY,
    });
  });
});
