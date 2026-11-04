import { test, expect } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
import { materialRow, uploadMaterial } from "./material-list.mjs";

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
    const create = page
      .getByRole("button", { name: "Material hochladen", exact: true })
      .first();
    const createBox = await create.boundingBox();
    expect(createBox.height).toBeGreaterThanOrEqual(width <= 760 ? 43 : 31);
    expect(createBox.height).toBeLessThanOrEqual(width <= 760 ? 48 : 40);
    await expect(create).toHaveCSS("font-weight", "600");
    // Touch targets are 44 px on phones; desktop shell controls are 32 px.
    const iconTarget = width <= 760 ? 44 : 32;
    const iconButtonBox = await page
      .locator(".topbar .btn-icon:visible, .pwa-bar button:visible")
      .first()
      .boundingBox();
    expect(iconButtonBox.width).toBeGreaterThanOrEqual(iconTarget);
    expect(iconButtonBox.height).toBeGreaterThanOrEqual(iconTarget);
    if (width === 1440) {
      await page.setViewportSize({ width: 780, height: 844 });
      // Collapsed rail: sign-out stays one labelled click away.
      const logoutButton = page.getByTestId("logout");
      await expect(logoutButton).toBeVisible();
      await expect(logoutButton).toHaveAccessibleName("Abmelden");
      const logoutBox = await logoutButton.boundingBox();
      expect(logoutBox.width).toBeGreaterThanOrEqual(24);
      expect(logoutBox.height).toBeGreaterThanOrEqual(24);
      await page.setViewportSize({ width, height: 844 });
    }
    // The upload dialog checks the 25 MiB limit before anything is sent.
    await create.click();
    const dialog = page.getByRole("dialog", { name: "Material hochladen" });
    await dialog.getByLabel("Datei").setInputFiles({
      name: "zu-gross.bin",
      mimeType: "application/octet-stream",
      buffer: Buffer.alloc(25 * 1024 * 1024 + 1),
    });
    await expect(
      dialog.getByText(/Erlaubt sind höchstens 25 MiB/),
    ).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: "Hochladen", exact: true }),
    ).toBeDisabled();
    // The chosen file is a draft: cancelling asks first.
    await dialog.getByRole("button", { name: "Abbrechen" }).click();
    await page
      .getByRole("alertdialog", { name: "Entwurf verwerfen?" })
      .getByRole("button", { name: "Verwerfen" })
      .click();
    await expect(dialog).toBeHidden();

    const row = await uploadMaterial(
      page,
      baseURL,
      route.replace(/\/materials$/, ""),
      {
        title,
        file: {
          name: "original.txt",
          mimeType: "text/plain",
          buffer: original,
        },
      },
    );
    // A new version keeps the earlier one downloadable.
    await row
      .getByRole("button", { name: `Neue Version von ${title}` })
      .click();
    const version = page.getByRole("dialog", {
      name: "Neue Version hochladen",
    });
    await expect(version).toContainText(title);
    await version.getByLabel("Datei").setInputFiles({
      name: "updated.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("Zweite Version.\n"),
    });
    await version
      .getByRole("button", { name: "Hochladen", exact: true })
      .click();
    await expect(
      page.getByText("Version „updated.txt“ hochgeladen.", { exact: true }),
    ).toBeVisible();
    await expect(row).toContainText("2 Versionen");
    const versions = row.getByRole("table", { name: `Versionen von ${title}` });
    await expect(versions).toContainText("updated.txt");
    await expect(versions).toContainText("original.txt");
    const downloadPromise = page.waitForEvent("download");
    await versions
      .getByRole("button", { name: "original.txt herunterladen", exact: true })
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
    // The deep link (search hits) opens that material.
    const materialId = await row.getAttribute("data-material-id");
    const detailURL = `${baseURL}${route}/${materialId}`;
    await page.goto(detailURL);
    await expect(
      materialRow(page, title).getByRole("button", { expanded: true }),
    ).toBeVisible();
    await expect(materialRow(page, title)).toContainText("2 Versionen");
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
        surface === "pwa"
          ? "Das Material ist nicht verfügbar oder dein Zugriff wurde geändert."
          : "Das Material ist nicht verfügbar oder Ihr Zugriff wurde geändert.",
        { exact: true },
      ),
    ).toBeVisible();
    await expect(materialRow(denied, title)).toHaveCount(0);
    await foreign.close();
  });
}
