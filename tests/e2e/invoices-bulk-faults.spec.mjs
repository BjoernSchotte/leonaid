import { expect, test } from "./csp-guard.mjs";

/*
 * Bulk invoice release under transport faults, against the real stack.
 * The only interception: for one order, the request reaches the real
 * server, which commits the invoice; the browser then loses that answer.
 * Every other request and response passes unchanged. Runs after
 * invoices.spec.mjs (tools/invoices/test.sh) on the orders that
 * tools/invoices/browser_setup.py seeds for it.
 */

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const mailpitBaseUrl = process.env.LEONAID_E2E_MAILPIT_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const klaraSession = process.env.KLARA_FAULT_SESSION;
const email = "klara.kern@leonaid.invalid";
const actionId = "20000000-0000-4000-8000-000000000001";
const orders = {
  vier: "80000000-0000-4000-8000-0000000000b4",
  fuenf: "80000000-0000-4000-8000-0000000000b5",
  sechs: "80000000-0000-4000-8000-0000000000b6",
  sieben: "80000000-0000-4000-8000-0000000000b7",
};

if (!baseUrl || !mailpitBaseUrl || !artifactDirectory || !klaraSession) {
  throw new Error("Bulk fault browser environment is incomplete");
}

test.setTimeout(90_000);
test.describe.configure({ mode: "serial" });

function recipientAddresses(value) {
  const result = new Set();
  if (typeof value === "string") {
    if (value.includes("@")) result.add(value.toLowerCase());
  } else if (Array.isArray(value)) {
    for (const item of value) {
      for (const address of recipientAddresses(item)) result.add(address);
    }
  } else if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (
        ["address", "email"].includes(key.toLowerCase()) &&
        typeof item === "string"
      ) {
        result.add(item.toLowerCase());
      } else {
        for (const address of recipientAddresses(item)) result.add(address);
      }
    }
  }
  return result;
}

async function messageIds(request) {
  const response = await request.get(`${mailpitBaseUrl}/api/v1/messages`);
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  return new Set(
    (payload.messages ?? [])
      .map((message) => message.ID)
      .filter((id) => typeof id === "string"),
  );
}

async function waitForCode(request, previousIds) {
  let code;
  await expect
    .poll(
      async () => {
        const response = await request.get(`${mailpitBaseUrl}/api/v1/messages`);
        if (!response.ok()) return "mailpit-unavailable";
        const payload = await response.json();
        for (const summary of payload.messages ?? []) {
          if (
            previousIds.has(summary.ID) ||
            !recipientAddresses(summary.To).has(email)
          ) {
            continue;
          }
          const detailResponse = await request.get(
            `${mailpitBaseUrl}/api/v1/message/${summary.ID}`,
          );
          if (!detailResponse.ok()) continue;
          const detail = await detailResponse.json();
          const match =
            typeof detail.Text === "string"
              ? detail.Text.match(/\bCode ([0-9]{6})\b/)
              : null;
          if (match) {
            code = match[1];
            return "ready";
          }
        }
        return "pending";
      },
      {
        message: "echte Mailpit-Mail mit Fresh-Login-Code",
        timeout: 30_000,
        intervals: [100, 200, 400],
      },
    )
    .toBe("ready");
  return code;
}

/** Lose the answer of the first successful issue for this order, once. */
async function dropFirstAnswer(page, commitmentId) {
  const state = { dropped: false };
  await page.route(
    `**/api/v1/actions/${actionId}/commitments/${commitmentId}/invoice`,
    async (route) => {
      const response = await route.fetch();
      if (response.ok() && !state.dropped) {
        state.dropped = true;
        await route.abort("connectionreset");
        return;
      }
      await route.fulfill({ response });
    },
  );
  return state;
}

async function invoicesFor(page, commitmentId) {
  const response = await page.request.get(
    `${baseUrl}/api/v1/actions/${actionId}/invoices`,
  );
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const all = payload.items.map((item) => item.invoice.number);
  expect(new Set(all).size).toBe(all.length);
  return payload.items
    .filter((item) => item.invoice.commitmentId === commitmentId)
    .map((item) => item.invoice);
}

async function checkOrders(page, names) {
  for (const name of names) {
    await page
      .getByRole("checkbox", { name: new RegExp(`^${name} ·`) })
      .check();
  }
}

let context;
let page;
const pageErrors = [];

test.beforeAll(async ({ browser }) => {
  context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
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
  page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(error.message));
  // Confirm the sign-in once, so the issue calls below reach the server.
  await page.goto(
    `${baseUrl}/fresh-login?returnTo=${encodeURIComponent("/admin/orders")}`,
  );
  const previousMailIds = await messageIds(context.request);
  await page.getByTestId("request-login").click();
  await expect(page.locator("#complete-login-form")).toBeVisible();
  const code = await waitForCode(context.request, previousMailIds);
  await page.locator("#login-code").fill(code);
  await page.getByTestId("complete-login").click();
  await page.waitForURL(/\/admin\/orders/);
});

test.afterAll(async () => {
  await context?.close();
});

test("a lost bulk answer is sent again with the same key and stays one invoice", async () => {
  const lost = await dropFirstAnswer(page, orders.fuenf);
  await page.goto(`${baseUrl}/admin/orders?action=${actionId}&view=all`);
  await checkOrders(page, ["Sammel Vier KG", "Sammel Fünf KG"]);
  await page.getByTestId("bulk-release-open").click();
  const dialog = page.getByRole("dialog", { name: "Rechnungen freigeben" });
  const serviceOn = await dialog
    .getByTestId("bulk-release-service-on")
    .inputValue();

  // Newest first: Fünf's answer is lost, so the run stops before Vier.
  await dialog
    .getByRole("button", { name: "2 Rechnungen verbindlich ausstellen" })
    .click();
  const result = page.getByRole("dialog", { name: "Ergebnis der Freigabe" });
  await expect(result).toContainText("Verbindung unterbrochen.");
  const unfinished = result.getByTestId("bulk-release-unfinished");
  await expect(unfinished).toContainText("Sammel Fünf KG: Keine Antwort");
  await expect(unfinished).toContainText("Sammel Vier KG: nicht gesendet.");
  await expect(result.getByTestId("bulk-release-failed")).toHaveCount(0);
  expect(lost.dropped).toBe(true);
  // The server did commit Fünf.
  expect(await invoicesFor(page, orders.fuenf)).toHaveLength(1);

  // The retry replays Fünf's key and issues Vier.
  await result
    .getByRole("button", { name: "2 Rechnungen erneut senden" })
    .click();
  const issued = result.getByTestId("bulk-release-issued");
  await expect(issued).toContainText("Ausgestellt (2)");
  await expect(issued).toContainText(
    `Sammel Fünf KG · 108,00 € (war bereits ausgestellt, keine zweite Rechnung; Leistungsdatum ${serviceOn.split("-").reverse().join(".")})`,
  );
  await expect(issued).toContainText("Sammel Vier KG");
  await expect(unfinished).toHaveCount(0);
  await page.screenshot({
    path: `${artifactDirectory}/invoice-bulk-release-retry.png`,
  });

  const [vier, fuenf] = [
    await invoicesFor(page, orders.vier),
    await invoicesFor(page, orders.fuenf),
  ];
  expect([vier.length, fuenf.length]).toEqual([1, 1]);
  expect(vier[0].serviceOn).toBe(serviceOn);
  expect(fuenf[0].serviceOn).toBe(serviceOn);
  expect((await issued.locator("a").allTextContents()).sort()).toEqual(
    [vier[0].number, fuenf[0].number].sort(),
  );
  await result
    .locator(".modal-footer")
    .getByRole("button", { name: "Schließen" })
    .click();
  await page.unrouteAll({ behavior: "wait" });
  expect(pageErrors).toEqual([]);
});

test("a key already sent with another date is refused while the others are issued", async () => {
  // A single review of Sechs with the first day loses its answer.
  const lost = await dropFirstAnswer(page, orders.sechs);
  await page.goto(
    `${baseUrl}/admin/orders?action=${actionId}&view=all&invoice=${orders.sechs}`,
  );
  const review = page.getByTestId("invoice-review");
  const reviewDate = review.getByTestId("invoice-service-on");
  const firstDay = await reviewDate.getAttribute("min");
  await reviewDate.fill(firstDay);
  await review.getByTestId("issue-invoice").click();
  await expect(review).toContainText("nicht gespeichert");
  expect(lost.dropped).toBe(true);
  await page.unrouteAll({ behavior: "wait" });

  // Without a reload Sechs still looks review-ready; release it in bulk
  // with the default date together with Sieben.
  await checkOrders(page, ["Sammel Sechs KG", "Sammel Sieben KG"]);
  await page.getByTestId("bulk-release-open").click();
  const dialog = page.getByRole("dialog", { name: "Rechnungen freigeben" });
  const serviceOn = await dialog
    .getByTestId("bulk-release-service-on")
    .inputValue();
  expect(serviceOn).not.toBe(firstDay);
  await dialog
    .getByRole("button", { name: "2 Rechnungen verbindlich ausstellen" })
    .click();
  const result = page.getByRole("dialog", { name: "Ergebnis der Freigabe" });
  await expect(result.getByTestId("bulk-release-failed")).toContainText(
    "Sammel Sechs KG: Für diese Bestellung wurde schon eine Freigabe mit anderen Angaben",
  );
  const issued = result.getByTestId("bulk-release-issued");
  await expect(issued).toContainText("Ausgestellt (1)");
  await expect(issued).toContainText("Sammel Sieben KG");
  await expect(result.getByTestId("bulk-release-unfinished")).toHaveCount(0);
  await page.screenshot({
    path: `${artifactDirectory}/invoice-bulk-release-refused.png`,
  });

  // Sechs keeps the single invoice with the first day; Sieben has one.
  const [sechs, sieben] = [
    await invoicesFor(page, orders.sechs),
    await invoicesFor(page, orders.sieben),
  ];
  expect(sechs.map((invoice) => invoice.serviceOn)).toEqual([firstDay]);
  expect(sieben.map((invoice) => invoice.serviceOn)).toEqual([serviceOn]);
  expect(pageErrors).toEqual([]);
});
