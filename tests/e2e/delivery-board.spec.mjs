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

    // The board proof closed the window: Klara reopens it in the list.
    await page.goto(`${baseUrl}/admin/delivery?action=${actionId}`);
    await expect(
      page.getByRole("heading", { name: "Auslieferung", level: 1 }),
    ).toBeVisible();
    await page.getByTestId("delivery-day").selectOption({ index: 0 });
    await page.getByRole("button", { name: "Wieder öffnen" }).first().click();
    await expect(
      page.getByTestId("delivery-close-window").first(),
    ).toBeVisible();

    await page.goto(`${baseUrl}/admin/delivery?action=${actionId}&view=tours`);
    await expect(
      page.getByRole("heading", { name: "Auslieferung", level: 1 }),
    ).toBeVisible();
    const day = page.getByTestId("tour-day");
    if (await day.count()) await day.selectOption({ index: 0 });
    const anna = page
      .getByTestId("tour-column")
      .filter({ hasText: "Anna Akquise" });
    const unassigned = page.getByTestId("tour-unassigned");
    const open_ = (lane) => lane.locator("li.tour-stop:not(.is-done)");
    await expect(open_(anna).first()).toBeVisible();
    await expectAccessible(page);

    // The board proof gave every drop to Anna: take three open ones back,
    // then plan them again.
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

    // Two go back to Anna at the end; Klara moves the second one up and saves.
    const [first, second, third] = lastThree;
    await assign(unassigned, [first, second], "Anna Akquise");
    await expect(
      page.getByText(
        "2 Stopps Anna Akquise zugeordnet. Sie stehen am Ende ihres Fensters.",
      ),
    ).toBeVisible();
    await expect(open_(anna)).toHaveCount(openCount - 1);
    await stop(anna, second)
      .getByRole("button", { name: /nach oben/ })
      .click();
    const order = anna.getByTestId("tour-save-order");
    await expect(order).toBeEnabled();
    await order.click();
    await expect(
      page.getByText("Reihenfolge für Anna Akquise gespeichert."),
    ).toBeVisible();
    const planned = await open_(anna).evaluateAll((rows) =>
      rows.map((row) => row.getAttribute("data-commitment-id")),
    );
    expect(planned.slice(-2)).toEqual([second, first]);
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

    // Anna: the large card is Klara's first open stop.
    await mobile.goto(`${baseUrl}/app/delivery?action=${actionId}`);
    await expect(
      mobile.getByRole("heading", { name: "Meine Tour", level: 1 }),
    ).toBeVisible();
    const next = mobile.getByTestId("tour-next-stop");
    await expect(next).toBeVisible();
    await expect(mobile.getByTestId("tour-stop")).toHaveCount(openCount - 2);
    await expectAccessible(mobile);

    // She moves her first open stop down and finishes the edit.
    await mobile.getByTestId("tour-reorder").click();
    await mobile
      .getByTestId("tour-stop")
      .first()
      .getByRole("button", { name: /nach unten/ })
      .click();
    await mobile.getByTestId("tour-reorder-done").click();
    await expect(
      mobile.getByText("Deine Reihenfolge ist gespeichert."),
    ).toBeVisible();
    await expect(mobile.getByTestId("tour-reorder-done")).toHaveCount(0);

    // Deliver, undo, deliver again.
    const done = mobile.getByTestId("tour-stop-done");
    const doneBefore = await done.count();
    await next.getByRole("button", { name: "Zugestellt" }).click();
    await expect(mobile.getByText(/: zugestellt\.$/).last()).toBeVisible();
    await expect(done).toHaveCount(doneBefore + 1);
    await expect(mobile.getByTestId("tour-next-stop")).toBeVisible();
    await mobile.getByRole("button", { name: "Rückgängig" }).last().click();
    await expect(mobile.getByText(/ ist wieder offen\.$/).last()).toBeVisible();
    await expect(done).toHaveCount(doneBefore);
    await mobile
      .getByTestId("tour-next-stop")
      .getByRole("button", { name: "Zugestellt" })
      .click();
    await expect(done).toHaveCount(doneBefore + 1);
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
    const rows = mobile.locator("ol.tour-rows > li");
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
