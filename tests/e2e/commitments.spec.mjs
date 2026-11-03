import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";
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

test("acquirer captures a review-ready order from the sponsor context", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-390",
    "The writing browser path runs exactly once in the lead mobile browser.",
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

test("order capture stays responsive and accessible in all target browsers", async ({
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

test("charity admin sees the same inbox and the same golden totals", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-1440",
    "The admin cross-check runs once in the lead desktop browser.",
  );
  await authenticate(context, klaraSession);
  await page.goto(`${baseUrl}/admin/orders?view=all`);
  await expect(
    page.getByRole("heading", { name: "Bestellungen", exact: true }),
  ).toBeVisible();

  const proof = JSON.parse(await readFile(proofPath, "utf8"));
  const commitmentId = proof.browserCapture.commitmentId;
  const rows = page.locator(".listview li.row");
  const createdRow = rows.filter({
    has: page.locator(`[data-order-id="${commitmentId}"]`),
  });
  await expect(createdRow).toContainText("Musterwerk GmbH");
  await expect(createdRow).toContainText("2 × Krapfenbox");
  await expect(createdRow).toContainText("Prüfbereit");
  await expect(
    createdRow.getByRole("img", { name: "Erfasst von Anna Akquise" }),
  ).toBeVisible();
  await expect(createdRow).toContainText("72,00 €");

  // Draft and review-ready differ by shape and colour.
  const draftStatus = rows.locator(".status-label.is-draft");
  const readyStatus = rows.locator(".status-label.is-review");
  await expect(draftStatus.first()).toBeVisible();
  await expect(readyStatus.first()).toBeVisible();
  const look = (status) =>
    status.first().evaluate((element) => {
      const icon = element.querySelector("svg");
      return `${icon.innerHTML}|${getComputedStyle(icon).color}`;
    });
  expect(await look(draftStatus)).not.toBe(await look(readyStatus));

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
  await expect(rows).toHaveCount(apiTotals.items.length);

  // The old status links still land on a filtered list.
  await page.goto(`${baseUrl}/admin/orders?status=draft`);
  await expect(rows.first()).toBeVisible();
  const draftCount = apiTotals.items.filter(
    (item) => item.commitment.status === "draft",
  ).length;
  await expect(rows).toHaveCount(draftCount);
  await expect(rows.locator(".status-label")).toHaveText(
    Array(draftCount).fill("Entwurf"),
  );
  await page.getByRole("button", { name: "Zu prüfen" }).click();
  await expect(createdRow).toBeVisible();
  await page.getByRole("button", { name: "Alle", exact: true }).click();
  await expect(rows).toHaveCount(apiTotals.items.length);

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

test("charity admin works the orders list by keyboard", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-1440",
    "The keyboard walk runs once in the lead desktop browser.",
  );
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await authenticate(context, klaraSession);
  await page.goto(`${baseUrl}/admin/orders?view=all`);
  await expect(
    page.getByRole("heading", { name: "Bestellungen", exact: true }),
  ).toBeVisible();
  const links = page.locator(".listview .row-link");
  await expect(links.first()).toBeVisible();
  expect(await links.count()).toBeGreaterThan(1);

  // j/k move, Enter opens the pane, Esc closes it and returns to the row.
  await page.keyboard.press("j");
  await expect(links.first()).toBeFocused();
  await page.keyboard.press("j");
  await expect(links.nth(1)).toBeFocused();
  await page.keyboard.press("k");
  await expect(links.first()).toBeFocused();
  await page.keyboard.press("Enter");
  const pane = page.getByRole("complementary", { name: /^Details: / });
  await expect(pane).toBeVisible();
  await expect(page).toHaveURL(/[?&]open=[0-9a-f-]{36}/);
  await expect(pane.locator("[data-commitment-id]")).toBeVisible();
  // Status is read-only: no property row to edit in the pane.
  await expect(pane.getByRole("group", { name: "Eigenschaften" })).toHaveCount(
    0,
  );
  await assertNoSeriousAxeFindings(page);
  await page.keyboard.press("j");
  await expect(links.nth(1)).toBeFocused();
  await expect(page).toHaveURL(/[?&]open=[0-9a-f-]{36}/);
  await page.keyboard.press("Escape");
  await expect(pane).toHaveCount(0);
  await expect(links.nth(1)).toBeFocused();
  await expect(page).not.toHaveURL(/[?&]open=/);

  // x checks rows into the bulk bar; Esc clears the selection.
  await page.keyboard.press("x");
  await page.keyboard.press("k");
  await page.keyboard.press("x");
  const bulk = page.getByRole("region", { name: "Auswahl" });
  await expect(bulk).toContainText("2 ausgewählt");
  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/commitment-admin-keyboard.png`,
    fullPage: false,
  });
  await page.keyboard.press("Escape");
  await expect(bulk).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});
