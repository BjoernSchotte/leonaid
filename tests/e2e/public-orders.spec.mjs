import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL and LEONAID_E2E_ARTIFACT_DIR are required",
  );
}

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
  await page.getByRole("link", { name: "Jetzt bestellen" }).click();
  const form = page.locator("[data-order-form]");
  await expect(form).toBeVisible();
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
  await expect(
    form.locator('input[name="billingSameAsDelivery"]'),
  ).toBeChecked();
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
  let submitted = await submitOrder(form);
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
  submitted = await submitOrder(form);
  proof.orders.push({
    scenario: "existing-company",
    publicReference: submitted.reference,
  });
  await page.screenshot({
    path: `${artifactDirectory}/public-order-success-existing-company.png`,
    fullPage: true,
  });

  form = await openOrderForm(page);
  await fillOrder(form, {
    email: "paula.privat@leonaid.invalid",
    familyName: "Privat",
    givenName: "Paula",
    quantity: 3,
    recipient: "Paula Privat",
  });
  submitted = await submitOrder(form);
  proof.orders.push({
    scenario: "person-without-company",
    publicReference: submitted.reference,
  });
  await page.screenshot({
    path: `${artifactDirectory}/public-order-success-person.png`,
    fullPage: true,
  });

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
