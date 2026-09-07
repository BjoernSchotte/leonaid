import assert from "node:assert/strict";
import { writeFile } from "node:fs/promises";
import { chromium, firefox, webkit } from "playwright";

const path = "/campaigns/krapfentaxi-2026/";
const orders = [];
for (const [engineName, engine] of Object.entries({
  chromium,
  firefox,
  webkit,
})) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const javaScriptEnabled of [false, true]) {
      for (const scenario of ["new-company", "existing-company", "person"]) {
        const label = `${engineName}-${javaScriptEnabled ? "js" : "native"}-${scenario}`;
        console.log(`campaign-orders: starting ${label}`);
        const context = await browser.newContext({
          ignoreHTTPSErrors: true,
          javaScriptEnabled,
          viewport: { width: javaScriptEnabled ? 1280 : 390, height: 900 },
          // Independent synthetic visitors; native replay keeps this identity.
          // Do not disable Core's five-attempt per-client admission policy.
          userAgent: `Mozilla/5.0 LeonAidCampaignProof (${label})`,
          // A browser-supplied credential must not replace the server's key.
          extraHTTPHeaders: { "X-LeonAid-Order-Key": "0".repeat(64) },
        });
        const page = await context.newPage();
        assert.equal(
          (await page.goto(`https://proxy:8443${path}`)).status(),
          200,
        );
        const form = page.locator("[data-order-form]");
        const quantity =
          scenario === "new-company" ? 2 : scenario === "person" ? 3 : 1;
        const company =
          scenario === "new-company"
            ? `Synthetic ${label} GmbH`
            : scenario === "existing-company"
              ? "Musterwerk GmbH"
              : "";
        const email = `${label}@leonaid.invalid`;
        const fields = {
          companyName: company,
          givenName: "Synthetic",
          familyName: label,
          email,
          phone: "+49 821 123456",
          deliveryRecipientName: `Synthetic ${label}`,
          deliveryStreetLine1: "Testweg 1",
          deliveryPostalCode: "86150",
          deliveryCity: "Augsburg",
          message: "Bitte am Empfang abgeben.",
        };
        // Follow the visible form order instead of jumping back to its top
        // immediately before clicking consent on a long, smoothly scrolled page.
        await form.locator('[name="quantity"]').first().fill(String(quantity));
        for (const [name, value] of Object.entries(fields))
          await form.locator(`[name="${name}"]`).fill(value);
        try {
          // Establish the viewport independently of global smooth scrolling.
          // Consent still requires an ordinary hit-tested browser click.
          await form
            .locator('[name="privacyAcknowledged"]')
            .evaluate((element) =>
              element.scrollIntoView({ behavior: "instant", block: "center" }),
            );
          await form.locator('[name="privacyAcknowledged"]').check();
        } catch (error) {
          await page.screenshot({
            path: `/visual-proof/checkbox-failure-${label}.png`,
            fullPage: true,
          });
          console.log(
            `campaign-orders: checkbox failure screenshot retained for ${label}`,
          );
          throw error;
        }
        await form.locator('[name="bindingOrderConfirmed"]').check();
        const commandId = await form.locator('[name="commandId"]').inputValue();
        const retryForm = await form.evaluate((element) => ({
          action: element.action,
          entries: [...new FormData(element).entries()],
        }));
        assert.equal(
          await form.evaluate((element) => element.checkValidity()),
          true,
        );
        const submitted = page.waitForResponse(
          (response) =>
            response.request().method() === "POST" &&
            new URL(response.url()).pathname ===
              (javaScriptEnabled ? "/_actions/createPublicOrder/" : path),
        );
        await form.locator('[type="submit"]').click();
        const response = await submitted;
        assert.equal(response.request().redirectedFrom(), null);
        assert.equal(
          response.status(),
          200,
          `Astro order response for ${label}`,
        );
        const success = page.locator("[data-order-success]:visible");
        await success.waitFor({ timeout: 20000 });
        const reference = (
          await success.locator("[data-order-reference]").textContent()
        ).trim();
        assert.match(reference, /^LA-[A-F0-9]{32}$/);
        assert.match(
          await success.locator("[data-order-total]").textContent(),
          new RegExp(`${quantity * 36},00`),
        );
        assert.equal(
          await page.locator("[data-order-form]:visible").count(),
          0,
        );
        let nativeReplay = false;
        if (!javaScriptEnabled) {
          // Reload is GET in Firefox. Re-submit the exact original fields via
          // the browser's native form transport, preserving duplicate names.
          // This is test-driver retry simulation, not page-side JavaScript.
          // Arm before submission: waiting for load after response headers can
          // otherwise observe the old document's already-complete load state.
          const replayNavigation = page.waitForNavigation({
            waitUntil: "load",
          });
          await page.evaluate(({ action, entries }) => {
            const retry = document.createElement("form");
            retry.method = "POST";
            retry.action = action;
            for (const [name, value] of entries) {
              const input = document.createElement("input");
              input.type = "hidden";
              input.name = name;
              input.value = value;
              retry.append(input);
            }
            document.body.append(retry);
            retry.submit();
          }, retryForm);
          const replay = await replayNavigation;
          assert.equal(replay.request().method(), "POST");
          assert.equal(replay.status(), 200);
          assert.equal(new URL(replay.url()).pathname, path);
          assert.equal(
            (await page.locator("[data-order-reference]").textContent()).trim(),
            reference,
          );
          nativeReplay = true;
        }
        assert.equal(new URL(page.url()).pathname, path);
        assert.equal((await context.cookies()).length, 0);
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          true,
        );
        await success.screenshot({
          path: `/visual-proof/accepted-${label}.png`,
        });
        orders.push({
          engineName,
          javaScriptEnabled,
          scenario,
          quantity,
          company,
          email,
          label,
          commandId,
          publicReference: reference,
          nativeReplay,
        });
        await context.close();
        console.log(
          `campaign-orders-browser: ${label}; accepted through Astro/Core, reference and total visible; nativeReplay=${nativeReplay}`,
        );
      }
    }
  } finally {
    await browser.close();
  }
}
await writeFile("/proof/orders-ui.json", JSON.stringify(orders));
