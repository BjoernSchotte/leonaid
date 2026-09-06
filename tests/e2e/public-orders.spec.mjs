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
    deliveryEnabled = true,
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
  if (deliveryEnabled) {
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
  }
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
  const save = async (enabled, windows) => {
    const current = await read();
    expect(
      (
        await admin.request.put(url, {
          data: { ...current, enabled, windows: windows ?? current.windows },
        })
      ).ok(),
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
    await expect(form.locator("[data-delivery-required]")).toBeHidden();
    await expect(form.locator('[name="deliveryWindowId"]')).not.toHaveAttribute(
      "required",
    );
    await expect(form.locator('[name="deliveryRecipientName"]')).toHaveValue(
      "Erhaltener Empfang",
    );
    form = await openOrderForm(page);
    await expect(form.locator('[name="deliveryWindowId"]')).toBeDisabled();
    await expect(form.locator("[data-delivery-required]")).toBeHidden();
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
    await expect(form.locator("[data-delivery-required]")).toBeVisible();
    await save(true, [
      ...original.windows.map((window) => ({ ...window, retired: true })),
      {
        id: crypto.randomUUID(),
        deliveryOn: "2026-09-01",
        startsAt: "09:00",
        endsAt: "10:00",
        retired: false,
      },
    ]);
    await form.locator("[data-delivery-reload]").click();
    await expect(form.locator('[name="deliveryWindowId"] option')).toHaveCount(
      1,
    );
    await expect(form.locator("#deliveryWindowId-help")).toContainText(
      "keine Lieferfenster verfügbar",
    );
    await expect(form.locator('[name="deliveryRecipientName"]')).toHaveValue(
      "Erhaltener neuer Empfang",
    );
    const noJs = await browser.newContext({
      javaScriptEnabled: false,
      ignoreHTTPSErrors: true,
    });
    try {
      const noJsForm = await openOrderForm(await noJs.newPage());
      await expect(
        noJsForm.locator('[name="deliveryWindowId"] option'),
      ).toHaveCount(1);
      await expect(noJsForm.locator("#deliveryWindowId-help")).toContainText(
        "Eine Bestellung ist erst mit einem verfügbaren Fenster möglich",
      );
      await expect(
        noJsForm.locator('[name="deliveryWindowId"]'),
      ).toHaveAttribute("required", "");
    } finally {
      await noJs.close();
    }
    await save(original.enabled, original.windows);
    await form.locator("[data-delivery-reload]").click();
    await expect(form.locator('[name="deliveryWindowId"] option')).toHaveCount(
      original.windows.filter((window) => !window.retired).length + 1,
    );
    const commitmentsUrl = url.replace(/\/delivery$/, "/commitments");
    const before = await (await admin.request.get(commitmentsUrl)).json();
    for (const javaScriptEnabled of [true, false]) {
      await save(false, original.windows);
      const staleContext = await browser.newContext({
        javaScriptEnabled,
        reducedMotion: "reduce",
        viewport: { width: 390, height: 844 },
        ignoreHTTPSErrors: true,
      });
      try {
        const stalePage = await staleContext.newPage();
        const staleForm = await openOrderForm(stalePage);
        await fillOrder(staleForm, {
          companyName: "Policy Test GmbH",
          givenName: "Test",
          familyName: "Policy",
          email: "policy@example.invalid",
          recipient: "Erhaltener Policy-Empfang",
          city: "Augsburg",
          quantity: 1,
          deliveryEnabled: false,
        });
        await save(true, original.windows);
        if (javaScriptEnabled) {
          await staleForm.locator('button[type="submit"]').click();
        } else {
          await Promise.all([
            stalePage.waitForNavigation(),
            staleForm.locator('button[type="submit"]').click(),
          ]);
        }
        await expect(staleForm.locator("[data-form-message]")).toBeVisible();
        await expect(staleForm.locator("[data-form-message]")).toContainText(
          "Liefer",
        );
        await expect(
          staleForm.locator('[name="deliveryRecipientName"]'),
        ).toHaveValue("Erhaltener Policy-Empfang");
        await expect(
          staleForm.locator('[name="quantity"]').first(),
        ).toHaveValue("1");
        await expect(
          staleForm.locator('[name="privacyAcknowledged"]'),
        ).toBeChecked();
        if (javaScriptEnabled)
          await staleForm.locator("[data-delivery-reload]").click();
        await expect(
          staleForm.locator('[name="deliveryWindowId"]'),
        ).toBeEnabled();
        await expect(
          staleForm.locator('[name="deliveryWindowId"]'),
        ).toHaveAttribute("required", "");
        await staleForm
          .locator('[name="deliveryWindowId"]')
          .selectOption("90000000-0000-4000-8000-000000000072");
        await expect(
          staleForm.locator('[name="deliveryRecipientName"]'),
        ).toHaveValue("Erhaltener Policy-Empfang");
      } finally {
        await staleContext.close();
      }
    }
    const after = await (await admin.request.get(commitmentsUrl)).json();
    expect(after.items.length).toBe(before.items.length);
  } finally {
    await save(original.enabled, original.windows);
    await admin.close();
  }
});

test("Gemeinsame Lieferplanung erreicht Anna und öffentliche Bestellung ohne Neubau", async ({
  browser,
}) => {
  const contexts = [];
  async function openContext(token) {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      reducedMotion: "reduce",
      viewport: { width: 390, height: 844 },
    });
    contexts.push(context);
    if (token)
      await context.addCookies([
        {
          name: "__Host-leonaid_session",
          value: token,
          url: baseUrl,
          httpOnly: true,
          secure: true,
          sameSite: "Lax",
        },
      ]);
    return context;
  }
  try {
    expect(process.env.ANNA_SESSION).toBeTruthy();
    expect(process.env.KLARA_SESSION).toBeTruthy();
    const admin = await openContext(process.env.KLARA_SESSION);
    const anna = await openContext(process.env.ANNA_SESSION);
    const visitor = await openContext();
    const adminPage = await admin.newPage();
    const annaPage = await anna.newPage();
    const publicPage = await visitor.newPage();
    const actionId = "20000000-0000-4000-8000-000000000001";
    const scheduleUrl = `${baseUrl}/api/v1/actions/${actionId}/delivery`;
    // Load both consumer forms before editing the operational configuration.
    await annaPage.goto(`${baseUrl}/app/commitments/new?action=${actionId}`);
    await expect(annaPage.locator("#delivery-date")).toBeVisible();
    await openOrderForm(publicPage);
    await adminPage.goto(`${baseUrl}/admin/actions/${actionId}`);
    await adminPage.getByTestId("management-tab-delivery").click();
    const editor = adminPage.locator(".delivery-editor");
    const firstDay = editor.locator(".delivery-day").first();
    await expect(firstDay.getByLabel("Datum", { exact: true })).toHaveValue(
      "2026-10-01",
    );
    for (const [index, start, end] of [
      [2, "11:00", "13:00"],
      [3, "13:00", "15:00"],
    ]) {
      await firstDay
        .getByRole("button", { name: "Zeitfenster hinzufügen", exact: true })
        .click();
      await firstDay.getByLabel(`Beginn ${index}`, { exact: true }).fill(start);
      await firstDay.getByLabel(`Ende ${index}`, { exact: true }).fill(end);
    }
    await firstDay
      .getByRole("button", { name: "Fenster auf neuen Tag kopieren" })
      .click();
    await editor.getByLabel("Datum", { exact: true }).last().fill("2026-10-02");
    await editor
      .getByRole("button", { name: "Tag hinzufügen", exact: true })
      .click();
    const thirdDay = editor.locator(".delivery-day").last();
    await thirdDay.getByLabel("Datum", { exact: true }).fill("2026-10-03");
    await thirdDay
      .getByRole("button", { name: "Zeitfenster hinzufügen", exact: true })
      .click();
    await thirdDay.getByLabel("Beginn 1", { exact: true }).fill("10:00");
    await thirdDay.getByLabel("Ende 1", { exact: true }).fill("12:00");
    const saved = adminPage.waitForResponse(
      (response) =>
        response.url() === scheduleUrl && response.request().method() === "PUT",
    );
    await editor
      .getByRole("button", { name: "Lieferplanung speichern" })
      .click();
    expect((await saved).status()).toBe(200);
    const configuration = await (await admin.request.get(scheduleUrl)).json();
    expect(configuration.windows).toHaveLength(7);
    expect(
      ["2026-10-01", "2026-10-02", "2026-10-03"].map(
        (date) =>
          configuration.windows.filter((window) => window.deliveryOn === date)
            .length,
      ),
    ).toEqual([3, 3, 1]);
    await annaPage.reload();
    await publicPage
      .getByRole("button", { name: "Lieferfenster aktualisieren" })
      .click();
    const capture = await (
      await anna.request.get(
        `${baseUrl}/api/v1/actions/${actionId}/commitment-capture`,
      )
    ).json();
    expect(capture.delivery.windows.map((window) => window.id).sort()).toEqual(
      configuration.windows.map((window) => window.id).sort(),
    );
    const publicOptions = publicPage.locator(
      "#deliveryWindowId option[value]:not([value=''])",
    );
    await expect(publicOptions).toHaveCount(7);
    expect(
      await publicOptions.evaluateAll((options) =>
        options.map((option) => option.value).sort(),
      ),
    ).toEqual(configuration.windows.map((window) => window.id).sort());
    for (const date of ["2026-10-01", "2026-10-02", "2026-10-03"]) {
      await annaPage.locator("#delivery-date").selectOption(date);
      await expect(annaPage.locator("#delivery-window")).toHaveValue("");
      const options = annaPage.locator(
        "#delivery-window option[value]:not([value=''])",
      );
      expect(
        await options.evaluateAll((items) =>
          items.map((item) => item.value).sort(),
        ),
      ).toEqual(
        configuration.windows
          .filter((window) => window.deliveryOn === date)
          .map((window) => window.id)
          .sort(),
      );
    }
    await expect(publicPage.locator("#deliveryWindowId")).toHaveValue("");
    await expect(publicPage.locator("#deliveryWindowId")).toHaveAttribute(
      "required",
      "",
    );
    await expect(annaPage.locator("#delivery-contact")).toBeVisible();
    await expect(annaPage.locator("#delivery-instructions")).toBeVisible();
    await expect(publicPage.locator("#deliveryContactName")).toBeVisible();
    await expect(publicPage.locator("#deliveryInstructions")).toBeVisible();
    let selectedWindow = configuration.windows.find(
      (window) => window.deliveryOn === "2026-10-03",
    );
    for (const [field, value] of Object.entries({
      recipientName: "Gemeinsame Lieferstelle",
      streetLine1: "Lieferweg 31",
      postalCode: "97070",
      city: "Würzburg",
    })) {
      await annaPage.locator(`#delivery-${field}`).fill(value);
    }
    await annaPage
      .locator("#delivery-contact")
      .fill("Gemeinsamer Lieferkontakt");
    await annaPage.locator("#delivery-phone").fill("+49 931 313131");
    await annaPage
      .locator("#delivery-instructions")
      .fill("Abteilung Integration\nEingang links");
    await annaPage.locator("#delivery-window").selectOption(selectedWindow.id);
    await annaPage
      .locator("#commitment-email")
      .fill("integration-rechnung@leonaid.invalid");
    const publicForm = publicPage.locator("[data-order-form]");
    await fillOrder(publicForm, {
      email: "integration-bestellung@leonaid.invalid",
      givenName: "Irene",
      familyName: "Integration",
      quantity: 1,
      recipient: "Gemeinsame Lieferstelle",
      street: "Lieferweg 31",
      postalCode: "97070",
      city: "Würzburg",
    });
    await publicForm
      .locator("#deliveryWindowId")
      .selectOption(selectedWindow.id);
    await publicForm.locator("#deliveryCountryCode").fill("DE");
    await publicForm
      .locator("#deliveryContactName")
      .fill("Gemeinsamer Lieferkontakt");
    await publicForm
      .locator('input[name="deliveryContactPhone"]')
      .fill("+49 931 313131");
    await publicForm
      .locator("#deliveryInstructions")
      .fill("Abteilung Integration\nEingang links");
    await publicForm.locator('input[name="billingSameAsDelivery"]').uncheck();
    for (const [field, value] of Object.entries({
      invoiceRecipientName: "Zentrale Integration",
      invoiceStreetLine1: "Rechnungsweg 32",
      invoicePostalCode: "97070",
      invoiceCity: "Würzburg",
      invoiceCountryCode: "DE",
    })) {
      await publicForm.locator(`#${field}`).fill(value);
    }
    const retiredWindowId = selectedWindow.id;
    const beforeOrders = await (
      await admin.request.get(
        `${baseUrl}/api/v1/actions/${actionId}/commitments`,
      )
    ).json();
    await thirdDay.getByLabel("Zur Auswahl", { exact: true }).uncheck();
    const retiredResponse = adminPage.waitForResponse(
      (response) =>
        response.url() === scheduleUrl && response.request().method() === "PUT",
    );
    await editor
      .getByRole("button", { name: "Lieferplanung speichern" })
      .click();
    expect((await retiredResponse).status()).toBe(200);
    const rejectedAnna = annaPage.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith(`/actions/${actionId}/commitments`),
    );
    await annaPage.getByTestId("commitment-save-ready").click();
    expect((await (await rejectedAnna).json()).error.code).toBe(
      "delivery_window_unavailable",
    );
    await expect(
      annaPage.getByText(/Dieses Lieferfenster ist nicht mehr verfügbar/),
    ).toBeVisible();
    await publicForm.locator('button[type="submit"]').click();
    await expect(publicForm.locator("[data-form-message]")).toContainText(
      /Liefer/,
    );
    await expect(annaPage.locator("#delivery-streetLine1")).toHaveValue(
      "Lieferweg 31",
    );
    await expect(annaPage.locator("#delivery-instructions")).toHaveValue(
      "Abteilung Integration\nEingang links",
    );
    await expect(publicForm.locator("#deliveryStreetLine1")).toHaveValue(
      "Lieferweg 31",
    );
    await expect(publicForm.locator("#deliveryInstructions")).toHaveValue(
      "Abteilung Integration\nEingang links",
    );
    await expect(publicForm.locator("#invoiceStreetLine1")).toHaveValue(
      "Rechnungsweg 32",
    );
    await expect(
      publicForm.locator('input[name="privacyAcknowledged"]'),
    ).toBeChecked();
    const afterRejections = await (
      await admin.request.get(
        `${baseUrl}/api/v1/actions/${actionId}/commitments`,
      )
    ).json();
    expect(afterRejections.items).toHaveLength(beforeOrders.items.length);
    await annaPage
      .getByRole("button", { name: "Lieferfenster neu laden" })
      .click();
    await publicPage
      .getByRole("button", { name: "Lieferfenster aktualisieren" })
      .click();
    await expect(
      publicForm.locator(
        `#deliveryWindowId option[value="${retiredWindowId}"]`,
      ),
    ).toHaveCount(0);
    await expect(publicForm.locator("#deliveryWindowId")).toHaveValue("");
    selectedWindow = configuration.windows.find(
      (window) => window.deliveryOn === "2026-10-02",
    );
    await annaPage
      .locator("#delivery-date")
      .selectOption(selectedWindow.deliveryOn);
    await expect(annaPage.locator("#delivery-window")).toHaveValue("");
    await annaPage.locator("#delivery-window").selectOption(selectedWindow.id);
    await publicForm
      .locator("#deliveryWindowId")
      .selectOption(selectedWindow.id);
    const acceptedAnna = annaPage.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        response.url().endsWith(`/actions/${actionId}/commitments`),
    );
    await annaPage.getByTestId("commitment-save-ready").click();
    const annaResponse = await acceptedAnna;
    expect(annaResponse.status(), await annaResponse.text()).toBe(201);
    const annaOrder = await annaResponse.json();
    expect(annaOrder.deliveryWindowId).toBe(selectedWindow.id);
    expect(annaOrder.invoiceRecipient.streetLine1).toBe("Lieferweg 31");
    const publicOrder = await submitOrder(publicForm);
    const adminOrdersResponse = await admin.request.get(
      `${baseUrl}/api/v1/actions/${actionId}/commitments`,
    );
    expect(adminOrdersResponse.status()).toBe(200);
    const adminOrders = await adminOrdersResponse.json();
    const captured = adminOrders.items
      .map((item) => item.commitment)
      .filter(
        (order) =>
          order.deliveryRecipient?.contactName === "Gemeinsamer Lieferkontakt",
      );
    expect(captured).toHaveLength(2);
    for (const order of captured) {
      expect(order.deliveryRecipient.instructions).toBe(
        "Abteilung Integration\nEingang links",
      );
      expect(order.deliveryRecipient.streetLine1).toBe("Lieferweg 31");
      expect(order.deliveryWindowId).toBe(selectedWindow.id);
      expect(order.deliveryWindowSnapshot).toEqual(
        annaOrder.deliveryWindowSnapshot,
      );
      expect(order.invoiceRecipient.streetLine1).toBe(
        order.source === "acquisition" ? "Lieferweg 31" : "Rechnungsweg 32",
      );
    }
    await adminPage.goto(`${baseUrl}/admin/orders`);
    await expect(
      adminPage.getByRole("heading", { name: "Bestellungen prüfen" }),
    ).toBeVisible();
    for (const order of captured) {
      const row = adminPage.locator(`[data-commitment-id="${order.id}"]`);
      const disclosure = row.locator(".commitment-delivery-review summary");
      await disclosure.focus();
      await adminPage.keyboard.press("Enter");
      const details = row.locator(".commitment-delivery-review");
      await expect(details).toHaveAttribute("open", "");
      await expect(details).toContainText("Gemeinsamer Lieferkontakt");
      await expect(details).toContainText("+49 931 313131");
      await expect(
        details.locator(".commitment-delivery-instructions"),
      ).toHaveText("Abteilung Integration\nEingang links");
      await expect(details).toContainText("Europe/Berlin");
      await expect(details).toContainText(
        order.source === "acquisition"
          ? "Rechnung: Gemeinsame Lieferstelle, Lieferweg 31"
          : "Rechnung: Zentrale Integration, Rechnungsweg 32",
      );
      await disclosure.focus();
      await adminPage.keyboard.press("Enter");
      await expect(details).not.toHaveAttribute("open", "");
    }
    await writeFile(
      `${artifactDirectory}/delivery-cross-surface-policy.json`,
      JSON.stringify(
        {
          actionId,
          windows: configuration.windows,
          counts: [3, 3, 1],
          annaOrderId: annaOrder.id,
          publicReference: publicOrder.reference,
          selectedWindow,
          retiredWindowId,
          rejectedOrderCountUnchanged: true,
          channels: ["admin", "acquisition", "public"],
        },
        null,
        2,
      ),
    );
  } finally {
    for (const context of contexts) await context.close();
  }
});
