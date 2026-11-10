import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

/*
 * Delivery day board against the real stack (runs after the invoice proofs
 * on their seeded data: delivery planning on, one past window with orders).
 * Klara manages the board; Anna drives and sees only her drops in the PWA.
 */

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_BOARD_SESSION;
const annaSession = process.env.ANNA_DRIVER_SESSION;
const actionId = "20000000-0000-4000-8000-000000000001";

if (!baseUrl || !artifactDirectory || !klaraSession || !annaSession) {
  throw new Error("Delivery board browser environment is incomplete");
}

test.setTimeout(90_000);

function cookie(value) {
  return {
    name: "__Host-leonaid_session",
    value,
    url: baseUrl,
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
  };
}

async function expectAccessible(page) {
  const result = await analyzeAccessibility(page);
  expect(
    result.violations.filter((violation) =>
      ["critical", "serious"].includes(violation.impact),
    ),
  ).toEqual([]);
}

test("managers assign, tick and close; drivers tick only their drops", async ({
  browser,
}) => {
  const admin = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await admin.addCookies([cookie(klaraSession)]);
  const page = await admin.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const driver = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await driver.addCookies([cookie(annaSession)]);
  const mobile = await driver.newPage();
  mobile.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/delivery?action=${actionId}`);
    await expect(
      page.getByRole("heading", { name: "Auslieferung", level: 1 }),
    ).toBeVisible();
    const drops = page.getByTestId("delivery-drop");
    // Without a delivery day today or later the board opens the latest day.
    // The invoice proof booked its orders into the window three days ago,
    // the earliest of the seeded days.
    await page.getByTestId("delivery-day").selectOption({ index: 0 });
    await expect(drops.first()).toBeVisible();
    const dropCount = await drops.count();
    expect(dropCount).toBeGreaterThanOrEqual(3);
    await expectAccessible(page);

    // Nobody drives yet: the next step assigns all open drops at once.
    await page.getByTestId("delivery-next-assign").click();
    await page
      .getByRole("dialog", { name: "Fahrer wählen" })
      .getByRole("option", { name: "Anna Akquise" })
      .click();
    await expect(page.getByText("Fahrer zugewiesen.")).toBeVisible();
    await expect(page.getByTestId("delivery-next-assign")).toHaveCount(0);

    // j moves to the first drop, d ticks it.
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("j");
    await expect(page.locator(".drop-check").first()).toBeFocused();
    await page.keyboard.press("d");
    await expect(page.getByText(/: geliefert\.$/)).toBeVisible();
    await expect(page.locator(".drop.is-done")).toHaveCount(1);
    await page.screenshot({
      path: `${artifactDirectory}/delivery-board-desktop.png`,
    });
    // Fidelity set: 1440 and 390, light and dark (theme follows the system).
    await page.mouse.move(0, 0);
    for (const [width, height] of [
      [1440, 900],
      [390, 844],
    ]) {
      await page.setViewportSize({ width, height });
      for (const scheme of ["light", "dark"]) {
        await page.emulateMedia({ colorScheme: scheme });
        // Finish colour transitions: a theme switch would otherwise be
        // caught mid-fade (buttons look grey).
        await page.screenshot({
          animations: "disabled",
          path: `${artifactDirectory}/delivery-board-fidelity-${width}-${scheme}.png`,
        });
      }
    }
    await page.emulateMedia({ colorScheme: "light" });
    await page.setViewportSize({ width: 1440, height: 1000 });

    // Anna, in the PWA: her drops, no amounts, no planning controls.
    await mobile.goto(`${baseUrl}/app/delivery?action=${actionId}`);
    await expect(
      mobile.getByRole("heading", { name: "Auslieferung", level: 1 }),
    ).toBeVisible();
    const driverDrops = mobile.getByTestId("delivery-drop");
    await expect(driverDrops).toHaveCount(dropCount);
    await expect(
      mobile.getByText(/Du siehst nur deine Lieferungen/),
    ).toBeVisible();
    await expect(mobile.getByTestId("delivery-driver-filter")).toHaveCount(0);
    await expect(mobile.getByTestId("delivery-close-window")).toHaveCount(0);
    expect(await mobile.locator("main").innerText()).not.toContain("€");
    const open = mobile.locator(".drop:not(.is-done) .drop-check").first();
    await open.click();
    await expect(mobile.getByText(/: geliefert\.$/)).toBeVisible();
    expect(
      await mobile.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await expectAccessible(mobile);
    await mobile.screenshot({
      path: `${artifactDirectory}/delivery-board-driver-mobile.png`,
      fullPage: true,
    });

    // Offline (P4): the shell banner and no drops; back online, they reload.
    await driver.setOffline(true);
    await expect(mobile.getByText(/Du bist offline\./)).toBeVisible();
    await expect(
      mobile.getByText(/Ohne Verbindung zeigen wir keine Lieferungen/),
    ).toBeVisible();
    await expect(driverDrops).toHaveCount(0);
    await driver.setOffline(false);
    await expect(driverDrops).toHaveCount(dropCount);

    // Klara closes the window with the remaining open drops.
    await page.reload();
    await expect(page.locator(".drop.is-done")).toHaveCount(2);
    await page.getByTestId("delivery-close-window").first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("noch nicht abgehakt");
    await dialog.getByTestId("delivery-close-confirm").click();
    await expect(page.getByText(/^Fenster abgeschlossen\./)).toBeVisible();
    await expect(
      page.getByText("Abgeschlossen", { exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Nachliefern").first()).toBeVisible();

    // The driver can no longer tick a closed window.
    await mobile.reload();
    await expect(mobile.locator(".drop-check").first()).toBeDisabled();
    expect(pageErrors).toEqual([]);
  } finally {
    await admin.close();
    await driver.close();
  }
});

/** Switch the delivery.tours flag as system admin (fresh session, same origin). */
async function setToursFlag(request, enabled) {
  const url = `${baseUrl}/api/v1/admin/feature-flags`;
  const listed = await request.get(url);
  expect(listed.ok()).toBe(true);
  const flag = (await listed.json()).flags.find(
    (item) => item.key === "delivery.tours",
  );
  expect(flag).toBeTruthy();
  if (flag.enabled === enabled) return;
  const updated = await request.put(`${url}/delivery.tours`, {
    headers: { Origin: baseUrl },
    data: { enabled, expectedRevision: flag.revision },
  });
  expect(updated.ok()).toBe(true);
}

/** Klara's API session: first day's windows open, all drops open, all Anna's. */
async function arrangeStart(request) {
  const api = `${baseUrl}/api/v1/actions/${actionId}`;
  const headers = { Origin: baseUrl };
  const read = async (query = "") => {
    const response = await request.get(`${api}/delivery-board${query}`);
    expect(response.ok()).toBe(true);
    return response.json();
  };
  const first = await read();
  const board = await read(`?day=${first.days[0]}`);
  const anna = board.drivers.find(
    (item) => item.displayName === "Anna Akquise",
  );
  expect(anna).toBeTruthy();
  for (const window of board.windows.filter((item) => item.closure)) {
    const reopened = await request.delete(
      `${api}/delivery-windows/${window.id}/closure`,
      { headers },
    );
    expect(reopened.ok()).toBe(true);
  }
  const drops = (await read(`?day=${first.days[0]}`)).windows
    .flatMap((window) => window.drops)
    .filter((drop) => drop.orderStatus !== "cancelled");
  expect(drops.length).toBeGreaterThanOrEqual(4);
  for (const drop of drops.filter((item) => item.state !== "open")) {
    const reset = await request.put(
      `${api}/commitments/${drop.commitmentId}/delivery-state`,
      {
        headers,
        data: {
          delivered: false,
          missed: false,
          expectedRevision: drop.revision,
        },
      },
    );
    expect(reset.ok()).toBe(true);
  }
  const assigned = await request.put(`${api}/delivery-board/drivers`, {
    headers,
    data: {
      commitmentIds: drops.map((drop) => drop.commitmentId),
      driverUserId: anna.userId,
    },
  });
  expect(assigned.ok()).toBe(true);
}

/** The map's numbered pins as [commitment id, number], sorted by id. */
async function mapPins(map) {
  return (
    await map
      .locator(".tour-pin[data-pin-id]")
      .evaluateAll((pins) =>
        pins.map((pin) => [pin.dataset.pinId, pin.textContent]),
      )
  ).sort(([a], [b]) => a.localeCompare(b));
}

test("managers plan a tour; the driver reorders, delivers and sees a later stop as neu", async ({
  browser,
}) => {
  const flagSession = process.env.SIMONE_FLAG_SESSION;
  if (!flagSession) throw new Error("SIMONE_FLAG_SESSION is missing");
  const pageErrors = [];
  const open = async (session, viewport) => {
    const context = await browser.newContext({
      viewport,
      ignoreHTTPSErrors: true,
    });
    await context.addCookies([cookie(session)]);
    const page = await context.newPage();
    page.on("pageerror", (error) => pageErrors.push(error.message));
    return { context, page };
  };
  const flagAdmin = await open(flagSession, { width: 1440, height: 1000 });
  const planner = await open(klaraSession, { width: 1440, height: 1000 });
  const driver = await open(annaSession, { width: 390, height: 844 });
  const { page } = planner;
  const mobile = driver.page;

  try {
    await setToursFlag(flagAdmin.context.request, true);

    // Own start state, whatever ran before: the first day's windows open,
    // every drop open and driven by Anna.
    await arrangeStart(planner.context.request);

    await page.goto(`${baseUrl}/admin/delivery?action=${actionId}&view=tours`);
    await expect(
      page.getByRole("heading", { name: "Auslieferung", level: 1 }),
    ).toBeVisible();
    // The columns first: the day picker renders with them.
    await expect(page.getByTestId("tour-unassigned")).toBeVisible();
    const day = page.getByTestId("tour-day");
    if (await day.count()) await day.selectOption({ index: 0 });
    const anna = page
      .getByTestId("tour-column")
      .filter({ hasText: "Anna Akquise" });
    const unassigned = page.getByTestId("tour-unassigned");
    const open_ = (lane) => lane.locator("li.tour-stop:not(.is-done)");
    await expect(open_(anna).first()).toBeVisible();
    await expectAccessible(page);

    // Take three open stops back from Anna, then plan them again.
    const openCount = await open_(anna).count();
    expect(openCount).toBeGreaterThanOrEqual(3);
    const ids = await open_(anna).evaluateAll((rows) =>
      rows.map((row) => row.getAttribute("data-commitment-id")),
    );
    const stop = (lane, id) =>
      lane.locator(`li.tour-stop[data-commitment-id="${id}"]`);
    const assign = async (lane, picked, label) => {
      for (const id of picked) {
        await stop(lane, id).getByRole("checkbox").check();
      }
      await page.getByRole("button", { name: "Fahrer zuordnen" }).click();
      await page
        .getByRole("dialog", { name: "Fahrer wählen" })
        .getByRole("option", { name: label })
        .click();
    };
    const lastThree = ids.slice(-3);
    await assign(anna, lastThree, "Kein Fahrer");
    await expect(page.getByText("Fahrer entfernt (3 Stopps).")).toBeVisible();
    await expect(unassigned.locator("li.tour-stop")).toHaveCount(3);

    // Two go back to Anna at the end; Klara moves the second one up, and
    // the move saves on its own (D19 2a).
    const [first, second, third] = lastThree;
    await assign(unassigned, [first, second], "Anna Akquise");
    await expect(
      page.getByText(
        "2 Stopps Anna Akquise zugeordnet. Sie stehen am Ende ihres Fensters.",
      ),
    ).toBeVisible();
    await expect(open_(anna)).toHaveCount(openCount - 1);
    // The row's tools show when the row is pointed at.
    await stop(anna, second).hover();
    await stop(anna, second)
      .getByRole("button", { name: /nach oben/ })
      .click();
    await expect(anna.getByTestId("tour-save-order")).toHaveCount(0);
    await expect(
      page.getByText("Reihenfolge für Anna Akquise gespeichert."),
    ).toBeVisible();
    const planned = await open_(anna).evaluateAll((rows) =>
      rows.map((row) => row.getAttribute("data-commitment-id")),
    );
    expect(planned.slice(-2)).toEqual([second, first]);

    // One stop to another driver by its grip: the stop follows the pointer
    // as a ghost, the column under it says what the drop does, and a drop on
    // the column's head counts (not only on a stop). "Rückgängig" gives the
    // stop back.
    const waiting = stop(unassigned, third);
    const grip = await waiting
      .getByRole("button", { name: /^Stopp verschieben: / })
      .boundingBox();
    const head = await anna.getByRole("heading", { level: 2 }).boundingBox();
    expect(grip && head).toBeTruthy();
    // A real target with a grab cursor, not a bare icon.
    expect(grip.width).toBeGreaterThanOrEqual(28);
    await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
    await page.mouse.down();
    await page.mouse.move(head.x + head.width / 2, head.y + head.height / 2, {
      steps: 16,
    });
    await expect(page.getByTestId("tour-drag-ghost")).toBeVisible();
    await expect(anna.getByTestId("tour-lane-drop")).toContainText(
      "Loslassen: ans Ende von",
    );
    await page.mouse.up();
    const assigned = page.getByTestId("toast").filter({
      hasText:
        "1 Stopp Anna Akquise zugeordnet. Sie stehen am Ende ihres Fensters.",
    });
    await expect(assigned).toBeVisible();
    await expect(stop(anna, third)).toBeVisible();
    await expect(unassigned.locator("li.tour-stop")).toHaveCount(0);
    await assigned.getByRole("button", { name: "Rückgängig" }).click();
    await expect(
      page
        .getByTestId("toast")
        .filter({ hasText: "Zuordnung zurückgenommen." }),
    ).toBeVisible();
    await expect(stop(unassigned, third)).toBeVisible();

    // The map (§6.1, §6.4): the test stack cannot geocode, so Klara sets
    // two of Anna's pins by a click on the map. Pins stay between runs.
    // The map is a choice; at this width it starts closed.
    const mapToggle = page.getByTestId("tour-map-toggle");
    if ((await mapToggle.getAttribute("aria-pressed")) !== "true") {
      await mapToggle.click();
    }
    const plannerMap = page.getByTestId("tour-plan-map");
    const plannerCanvas = plannerMap.getByTestId("tour-map-canvas");
    await expect(plannerCanvas).toHaveAttribute("data-ready", "true");
    const noPin = anna.getByTestId("tour-set-pin");
    for (const x of [0.4, 0.6]) {
      const missing = await noPin.count();
      if (!missing) break;
      await noPin.first().click();
      await expect(plannerMap.getByRole("status")).toContainText(
        "Klicken Sie in die Karte",
      );
      const box = await plannerCanvas.boundingBox();
      await page.mouse.click(box.x + box.width * x, box.y + box.height * 0.5);
      await expect(noPin).toHaveCount(missing - 1);
    }
    // The day on screen (no picker: the only day, which the API picks too).
    const shownDay = (await day.count()) ? await day.inputValue() : null;
    const tours = await page.request.get(
      `${baseUrl}/api/v1/actions/${actionId}/delivery-board/tours${
        shownDay ? `?day=${shownDay}` : ""
      }`,
    );
    expect(tours.ok()).toBe(true);
    const body = await tours.json();
    const located = [
      ...body.unassigned,
      ...body.tours.flatMap((tour) => tour.windows),
    ]
      .flatMap((window) => window.stops)
      .filter((item) => item.lat !== null && item.lon !== null);
    expect(located.length).toBeGreaterThanOrEqual(2);
    await expect(plannerMap.locator(".tour-pin[data-pin-id]")).toHaveCount(
      located.length,
    );
    // Tiles come from the test proxy under 'self', never from outside.
    const tileSources = await plannerCanvas
      .locator("img.leaflet-tile")
      .evaluateAll((tiles) => tiles.map((tile) => tile.src));
    expect(tileSources.length).toBeGreaterThan(0);
    for (const source of tileSources) {
      expect(source.startsWith(`${baseUrl}/e2e-tiles/`)).toBe(true);
    }
    const annaIds = await anna
      .locator("li.tour-stop")
      .evaluateAll((rows) =>
        rows.map((row) => row.getAttribute("data-commitment-id")),
      );
    const annaPins = (await mapPins(plannerMap)).filter(([id]) =>
      annaIds.includes(id),
    );
    expect(annaPins.length).toBeGreaterThanOrEqual(2);
    await expectAccessible(page);
    await page.screenshot({
      animations: "disabled",
      path: `${artifactDirectory}/delivery-tours-1440-light.png`,
    });
    await page.emulateMedia({ colorScheme: "dark" });
    await page.screenshot({
      animations: "disabled",
      path: `${artifactDirectory}/delivery-tours-1440-dark.png`,
    });
    await page.emulateMedia({ colorScheme: "light" });

    // Anna: the dock holds Klara's first open stop; "Tour" leads the tabs.
    const tourPage = await mobile.goto(
      `${baseUrl}/app/delivery?action=${actionId}`,
    );
    // The CSP opens img-src for the tile origin only (D3, §8.1).
    const policy = tourPage.headers()["content-security-policy"];
    expect(policy).toContain(
      "img-src 'self' data: blob: https://tile.openstreetmap.org;",
    );
    expect(policy).toContain("connect-src 'self';");
    expect(policy).toContain("script-src 'self';");
    await expect(mobile.getByTestId("tour-bar-sub")).toContainText(
      "Meine Tour",
    );
    await expect(
      mobile.locator('.pwa-tab[data-nav-key="delivery"]'),
    ).toHaveAttribute("aria-current", "page");
    const next = mobile.getByTestId("tour-next-stop");
    await expect(next).toBeVisible();
    await expect(mobile.getByTestId("tour-stop")).toHaveCount(openCount - 1);
    await expect(mobile.getByText("Reihenfolge ändern")).toHaveCount(0);
    await expectAccessible(mobile);

    // The dock's still map (D17) for the next stop, when it has a pin.
    // Long names and the map never widen the dock past the screen.
    expect(
      await mobile
        .getByTestId("tour-dock")
        .evaluate((dock) => dock.scrollWidth <= dock.clientWidth),
    ).toBe(true);
    for (const scheme of ["light", "dark"]) {
      await mobile.emulateMedia({ colorScheme: scheme });
      await mobile.screenshot({
        animations: "disabled",
        path: `${artifactDirectory}/delivery-tours-dock-390-${scheme}.png`,
      });
    }
    await mobile.emulateMedia({ colorScheme: "light" });

    // "Karte" (§7.2): the same numbered pins as on Klara's map.
    const mapToggle = mobile.getByRole("button", {
      name: "Karte",
      exact: true,
    });
    await mapToggle.click();
    const mapView = mobile.getByTestId("tour-mapview");
    await expect(mapView.getByTestId("tour-map-canvas")).toHaveAttribute(
      "data-ready",
      "true",
    );
    await expect(mapView.locator(".tour-pin[data-pin-id]")).toHaveCount(
      annaPins.length,
    );
    expect(await mapPins(mapView)).toEqual(annaPins);
    // 44 px targets for pins and zoom buttons (WCAG 2.5.5, car mount).
    for (const target of [
      mapView.locator(".tour-pin[data-pin-id]").first(),
      mapView.locator(".leaflet-control-zoom-in"),
      mapView.locator(".leaflet-control-zoom-out"),
    ]) {
      const box = await target.boundingBox();
      expect(box.width).toBeGreaterThanOrEqual(44);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
    await expectAccessible(mobile);
    for (const scheme of ["light", "dark"]) {
      await mobile.emulateMedia({ colorScheme: scheme });
      await mobile.screenshot({
        animations: "disabled",
        path: `${artifactDirectory}/delivery-tours-map-390-${scheme}.png`,
      });
    }
    await mobile.emulateMedia({ colorScheme: "light" });
    // A pin opens its stop as a sheet with the dock's buttons.
    await mapView.locator(".tour-pin[data-pin-id]").first().click();
    await expect(
      mobile.getByTestId("tour-dock").or(mobile.getByTestId("tour-done-sheet")),
    ).toBeVisible();
    await mapToggle.click();
    await expect(mapView).toHaveCount(0);

    // She moves an open stop down at its grip; the move saves at once (D16).
    // A stop whose next row in the window is open too, so down can move.
    const movable = await mobile
      .locator("ol.tour-rows > li[data-testid='tour-stop']")
      .evaluateAll((rows) =>
        rows
          .find(
            (row) =>
              row.querySelector(".task-order-handle") &&
              row.nextElementSibling?.getAttribute("data-testid") ===
                "tour-stop",
          )
          ?.getAttribute("data-commitment-id"),
      );
    expect(movable).toBeTruthy();
    const moved = mobile.locator(`li[data-commitment-id="${movable}"]`);
    const below = moved.locator("xpath=following-sibling::li[1]");
    const grip = await moved
      .getByRole("button", { name: /^Stopp verschieben: / })
      .boundingBox();
    const target = await below.boundingBox();
    const belowId = await below.getAttribute("data-commitment-id");
    expect(grip && target && belowId).toBeTruthy();
    // Drag at the grip onto the lower half of the next row.
    await mobile.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2);
    await mobile.mouse.down();
    await mobile.mouse.move(
      grip.x + grip.width / 2,
      target.y + target.height * 0.75,
      { steps: 12 },
    );
    await mobile.mouse.up();
    await expect(
      moved.locator("xpath=preceding-sibling::li[1]"),
    ).toHaveAttribute("data-commitment-id", belowId);
    await expect(mobile.getByText("Reihenfolge gespeichert.")).toBeVisible();
    await expect(mobile.getByTestId("tour-bar-sub")).toContainText(
      "Eigene Reihenfolge",
    );

    // Deliver, undo, deliver again. The delivered stop stays in its place,
    // greyed (D15), and the dock moves on without scrolling (critique P0-1);
    // "Rückgängig" is the one on the toast just shown.
    const rows = mobile.locator("ol.tour-rows > li");
    const done = mobile.getByTestId("tour-stop-done");
    const doneBefore = await done.count();
    const slot = await rows.evaluateAll((items) =>
      items.findIndex((item) => item.classList.contains("is-current")),
    );
    expect(slot).toBeGreaterThanOrEqual(0);
    const docked = await next.getByRole("heading").textContent();
    const deliver = next.getByRole("button", { name: "Zugestellt" });
    const scrolled = await mobile.evaluate(() => window.scrollY);
    await deliver.click();
    await expect(mobile.getByText(/: zugestellt\.$/)).toBeVisible();
    await expect(done).toHaveCount(doneBefore + 1);
    await expect(rows.nth(slot)).toHaveAttribute(
      "data-testid",
      "tour-stop-done",
    );
    await expect(rows.nth(slot)).toHaveClass(/is-done/);
    await expect(next.getByRole("heading")).not.toHaveText(docked ?? "");
    await expect(
      next.getByRole("button", { name: "Zugestellt" }),
    ).toBeInViewport();
    expect(await mobile.evaluate(() => window.scrollY)).toBe(scrolled);
    // The order toast may still show its own "Rückgängig": take the stop's.
    await mobile
      .locator(".toast")
      .filter({ hasText: /: zugestellt\./ })
      .getByRole("button", { name: "Rückgängig" })
      .click();
    await expect(mobile.getByText(/ ist wieder offen\.$/)).toBeVisible();
    await expect(done).toHaveCount(doneBefore);
    await mobile
      .getByTestId("tour-next-stop")
      .getByRole("button", { name: "Zugestellt" })
      .click();
    await expect(done).toHaveCount(doneBefore + 1);
    await expect(rows.nth(slot)).toHaveAttribute(
      "data-testid",
      "tour-stop-done",
    );

    // "Nicht angetroffen" survives a reload (D13).
    await mobile
      .getByTestId("tour-next-stop")
      .getByRole("button", { name: "Nicht angetroffen" })
      .click();
    await expect(mobile.getByText(/: nicht angetroffen\.$/)).toBeVisible();
    await mobile.reload();
    await expect(
      done.filter({
        has: mobile.getByRole("img", { name: "Nicht angetroffen" }),
      }),
    ).toHaveCount(1);
    for (const scheme of ["light", "dark"]) {
      await mobile.emulateMedia({ colorScheme: scheme });
      await mobile.screenshot({
        animations: "disabled",
        fullPage: true,
        path: `${artifactDirectory}/delivery-tours-390-${scheme}.png`,
      });
    }
    await mobile.emulateMedia({ colorScheme: "light" });

    // Klara sees Anna's own order and appends a third stop.
    await page.reload();
    const banner = anna.getByTestId("tour-driver-order-banner");
    await expect(banner).toContainText("Fahrer hat eigene Reihenfolge");
    await assign(unassigned, [third], "Anna Akquise");
    await expect(
      page.getByText(
        "1 Stopp Anna Akquise zugeordnet. Sie stehen am Ende ihres Fensters.",
      ),
    ).toBeVisible();

    // Anna: the new stop is last and marked neu.
    await mobile.reload();
    await expect(rows.last()).toContainText("neu");
    await expect(mobile.getByText("neu", { exact: true })).toHaveCount(1);
    await expectAccessible(mobile);
    expect(
      await mobile.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(pageErrors).toEqual([]);
  } finally {
    try {
      await setToursFlag(flagAdmin.context.request, false);
    } finally {
      await flagAdmin.context.close();
      await planner.context.close();
      await driver.context.close();
    }
  }
});
