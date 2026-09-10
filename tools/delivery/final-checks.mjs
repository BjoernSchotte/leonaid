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
try {
  await adminPage.goto(`${origin}/login?returnTo=%2Fadmin%2Factions`);
  await browserLogin(admin, adminPage, "/admin/actions");
  const anonymous = await browser.newContext();
  const page = await anonymous.newPage();
  const target = "20000000-0000-4000-8000-000000000003";
  const aliasName = `lieferguard-${randomUUID().slice(0, 8)}`;
  let owner = golden;
  let alias = await json(
    await admin.request.post(`${api}/redirect-aliases`, {
      headers,
      data: {
        alias: aliasName,
        aliasId: randomUUID(),
        commandId: randomUUID(),
        enabled: true,
      },
    }),
  );
  const email = `${aliasName}@leonaid.invalid`;
  try {
    await page.goto(publicOrigin + "/" + aliasName);
    await expect(page).toHaveURL(publicOrigin + "/campaigns/krapfentaxi-2026/");
    await expect(page.locator('[name="publicAlias"]')).toHaveValue(
      "krapfentaxi",
    );
    for (const state of ["active", "disabled", "moved"]) {
      if (state !== "active") {
        alias = await json(
          await admin.request.put(
            `${origin}/api/v1/actions/${owner}/redirect-aliases/${alias.aliasId}`,
            {
              headers,
              data: {
                commandId: randomUUID(),
                revision: alias.revision,
                alias: aliasName,
                enabled: state === "moved",
                targetActionId: state === "moved" ? target : golden,
              },
            },
          ),
        );
        if (state === "moved") owner = target;
        const probe = await anonymous.newPage();
        await probe.goto(publicOrigin + "/" + aliasName);
        await expect(probe.locator("[data-order-form]")).toHaveCount(0);
        await probe.close();
      }
      // Tampered route with a real token must fail before CRM/admission. The
      // earlier canonical form remains bound to its original Core primary alias.
      const response = await page.evaluate(
        async ({ aliasName, email }) => {
          const form = document.querySelector("[data-order-form]");
          const data = new FormData(form);
          for (const [name, value] of Object.entries({
            publicAlias: aliasName,
            commandId: crypto.randomUUID(),
            companyName: "Musterwerk GmbH",
            givenName: "Synthetic",
            familyName: "Aliasprüfung",
            email,
            deliveryRecipientName: "Musterwerk Warenannahme",
            deliveryStreetLine1: "Lieferweg 22",
            deliveryPostalCode: "12345",
            deliveryCity: "Teststadt",
            deliveryWindowId: form.querySelector('[name="deliveryWindowId"]')
              .value,
            deliveryContactName: "Test Warenannahme",
            billingSameAsDelivery: "true",
            privacyAcknowledged: "true",
            bindingOrderConfirmed: "true",
          }))
            data.set(name, value);
          const result = await fetch(form.action, {
            method: "POST",
            body: data,
          });
          return { status: result.status, body: await result.text() };
        },
        { aliasName, email },
      );
      assert.ok(
        response.body.includes("Das Bestellformular ist nicht mehr gültig"),
        "Expected Core token/alias rejection",
      );
      for (const actionId of [golden, target]) {
        const orders = await json(
          await admin.request.get(
            `${origin}/api/v1/actions/${actionId}/commitments`,
          ),
        );
        assert.equal(
          orders.items.filter((item) => item.commitment.buyer.email === email)
            .length,
          0,
        );
      }
      assert.equal(
        await page.locator("[data-order-form]").getAttribute("data-action-id"),
        golden,
      );
      console.log(
        `Alias ${state} PASS: original canonical identity, tampered alias rejected, no order for either action`,
      );
    }
  } finally {
    await json(
      await admin.request.delete(
        `${origin}/api/v1/actions/${owner}/redirect-aliases/${alias.aliasId}`,
        {
          headers,
          data: { commandId: randomUUID(), revision: alias.revision },
        },
      ),
    );
  }
  // Preserve a genuinely booked historical window on the separate synthetic
  // Anna proof action, leaving all six December demo windows available.
  const historical = JSON.parse(
    await readFile("/proof/orders-state.json", "utf8"),
  );
  const oldApi = `${origin}/api/v1/actions/${historical.actionId}`;
  const before = await json(
    await admin.request.get(`${oldApi}/commitments/${historical.orderId}`),
  );
  const config = await json(
    await admin.request.get(`${oldApi}/delivery-configuration`),
  );
  if (
    !config.windows.find((window) => window.id === before.deliveryWindowId)
      .retired
  ) {
    await json(
      await admin.request.put(`${oldApi}/delivery-configuration`, {
        headers,
        data: {
          expectedRevision: config.revision,
          enabled: true,
          timezone: config.timezone,
          windows: config.windows.map((window) => ({
            ...window,
            retired: window.retired || window.id === before.deliveryWindowId,
          })),
        },
      }),
    );
  }
  assert.deepEqual(
    await json(
      await admin.request.get(`${oldApi}/commitments/${historical.orderId}`),
    ),
    before,
  );
  await writeFile(
    "/proof/historical-order-state.json",
    JSON.stringify({
      actionId: historical.actionId,
      orderId: before.id,
      windowId: before.deliveryWindowId,
    }),
  );
  console.log(
    "Historical order PASS: booked window retired through normal API, persisted order and snapshots unchanged",
  );
} finally {
  await browser.close();
}
