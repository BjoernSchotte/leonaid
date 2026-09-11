import assert from "node:assert/strict";
import { createHash, X509Certificate } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import { chromium } from "playwright";
import { expect } from "@playwright/test";
import { browserLogin } from "../emdash_spike/browser-login.mjs";

const origin = "https://proxy:8443";
const certificate = new X509Certificate(await readFile("/proof/server.crt"));
const pin = createHash("sha256")
  .update(certificate.publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");
// Trust only this disposable test project's Caddy key in this browser process.
// Node HTTP requests separately verify the CA via NODE_EXTRA_CA_CERTS.
const browser = await chromium.launch({
  args: [`--ignore-certificate-errors-spki-list=${pin}`],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1050 },
});
const page = await context.newPage();
await mkdir("/proof/screenshots", { recursive: true });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
try {
  await page.goto(`${origin}/login?returnTo=%2Fadmin%2Factions`);
  await browserLogin(context, page, "/admin/actions");
  const suffix = Date.now();
  await page.goto(`${origin}/admin/actions/new`);
  await page
    .getByRole("combobox", { name: /Aktionsvorlage/ })
    .selectOption("krapfentaxi");
  for (const [field, value] of Object.entries({
    "action-slug": `delivery-admin-${suffix}`,
    "action-carrier": "Synthetischer Testclub",
    "action-name": "Krapfentaxi Lieferplanung – Browsertest",
    "action-purpose": "Synthetische Abnahme der Lieferplanung",
    "action-start": "2037-12-01",
    "action-end": "2037-12-31",
    "beneficiary-name-0": "Testorganisation",
    "beneficiary-description-0": "Synthetische Begünstigte",
    "action-goal": "100",
    "action-unit": "Boxen",
  }))
    await page.getByTestId(field).fill(value);
  await page.evaluate(() => {
    document.activeElement?.blur();
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  await page.screenshot({
    path: "/proof/screenshots/create-template.png",
    fullPage: true,
  });
  const [create] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/actions/from-template") &&
        response.request().method() === "POST",
    ),
    page.getByTestId("action-submit").click(),
  ]);
  assert.equal(create.status(), 201);
  const { action } = await create.json();
  const actionPath = `/admin/actions/${action.id}#delivery`;
  const configPath = `${origin}/api/v1/actions/${action.id}/delivery-configuration`;
  await expect(page.locator("#action-status")).toHaveAttribute(
    "data-state",
    "success",
  );
  await expect(
    page.getByRole("heading", { name: "Lieferung planen", exact: true }),
  ).toBeVisible();
  await page.goto(origin + actionPath);
  await expect(
    page.getByRole("heading", { name: "Lieferung planen", exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/Noch keine Lieferfenster/)).toBeVisible();
  for (let day = 1; day <= 2; day++) {
    await page
      .getByRole("button", { name: "Weiteren Tag hinzufügen", exact: true })
      .click();
    await page
      .getByLabel(`Datum für Liefertag ${day}`, { exact: true })
      .fill(`2037-12-${day === 1 ? "04" : "05"}`);
    const group = page.getByRole("group", {
      name: `Neuer Liefertag ${day}`,
      exact: true,
    });
    for (let slot = 1; slot <= 3; slot++) {
      if (slot > 1)
        await group
          .getByRole("button", { name: "Zeitfenster hinzufügen", exact: true })
          .click();
      await page
        .getByLabel(`Beginn ${slot} am Liefertag ${day}`, { exact: true })
        .fill(`${String(6 + 2 * slot).padStart(2, "0")}:00`);
      await page
        .getByLabel(`Ende ${slot} am Liefertag ${day}`, { exact: true })
        .fill(`${String(8 + 2 * slot).padStart(2, "0")}:00`);
    }
  }
  await page
    .getByRole("button", { name: "Lieferplanung speichern", exact: true })
    .click();
  await expect(page.getByText(/Lieferplanung gespeichert/)).toBeVisible();
  let saved = await (await context.request.get(configPath)).json();
  assert.equal(saved.windows.length, 6);
  await expect(page.locator('input[type="time"]')).toHaveCount(0);
  // A server-side concurrent edit exercises the real 409 response, not a mock.
  const firstDay = page.getByRole("group", {
    name: "Freitag, 4. Dezember 2037",
    exact: true,
  });
  await firstDay
    .getByRole("button", { name: "Zeitfenster hinzufügen", exact: true })
    .click();
  await page
    .getByLabel("Beginn 4 am Liefertag 1", { exact: true })
    .fill("14:00");
  await page.getByLabel("Ende 4 am Liefertag 1", { exact: true }).fill("16:00");
  const parallel = await context.request.put(configPath, {
    headers: { Origin: origin },
    data: {
      expectedRevision: saved.revision,
      enabled: true,
      timezone: saved.timezone,
      windows: [
        ...saved.windows,
        { deliveryOn: "2037-12-06", startsAt: "08:00", endsAt: "10:00" },
      ],
    },
  });
  assert.equal(parallel.status(), 200);
  await page
    .getByRole("button", { name: "Lieferplanung speichern", exact: true })
    .click();
  await expect(
    page.getByText(/Die Lieferplanung wurde inzwischen geändert/),
  ).toBeVisible();
  await expect(
    page.getByLabel("Beginn 4 am Liefertag 1", { exact: true }),
  ).toHaveValue("14:00");
  await page
    .getByRole("button", {
      name: "Aktuellen Stand laden und Eingaben behalten",
      exact: true,
    })
    .click();
  await expect(page.getByText(/Aktueller Stand geladen/)).toBeVisible();
  await expect(
    page.getByLabel("Beginn 4 am Liefertag 1", { exact: true }),
  ).toHaveValue("14:00");
  await page
    .getByRole("button", { name: "Lieferplanung speichern", exact: true })
    .click();
  await expect(page.getByText(/Lieferplanung gespeichert/)).toBeVisible();
  saved = await (await context.request.get(configPath)).json();
  assert.equal(saved.windows.length, 8);
  for (const [name, width] of [
    ["desktop", 1440],
    ["mobile", 390],
    ["user-562", 562],
  ]) {
    await page.setViewportSize({ width, height: 1050 });
    await page.evaluate(() => {
      document.activeElement?.blur();
      window.scrollTo({ top: 0, behavior: "instant" });
    });
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
    await expect(
      page.getByRole("heading", { name: "Lieferung planen", exact: true }),
    ).toBeVisible();
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      true,
    );
    await page.screenshot({
      path: `/proof/screenshots/${name}.png`,
      fullPage: true,
    });
  }
  await page.setViewportSize({ width: 780, height: 1050 });
  await page.evaluate(() => (document.documentElement.style.fontSize = "200%"));
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.screenshot({
    path: "/proof/screenshots/text-200.png",
    fullPage: true,
  });
  const overflow = await page.evaluate(() =>
    [...document.querySelectorAll("body *")]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return (
          rect.width > 0 &&
          rect.right > innerWidth + 1 &&
          !element.closest("[hidden]") &&
          getComputedStyle(element).position !== "fixed"
        );
      })
      .map((element) => ({
        tag: element.tagName,
        id: element.id,
        className: element.className,
        width: element.getBoundingClientRect().width,
      }))
      .slice(0, 12),
  );
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    true,
    JSON.stringify(overflow),
  );
  await page.evaluate(() =>
    document.documentElement.style.removeProperty("font-size"),
  );
  await page
    .getByLabel("08:00–10:00 Uhr stilllegen", { exact: true })
    .first()
    .check();
  await page
    .getByRole("button", { name: "Lieferplanung speichern", exact: true })
    .click();
  await expect(page.getByText("Stillgelegt", { exact: true })).toBeVisible();
  saved = await (await context.request.get(configPath)).json();
  assert.equal(saved.windows.filter((window) => window.retired).length, 1);
  assert.deepEqual(errors, []);
  console.log(
    "KLF-040 browser PASS: real passwordless login, six windows, immutable saved dates, concurrent 409 with retained input and merge, eight variable windows, retirement, desktop/mobile/user viewport/200% text without page overflow",
  );
} finally {
  await context.close();
  await browser.close();
}
