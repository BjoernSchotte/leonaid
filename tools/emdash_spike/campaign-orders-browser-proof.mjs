import assert from "node:assert/strict";
import { readdir, writeFile } from "node:fs/promises";
import { chromium, firefox, webkit } from "playwright";

const path = "/campaigns/krapfentaxi-2026/";
const orders = [];
const burst = process.argv.includes("--burst");
const imported = process.argv.includes("--imported");
const beforeRecovery = process.argv.includes("--before-recovery");
const afterRecovery = process.argv.includes("--after-recovery");
assert.ok(!(beforeRecovery && afterRecovery));
assert.ok(!(burst && (beforeRecovery || afterRecovery)));
if (beforeRecovery || afterRecovery) {
  assert.ok(
    (await readdir("/proof")).every((name) => name === "orders-ui.json"),
    "Recovery browser must receive only its receipt directory, not operator secrets",
  );
}
const recoveryPrefix = beforeRecovery
  ? "before-recovery-"
  : afterRecovery
    ? "after-recovery-"
    : "";
let timedOutOrders = 0;
// Functional acceptance, not a burst/load test: each order performs several
// CRM requests under Core's unchanged 100 requests/minute limiter. Keep these
// synthetic visitors eight seconds apart; deadline/load behaviour is a separate
// required gate, including the observed unpaced 18th-order failure.
let nextOrderAt = 0;
for (const [engineName, engine] of Object.entries({
  chromium,
  firefox,
  webkit,
})) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const javaScriptEnabled of [false, true]) {
      for (const scenario of [
        "new-company",
        "existing-company",
        "person",
        "mixed",
      ]) {
        const label = `${recoveryPrefix}${burst ? "burst-" : ""}${engineName}-${javaScriptEnabled ? "js" : "native"}-${scenario}`;
        if (!burst)
          await new Promise((resolve) =>
            setTimeout(resolve, Math.max(0, nextOrderAt - Date.now())),
          );
        nextOrderAt = Date.now() + 8000;
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
        if (imported) {
          assert.equal(
            await page.locator("body").getAttribute("class"),
            "taxi-site",
          );
          assert.equal(
            await page
              .getByRole("heading", {
                name: "Published imported campaign webkit",
                exact: true,
              })
              .count(),
            1,
          );
          assert.ok(
            !(await page.locator("body").textContent()).includes(
              "Private follow-up webkit",
            ),
          );
          assert.equal(await page.locator("[data-order-form]").count(), 1);
        }
        const form = page.locator("[data-order-form]");
        const quantity =
          scenario === "new-company"
            ? 2
            : ["person", "mixed"].includes(scenario)
              ? 3
              : 1;
        const company = ["new-company", "mixed"].includes(scenario)
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
        if (scenario === "mixed") {
          for (const [index, value] of [3, 2, 4, 1].entries()) {
            await form
              .locator('[name="quantity"]')
              .nth(index)
              .fill(String(value));
          }
        }
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
        const submissionStartedAt = Date.now();
        await form.locator('[type="submit"]').click();
        const response = await submitted;
        const responseElapsed = Date.now() - submissionStartedAt;
        console.log(
          `campaign-orders: ${label}; Astro response after ${responseElapsed}ms`,
        );
        assert.equal(response.request().redirectedFrom(), null);
        if (response.status() === 503)
          assert.ok(
            burst && javaScriptEnabled,
            `Unexpected Astro failure for ${label}`,
          );
        else
          assert.equal(
            response.status(),
            200,
            `Astro order response for ${label}`,
          );
        const success = page.locator("[data-order-success]:visible");
        if (burst) {
          const error = page.locator(
            '[data-form-message][data-state="error"]:visible',
          );
          await success.or(error).first().waitFor({ timeout: 15000 });
          if (await error.isVisible()) {
            // The Core processing deadline, not Astro's transport timeout or
            // an arbitrary validation failure, must be visible to the visitor.
            assert.match(
              await error.textContent(),
              /Die Verarbeitung dauert gerade zu lange/,
            );
            assert.ok(responseElapsed >= 7500 && responseElapsed < 11000);
            assert.equal(response.status(), javaScriptEnabled ? 503 : 200);
            await error.screenshot({
              path: `/visual-proof/timeout-${label}.png`,
            });
            assert.equal(
              await form.locator('[name="commandId"]').inputValue(),
              commandId,
            );
            for (const [name, value] of Object.entries(fields))
              assert.equal(
                await form.locator(`[name="${name}"]`).inputValue(),
                value,
              );
            timedOutOrders += 1;
            console.log(
              `campaign-orders: ${label}; bounded Core deadline observed, retrying the unchanged command after CRM window recovery`,
            );
            await new Promise((resolve) => setTimeout(resolve, 45000));
            await form
              .locator('[name="privacyAcknowledged"]')
              .evaluate((element) =>
                element.scrollIntoView({
                  behavior: "instant",
                  block: "center",
                }),
              );
            await form.locator('[name="privacyAcknowledged"]').check();
            await form.locator('[name="bindingOrderConfirmed"]').check();
            const retried = page.waitForResponse(
              (reply) =>
                reply.request().method() === "POST" &&
                new URL(reply.url()).pathname ===
                  (javaScriptEnabled ? "/_actions/createPublicOrder/" : path),
            );
            await form.locator('[type="submit"]').click();
            assert.equal((await retried).status(), 200);
          }
        }
        try {
          await success.waitFor({ timeout: 20000 });
        } catch (error) {
          await page.screenshot({
            path: `/visual-proof/order-failure-${label}.png`,
            fullPage: true,
          });
          console.log(
            `campaign-orders: failure screenshot retained for ${label}`,
          );
          throw error;
        }
        const reference = (
          await success.locator("[data-order-reference]").textContent()
        ).trim();
        assert.match(reference, /^LA-[A-F0-9]{32}$/);
        assert.match(
          await success.locator("[data-order-total]").textContent(),
          new RegExp(`${scenario === "mixed" ? 115 : quantity * 36},00`),
        );
        const expectedQuantity =
          scenario === "mixed"
            ? "3 Boxen (72 Stück) · 2 Pakete · 4 Stück · 1 Sponsoring"
            : `${quantity} ${quantity === 1 ? "Box" : "Boxen"} (${quantity * 24} Stück)`;
        assert.equal(
          (await success.locator("[data-order-quantity]").textContent()).trim(),
          expectedQuantity,
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
          assert.equal(
            (await page.locator("[data-order-quantity]").textContent()).trim(),
            expectedQuantity,
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
if (burst)
  assert.ok(
    timedOutOrders > 0,
    "Burst must exercise actual deadline recovery, not just successful requests",
  );
await writeFile("/proof/orders-ui.json", JSON.stringify(orders));
