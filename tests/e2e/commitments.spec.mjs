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
  const sponsor = page
    .locator('[data-testid="sponsor-row"]')
    .filter({ hasText: "Musterwerk GmbH" });
  await expect(sponsor).toHaveCount(1);
  const captureLink = sponsor.getByRole("link", { name: "Bestellung" });
  const href = await captureLink.getAttribute("href");
  expect(href).toMatch(/^\/app\/commitments\/new\?/);
  await captureLink.click();
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
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-390",
    "Der schreibende Browserweg läuft genau einmal im mobilen Leitbrowser.",
  );
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
  await page.getByTestId("commitment-quantity").fill("2");
  await page.getByTestId("commitment-street").fill("Musterstraße 12");
  await expect(page.getByTestId("commitment-preview-total")).toHaveText(
    "72,00 €",
  );
  await expect(
    page.getByRole("heading", { name: "Bestellübersicht" }),
  ).toBeVisible();
  await expect(page.getByTestId("commitment-save-draft")).toBeVisible();
  await expect(page.getByTestId("commitment-save-ready")).toBeVisible();

  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/commitment-capture-mobile.png`,
    fullPage: true,
  });

  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        candidate.request().method() === "POST" &&
        candidate.url().includes("/commitments"),
    ),
    page.getByTestId("commitment-save-ready").click(),
  ]);
  expect(response.status()).toBe(201);
  const payload = await response.json();
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
    const scaledOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(scaledOverflow).toBeLessThanOrEqual(1);
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
