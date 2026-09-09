import assert from "node:assert/strict";
// Decode real RPC receipts with the installed Astro implementation, not a
// hand-written approximation of its devalue wire format.
import { deserializeActionResult } from "../../node_modules/astro/dist/actions/runtime/client.js";
import { readdir, writeFile } from "node:fs/promises";
import { chromium, firefox, webkit } from "playwright";
import {
  deadlineSignal,
  deadlineWait,
} from "./native-order-deadline-control.mjs";

async function checkConsents(page, form, label) {
  try {
    for (const name of ["privacyAcknowledged", "bindingOrderConfirmed"]) {
      const checkbox = form.locator(`[name="${name}"]`);
      // Position each control independently on the long, smoothly scrolled
      // page. The consent itself still requires an ordinary hit-tested click.
      await checkbox.evaluate((element) =>
        element.scrollIntoView({ behavior: "instant", block: "center" }),
      );
      await checkbox.check();
      assert.equal(await checkbox.isChecked(), true);
    }
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
}

const legacyEntry = process.argv.includes("--legacy-entry");
const primaryAlias = process.argv.includes("--primary-alias");
const postCutover = process.argv.includes("--after-cutover");
assert.ok(!(legacyEntry && primaryAlias));
const path = legacyEntry ? "/krapfentaxi" : "/campaigns/krapfentaxi-2026/";
const orders = [];
assert.ok(!process.argv.includes("--burst"), "Stress mode is not supported");
const imported = process.argv.includes("--imported");
const partialCrm = process.argv.includes("--partial-crm");
const scriptDeadline = process.argv.includes("--script-deadline");
assert.ok(
  [
    partialCrm,
    scriptDeadline,
    process.argv.includes("--native-deadline"),
  ].filter(Boolean).length <= 1,
);
const controlledDeadline =
  process.argv.includes("--native-deadline") || partialCrm || scriptDeadline;
const beforeRecovery = process.argv.includes("--before-recovery");
const afterRecovery = process.argv.includes("--after-recovery");
const afterRollback = process.argv.includes("--after-rollback");
assert.ok(
  [beforeRecovery, afterRecovery, afterRollback].filter(Boolean).length <= 1,
);
assert.ok(!postCutover || (imported && afterRecovery && primaryAlias));
assert.ok(!legacyEntry || afterRollback);
assert.ok(
  !controlledDeadline ||
    (imported &&
      !beforeRecovery &&
      !afterRecovery &&
      !afterRollback &&
      !postCutover &&
      !legacyEntry &&
      !primaryAlias),
);
if (beforeRecovery || afterRecovery || afterRollback) {
  assert.ok(
    (await readdir("/proof")).every((name) => name === "orders-ui.json"),
    "Recovery browser must receive only its receipt directory, not operator secrets",
  );
}
const recoveryPrefix = beforeRecovery
  ? "before-recovery-"
  : afterRecovery
    ? "after-recovery-"
    : afterRollback
      ? "after-rollback-"
      : "";
let timedOutOrders = 0;
// Functional acceptance, not a burst/load test: each order performs several
// CRM requests under Core's unchanged 100 requests/minute limiter. Keep these
// synthetic visitors eight seconds apart. Targeted real SQL locks exercise
// deadline recovery separately, without deliberately exhausting CRM capacity.
let nextOrderAt = 0;
for (const [engineName, engine] of Object.entries({
  chromium,
  firefox,
  webkit,
})) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const javaScriptEnabled of controlledDeadline
      ? [scriptDeadline]
      : [false, true]) {
      for (const scenario of controlledDeadline
        ? [partialCrm ? "new-company" : "person"]
        : ["new-company", "existing-company", "person", "mixed"]) {
        const label = `${partialCrm ? "partial-" : controlledDeadline ? "deadline-" : ""}${recoveryPrefix}${engineName}-${javaScriptEnabled ? "js" : "native"}-${scenario}`;
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
        const entered = await page.goto(
          `https://proxy:8443${primaryAlias ? "/krapfentaxi" : path}`,
        );
        assert.equal(entered.status(), 200);
        if (primaryAlias) {
          assert.equal(page.url(), `https://proxy:8443${path}`);
          const redirected = entered.request().redirectedFrom();
          assert.ok(redirected);
          assert.equal(redirected.url(), "https://proxy:8443/krapfentaxi");
          assert.equal(redirected.redirectedFrom(), null);
        }
        if (imported) {
          assert.equal(
            await page.locator("body").getAttribute("class"),
            "taxi-site",
          );
          assert.equal(
            await page
              .getByRole("heading", {
                name: postCutover
                  ? "Published after recovery point"
                  : "Published imported campaign webkit",
                exact: true,
              })
              .count(),
            1,
          );
          assert.ok(
            !(await page.locator("body").textContent()).includes(
              postCutover
                ? "Private after recovery point"
                : "Private follow-up webkit",
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
        await checkConsents(page, form, label);
        const commandId = await form.locator('[name="commandId"]').inputValue();
        const retryForm = await form.evaluate((element) => ({
          action: element.action,
          entries: [...new FormData(element).entries()],
        }));
        assert.equal(
          await form.evaluate((element) => element.checkValidity()),
          true,
        );
        if (partialCrm) await deadlineSignal(label, "submitted", { commandId });
        if (controlledDeadline) await deadlineWait(label, "locked");
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
        assert.equal(
          response.status(),
          scriptDeadline ? 503 : 200,
          `Astro order response for ${label}`,
        );
        let acceptedActionData;
        const success = page.locator("[data-order-success]:visible");
        if (controlledDeadline) {
          const error = page.locator(
            '[data-form-message][data-state="error"]:visible',
          );
          await success.or(error).first().waitFor({ timeout: 15000 });
          if (controlledDeadline)
            assert.ok(
              await error.isVisible(),
              "Real locked order must show its bounded timeout",
            );
          if (await error.isVisible()) {
            // Require the exact expected deadline: Core processing for the
            // party lock, or the existing CRM write transport timeout for a
            // partially committed company/contact operation. Never accept an
            // arbitrary validation error or extend either production budget.
            assert.match(
              await error.textContent(),
              partialCrm
                ? /Twenty hat nicht innerhalb des konfigurierten Timeouts geantwortet\./
                : /Die Verarbeitung dauert gerade zu lange/,
            );
            assert.ok(
              responseElapsed >= (partialCrm ? 4500 : 7500) &&
                responseElapsed < 11000,
            );
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
            assert.equal(
              await form.locator('[name="quantity"]').first().inputValue(),
              String(quantity),
            );
            timedOutOrders += 1;
            console.log(
              `campaign-orders: ${label}; bounded ${partialCrm ? "CRM write" : "Core"} deadline observed, retrying the unchanged command after verified SQL lock release`,
            );
            await deadlineSignal(label, "timeout");
            await deadlineWait(label, "released");
            await checkConsents(page, form, `${label}-retry`);
            const retried = page.waitForResponse(
              (reply) =>
                reply.request().method() === "POST" &&
                new URL(reply.url()).pathname ===
                  (javaScriptEnabled ? "/_actions/createPublicOrder/" : path),
            );
            await form.locator('[type="submit"]').click();
            const acceptedResponse = await retried;
            assert.equal(acceptedResponse.status(), 200);
            if (scriptDeadline) {
              const decoded = deserializeActionResult({
                type: "data",
                status: 200,
                body: await acceptedResponse.text(),
              });
              assert.equal(decoded.error, undefined);
              acceptedActionData = decoded.data;
              assert.equal(acceptedActionData.replayed, false);
            }
          }
        }
        try {
          await success.waitFor({ timeout: 20000 });
        } catch (error) {
          // Classify only fixed public errors. Never print arbitrary page text,
          // submitted fields, response bodies, tokens or CRM diagnostics.
          const failureText = await page
            .locator('[data-form-message][data-state="error"]:visible')
            .allTextContents();
          const publicFailure = failureText.join(" ");
          const classification = publicFailure.includes(
            "Twenty hat nicht innerhalb des konfigurierten Timeouts geantwortet.",
          )
            ? "crm-timeout"
            : publicFailure.includes("Twenty hat das Anfrage-Limit erreicht.")
              ? "crm-rate-limit"
              : publicFailure.includes(
                    "Die Verarbeitung dauert gerade zu lange",
                  )
                ? "core-processing-deadline"
                : failureText.length
                  ? "other-public-error"
                  : "missing-success-without-public-error";
          console.log(
            `campaign-orders: ${label}; failure=${classification}; status=${response.status()}; responseMs=${responseElapsed}`,
          );
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
        if (controlledDeadline) {
          await deadlineSignal(label, "accepted", { commandId, reference });
          await deadlineWait(label, "replay-ready");
        }
        if (!javaScriptEnabled) {
          // Reload is GET in Firefox. Re-submit the exact original fields via
          // the browser's native form transport, preserving duplicate names.
          // This is test-driver retry simulation, not page-side JavaScript.
          // Arm before submission to bind to the new document. Order replay
          // asserts the response and its receipt DOM below, not the load event
          // of unrelated images/fonts; media rendering has separate live gates.
          const replayNavigation = page.waitForNavigation({
            waitUntil: "domcontentloaded",
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
          await success.waitFor({ timeout: 20000 });
          assert.equal(
            await page.locator("[data-order-form]:visible").count(),
            0,
          );
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
        if (scriptDeadline) {
          // Repeat the real enhanced request through the browser fetch stack.
          // Preserve its original multipart bytes/boundary and command ID; do
          // not reconstruct a privileged Core call or inject a server result.
          const body = response.request().postData();
          const contentType = response.request().headers()["content-type"];
          assert.ok(body && contentType);
          assert.equal(acceptedActionData.publicReference, reference);
          const replay = await page.evaluate(
            async ({ url, body, contentType }) => {
              const reply = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": contentType },
                body,
                redirect: "error",
                signal: AbortSignal.timeout(11000),
              });
              return {
                status: reply.status,
                body: await reply.text(),
                cacheControl: reply.headers.get("cache-control"),
              };
            },
            { url: response.url(), body, contentType },
          );
          assert.equal(replay.status, 200);
          assert.equal(replay.cacheControl, "no-store");
          const decoded = deserializeActionResult({
            type: "data",
            status: replay.status,
            body: replay.body,
          });
          assert.equal(decoded.error, undefined);
          assert.equal(decoded.data.replayed, true);
          assert.deepEqual(
            { ...decoded.data, replayed: false },
            acceptedActionData,
          );
          console.log(
            `campaign-orders: ${label}; exact enhanced RPC replay passed`,
          );
        }
        if (controlledDeadline) {
          await deadlineSignal(label, "replayed");
          await deadlineWait(label, "verified");
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
if (controlledDeadline) assert.equal(timedOutOrders, 3);
await writeFile("/proof/orders-ui.json", JSON.stringify(orders));
