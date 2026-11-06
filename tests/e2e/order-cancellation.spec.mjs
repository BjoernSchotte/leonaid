import { analyzeAccessibility, WCAG_TAGS } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";
import { readFile } from "node:fs/promises";

/*
 * Klara Kern (charity admin) cancels the order Anna captured in
 * commitments.spec.mjs. Runs after the golden totals are verified
 * (tools/commitments/test.sh), because it changes them on purpose.
 */
const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_SESSION;
const proofPath = process.env.LEONAID_E2E_PROOF_PATH;
const actionId = "20000000-0000-4000-8000-000000000001";
// Golden order with the paid invoice KT26-0002.
const paidOrderId = "80000000-0000-4000-8000-000000000005";
const reason = "Sponsor hat die Bestellung zurückgezogen";

if (!baseUrl || !artifactDirectory || !klaraSession || !proofPath) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR, KLARA_SESSION und LEONAID_E2E_PROOF_PATH sind erforderlich",
  );
}

async function authenticate(context) {
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: klaraSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
}

async function assertNoSeriousAxeFindings(page) {
  const results = await analyzeAccessibility(page, { tags: WCAG_TAGS });
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

async function listOrders(page) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/actions/${id}/commitments`, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }, actionId);
}

test("charity admin cancels an order with a reason and sees it everywhere", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-1440",
    "The cancellation runs exactly once in the lead desktop browser.",
  );
  const proof = JSON.parse(await readFile(proofPath, "utf8"));
  const orderId = proof.browserCapture.commitmentId;
  await authenticate(context);
  await page.goto(`${baseUrl}/admin/orders?action=${actionId}&view=all`);
  await expect(
    page.getByRole("heading", { name: "Bestellungen", exact: true }),
  ).toBeVisible();
  const before = await listOrders(page);
  const totals = page.getByTestId("commitment-totals");
  await expect(totals).toHaveAttribute(
    "data-total-minor",
    String(before.currencyTotals[0].totalMinor),
  );

  const row = page.locator(".listview li.row").filter({
    has: page.locator(`[data-order-id="${orderId}"]`),
  });
  await row.locator(".row-link").click();
  const pane = page.getByRole("complementary", { name: /^Details: / });
  await expect(pane.locator(`[data-commitment-id="${orderId}"]`)).toBeVisible();

  await pane.getByTestId("open-order-cancellation").click();
  const dialog = page.getByRole("alertdialog", {
    name: "Bestellung von Musterwerk GmbH stornieren?",
  });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    "LeonAid benachrichtigt den Besteller nicht automatisch.",
  );
  await expect(dialog.getByTestId("order-cancellation-reason")).toBeFocused();
  await assertNoSeriousAxeFindings(page);

  // A reason is required, eight characters at least.
  await dialog.getByTestId("order-cancellation-reason").fill("zu kurz");
  await dialog.getByTestId("cancel-order").click();
  await expect(dialog).toContainText(
    "Bitte geben Sie einen Grund mit mindestens 8 Zeichen an.",
  );
  await dialog.getByTestId("order-cancellation-reason").fill(reason);
  await dialog
    .getByTestId("order-cancellation-note")
    .fill("Rückruf am Montag vereinbart.");
  await page.screenshot({
    path: `${artifactDirectory}/order-cancellation-dialog.png`,
  });
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        candidate.request().method() === "POST" &&
        candidate.url().endsWith(`/commitments/${orderId}/cancellation`),
    ),
    dialog.getByTestId("cancel-order").click(),
  ]);
  expect(response.status()).toBe(201);
  expect(response.request().headers()["idempotency-key"]).toMatch(
    /^order-cancellation:/,
  );
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("Bestellung storniert.")).toBeVisible();

  // The pane: stamp, Storno section, history; no second cancellation.
  await expect(pane.getByTestId("order-stamp")).toContainText("Storniert");
  await expect(pane.getByTestId("order-cancellation")).toContainText(reason);
  await expect(pane.getByTestId("order-cancellation")).toContainText(
    "Rückruf am Montag vereinbart.",
  );
  await expect(pane.getByText("Storniert von Klara Kern")).toBeVisible();
  await expect(pane.getByTestId("open-order-cancellation")).toHaveCount(0);

  // The list keeps it, struck through; totals no longer count it.
  await expect(row).toContainText("Storniert");
  await expect(row.locator(".is-struck")).toContainText("72,00");
  const after = await listOrders(page);
  expect(after.items).toHaveLength(before.items.length);
  expect(after.currencyTotals[0].totalMinor).toBe(
    before.currencyTotals[0].totalMinor - 7200,
  );
  expect(after.totalBoxes).toBe(before.totalBoxes - 2);
  await expect(totals).toHaveAttribute(
    "data-total-minor",
    String(after.currencyTotals[0].totalMinor),
  );
  const record = after.items.find((item) => item.commitment.id === orderId);
  expect(record.commitment.status).toBe("cancelled");
  expect(record.cancellation.reason).toBe(reason);
  expect(record.cancellation.requestedByDisplayName).toBe("Klara Kern");
  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/order-cancelled-pane.png`,
    fullPage: true,
  });

  // The status filter finds the cancelled orders.
  await page.goto(
    `${baseUrl}/admin/orders?action=${actionId}&view=all&f.status=cancelled`,
  );
  const rows = page.locator(".listview li.row");
  await expect(rows).toHaveCount(
    after.items.filter((item) => item.commitment.status === "cancelled").length,
  );
  await expect(
    rows.filter({ has: page.locator(`[data-order-id="${orderId}"]`) }),
  ).toBeVisible();
});

test("a paid order explains that the payment comes back first", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-1440",
    "The refusal runs exactly once in the lead desktop browser.",
  );
  await authenticate(context);
  await page.goto(
    `${baseUrl}/admin/orders?action=${actionId}&view=all&open=${paidOrderId}`,
  );
  const pane = page.getByRole("complementary", { name: /^Details: / });
  await expect(
    pane.locator(`[data-commitment-id="${paidOrderId}"]`),
  ).toBeVisible();
  await pane.getByTestId("open-order-cancellation").click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog.getByRole("alert")).toContainText(
    "Zur Rechnung KT26-0002 ist eine Zahlung erfasst. Buchen Sie die Zahlung in der Rechnung erst zurück (Zahlung zurückbuchen)",
  );
  await expect(dialog.getByTestId("cancel-order")).toBeDisabled();
  await assertNoSeriousAxeFindings(page);
  await dialog.getByRole("button", { name: "Abbrechen" }).click();
  await expect(dialog).toHaveCount(0);

  // The server refuses it too, without a trace.
  const refused = await page.evaluate(
    async ({ action, order }) => {
      const list = await fetch(`/api/v1/actions/${action}/commitments`, {
        credentials: "include",
      }).then((response) => response.json());
      const record = list.items.find((item) => item.commitment.id === order);
      const response = await fetch(
        `/api/v1/actions/${action}/commitments/${order}/cancellation`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `e2e-paid-refusal:${crypto.randomUUID()}`,
          },
          body: JSON.stringify({
            expectedVersion: record.commitment.deliveryCompletionVersion,
            reason: "Versuch trotz Zahlung",
          }),
        },
      );
      return { status: response.status, body: await response.json() };
    },
    { action: actionId, order: paidOrderId },
  );
  expect(refused.status).toBe(409);
  expect(refused.body.error.code).toBe(
    "commitment_cancellation_payment_recorded",
  );
});
