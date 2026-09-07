import assert from "node:assert/strict";
import { chromium, firefox, webkit } from "playwright";

const campaign = process.argv.includes("--campaign");
const pagePath = campaign ? "/campaigns/krapfentaxi-2026/" : "/krapfentaxi";

// Real public Astro + Core. This fixture intentionally has no CRM credentials:
// prove form rendering/validation and failure UX, never claim accepted orders.
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const javaScriptEnabled of [false, true]) {
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        javaScriptEnabled,
        viewport: { width: javaScriptEnabled ? 1280 : 390, height: 900 },
      });
      const page = await context.newPage();
      const response = await page.goto(`https://proxy:8443${pagePath}`);
      assert.equal(response.status(), 200);
      assert.match(response.headers()["cache-control"], /no-store/);
      const form = page.locator("[data-order-form]");
      await form.waitFor();
      assert.equal(await form.count(), 1);
      assert.equal(
        await form.locator('[name="publicAlias"]').inputValue(),
        "krapfentaxi",
      );
      assert.ok(
        (await form.locator('[name="accessToken"]').inputValue()).length >= 32,
      );
      assert.equal(await page.locator("h1").count(), 1);
      for (const [field, value] of Object.entries({
        companyName: "Synthetic Form Proof",
        givenName: "Synthetic",
        familyName: "Order",
        email: "form-proof@leonaid.invalid",
        phone: "+49 821 123456",
        deliveryRecipientName: "Synthetic Form Proof",
        deliveryStreetLine1: "Testweg 1",
        deliveryPostalCode: "86150",
        deliveryCity: "Augsburg",
      }))
        await form.locator(`[name="${field}"]`).fill(value);
      await form.locator('[name="privacyAcknowledged"]').check();
      await form.locator('[name="bindingOrderConfirmed"]').check();
      assert.equal(
        await form.evaluate((element) => element.checkValidity()),
        true,
      );
      const submitted = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname ===
            (javaScriptEnabled ? "/_actions/createPublicOrder/" : pagePath),
      );
      await form.locator('[type="submit"]').click();
      const submission = await submitted;
      assert.equal(submission.request().redirectedFrom(), null);
      await page.locator('[data-form-message][data-state="error"]').waitFor();
      assert.equal(
        (await page.locator("[data-form-message]").textContent()).trim(),
        "Das Bestellformular ist vorübergehend nicht verfügbar.",
      );
      assert.equal(await page.locator("[data-order-form]").isVisible(), true);
      assert.equal(
        await page.locator("[data-order-success]:visible").count(),
        0,
      );
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
      assert.equal((await context.cookies()).length, 0);
      assert.equal(new URL(page.url()).pathname, pagePath);
      if (javaScriptEnabled) {
        assert.equal(
          await form.locator('[name="email"]').inputValue(),
          "form-proof@leonaid.invalid",
        );
        await page.screenshot({
          path: `/visual-proof/${campaign ? "campaign-" : ""}order-${name}-desktop.png`,
          fullPage: true,
        });
      } else
        await page.screenshot({
          path: `/visual-proof/${campaign ? "campaign-" : ""}order-${name}-mobile-nojs.png`,
          fullPage: true,
        });
      await context.close();
      console.log(
        `public-order-component: campaign=${campaign} ${name} JS=${javaScriptEnabled}; shared form, actual POST without redirect, real unavailable-CRM response, no false success and responsive error state passed`,
      );
    }
  } finally {
    await browser.close();
  }
}
