import assert from "node:assert/strict";
import { createHash, X509Certificate, randomUUID } from "node:crypto";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "playwright";
import { expect } from "@playwright/test";
import { browserLogin } from "../emdash_spike/browser-login.mjs";
import { configureDeliveryDemo } from "./demo-configuration.mjs";
import { lookup } from "node:dns/promises";

const origin = "https://proxy:8443";
const publicOrigin = "https://localhost:28443";
const golden = "20000000-0000-4000-8000-000000000001";
const api = `${origin}/api/v1/actions/${golden}`;
const certificate = new X509Certificate(await readFile("/proof/server.crt"));
const pin = createHash("sha256")
  .update(certificate.publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");
const localCertificate = new X509Certificate(
  await readFile("/proof/localhost.crt"),
);
const localPin = createHash("sha256")
  .update(localCertificate.publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");
const gateway = await lookup("host.docker.internal");
const browser = await chromium.launch({
  args: [
    `--ignore-certificate-errors-spki-list=${pin},${localPin}`,
    `--host-resolver-rules=MAP localhost ${gateway.address}`,
  ],
});
const admin = await browser.newContext();
const adminPage = await admin.newPage();
const headers = { Origin: origin };
const json = async (response, status = 200) => {
  assert.equal(response.status(), status, await response.text());
  return response.json();
};
// An explicit resume keeps already verified order receipts after an interrupted
// browser run. The default always exercises every route from the beginning.
const receipts =
  process.env.PUBLIC_PROOF_RESUME === "1"
    ? JSON.parse(await readFile("/proof/public-orders-state.json", "utf8"))
        .receipts
    : [];
await mkdir("/proof/screenshots", { recursive: true });
try {
  await adminPage.goto(`${origin}/login?returnTo=%2Fadmin%2Factions`);
  await browserLogin(admin, adminPage, "/admin/actions");
  let configuration = await configureDeliveryDemo(
    admin.request,
    origin,
    golden,
  );
  const repeated = await configureDeliveryDemo(admin.request, origin, golden);
  assert.deepEqual(repeated, configuration, "Demo configuration is idempotent");
  console.log("Demo: six December windows configured idempotently");
  const aliases = await json(
    await admin.request.get(`${api}/redirect-aliases`),
  );
  let alias = aliases.items.find((item) => item.alias === "lieferpruefung");
  if (!alias) {
    const created = await json(
      await admin.request.post(`${api}/redirect-aliases`, {
        headers,
        data: {
          alias: "lieferpruefung",
          aliasId: randomUUID(),
          commandId: randomUUID(),
          enabled: true,
        },
      }),
      200,
    );
    alias = created;
  }
  assert.ok(alias);
  // Both renderers share the Core ordering alias; the extra redirect exercises
  // CMS routing while the primary alias remains on the legacy renderer.
  const paths = [
    "/krapfentaxi",
    "/campaigns/krapfentaxi-2026/",
    "/lieferpruefung",
  ];
  let nextOrderAt = 0;
  const admitNext = async () => {
    await delay(Math.max(0, nextOrderAt - Date.now()));
    nextOrderAt = Date.now() + 125000;
  };
  for (const [routeIndex, path] of paths.entries()) {
    for (const javaScriptEnabled of [true, false]) {
      const label = `public-${routeIndex}-${javaScriptEnabled ? "js" : "native"}`;
      if (receipts.some((receipt) => receipt.label === label)) {
        console.log(`${label}: retaining earlier verified receipt`);
        continue;
      }
      const context = await browser.newContext({
        javaScriptEnabled,
        viewport: { width: 499, height: 1000 },
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      try {
        const staleScenario =
          (routeIndex === 0 && javaScriptEnabled) ||
          (routeIndex === 1 && !javaScriptEnabled);
        let temporaryWindow;
        if (staleScenario) {
          configuration = await json(
            await admin.request.get(`${api}/delivery-configuration`),
          );
          const previousIds = new Set(
            configuration.windows.map((window) => window.id),
          );
          configuration = await json(
            await admin.request.put(`${api}/delivery-configuration`, {
              headers,
              data: {
                expectedRevision: configuration.revision,
                enabled: true,
                timezone: configuration.timezone,
                windows: [
                  ...configuration.windows,
                  {
                    deliveryOn: "2026-12-06",
                    startsAt: "16:00",
                    endsAt: "18:00",
                  },
                ],
              },
            }),
          );
          temporaryWindow = configuration.windows.find(
            (window) => !previousIds.has(window.id),
          );
          assert.ok(temporaryWindow);
        }
        console.log(`${label}: opening ${path}`);
        const entered = await page.goto(publicOrigin + path);
        assert.equal(entered.status(), 200);
        const form = page.locator("[data-order-form]");
        await expect(form).toBeVisible();
        assert.equal(await form.getAttribute("data-action-id"), golden);
        await expect(form.locator('[name="deliveryWindowId"]')).toHaveCount(
          staleScenario ? 7 : 6,
        );
        await expect(
          form.locator('[name="deliveryWindowId"]:checked'),
        ).toHaveCount(0);
        const fields = {
          companyName: "Musterwerk GmbH",
          givenName: "Synthetic",
          familyName: "Lieferprüfung",
          email: `${label}-${Date.now()}@leonaid.invalid`,
          phone: "+49 123 100",
          deliveryRecipientName: "Musterwerk Warenannahme",
          deliveryStreetLine1: "Lieferweg 22",
          deliveryPostalCode: "12345",
          deliveryCity: "Teststadt",
          deliveryContactName: "Test Warenannahme",
          deliveryContactPhone: "+49 123 / 456",
        };
        for (const [name, value] of Object.entries(fields))
          await form.locator(`[name="${name}"]`).fill(value);
        await form.locator('[name="billingSameAsDelivery"]').uncheck();
        for (const [name, value] of Object.entries({
          invoiceRecipientName: "Musterwerk Rechnung",
          invoiceStreetLine1: "Rechnungsweg 11",
          invoicePostalCode: "12345",
          invoiceCity: "Teststadt",
          invoiceEmail: fields.email,
        }))
          await form.locator(`[name="${name}"]`).fill(value);
        const chosen = configuration.windows.filter(
          (window) => !window.retired,
        )[routeIndex];
        await form
          .locator(`[name="deliveryWindowId"][value="${chosen.id}"]`)
          .check();
        for (const name of ["privacyAcknowledged", "bindingOrderConfirmed"]) {
          const control = form.locator(`[name="${name}"]`);
          await control.evaluate((element) =>
            element.scrollIntoView({ behavior: "instant", block: "center" }),
          );
          await control.check();
        }
        if (temporaryWindow) {
          await form
            .locator(`[name="deliveryWindowId"][value="${temporaryWindow.id}"]`)
            .check();
          const previousCommand = await form
            .locator('[name="commandId"]')
            .inputValue();
          configuration = await json(
            await admin.request.put(`${api}/delivery-configuration`, {
              headers,
              data: {
                expectedRevision: configuration.revision,
                enabled: true,
                timezone: configuration.timezone,
                windows: configuration.windows.map((window) => ({
                  ...window,
                  retired: window.retired || window.id === temporaryWindow.id,
                })),
              },
            }),
          );
          await admitNext();
          const submit = form.locator("[data-order-submit]");
          await submit.evaluate((element) =>
            element.scrollIntoView({ behavior: "instant", block: "center" }),
          );
          if (javaScriptEnabled) await submit.click();
          else {
            await submit.focus();
            await submit.press("Enter");
          }
          await expect(form.locator("[data-form-message]")).toContainText(
            "Lieferfenster",
            { timeout: 30000 },
          );
          await expect(form.locator('[name="deliveryWindowId"]')).toHaveCount(
            6,
          );
          await expect(
            form.locator('[name="deliveryWindowId"]:checked'),
          ).toHaveCount(0);
          for (const [name, value] of Object.entries(fields))
            await expect(form.locator(`[name="${name}"]`)).toHaveValue(value);
          await expect(form.locator('[name="invoiceStreetLine1"]')).toHaveValue(
            "Rechnungsweg 11",
          );
          await expect(form.locator('[name="commandId"]')).toHaveValue(
            previousCommand,
          );
          const failedOrders = await json(
            await admin.request.get(`${api}/commitments`),
          );
          assert.equal(
            failedOrders.items.filter(
              (item) => item.commitment.buyer.email === fields.email,
            ).length,
            0,
          );
          await form
            .locator(`[name="deliveryWindowId"][value="${chosen.id}"]`)
            .check();
          // Native error redisplay deliberately requires renewed consent.
          for (const name of ["privacyAcknowledged", "bindingOrderConfirmed"]) {
            const control = form.locator(`[name="${name}"]`);
            await control.evaluate((element) =>
              element.scrollIntoView({ behavior: "instant", block: "center" }),
            );
            await control.check();
          }
          console.log(
            `${label}: actual retirement rejected, all inputs retained, valid window selected`,
          );
        }
        if (javaScriptEnabled && routeIndex < 2) {
          for (const [suffix, width, size] of [
            ["desktop", 1440, 100],
            ["mobile", 390, 100],
            ["user-499", 499, 100],
            ["text-200", 780, 200],
          ]) {
            await page.setViewportSize({ width, height: 1000 });
            await page.evaluate((size) => {
              document.documentElement.style.fontSize = `${size}%`;
              document.activeElement?.blur();
              window.scrollTo({ top: 0, behavior: "instant" });
            }, size);
            await page.screenshot({
              path: `/proof/screenshots/${label}-${suffix}.png`,
              fullPage: true,
            });
            await form.locator(".order-delivery-details").screenshot({
              path: `/proof/screenshots/${label}-delivery-${suffix}.png`,
            });
            assert.ok(
              await page.evaluate(
                () => document.documentElement.scrollWidth <= innerWidth + 1,
              ),
              `${label}-${suffix} overflow`,
            );
            assert.equal(
              await page.evaluate(
                () => getComputedStyle(document.documentElement).scrollbarWidth,
              ),
              "none",
            );
          }
          await page.keyboard.press("PageDown");
          await expect
            .poll(() => page.evaluate(() => scrollY))
            .toBeGreaterThan(0);
          await page.evaluate(
            () => (document.documentElement.style.fontSize = "100%"),
          );
        }
        const commandId = await form.locator('[name="commandId"]').inputValue();
        const retry = await form.evaluate((element) => ({
          action: element.action,
          entries: [...new FormData(element).entries()],
        }));
        // Stay inside the unchanged per-client admission window; no limiter
        // reset, forwarded headers, or synthetic user-agent rotation.
        await admitNext();
        const submit = form.locator("[data-order-submit]");
        await submit.evaluate((element) =>
          element.scrollIntoView({ behavior: "instant", block: "center" }),
        );
        if (javaScriptEnabled) await submit.click();
        else {
          await submit.focus();
          await submit.press("Enter");
        }
        await expect(page.locator("[data-order-success]:visible")).toBeVisible({
          timeout: 30000,
        });
        const orders = await json(
          await admin.request.get(`${api}/commitments`),
        );
        const order = orders.items
          .map((item) => item.commitment)
          .find((item) => item.buyer.email === fields.email);
        assert.ok(order, `${label}: persisted order missing`);
        assert.equal(order.deliveryWindowId, chosen.id);
        assert.equal(
          order.deliveryRecipient.streetLine1,
          fields.deliveryStreetLine1,
        );
        assert.equal(order.invoiceRecipient.streetLine1, "Rechnungsweg 11");
        assert.deepEqual(order.deliveryContact, {
          name: fields.deliveryContactName,
          phone: fields.deliveryContactPhone,
        });
        assert.equal(order.deliveryWindowSnapshot.timezone, "Europe/Berlin");
        // Native action replay uses the identical command and body, and is
        // served from the receipt without another order or CRM side effect.
        const replayStatus = await page.evaluate(
          async ({ action, entries }) => {
            const response = await fetch(action, {
              method: "POST",
              headers: { "Content-Type": "application/x-www-form-urlencoded" },
              body: new URLSearchParams(entries).toString(),
            });
            return response.status;
          },
          retry,
        );
        assert.equal(replayStatus, 200);
        const again = await json(await admin.request.get(`${api}/commitments`));
        assert.equal(
          again.items.filter(
            (item) => item.commitment.buyer.email === fields.email,
          ).length,
          1,
        );
        receipts.push({
          label,
          path,
          commandId,
          orderId: order.id,
          windowId: chosen.id,
        });
        await writeFile(
          "/proof/public-orders-state.json",
          JSON.stringify(
            { actionId: golden, configuration, receipts },
            null,
            2,
          ),
        );
        assert.deepEqual(errors, []);
        console.log(
          `${label} PASS: real order, separate address/contact, window snapshot, stable replay, ${path}`,
        );
      } catch (error) {
        await page.screenshot({
          path: `/proof/screenshots/${label}-failure.png`,
        });
        console.error(
          await page.locator("[data-form-message]").allTextContents(),
        );
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  console.log(
    "KLF-060 public browser PASS: legacy, CMS canonical and redirect alias, each with JavaScript and native POST; real Core/Mailpit/Twenty",
  );
  const anna = await browser.newContext();
  const annaPage = await anna.newPage();
  await annaPage.goto(`${origin}/login?returnTo=%2Fapp%2F`);
  await browserLogin(
    anna,
    annaPage,
    "/app/",
    false,
    "anna.akquise@leonaid.invalid",
  );
  await annaPage.goto(`${origin}/app/commitments/new?action=${golden}`);
  const customers = annaPage.getByTestId("commitment-sponsor");
  const option = customers
    .locator("option")
    .filter({ hasText: "Musterwerk GmbH" });
  await expect(option).toHaveCount(1);
  await customers.selectOption(await option.getAttribute("value"));
  await expect(annaPage.locator("#commitment-recipient-name")).toHaveValue(
    "Musterwerk GmbH",
  );
  await annaPage.locator("#commitment-street").fill("Rechnungsweg 11");
  await annaPage.locator("#commitment-postal-code").fill("12345");
  await annaPage.locator("#commitment-city").fill("Teststadt");
  await annaPage
    .getByRole("button", {
      name: "Lieferadresse wie Rechnungsadresse übernehmen",
      exact: true,
    })
    .click();
  await annaPage
    .getByLabel("Lieferempfänger", { exact: true })
    .fill("Musterwerk Warenannahme");
  await annaPage
    .getByLabel("Straße und Hausnummer für die Lieferung", { exact: true })
    .fill("Lieferweg 22");
  await annaPage
    .getByLabel("Ansprechpartner bei der Lieferung (optional)", { exact: true })
    .fill("Test Warenannahme");
  await annaPage
    .getByLabel("Telefonnummer für die Lieferung (optional)", { exact: true })
    .fill("+49 123 / 456");
  const first = configuration.windows.find((window) => !window.retired);
  await expect(annaPage.locator('input[name="delivery-window"]')).toHaveCount(
    6,
  );
  await annaPage.locator(`input[value="${first.id}"]`).check();
  const [createdResponse] = await Promise.all([
    annaPage.waitForResponse(
      (response) =>
        response.url() === `${api}/commitments` &&
        response.request().method() === "POST",
    ),
    annaPage.getByTestId("commitment-save-ready").click(),
  ]);
  const internal = await json(createdResponse, 201);
  assert.equal(internal.deliveryRecipient.streetLine1, "Lieferweg 22");
  assert.equal(internal.invoiceRecipient.streetLine1, "Rechnungsweg 11");
  assert.deepEqual(internal.deliveryContact, {
    name: "Test Warenannahme",
    phone: "+49 123 / 456",
  });
  assert.equal(internal.deliveryWindowId, first.id);
  receipts.push({
    label: "anna-demo",
    orderId: internal.id,
    windowId: first.id,
  });
  await writeFile(
    "/proof/public-orders-state.json",
    JSON.stringify({ actionId: golden, configuration, receipts }, null, 2),
  );
  console.log(
    "KLF-070 Anna demo PASS: same six December windows and same delivery fields as both public renderers",
  );
} finally {
  await browser.close();
}
