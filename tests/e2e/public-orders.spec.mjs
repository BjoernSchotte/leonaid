import { expect, test } from "./csp-guard.mjs";
import { readFile, writeFile } from "node:fs/promises";

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
  // Styles ship as files; the footer links the page's privacy notice.
  expect(await response?.text()).not.toMatch(/<style[\s>]/);
  await expect(page.locator("body")).toHaveClass("taxi-site");
  await expect(page.locator(".taxi-hero__logo")).toBeVisible();
  await page.getByRole("link", { name: "Jetzt bestellen" }).click();
  const form = page.locator("[data-order-form]");
  await expect(form).toBeVisible();
  await expect(form).toHaveAttribute("method", "POST");
  await expect(
    page.locator('form[action*="lions-krapfentaxi.de"]'),
  ).toHaveCount(0);
  const legal = page.locator("[data-footer-legal]");
  await expect(legal.getByRole("link", { name: "Impressum" })).toHaveAttribute(
    "href",
    "/impressum",
  );
  await expect(
    legal.getByRole("link", { name: "Datenschutz" }),
  ).toHaveAttribute("href", "/datenschutz");
  // The per-action notice stays on the page and links the full policy.
  await expect(page.locator("#datenschutz")).toHaveCount(1);
  await expect(page.locator("[data-privacy-full-link]")).toHaveAttribute(
    "href",
    "/datenschutz",
  );
  await expect(form.locator("[data-order-privacy-link]")).toHaveAttribute(
    "href",
    "/datenschutz",
  );
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
  if (companyName) {
    await form.locator('input[name="companyName"]').fill(companyName);
  } else {
    // A private order: the company field is hidden and sends nothing.
    await form.getByText("Privatperson", { exact: true }).click();
    await expect(form.locator('input[name="companyName"]')).toBeHidden();
  }
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
  return submitOrderResult(form);
}

async function submitOrderResult(form) {
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
  await expect(success).toContainText(
    "Eine Bestellbestätigung mit allen Angaben geht an die angegebene E-Mail-Adresse.",
  );
  return { reference, success };
}

test("new company, existing company and private person order in the guided form", async ({
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
  // The error summary takes the focus and links every problem to its field.
  const summary = form.locator("[data-form-message]");
  await expect(summary).toBeFocused();
  await expect(summary).toHaveAttribute("role", "alert");
  await expect(summary).toContainText("Bitte prüfen Sie");
  const givenNameLink = summary.getByRole("link", {
    name: "Vorname: Bitte geben Sie Ihren Vornamen an.",
  });
  await expect(givenNameLink).toBeVisible();
  await givenNameLink.click();
  await expect(form.locator('input[name="givenName"]')).toBeFocused();
  await expect(form.locator('input[name="givenName"]')).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(form.locator('input[name="companyName"]')).toHaveValue(
    "POC072 Browseratelier GmbH",
  );
  proof.validation = {
    focusedSummary: true,
    summaryLinkFocusesField: "givenName",
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

test("a double submit sends one order request and shows the confirmation", async ({
  page,
}) => {
  const form = await openOrderForm(page);
  await fillOrder(form, {
    companyName: "POC072 Doppelklick GmbH",
    email: "dora.doppelklick@leonaid.invalid",
    familyName: "Doppelklick",
    givenName: "Dora",
    quantity: 1,
    recipient: "POC072 Doppelklick GmbH",
  });
  let orderRequests = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("createPublicOrder")
    )
      orderRequests += 1;
  });
  await form.locator('button[type="submit"]').dblclick();
  const { success } = await submitOrderResult(form);
  expect(orderRequests).toBe(1);
  // Confirmation layout: check mark, heading, reference, facts, next steps.
  await expect(success.locator(".public-thanks-icon")).toBeVisible();
  await expect(
    success.getByRole("heading", { name: "Danke für Ihre Bestellung!" }),
  ).toBeVisible();
  await expect(success.locator("[data-order-total]")).toHaveText(/36,00/);
  await expect(success.locator(".public-next li")).toHaveCount(5);
  await expect(
    success.getByRole("link", { name: "Zur Aktionsseite" }),
  ).toBeVisible();
  await page.screenshot({
    path: `${artifactDirectory}/public-order-confirmation-mobile.png`,
    fullPage: true,
  });
});

test("without JavaScript the confirmation is the focused target of the post", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    javaScriptEnabled: false,
    // Own rate-limit bucket (address + user agent): the guided paths above
    // already use most of the five orders per ten minutes.
    userAgent: "LeonAid public-order proof (no JavaScript)",
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/krapfentaxi`, { waitUntil: "networkidle" });
    const form = page.locator("[data-order-form]");
    // No script: steppers and the customer-kind toggle stay hidden.
    await expect(form.locator("[data-step]").first()).toBeHidden();
    await expect(form.locator("[data-customer-kind]")).toBeHidden();
    await form.locator('input[name="quantity"]').first().fill("1");
    await form
      .locator('input[name="companyName"]')
      .fill("POC072 Ohne Skript GmbH");
    await form.locator('input[name="givenName"]').fill("Otto");
    await form.locator('input[name="familyName"]').fill("Ohneskript");
    await form
      .locator('input[name="email"]')
      .fill("otto.ohneskript@leonaid.invalid");
    await form
      .locator('input[name="deliveryRecipientName"]')
      .fill("POC072 Ohne Skript GmbH");
    await form.locator('input[name="deliveryStreetLine1"]').fill("Formweg 7");
    await form.locator('input[name="deliveryPostalCode"]').fill("86150");
    await form.locator('input[name="deliveryCity"]').fill("Augsburg");
    await form.locator('input[name="privacyAcknowledged"]').check();
    await form.locator('input[name="bindingOrderConfirmed"]').check();
    await form.locator('button[type="submit"]').click();
    await page.waitForLoadState("domcontentloaded");
    const success = page.locator("[data-order-success]");
    await expect(success).toBeVisible();
    await expect(success).toHaveAttribute("autofocus", "");
    await expect(success).toBeFocused();
    await expect(success).toBeInViewport();
    await expect(success.locator("[data-order-reference]")).toHaveText(
      /^LA-[A-F0-9]{32}$/,
    );
  } finally {
    await context.close();
  }
});

test("without JavaScript a refused order comes back focused with the entries kept", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    javaScriptEnabled: false,
    userAgent: "LeonAid public-order proof (no JavaScript, refused)",
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/krapfentaxi`, { waitUntil: "networkidle" });
    const form = page.locator("[data-order-form]");
    // A stale price quote, as after a price change while the form was open:
    // Core refuses the order and the page renders the form again. Playwright
    // sets the hidden field; the page itself runs no script.
    await form
      .locator('input[name="quotedUnitPriceMinor"]')
      .first()
      .evaluate((input) => {
        input.value = "1";
      });
    await form.locator('input[name="quantity"]').first().fill("1");
    await form
      .locator('input[name="companyName"]')
      .fill("POC072 Preisalt GmbH");
    await form.locator('input[name="givenName"]').fill("Petra");
    await form.locator('input[name="familyName"]').fill("Preisalt");
    await form
      .locator('input[name="email"]')
      .fill("petra.preisalt@leonaid.invalid");
    await form
      .locator('input[name="deliveryRecipientName"]')
      .fill("POC072 Preisalt GmbH");
    await form.locator('input[name="deliveryStreetLine1"]').fill("Preisweg 3");
    await form.locator('input[name="deliveryPostalCode"]').fill("86150");
    await form.locator('input[name="deliveryCity"]').fill("Augsburg");
    await form.locator('input[name="privacyAcknowledged"]').check();
    await form.locator('input[name="bindingOrderConfirmed"]').check();
    await form.locator('button[type="submit"]').click();
    await page.waitForLoadState("domcontentloaded");
    const summary = page.locator("[data-form-message]");
    await expect(summary).toBeVisible();
    await expect(summary).toHaveAttribute("data-state", "error");
    await expect(summary).toHaveAttribute("autofocus", "");
    await expect(summary).toBeFocused();
    await expect(summary).toBeInViewport();
    await expect(summary).toContainText("Ihre Eingaben wurden übernommen.");
    await expect(summary).not.toContainText(/\b(du|dein|bitte lade)\b/i);
    await expect(page.locator("[data-order-success]")).toBeHidden();
    const redisplayed = page.locator("[data-order-form]");
    await expect(redisplayed.locator('input[name="givenName"]')).toHaveValue(
      "Petra",
    );
    await expect(redisplayed.locator('input[name="companyName"]')).toHaveValue(
      "POC072 Preisalt GmbH",
    );
  } finally {
    await context.close();
  }
});

test("the same form posted twice without JavaScript creates one order", async ({
  page,
}) => {
  const form = await openOrderForm(page);
  await fillOrder(form, {
    companyName: "POC072 Zweimal GmbH",
    email: "zoe.zweimal@leonaid.invalid",
    familyName: "Zweimal",
    givenName: "Zoe",
    quantity: 1,
    recipient: "POC072 Zweimal GmbH",
  });
  // The serialized form as a browser without JavaScript would send it.
  const body = await form.evaluate((element) =>
    new URLSearchParams(
      [...new FormData(element)].map(([name, value]) => [name, String(value)]),
    ).toString(),
  );
  const action = await form.evaluate((element) => element.action);
  const post = () =>
    page.request.post(action, {
      data: body,
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Origin: new URL(baseUrl).origin,
        "User-Agent": "LeonAid public-order proof (double post)",
      },
    });
  const references = [];
  for (const response of [await post(), await post()]) {
    expect(response.status()).toBe(200);
    const html = await response.text();
    const match = html.match(/data-order-reference[^>]*>\s*(LA-[A-F0-9]{32})/);
    expect(
      match,
      `the post renders the confirmation: ${html.match(/data-form-message[\s\S]{0,600}/)?.[0] ?? html.slice(0, 300)}`,
    ).not.toBeNull();
    references.push(match[1]);
  }
  expect(references[1]).toBe(references[0]);
});

const windowRequest = ({ id, deliveryOn, startsAt, endsAt, retired }) => ({
  id,
  deliveryOn,
  startsAt,
  endsAt,
  retired,
});

// tools/public_orders/delivery_cleanup.py reads this file around the
// browser step: the proof window IDs to retire.
const deliveryProofPath =
  process.env.LEONAID_E2E_DELIVERY_STATE ??
  `${artifactDirectory}/public-orders-delivery.json`;

async function recordDeliveryProof(change) {
  let proof = { windowIds: [] };
  try {
    proof = JSON.parse(await readFile(deliveryProofPath, "utf8"));
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  await writeFile(deliveryProofPath, JSON.stringify(change(proof)));
}

/** A calendar day in Berlin, `days` from today. */
function berlinDay(days) {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Berlin" }).format(
    new Date(Date.now() + days * 86_400_000),
  );
}

/**
 * The proof windows lie two days ahead: a new window must start after now
 * and inside the action period. The seed runs the golden action from 60
 * days before to 75 days after the seed day (tools/seed/golden.py).
 */
const proofDeliveryDay = () => berlinDay(2);

async function addProofWindows(request, actionId, day) {
  const configured = await deliveryConfiguration(
    request,
    actionId,
    (configuration) => ({
      expectedRevision: configuration.revision,
      enabled: true,
      timezone: configuration.timezone,
      windows: [
        ...configuration.windows.map(windowRequest),
        { deliveryOn: day, startsAt: "08:00", endsAt: "10:00" },
        { deliveryOn: day, startsAt: "10:00", endsAt: "12:00" },
      ],
    }),
  );
  const added = configured.windows
    .filter((window) => window.deliveryOn === day && !window.retired)
    .sort((a, b) => a.startsAt.localeCompare(b.startsAt));
  expect(added).toHaveLength(2);
  await recordDeliveryProof((proof) => ({
    ...proof,
    windowIds: [...proof.windowIds, ...added.map((window) => window.id)],
  }));
  return added;
}

async function retireAllWindows(request, actionId) {
  await deliveryConfiguration(request, actionId, (configuration) => ({
    expectedRevision: configuration.revision,
    enabled: true,
    timezone: configuration.timezone,
    windows: configuration.windows.map((window) => ({
      ...windowRequest(window),
      retired: true,
    })),
  }));
}

async function deliveryConfiguration(request, actionId, change) {
  const url = `${baseUrl}/api/v1/actions/${actionId}/delivery-configuration`;
  const current = await request.get(url);
  expect(current.status(), await current.text()).toBe(200);
  const configuration = await current.json();
  const saved = await request.put(url, {
    headers: { Origin: new URL(baseUrl).origin },
    data: change(configuration),
  });
  expect(saved.status(), await saved.text()).toBe(200);
  return saved.json();
}

test("an unselected delivery window is listed and linked in the error summary", async ({
  context,
  page,
}) => {
  const session = process.env.KLARA_SESSION;
  expect(session, "KLARA_SESSION for the delivery configuration").toBeTruthy();
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: session,
      url: baseUrl,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  let form = await openOrderForm(page);
  const actionId = await form.getAttribute("data-action-id");
  const day = proofDeliveryDay();
  try {
    await addProofWindows(page.request, actionId, day);
    form = await openOrderForm(page);
    const windows = form.locator('input[name="deliveryWindowId"]');
    await expect(windows).toHaveCount(2);
    await form.locator('input[name="givenName"]').fill("Wanda");
    await form.locator('input[name="familyName"]').fill("Fenster");
    await form.locator('input[name="email"]').fill("wanda@leonaid.invalid");
    await form.locator('input[name="deliveryRecipientName"]').fill("Wanda");
    await form
      .locator('input[name="deliveryStreetLine1"]')
      .fill("Fensterweg 1");
    await form.locator('input[name="deliveryPostalCode"]').fill("86150");
    await form.locator('input[name="deliveryCity"]').fill("Augsburg");
    await form.locator('input[name="privacyAcknowledged"]').check();
    await form.locator('input[name="bindingOrderConfirmed"]').check();
    await form.locator('button[type="submit"]').click();
    const summary = form.locator("[data-form-message]");
    await expect(summary).toBeFocused();
    await expect(summary).toContainText("Bitte prüfen Sie eine Angabe");
    const link = summary.getByRole("link", {
      name: "Lieferfenster: Bitte wählen Sie ein Lieferfenster.",
    });
    await expect(link).toBeVisible();
    await link.click();
    await expect(windows.first()).toBeFocused();
  } finally {
    // Retire the proof windows; tools/public_orders/delivery_cleanup.py then
    // restores the golden state (planning cannot be switched off by API).
    await retireAllWindows(page.request, actionId);
  }
});

test("a window marked ausgebucht is shown but cannot be chosen, also when it fills while the form is open", async ({
  browser,
}) => {
  const session = process.env.KLARA_SESSION;
  expect(session, "KLARA_SESSION for the delivery configuration").toBeTruthy();
  // An own user agent: the public rate limit counts per address and agent,
  // and the earlier cases already sent several orders.
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
    userAgent: "LeonAid public-order proof (ausgebucht)",
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: session,
      url: baseUrl,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  let form = await openOrderForm(page);
  const actionId = await form.getAttribute("data-action-id");
  const day = proofDeliveryDay();
  let first;
  let second;
  const markFull = async (window, fullyBooked) => {
    const response = await page.request.put(
      `${baseUrl}/api/v1/actions/${actionId}/delivery-windows/${window.id}/fully-booked`,
      { headers: { Origin: new URL(baseUrl).origin }, data: { fullyBooked } },
    );
    expect(response.status(), await response.text()).toBe(200);
  };
  const radio = (window) =>
    form.locator(`input[name="deliveryWindowId"][value="${window.id}"]`);
  try {
    [first, second] = await addProofWindows(page.request, actionId, day);
    // A full window is listed, marked and not selectable.
    await markFull(first, true);
    form = await openOrderForm(page);
    await expect(radio(first)).toBeDisabled();
    await expect(radio(first).locator("xpath=..")).toContainText("ausgebucht");
    await expect(radio(second)).toBeEnabled();
    await page.screenshot({
      path: `${artifactDirectory}/public-order-window-full-mobile.png`,
      fullPage: true,
    });

    // A free window left: ordering stays possible.
    const submit = () => form.locator("[data-order-submit]");
    const blocked = () => form.locator("[data-order-submit-blocked]");
    await expect(submit()).toBeEnabled();
    await expect(blocked()).toBeHidden();

    // All full: the form says so and "Verbindlich bestellen" is off.
    await markFull(second, true);
    form = await openOrderForm(page);
    await expect(
      form.getByText("Alle Lieferfenster sind ausgebucht."),
    ).toBeVisible();
    await expect(submit()).toBeDisabled();
    await expect(blocked()).toBeVisible();
    await expect(blocked()).toContainText(
      "Bestellen ist gerade nicht möglich, weil kein Lieferfenster frei ist.",
    );
    await expect(submit()).toHaveAttribute(
      "aria-describedby",
      "order-submit-blocked",
    );
    await page.screenshot({
      path: `${artifactDirectory}/public-order-all-full-mobile.png`,
      fullPage: true,
    });

    // The same without JavaScript: the server renders the button disabled.
    const noScript = await browser.newContext({
      ignoreHTTPSErrors: true,
      javaScriptEnabled: false,
      userAgent: "LeonAid public-order proof (ausgebucht, no JavaScript)",
      viewport: { width: 390, height: 844 },
    });
    try {
      const plain = await noScript.newPage();
      await plain.goto(`${baseUrl}/krapfentaxi`, { waitUntil: "networkidle" });
      const plainForm = plain.locator("[data-order-form]");
      await expect(plainForm.locator("[data-order-submit]")).toBeDisabled();
      await expect(
        plainForm.locator("[data-order-submit-blocked]"),
      ).toBeVisible();
      await expect(
        plainForm.getByText("Alle Lieferfenster sind ausgebucht."),
      ).toBeVisible();
    } finally {
      await noScript.close();
    }

    // A window frees up while the form is open: refreshing the windows
    // enables ordering again.
    await markFull(second, false);
    await form.locator("[data-delivery-refresh]").click();
    await expect(form.locator("[data-delivery-refresh-status]")).toContainText(
      "Die Lieferfenster sind aktuell.",
    );
    await expect(radio(second)).toBeEnabled();
    await expect(submit()).toBeEnabled();
    await expect(blocked()).toBeHidden();
    await expect(submit()).not.toHaveAttribute("aria-describedby", /.+/);

    // Stale form: the chosen window fills before the order is sent.
    await markFull(first, false);
    await markFull(second, false);
    form = await openOrderForm(page);
    await form.locator('input[name="givenName"]').fill("Agnes");
    await form.locator('input[name="familyName"]').fill("Ausgebucht");
    await form.locator('input[name="email"]').fill("agnes@leonaid.invalid");
    await form.locator('input[name="deliveryRecipientName"]').fill("Agnes");
    await form
      .locator('input[name="deliveryStreetLine1"]')
      .fill("Fensterweg 2");
    await form.locator('input[name="deliveryPostalCode"]').fill("86150");
    await form.locator('input[name="deliveryCity"]').fill("Augsburg");
    await radio(first).check();
    await form.locator('input[name="privacyAcknowledged"]').check();
    await form.locator('input[name="bindingOrderConfirmed"]').check();
    await markFull(first, true);
    await form.locator('button[type="submit"]').click();
    const summary = form.locator("[data-form-message]");
    await expect(summary).toBeFocused();
    await expect(summary).toContainText(
      "Dieses Lieferfenster ist inzwischen ausgebucht. Bitte wählen Sie ein anderes.",
    );
    await expect(form.locator("[data-delivery-refresh-status]")).toContainText(
      "Das gewählte Lieferfenster ist nicht mehr verfügbar",
    );
    await expect(radio(first)).toBeDisabled();
    await expect(radio(first)).not.toBeChecked();
    await expect(form.locator('input[name="givenName"]')).toHaveValue("Agnes");
    await expect(form.locator('input[name="deliveryCity"]')).toHaveValue(
      "Augsburg",
    );
    // The summary links the window choice; the open window takes the focus.
    await summary.getByRole("link", { name: /^Lieferfenster: / }).click();
    await expect(radio(second)).toBeFocused();
    await expect(radio(second)).toBeEnabled();
  } finally {
    // Retiring also clears "ausgebucht"; delivery_cleanup.py then restores
    // the golden state.
    await retireAllWindows(page.request, actionId);
    await context.close();
  }
});
