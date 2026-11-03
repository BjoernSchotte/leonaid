import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";

const baseURL = process.env.LEONAID_E2E_BASE_URL;
const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);

for (const [surface, route, width] of [
  ["web", "/admin/materials", 1440],
  ["pwa", "/app/materials", 390],
]) {
  test(`${surface}: versioned upload, original download and private access`, async ({
    browser,
  }, testInfo) => {
    const context = await browser.newContext({
      viewport: { width, height: 844 },
      ignoreHTTPSErrors: true,
    });
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: fixture.sessions[0],
        url: baseURL,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const page = await context.newPage();
    const title = `Material Browsernachweis ${surface} ${randomUUID()}`;
    const original = Buffer.from("Erste Version bleibt erhalten.\n");
    await page.goto(`${baseURL}${route}`);
    await page.getByText("Neues Material", { exact: true }).click();
    await page.getByLabel("Materialtitel", { exact: true }).fill(title);
    await page.getByLabel("Datei", { exact: true }).setInputFiles({
      name: "original.txt",
      mimeType: "text/plain",
      buffer: original,
    });
    const uploadButton = page.getByRole("button", {
      name: "Hochladen",
      exact: true,
    });
    const uploadBox = await uploadButton.boundingBox();
    expect(uploadBox.height).toBeGreaterThanOrEqual(width <= 760 ? 44 : 40);
    expect(uploadBox.height).toBeLessThanOrEqual(width <= 760 ? 48 : 44);
    await expect(uploadButton).toHaveCSS("font-weight", "600");
    const iconButtonBox = await page
      .locator(".ui-icon-button:visible, .pwa-bar button:visible")
      .first()
      .boundingBox();
    expect(iconButtonBox.width).toBeGreaterThanOrEqual(44);
    expect(iconButtonBox.height).toBeGreaterThanOrEqual(44);
    if (width === 1440) {
      await page.setViewportSize({ width: 780, height: 844 });
      const logoutButton = page.getByRole("button", {
        name: "Abmelden",
        exact: true,
      });
      await expect(
        logoutButton.locator("span").filter({ hasText: /^Abmelden$/ }),
      ).toBeHidden();
      const logoutBox = await logoutButton.boundingBox();
      expect(logoutBox.width).toBeGreaterThanOrEqual(44);
      expect(logoutBox.height).toBeGreaterThanOrEqual(44);
      await page.setViewportSize({ width, height: 844 });
    }
    await uploadButton.click();
    await expect(
      page.getByRole("heading", { name: title, exact: true }),
    ).toBeVisible();
    const detailURL = page.url();
    await page.goto(detailURL);
    await page.getByLabel("Datei", { exact: true }).setInputFiles({
      name: "updated.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Zweite Version.\n"),
    });
    await page
      .getByRole("button", { name: "Neue Version hochladen", exact: true })
      .click();
    await expect(page.getByText(/Aktuelle Dateiversion 2/)).toBeVisible();
    await page.getByLabel("Dateiversion", { exact: true }).fill("1");
    await expect(page.getByText(/original.txt/)).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Dateiversion herunterladen", exact: true })
      .click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe("original.txt");
    expect(readFileSync(await download.path())).toEqual(original);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath(`${surface}-retained-version.png`),
      fullPage: false,
    });
    await page.goto(detailURL);
    await expect(page.getByText(/Aktuelle Dateiversion 2/)).toBeVisible();
    await context.close();

    const foreign = await browser.newContext({
      viewport: { width, height: 844 },
      ignoreHTTPSErrors: true,
    });
    await foreign.addCookies([
      {
        name: "__Host-leonaid_session",
        value: fixture.sessions[1],
        url: baseURL,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const denied = await foreign.newPage();
    await denied.goto(detailURL);
    await expect(
      denied.getByText(
        "Das Material ist nicht verfügbar oder dein Zugriff wurde geändert.",
        { exact: false },
      ),
    ).toBeVisible();
    await expect(
      denied.getByRole("heading", { name: title, exact: true }),
    ).toHaveCount(0);
    await expect(
      denied.getByRole("button", {
        name: "Dateiversion herunterladen",
        exact: true,
      }),
    ).toHaveCount(0);
    await foreign.close();
  });
}
