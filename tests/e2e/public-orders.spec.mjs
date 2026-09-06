import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL and LEONAID_E2E_ARTIFACT_DIR are required",
  );
}

test.setTimeout(90_000);

test.use({
  ignoreHTTPSErrors: true,
  viewport: { width: 390, height: 844 },
});

async function openOrderForm(page) {
  const response = await page.goto(`${baseUrl}/krapfentaxi`, {
    waitUntil: "networkidle",
  });
  expect(response?.status()).toBe(200);
  expect(response?.headers()["cache-control"]).toContain("no-store");
  await expect(page.locator("body")).toHaveClass("taxi-site");
  await expect(page.locator(".taxi-hero__logo")).toBeVisible();
  await page.getByRole("link", { name: "Jetzt bestellen" }).click();
  const form = page.locator("[data-order-form]");
  await expect(form).toBeVisible();
  await expect(form).toHaveAttribute("method", "POST");
  await expect(
    page.locator('form[action*="lions-krapfentaxi.de"]'),
  ).toHaveCount(0);
  await expect(form.getByText("Menge und Bestellwert")).toBeVisible();
  await expect(
    form.getByText("Eine bestehende Firma wird automatisch erkannt."),
  ).toBeVisible();
  await expect(
    form.getByText("Grundlage für die spätere Routenzuordnung."),
  ).toBeVisible();
  return form;
}

async function fillOrder(
  form,
  {
    city = "Augsburg",
    companyName = "",
    email,
    familyName,
    givenName,
    postalCode = "86150",
    quantity,
    recipient,
    street = "Browserweg 72",
  },
) {
  await form.locator('input[name="quantity"]').first().fill(String(quantity));
  await form.locator('input[name="companyName"]').fill(companyName);
  await form.locator('input[name="givenName"]').fill(givenName);
  await form.locator('input[name="familyName"]').fill(familyName);
  await form.locator('input[name="email"]').fill(email);
  await form.locator('input[name="phone"]').fill("+49 821 123456");
  await form.locator('input[name="deliveryRecipientName"]').fill(recipient);
  await form.locator('input[name="deliveryStreetLine1"]').fill(street);
  await form.locator('input[name="deliveryPostalCode"]').fill(postalCode);
  await form.locator('input[name="deliveryCity"]').fill(city);
  await form.locator('input[name="deliveryCountryCode"]').fill("at");
  await form
    .locator('select[name="deliveryWindowId"]')
    .selectOption("90000000-0000-4000-8000-000000000072");
  await form
    .locator('input[name="deliveryContactName"]')
    .fill("Alex Lieferung");
  await form
    .locator('input[name="deliveryContactPhone"]')
    .fill("+49 821 765432");
  await form
    .locator('textarea[name="deliveryInstructions"]')
    .fill("Abteilung Bildung\nEingang links <b>Hinweis</b>");
  await expect(
    form.locator('input[name="billingSameAsDelivery"]'),
  ).toBeChecked();
  await form
    .locator('input[name="invoiceEmail"]')
    .fill("rechnung@leonaid.invalid");
  await form.locator('input[name="privacyAcknowledged"]').check();
  await form.locator('input[name="bindingOrderConfirmed"]').check();
}

async function submitOrder(form) {
  await form.locator('button[type="submit"]').click();
  const success = form.locator("xpath=..").locator("[data-order-success]");
  const failure = form.locator("[data-form-message]");
  await expect
    .poll(
      async () => {
        if (await success.isVisible()) return "success";
        if (await failure.isVisible()) {
          return `failure: ${(await failure.textContent())?.trim()}`;
        }
        return "pending";
      },
      { timeout: 15_000 },
    )
    .toBe("success");
  await expect(success).toBeFocused();
  const reference = (
    await success.locator("[data-order-reference]").textContent()
  )?.trim();
  expect(reference).toMatch(/^LA-[A-F0-9]{32}$/);
  await expect(success).toContainText(
    "Eine Rechnung folgt separat, sobald der Club die Bestellung geprüft hat.",
  );
  return { reference, success };
}

test("neue Firma, bestehende Firma und Privatperson bestellen im geführten Formular", async ({
  browser,
  page,
}) => {
  const proof = {
    orders: [],
    validation: {},
  };

  let form = await openOrderForm(page);
  await page.screenshot({
    path: `${artifactDirectory}/public-order-form-mobile.png`,
    fullPage: true,
  });

  await form
    .locator('input[name="companyName"]')
    .fill("POC072 Browseratelier GmbH");
  await form.locator('button[type="submit"]').click();
  await expect(form.locator('input[name="givenName"]')).toBeFocused();
  await expect(form.locator('input[name="companyName"]')).toHaveValue(
    "POC072 Browseratelier GmbH",
  );
  proof.validation = {
    firstFocusedField: "givenName",
    retainedCompanyName: "POC072 Browseratelier GmbH",
  };
  await page.screenshot({
    path: `${artifactDirectory}/public-order-validation-mobile.png`,
    fullPage: true,
  });

  await fillOrder(form, {
    companyName: "POC072 Browseratelier GmbH",
    email: "nora.browseratelier@leonaid.invalid",
    familyName: "Browser",
    givenName: "Nora",
    quantity: 2,
    recipient: "POC072 Browseratelier GmbH",
  });
  const initialCommand = await form
    .locator('input[name="commandId"]')
    .inputValue();
  // A stale client may retain an ID no longer offered by Core. Exercise the
  // real rejection/refresh path without changing another test's schedule.
  await form.locator('select[name="deliveryWindowId"]').evaluate((select) => {
    const option = new Option(
      "Nicht mehr verfügbar",
      "90000000-0000-4000-8000-000000000099",
    );
    select.append(option);
    select.value = option.value;
  });
  await form.locator('button[type="submit"]').click();
  await expect(form.locator("[data-form-message]")).toBeVisible();
  await expect(form.locator('input[name="givenName"]')).toHaveValue("Nora");
  await form.locator("[data-delivery-reload]").click();
  await expect(form.locator("#deliveryWindowId-help")).toContainText(
    "Lieferfenster aktualisiert",
  );
  await expect(form.locator('select[name="deliveryWindowId"]')).toHaveValue("");
  await form
    .locator('select[name="deliveryWindowId"]')
    .selectOption("90000000-0000-4000-8000-000000000072");
  let submitted = await submitOrder(form);
  await expect(form.locator('input[name="commandId"]')).not.toHaveValue(
    initialCommand,
  );
  proof.orders.push({
    scenario: "new-company",
    publicReference: submitted.reference,
  });
  await page.screenshot({
    path: `${artifactDirectory}/public-order-success-new-company.png`,
    fullPage: true,
  });

  form = await openOrderForm(page);
  await fillOrder(form, {
    companyName: "Musterwerk GmbH",
    email: "mara.muster@musterwerk.leonaid.invalid",
    familyName: "Muster",
    givenName: "Mara",
    quantity: 1,
    recipient: "Musterwerk GmbH",
  });
  const replayCommand = await form
    .locator('input[name="commandId"]')
    .inputValue();
  // Commit through the real server, then lose only its response. The retry
  // must return the same order, not create a fourth persisted order.
  await page.route(
    /\/_actions\/createPublicOrder/,
    async (route) => {
      const response = await route.fetch();
      expect(response.ok()).toBeTruthy();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await form.locator('button[type="submit"]').click();
  await expect(form.locator("[data-form-message]")).toBeVisible();
  await form.locator('input[name="givenName"]').fill("Geändert");
  await form.locator('button[type="submit"]').click();
  await expect(form.locator("[data-form-message]")).toContainText(
    "Ausgang der letzten Übermittlung ist unklar",
  );
  await form.locator('input[name="givenName"]').fill("Mara");
  submitted = await submitOrder(form);
  await expect(form.locator('input[name="commandId"]')).toHaveValue(
    replayCommand,
  );
  proof.orders.push({
    scenario: "existing-company",
    publicReference: submitted.reference,
  });
  await page.screenshot({
    path: `${artifactDirectory}/public-order-success-existing-company.png`,
    fullPage: true,
  });

  const noJsContext = await browser.newContext({
    javaScriptEnabled: false,
    reducedMotion: "reduce",
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  const noJsPage = await noJsContext.newPage();
  form = await openOrderForm(noJsPage);
  await fillOrder(form, {
    email: "paula.privat@leonaid.invalid",
    familyName: "Privat",
    givenName: "Paula",
    quantity: 3,
    recipient: "Paula Privat",
  });
  await form.locator('input[name="billingSameAsDelivery"]').uncheck();
  await form
    .locator('input[name="invoiceRecipientName"]')
    .fill("Paula Rechnung");
  await form.locator('input[name="invoiceStreetLine1"]').fill("Rechnungsweg 8");
  await form.locator('input[name="invoicePostalCode"]').fill("86150");
  await form.locator('input[name="invoiceCity"]').fill("Augsburg");
  const rejectedCommand = await form
    .locator('input[name="commandId"]')
    .inputValue();
  await form.locator('input[name="invoiceCity"]').fill(" ");
  await Promise.all([
    noJsPage.waitForNavigation(),
    form.locator('button[type="submit"]').click(),
  ]);
  await expect(form.locator("[data-form-message]")).toBeVisible();
  await expect(form.locator('input[name="givenName"]')).toHaveValue("Paula");
  await expect(form.locator('input[name="quantity"]').first()).toHaveValue("3");
  await expect(form.locator('input[name="invoiceStreetLine1"]')).toHaveValue(
    "Rechnungsweg 8",
  );
  await expect(
    form.locator('input[name="billingSameAsDelivery"]'),
  ).not.toBeChecked();
  await expect(form.locator('input[name="privacyAcknowledged"]')).toBeChecked();
  await expect(form.locator('select[name="deliveryWindowId"]')).toHaveValue(
    "90000000-0000-4000-8000-000000000072",
  );
  await expect(
    form.locator('textarea[name="deliveryInstructions"]'),
  ).toHaveValue("Abteilung Bildung\nEingang links <b>Hinweis</b>");
  await expect(form.locator('input[name="commandId"]')).not.toHaveValue(
    rejectedCommand,
  );
  await expect(form.locator("[data-order-preview-total]")).toContainText(
    "108,00",
  );
  await expect(form.locator("[data-order-preview-quantity]")).toContainText(
    "72 Stück",
  );
  await noJsPage.screenshot({
    path: `${artifactDirectory}/public-order-nojs-error.png`,
    fullPage: true,
  });
  await form.locator('input[name="invoiceCity"]').fill("Augsburg");
  await Promise.all([
    noJsPage.waitForNavigation(),
    form.locator('button[type="submit"]').click(),
  ]);
  const noJsSuccess = noJsPage.locator("[data-order-success]");
  await expect(noJsSuccess).toBeVisible();
  submitted = {
    reference: (
      await noJsSuccess.locator("[data-order-reference]").textContent()
    ).trim(),
  };
  proof.orders.push({
    scenario: "person-without-company",
    publicReference: submitted.reference,
  });
  await noJsPage.screenshot({
    path: `${artifactDirectory}/public-order-success-person.png`,
    fullPage: true,
  });

  await noJsContext.close();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openOrderForm(page);
  await page.screenshot({
    path: `${artifactDirectory}/public-order-form-desktop.png`,
    fullPage: true,
  });

  await writeFile(
    `${artifactDirectory}/public-orders-ui-proof.json`,
    `${JSON.stringify(proof, null, 2)}\n`,
  );
});

test("Lieferregeln erreichen ein bereits geladenes öffentliches Formular", async ({
  browser,
  page,
}) => {
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  await admin.addCookies([
    {
      name: "__Host-leonaid_session",
      value: process.env.KLARA_SESSION,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const url = `${baseUrl}/api/v1/actions/20000000-0000-4000-8000-000000000001/delivery`;
  const read = async () => {
    const response = await admin.request.get(url);
    expect(response.ok()).toBeTruthy();
    const result = await response.json();
    delete result.actionId;
    return result;
  };
  const original = await read();
  const save = async (enabled) => {
    const current = await read();
    expect(
      (await admin.request.put(url, { data: { ...current, enabled } })).ok(),
    ).toBeTruthy();
  };
  try {
    let form = await openOrderForm(page);
    await form
      .locator('[name="deliveryRecipientName"]')
      .fill("Erhaltener Empfang");
    await save(false);
    await form.locator("[data-delivery-reload]").click();
    await expect(form.locator('[name="deliveryWindowId"]')).toBeDisabled();
    await expect(form.locator('[name="deliveryWindowId"]')).not.toHaveAttribute(
      "required",
    );
    await expect(form.locator('[name="deliveryRecipientName"]')).toHaveValue(
      "Erhaltener Empfang",
    );
    form = await openOrderForm(page);
    await expect(form.locator('[name="deliveryWindowId"]')).toBeDisabled();
    await form
      .locator('[name="deliveryRecipientName"]')
      .fill("Erhaltener neuer Empfang");
    await save(true);
    await form.locator("[data-delivery-reload]").click();
    await expect(form.locator('[name="deliveryWindowId"]')).toBeEnabled();
    await expect(form.locator('[name="deliveryWindowId"]')).toHaveAttribute(
      "required",
      "",
    );
    await expect(form.locator('[name="deliveryContactName"]')).toBeVisible();
    await expect(form.locator('[name="deliveryInstructions"]')).toBeVisible();
    await expect(form.locator('[name="deliveryRecipientName"]')).toHaveValue(
      "Erhaltener neuer Empfang",
    );
    await expect(form.locator('[name="deliveryWindowId"]')).toHaveValue("");
  } finally {
    await save(original.enabled);
    await admin.close();
  }
});
