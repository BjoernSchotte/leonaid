import AxeBuilder from "@axe-core/playwright";
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
  const result = await new AxeBuilder({ page }).analyze();
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
        await page.screenshot({
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
