import assert from "node:assert/strict";
import { createHash, X509Certificate, randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";
import { expect } from "@playwright/test";
import { browserLogin } from "../emdash_spike/browser-login.mjs";

const origin = "https://proxy:8443";
const golden = "20000000-0000-4000-8000-000000000001";
const anna = "10000000-0000-4000-8000-000000000004";
const system = "10000000-0000-4000-8000-000000000001";
const certificate = new X509Certificate(await readFile("/proof/server.crt"));
const pin = createHash("sha256")
  .update(certificate.publicKey.export({ type: "spki", format: "der" }))
  .digest("base64");
const browser = await chromium.launch({
  args: [`--ignore-certificate-errors-spki-list=${pin}`],
});
const admin = await browser.newContext({
  viewport: { width: 1440, height: 1050 },
});
const customer = await browser.newContext({
  viewport: { width: 1440, height: 1050 },
});
const managerPage = await admin.newPage();
const page = await customer.newPage();
const errors = [];
for (const target of [managerPage, page])
  target.on("pageerror", (error) => errors.push(error.message));
await mkdir("/proof/screenshots", { recursive: true });
async function json(response, status = 200) {
  assert.equal(response.status(), status, await response.text());
  return response.json();
}
const headers = { Origin: origin };
async function captureState(target, stem) {
  for (const [name, width] of [
    ["desktop", 1440],
    ["mobile", 390],
  ]) {
    await target.setViewportSize({ width, height: 1050 });
    await target.evaluate(() => {
      document.activeElement?.blur();
      window.scrollTo({ top: 0, behavior: "instant" });
    });
    assert.ok(
      await target.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      `${stem}-${name}: overflow`,
    );
    await target.screenshot({
      path: `/proof/screenshots/${stem}-${name}.png`,
      fullPage: true,
    });
  }
  await target.setViewportSize({ width: 1440, height: 1050 });
}
try {
  await managerPage.goto(`${origin}/login?returnTo=%2Fadmin%2Factions`);
  await browserLogin(admin, managerPage, "/admin/actions");
  const copied = await json(
    await admin.request.post(`${origin}/api/v1/actions/${golden}/copies`, {
      headers,
      data: {
        name: "Krapfentaxi – Kundenbestellung Lieferprüfung",
        startsOn: "2037-12-01",
        endsOn: "2037-12-31",
        archiveSlug: `delivery-orders-${Date.now()}`,
      },
    }),
    201,
  );
  const action = copied.action;
  const api = `${origin}/api/v1/actions/${action.id}`;
  for (const [id, role] of [
    [anna, "acquirer"],
    [system, "charity_admin"],
  ]) {
    const member = await json(
      await admin.request.get(`${origin}/api/v1/admin/members/${id}`),
    );
    if (
      !member.actionMemberships.some(
        (item) => item.actionId === action.id && item.role === role,
      )
    ) {
      await json(
        await admin.request.patch(
          `${origin}/api/v1/admin/members/${id}/actions/${action.id}/roles/${role}`,
          {
            headers: {
              ...headers,
              "Idempotency-Key": `delivery-role:${randomUUID()}`,
            },
            data: { expectedRevision: member.revision, enabled: true },
          },
        ),
      );
    }
  }
  let configuration = await json(
    await admin.request.get(`${api}/delivery-configuration`),
  );
  configuration = await json(
    await admin.request.put(`${api}/delivery-configuration`, {
      headers,
      data: {
        expectedRevision: configuration.revision,
        enabled: true,
        timezone: "Europe/Berlin",
        windows: ["2037-12-04", "2037-12-05"].flatMap((deliveryOn) =>
          [8, 10, 12].map((hour) => ({
            deliveryOn,
            startsAt: `${String(hour).padStart(2, "0")}:00`,
            endsAt: `${String(hour + 2).padStart(2, "0")}:00`,
          })),
        ),
      },
    }),
  );
  const parties = await json(
    await admin.request.get(
      `${origin}/api/v1/actions/${golden}/acquisition/parties?limit=100`,
    ),
  );
  const companies = parties.items
    .filter((item) => item.partyKind === "company")
    .slice(0, 2);
  assert.equal(
    companies.length,
    2,
    "Two existing synthetic CRM companies are required",
  );
  const assignments = [];
  for (const company of companies) {
    const assigned = await json(
      await admin.request.post(`${api}/acquisition/assignments`, {
        headers,
        data: {
          partyKind: company.partyKind,
          partyId: company.twentyId,
          acquirerUserId: anna,
        },
      }),
      201,
    );
    assignments.push(assigned.assignment);
  }
  await page.goto(`${origin}/login?returnTo=%2Fapp%2F`);
  await browserLogin(
    customer,
    page,
    "/app/",
    false,
    "anna.akquise@leonaid.invalid",
  );
  const formPath = `/app/commitments/new?action=${action.id}`;
  await writeFile(
    "/proof/orders-state.json",
    JSON.stringify(
      {
        actionId: action.id,
        formPath,
        assignments,
        companies,
        windows: configuration.windows,
      },
      null,
      2,
    ),
  );
  await page.goto(origin + formPath);
  await expect(page.getByTestId("commitment-sponsor")).toBeVisible();
  assert.equal(
    await page.getByText("Für mich selbst", { exact: true }).count(),
    0,
  );
  const context = await json(
    await customer.request.get(`${api}/commitment-capture`),
  );
  assert.ok(!("selfBuyer" in context));
  assert.equal(context.deliveryConfiguration.windows.length, 6);
  assert.ok(context.offerings.length > 0);
  await page.getByTestId("commitment-sponsor").selectOption(assignments[0].id);
  await expect(page.locator("#commitment-recipient-name")).toHaveValue(
    companies[0].displayName,
  );
  await page.locator("#commitment-street").fill("Rechnungsweg 11");
  await page.locator("#commitment-postal-code").fill("12345");
  await page.locator("#commitment-city").fill("Teststadt");
  await page
    .getByRole("button", {
      name: "Lieferadresse wie Rechnungsadresse übernehmen",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Straße und Hausnummer für die Lieferung", { exact: true })
    .fill("Warenannahme 22");
  await page
    .getByLabel("Ansprechpartner bei der Lieferung (optional)", { exact: true })
    .fill("Test Warenannahme");
  await page
    .getByLabel("Telefonnummer für die Lieferung (optional)", { exact: true })
    .fill("+49 123 / 456");
  await expect(
    page.locator('input[name="delivery-window"]:checked'),
  ).toHaveCount(0);
  await expect(page.getByTestId("commitment-save-ready")).toBeDisabled();
  await page.locator(`input[value="${configuration.windows[0].id}"]`).check();
  // Customer switches reset delivery snapshots, including contact and selected window.
  await page.getByTestId("commitment-sponsor").selectOption(assignments[1].id);
  await expect(page.locator("#commitment-recipient-name")).toHaveValue(
    companies[1].displayName,
  );
  await expect(page.getByLabel("Lieferempfänger", { exact: true })).toHaveValue(
    "",
  );
  await expect(
    page.getByLabel("Ansprechpartner bei der Lieferung (optional)", {
      exact: true,
    }),
  ).toHaveValue("");
  await expect(
    page.locator('input[name="delivery-window"]:checked'),
  ).toHaveCount(0);
  await page.locator("#commitment-street").fill("Rechnungsweg 11");
  await page.locator("#commitment-postal-code").fill("12345");
  await page.locator("#commitment-city").fill("Teststadt");
  await page
    .getByRole("button", {
      name: "Lieferadresse wie Rechnungsadresse übernehmen",
      exact: true,
    })
    .click();
  await page
    .getByLabel("Straße und Hausnummer für die Lieferung", { exact: true })
    .fill("Warenannahme 22");
  await page
    .getByLabel("Ansprechpartner bei der Lieferung (optional)", { exact: true })
    .fill("Test Warenannahme");
  await page
    .getByLabel("Telefonnummer für die Lieferung (optional)", { exact: true })
    .fill("+49 123 / 456");
  await page.locator(`input[value="${configuration.windows[0].id}"]`).check();
  // A real retirement between display and submission preserves entered values.
  await expect(page.getByTestId("commitment-save-ready")).toBeEnabled();
  configuration = await json(
    await admin.request.put(`${api}/delivery-configuration`, {
      headers,
      data: {
        expectedRevision: configuration.revision,
        enabled: true,
        timezone: configuration.timezone,
        windows: configuration.windows.map((item, index) => ({
          ...item,
          retired: index === 0,
        })),
      },
    }),
  );
  await page.getByTestId("commitment-save-ready").click();
  await expect(page.locator('input[name="delivery-window"]')).toHaveCount(5);
  await expect(
    page.locator('input[name="delivery-window"]:checked'),
  ).toHaveCount(0);
  await expect(
    page.getByLabel("Straße und Hausnummer für die Lieferung", { exact: true }),
  ).toHaveValue("Warenannahme 22");
  await expect(
    page.getByLabel("Ansprechpartner bei der Lieferung (optional)", {
      exact: true,
    }),
  ).toHaveValue("Test Warenannahme");
  await page.locator(`input[value="${configuration.windows[1].id}"]`).check();
  await expect(
    page.getByText(
      "Dieses Lieferfenster ist nicht mehr verfügbar. Bitte erneut auswählen.",
      { exact: true },
    ),
  ).toHaveCount(0);
  // One batched responsive inspection, with keyboard scrolling still usable.
  for (const [name, width, textSize] of [
    ["anna-desktop", 1440, 100],
    ["anna-mobile", 390, 100],
    ["anna-user-499", 499, 100],
    ["anna-text-200", 780, 200],
  ]) {
    await page.setViewportSize({ width, height: 1050 });
    await page.evaluate((size) => {
      document.documentElement.style.fontSize = `${size}%`;
      document.activeElement?.blur();
      window.scrollTo({ top: 0, behavior: "instant" });
    }, textSize);
    const measures = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      width: innerWidth,
      bars: getComputedStyle(document.documentElement).scrollbarWidth,
    }));
    assert.ok(
      measures.scroll <= measures.width + 1,
      `${name}: horizontal overflow ${JSON.stringify(measures)}`,
    );
    assert.equal(measures.bars, "none");
    await page.screenshot({
      path: `/proof/screenshots/${name}.png`,
      fullPage: true,
    });
  }
  await page.keyboard.press("PageDown");
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(0);
  await page.setViewportSize({ width: 1440, height: 1050 });
  await page.evaluate(() => (document.documentElement.style.fontSize = "100%"));
  const [createdResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url() === `${api}/commitments` &&
        response.request().method() === "POST",
    ),
    page.getByTestId("commitment-save-ready").click(),
  ]);
  const order = await json(createdResponse, 201);
  await expect(page.getByTestId("commitment-success")).toBeVisible();
  assert.equal(order.buyer.twentyId, companies[1].twentyId);
  assert.equal(order.deliveryRecipient.streetLine1, "Warenannahme 22");
  assert.equal(order.invoiceRecipient.streetLine1, "Rechnungsweg 11");
  assert.equal(order.deliveryContact.name, "Test Warenannahme");
  assert.equal(order.deliveryWindowId, configuration.windows[1].id);
  await expect(
    page.getByText("Test Warenannahme", { exact: false }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("commitment-success")).toBeVisible();
  // Incomplete delivery can be saved as a draft and resumed through its real URL.
  await captureState(page, "anna-success");
  await page.goto(origin + formPath);
  await page.getByTestId("commitment-sponsor").selectOption(assignments[0].id);
  await page.locator("#commitment-street").fill("Entwurfsweg 33");
  await page.locator("#commitment-postal-code").fill("12345");
  await page.locator("#commitment-city").fill("Teststadt");
  const [draftResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url() === `${api}/commitments` &&
        response.request().method() === "POST",
    ),
    page.getByTestId("commitment-save-draft").click(),
  ]);
  const draft = await json(draftResponse, 201);
  assert.equal(draft.status, "draft");
  assert.equal(draft.deliveryRecipient, null);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Entwurf abschließen", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "Lieferadresse wie Rechnungsadresse übernehmen",
      exact: true,
    })
    .click();
  await page.locator(`input[value="${configuration.windows[2].id}"]`).check();
  await page
    .getByLabel("Telefonnummer für die Lieferung (optional)", { exact: true })
    .fill("+49 456 789");
  await captureState(page, "anna-draft");
  await page
    .getByRole("button", {
      name: "Entwurf prüfbereit abschließen",
      exact: true,
    })
    .click();
  await expect(
    page.getByRole("heading", { name: "Bereit für die Prüfung", exact: true }),
  ).toBeVisible();
  const completed = await json(
    await customer.request.get(`${api}/commitments/${draft.id}`),
  );
  assert.equal(completed.deliveryContact.name, null);
  assert.equal(completed.deliveryContact.phone, "+49 456 789");
  for (const key of ["buyer", "invoiceRecipient", "lines", "totalMinor"])
    assert.deepEqual(completed[key], draft[key]);
  const managerDraft = await json(
    await customer.request.post(`${api}/commitments`, {
      headers: {
        ...headers,
        "Idempotency-Key": `delivery-manager:${randomUUID()}`,
      },
      data: {
        source: "acquisition",
        readyForReview: false,
        buyer: draft.buyer,
        invoiceRecipient: draft.invoiceRecipient,
        lines: draft.lines.map((line) => ({
          offeringId: line.offeringId,
          quantity: line.quantity,
          unit: line.unit,
        })),
      },
    }),
    201,
  );
  // Manager view reads the stored delivery snapshot rather than CRM address data.
  await managerPage.goto(`${origin}/admin/orders?action=${action.id}`);
  const row = managerPage.locator(`[data-commitment-id="${order.id}"]`);
  await row
    .getByText("Lieferdaten und Bestellkontakt", { exact: true })
    .click();
  await expect(
    row.getByText("Warenannahme 22", { exact: false }),
  ).toBeVisible();
  await expect(
    row.getByText("Test Warenannahme", { exact: false }),
  ).toBeVisible();
  const draftRow = managerPage.locator(
    `[data-commitment-id="${managerDraft.id}"]`,
  );
  await draftRow
    .getByText("Lieferdaten und Bestellkontakt", { exact: true })
    .click();
  await draftRow
    .getByRole("button", {
      name: "Lieferadresse wie Rechnungsadresse übernehmen",
      exact: true,
    })
    .click();
  await draftRow
    .locator(`input[value="${configuration.windows[3].id}"]`)
    .check();
  await captureState(managerPage, "manager-delivery");
  await draftRow
    .getByRole("button", {
      name: "Entwurf prüfbereit abschließen",
      exact: true,
    })
    .click();
  await expect(draftRow.locator(".commitment-status")).toHaveText("Prüfbereit");
  const managerCompleted = await json(
    await admin.request.get(`${api}/commitments/${managerDraft.id}`),
  );
  assert.equal(managerCompleted.deliveryWindowId, configuration.windows[3].id);
  assert.equal(managerCompleted.deliveryContact, null);
  await writeFile(
    "/proof/orders-state.json",
    JSON.stringify(
      {
        actionId: action.id,
        formPath,
        orderId: order.id,
        draftId: draft.id,
        assignments,
        companies,
        windows: configuration.windows,
      },
      null,
      2,
    ),
  );
  assert.deepEqual(errors, []);
  console.log(
    "KLF-050 browser PASS: existing CRM company selection, no self ordering, customer reset, separate delivery/invoice/contact, real retirement and retained input, draft reload and completion, stored snapshots, manager display, responsive/200-percent/hidden-scrollbar keyboard checks; real Core/Mailpit/Twenty",
  );
} catch (error) {
  console.error(error);
  if (await page.locator(".commitment-capture").count())
    console.error(
      await page.locator(".commitment-capture").evaluate((form) =>
        Array.from(form.querySelectorAll("input,select")).map((input) => ({
          id: input.id,
          type: input.type,
          value: input.value,
          checked: input.checked,
          valid: input.validity.valid,
        })),
      ),
    );
  await page.screenshot({
    path: "/proof/screenshots/anna-failure.png",
    fullPage: true,
  });
  throw error;
} finally {
  await browser.close();
}
