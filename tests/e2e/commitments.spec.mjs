import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;
const klaraSession = process.env.KLARA_SESSION;
const proofPath = process.env.LEONAID_E2E_PROOF_PATH;

if (
  !baseUrl ||
  !artifactDirectory ||
  !annaSession ||
  !klaraSession ||
  !proofPath
) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR, ANNA_SESSION, KLARA_SESSION und LEONAID_E2E_PROOF_PATH sind erforderlich",
  );
}

async function authenticate(context, token) {
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
}

async function assertNoSeriousAxeFindings(page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const severe = results.violations.filter(({ impact }) =>
    ["critical", "serious"].includes(impact),
  );
  expect(
    severe,
    severe
      .map(
        (violation) =>
          `${violation.id}: ${violation.description} (${violation.nodes.length})`,
      )
      .join("\n"),
  ).toEqual([]);
}

async function openMusterwerkCapture(context, page) {
  await authenticate(context, annaSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.locator('[data-testid="display-name"]')).toHaveText(
    "Anna Akquise",
  );
  await page
    .getByTestId("sponsor-action")
    .selectOption("20000000-0000-4000-8000-000000000001");
  const sponsor = page
    .locator('[data-testid="sponsor-row"]')
    .filter({ hasText: "Musterwerk GmbH" });
  await expect(sponsor).toHaveCount(1);
  const captureLink = sponsor.getByRole("link", { name: "Bestellung" });
  const href = await captureLink.getAttribute("href");
  expect(href).toMatch(/^\/app\/commitments\/new\?/);
  await Promise.all([
    page.waitForURL(/\/app\/commitments\/new\?/),
    captureLink.click(),
  ]);
  await expect(
    page.getByRole("heading", {
      name: "Vom Gespräch zur klaren Bestellung.",
    }),
  ).toBeVisible();
  await expect(page.getByTestId("commitment-party")).toContainText(
    "Musterwerk GmbH",
  );
}

test("Akquisiteurin erfasst eine prüfbereite Bestellung aus dem Sponsorkontext", async ({
  browser,
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-390",
    "Der schreibende Browserweg läuft genau einmal im mobilen Leitbrowser.",
  );
  const adminContext = await browser.newContext({ ignoreHTTPSErrors: true });
  await authenticate(adminContext, klaraSession);
  const scheduleUrl = `${baseUrl}/api/v1/actions/20000000-0000-4000-8000-000000000001/delivery`;
  const schedule = await (await adminContext.request.get(scheduleUrl)).json();
  const configured = await adminContext.request.put(scheduleUrl, {
    data: {
      revision: schedule.revision,
      enabled: true,
      timezone: "Europe/Berlin",
      windows: [
        {
          id: "90000000-0000-4000-8000-000000000081",
          deliveryOn: "2026-10-01",
          startsAt: "09:00",
          endsAt: "11:00",
          retired: false,
        },
      ],
    },
  });
  expect(configured.status()).toBe(200);
  await openMusterwerkCapture(context, page);

  await expect(page.getByTestId("commitment-offering")).toHaveValue(
    "70000000-0000-4000-8000-000000000001",
  );
  await expect(page.locator("#commitment-offering-help")).toContainText(
    "aktuell bestellbare Angebote",
  );
  await expect(page.locator("#commitment-quantity-help")).toContainText(
    "Einheit: Boxen",
  );
  await expect(page.getByTestId("commitment-preview-total")).toHaveText(
    "36,00 €",
  );
  // Switching buyers must not carry another recipient's private delivery data.
  const buyerSelect = page.getByTestId("commitment-sponsor");
  const originalBuyer = await buyerSelect.inputValue();
  const otherBuyer = await buyerSelect
    .locator("option")
    .evaluateAll(
      (options, selected) =>
        options.find((option) => option.value && option.value !== selected)
          ?.value,
      originalBuyer,
    );
  expect(otherBuyer).toBeTruthy();
  await page.locator("#delivery-streetLine1").fill("Private Lieferadresse 99");
  await page.locator("#delivery-contact").fill("Kontakt des ersten Bestellers");
  await page.locator("#delivery-phone").fill("+49 931 99999");
  await page
    .locator("#delivery-instructions")
    .fill("Vertraulicher Zugangshinweis");
  await page.locator("#delivery-date").selectOption("2026-10-01");
  await page
    .locator("#delivery-window")
    .selectOption("90000000-0000-4000-8000-000000000081");
  await page
    .getByLabel("Rechnungsadresse entspricht der Lieferadresse")
    .uncheck();
  await page.getByTestId("commitment-street").fill("Private Rechnung 99");
  await page.locator("#commitment-email").fill("privat@beispiel.invalid");
  await buyerSelect.selectOption(otherBuyer);
  await expect(page.locator("#delivery-streetLine1")).toHaveValue("");
  await expect(page.locator("#delivery-contact")).toHaveValue("");
  await expect(page.locator("#delivery-phone")).toHaveValue("");
  await expect(page.locator("#delivery-instructions")).toHaveValue("");
  await expect(page.locator("#delivery-date")).toHaveValue("");
  await expect(
    page.getByLabel("Rechnungsadresse entspricht der Lieferadresse"),
  ).toBeChecked();
  await page
    .getByLabel("Rechnungsadresse entspricht der Lieferadresse")
    .uncheck();
  await expect(page.getByTestId("commitment-street")).toHaveValue("");
  await expect(page.locator("#commitment-email")).not.toHaveValue(
    "privat@beispiel.invalid",
  );
  await buyerSelect.selectOption(originalBuyer);
  await expect(page.getByTestId("commitment-party")).toContainText(
    "Musterwerk GmbH",
  );
  await expect(page.locator("#delivery-streetLine1")).toHaveValue("");
  await expect(
    page.getByLabel("Rechnungsadresse entspricht der Lieferadresse"),
  ).toBeChecked();

  await page.locator("#delivery-streetLine1").fill("Nur erste Aktion 18");
  await page
    .locator("#delivery-instructions")
    .fill("Hinweis der ersten Aktion");
  await page.locator("#delivery-contact").fill("Kontakt der ersten Aktion");
  await page.locator("#delivery-date").selectOption("2026-10-01");
  await page
    .locator("#delivery-window")
    .selectOption("90000000-0000-4000-8000-000000000081");
  await page.getByLabel("Lieferdaten später ergänzen (nur Entwurf)").check();
  await page
    .locator("#commitment-action")
    .selectOption("20000000-0000-4000-8000-000000000003");
  await expect(page.getByTestId("commitment-sponsor")).toHaveValue("");
  await expect(page.getByTestId("commitment-save-ready")).toBeDisabled();
  await page
    .locator("#commitment-action")
    .selectOption("20000000-0000-4000-8000-000000000001");
  await expect(page.locator("#delivery-streetLine1")).toHaveValue("");
  await expect(page.locator("#delivery-instructions")).toHaveValue("");
  await expect(page.locator("#delivery-contact")).toHaveValue("");
  await expect(page.locator("#delivery-date")).toHaveValue("");
  await expect(
    page.getByLabel("Lieferdaten später ergänzen (nur Entwurf)"),
  ).not.toBeChecked();
  await expect(
    page.getByLabel("Rechnungsadresse entspricht der Lieferadresse"),
  ).toBeChecked();
  await buyerSelect.selectOption(originalBuyer);
  await page.getByTestId("commitment-quantity").fill("2");
  await page.locator("#delivery-streetLine1").fill("Lieferstraße 8");
  const sameAddress = page.getByLabel(
    "Rechnungsadresse entspricht der Lieferadresse",
  );
  await sameAddress.uncheck();
  await page.getByTestId("commitment-street").fill("Rechnungsstraße 4");
  await sameAddress.check();
  await sameAddress.uncheck();
  await expect(page.getByTestId("commitment-street")).toHaveValue(
    "Rechnungsstraße 4",
  );
  await sameAddress.check();
  await page.locator("#delivery-streetLine1").fill("Lieferstraße 12");
  await page.locator("#delivery-date").selectOption("2026-10-01");
  await expect(page.locator("#delivery-window")).toHaveValue("");
  await page
    .locator("#delivery-window")
    .selectOption("90000000-0000-4000-8000-000000000081");
  await page.locator("#delivery-date").selectOption("");
  await expect(page.locator("#delivery-window")).toHaveValue("");
  await page.locator("#delivery-date").selectOption("2026-10-01");
  await page
    .locator("#delivery-window")
    .selectOption("90000000-0000-4000-8000-000000000081");
  const deferDelivery = page.getByLabel(
    "Lieferdaten später ergänzen (nur Entwurf)",
  );
  await deferDelivery.check();
  await expect(page.getByTestId("commitment-save-ready")).toBeDisabled();
  await expect(page.getByTestId("commitment-save-draft")).toBeEnabled();
  await deferDelivery.uncheck();
  await expect(page.locator("#delivery-streetLine1")).toHaveValue(
    "Lieferstraße 12",
  );
  await page.locator("#delivery-contact").fill("Alex Lieferung");
  await page.locator("#delivery-phone").fill("+49 931 123456");
  await page
    .locator("#delivery-instructions")
    .fill("Abteilung Bildung\nVierter Stock, Eingang links <b>Test</b>");
  await page.locator("#commitment-email").fill("rechnung@beispiel.invalid");
  await expect(page.getByTestId("commitment-preview-total")).toHaveText(
    "72,00 €",
  );
  await expect(
    page.getByRole("heading", { name: "Bestellübersicht" }),
  ).toBeVisible();
  await expect(page.getByTestId("commitment-save-draft")).toBeVisible();
  await expect(page.getByTestId("commitment-save-ready")).toBeVisible();

  await assertNoSeriousAxeFindings(page);
  await page.evaluate(() => {
    document.activeElement?.blur();
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  await page.screenshot({
    path: `${artifactDirectory}/commitment-capture-mobile.png`,
    fullPage: true,
  });

  const currentSchedule = await configured.json();
  const replacementId = "90000000-0000-4000-8000-000000000082";
  const retired = await adminContext.request.put(scheduleUrl, {
    data: {
      revision: currentSchedule.revision,
      enabled: true,
      timezone: "Europe/Berlin",
      windows: [
        { ...currentSchedule.windows[0], retired: true },
        {
          ...currentSchedule.windows[0],
          id: replacementId,
          startsAt: "11:00",
          endsAt: "13:00",
          retired: false,
        },
      ],
    },
  });
  expect(retired.status(), await retired.text()).toBe(200);
  const [rejected] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        candidate.request().method() === "POST" &&
        candidate.url().includes("/commitments"),
    ),
    page.getByTestId("commitment-save-ready").click(),
  ]);
  expect((await rejected.json()).error.code).toBe(
    "delivery_window_unavailable",
  );
  await expect(
    page.getByText(/Dieses Lieferfenster ist nicht mehr verfügbar/),
  ).toBeVisible();
  await expect(page.locator("#delivery-streetLine1")).toHaveValue(
    "Lieferstraße 12",
  );
  await expect(page.locator("#delivery-instructions")).toHaveValue(
    "Abteilung Bildung\nVierter Stock, Eingang links <b>Test</b>",
  );
  await page.getByRole("button", { name: "Lieferfenster neu laden" }).click();
  await expect(
    page.locator(`#delivery-window option[value="${replacementId}"]`),
  ).toHaveCount(1);
  await page.locator("#delivery-window").selectOption(replacementId);
  const submissionPattern = "**/api/v1/actions/*/commitments";
  let acceptedBeforeFailure;
  let interceptedPosts = 0;
  const loseResponse = async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    interceptedPosts += 1;
    const accepted = await route.fetch();
    expect(accepted.status()).toBe(201);
    acceptedBeforeFailure = await accepted.json();
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "response_unavailable",
          requestId: "delivery-response-loss-proof",
          message: "Die Antwort konnte nicht zugestellt werden.",
        },
      }),
    });
  };
  await page.route(submissionPattern, loseResponse);
  await page.getByTestId("commitment-save-ready").click();
  await expect(page.getByText(/Die Serverantwort ist unklar/)).toBeVisible();
  await page.locator("#delivery-streetLine1").fill("Geänderte Lieferstraße 12");
  await page.getByTestId("commitment-save-ready").click();
  await expect(
    page.getByText(/Ausgang der letzten Übermittlung ist noch unklar/),
  ).toBeVisible();
  expect(interceptedPosts).toBe(1);
  await page.locator("#delivery-streetLine1").fill("Lieferstraße 12");
  await page.unroute(submissionPattern, loseResponse);
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        candidate.request().method() === "POST" &&
        candidate.url().includes("/commitments"),
    ),
    page.getByTestId("commitment-save-ready").click(),
  ]);
  expect(response.status(), await response.text()).toBe(201);
  const payload = await response.json();
  expect(payload.id).toBe(acceptedBeforeFailure.id);
  expect(payload.replayed).toBe(true);
  expect(payload.deliveryRecipient.streetLine1).toBe("Lieferstraße 12");
  expect(payload.invoiceRecipient.streetLine1).toBe("Lieferstraße 12");
  expect(payload.invoiceRecipient.email).toBe("rechnung@beispiel.invalid");
  expect(payload.deliveryRecipient.contactName).toBe("Alex Lieferung");
  expect(payload.deliveryRecipient.instructions).toBe(
    "Abteilung Bildung\nVierter Stock, Eingang links <b>Test</b>",
  );
  expect(payload.deliveryWindowSnapshot.deliveryOn).toBe("2026-10-01");
  expect(payload.deliveryWindowSnapshot.startsAt).toBe("11:00");
  expect(response.request().headers()["idempotency-key"]).not.toBe(
    rejected.request().headers()["idempotency-key"],
  );
  await adminContext.close();
  await expect(page.getByTestId("commitment-success")).toBeVisible();
  await expect(page.getByTestId("commitment-success")).toContainText(
    "Bereit für die Prüfung",
  );
  await expect(
    page.locator('.commitment-status[data-status="review_ready"]'),
  ).toHaveText("Prüfbereit");
  await expect(page.getByTestId("commitment-success")).toHaveAttribute(
    "data-commitment-id",
    payload.id,
  );
  await expect(page.locator("#commitment-success-heading")).toBeFocused();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({
    path: `${artifactDirectory}/commitment-success-mobile.png`,
    fullPage: true,
  });
  await writeFile(
    proofPath,
    `${JSON.stringify(
      {
        browserCapture: {
          commitmentId: payload.id,
          status: payload.status,
          totalBoxes: payload.totalBoxes,
          totalMinor: payload.totalMinor,
          totalPieces: payload.totalPieces,
        },
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
});

test("Bestellerfassung bleibt in allen Zielbrowsern responsiv und barrierearm", async ({
  context,
  page,
}, testInfo) => {
  await openMusterwerkCapture(context, page);

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  for (const locator of [
    page.getByTestId("commitment-sponsor"),
    page.getByTestId("commitment-quantity"),
    page.getByTestId("commitment-save-ready"),
    page.locator("#delivery-streetLine1"),
    page.locator("#delivery-contact"),
    page.locator("#delivery-phone"),
    page.locator("#delivery-instructions"),
    page.locator("#delivery-date"),
  ]) {
    const box = await locator.boundingBox();
    expect(box).not.toBeNull();
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
  await assertNoSeriousAxeFindings(page);

  if (testInfo.project.name === "chromium-390") {
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "32px";
    });
    for (const width of [360, 390, 430]) {
      await page.setViewportSize({ width, height: 844 });
      const scaledOverflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(scaledOverflow).toBeLessThanOrEqual(1);
    }
    await assertNoSeriousAxeFindings(page);
  }

  await page.screenshot({
    path: `${artifactDirectory}/commitment-capture-${testInfo.project.name}.png`,
    fullPage: true,
  });
});

test("Charity-Admin sieht denselben Eingang und dieselben Golden-Summen", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-1440",
    "Der Admin-Abgleich läuft einmal im Desktop-Leitbrowser.",
  );
  await authenticate(context, klaraSession);
  await page.goto(`${baseUrl}/admin/orders`);
  await expect(
    page.getByRole("heading", { name: "Bestellungen prüfen" }),
  ).toBeVisible();

  const proof = JSON.parse(await readFile(proofPath, "utf8"));
  const commitmentId = proof.browserCapture.commitmentId;
  const createdRow = page.locator(
    `[data-testid="commitment-row"][data-commitment-id="${commitmentId}"]`,
  );
  await expect(createdRow).toContainText("Musterwerk GmbH");
  await expect(createdRow).toContainText("2 × Krapfenbox");
  await expect(createdRow).toContainText("Prüfbereit");
  await expect(createdRow).toContainText("Erfasst von Anna Akquise");
  await expect(createdRow).toContainText("72,00 €");
  await createdRow
    .getByText("Liefer- und Rechnungsdaten ansehen", { exact: true })
    .click();
  await expect(createdRow).toContainText("Lieferstraße 12");
  await expect(createdRow).toContainText("Alex Lieferung");
  await expect(createdRow).toContainText(
    "Vierter Stock, Eingang links <b>Test</b>",
  );
  await expect(
    createdRow.locator(".commitment-delivery-instructions b"),
  ).toHaveCount(0);

  const draftStatus = page.locator('.commitment-status[data-status="draft"]');
  const readyStatus = page.locator(
    '.commitment-status[data-status="review_ready"]',
  );
  await expect(draftStatus.first()).toBeVisible();
  await expect(readyStatus.first()).toBeVisible();
  expect(
    await draftStatus.first().evaluate((element) => {
      const style = getComputedStyle(element);
      return `${style.borderStyle}|${style.color}|${style.backgroundColor}`;
    }),
  ).not.toBe(
    await readyStatus.first().evaluate((element) => {
      const style = getComputedStyle(element);
      return `${style.borderStyle}|${style.color}|${style.backgroundColor}`;
    }),
  );

  const apiTotals = await page.evaluate(async () => {
    const response = await fetch(
      "/api/v1/actions/20000000-0000-4000-8000-000000000001/commitments",
      { credentials: "include", headers: { Accept: "application/json" } },
    );
    if (!response.ok) {
      throw new Error(`Admin-API antwortet mit HTTP ${response.status}`);
    }
    return response.json();
  });
  const totals = page.getByTestId("commitment-totals");
  await expect(totals).toHaveAttribute(
    "data-total-minor",
    String(apiTotals.currencyTotals[0].totalMinor),
  );
  await expect(totals).toHaveAttribute(
    "data-total-boxes",
    String(apiTotals.totalBoxes),
  );
  await expect(totals).toHaveAttribute(
    "data-total-pieces",
    String(apiTotals.totalPieces),
  );
  expect(await page.locator('[data-testid="commitment-row"]').count()).toBe(
    apiTotals.items.length,
  );

  await page.getByRole("tab", { name: "Entwürfe" }).click();
  await expect(
    page.locator('[data-testid="commitment-row"] .commitment-status'),
  ).toHaveText(await draftStatus.allTextContents());
  await page.getByRole("tab", { name: "Prüfbereit" }).click();
  await expect(createdRow).toBeVisible();
  await page.getByRole("tab", { name: "Alle" }).click();

  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/commitment-admin-desktop.png`,
    fullPage: true,
  });
  await writeFile(
    proofPath,
    `${JSON.stringify(
      {
        ...proof,
        adminBrowser: {
          itemCount: apiTotals.items.length,
          totalBoxes: Number(await totals.getAttribute("data-total-boxes")),
          totalMinor: Number(await totals.getAttribute("data-total-minor")),
          totalPieces: Number(await totals.getAttribute("data-total-pieces")),
        },
        adminApi: {
          itemCount: apiTotals.items.length,
          totalBoxes: apiTotals.totalBoxes,
          totalMinor: apiTotals.currencyTotals[0].totalMinor,
          totalPieces: apiTotals.totalPieces,
        },
      },
      null,
      2,
    )}\n`,
    "utf8",
  );
});
