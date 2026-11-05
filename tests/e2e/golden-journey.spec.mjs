import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";
import { openInvoice } from "./invoice-list.mjs";
import { openInviteDialog, toast } from "./member-list.mjs";
import { writeFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const mailpitBaseUrl = process.env.LEONAID_E2E_MAILPIT_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const round = process.env.LEONAID_GOLDEN_JOURNEY_ROUND;

if (!baseUrl || !mailpitBaseUrl || !artifactDirectory || !round) {
  throw new Error("POC-122 browser environment is incomplete");
}

test.setTimeout(180_000);

// The Core's Twenty gateway keeps Twenty's budget of 100 requests in a
// sliding 60-second window and queues further CRM calls until the window
// frees up. Three browsers plus round setup can spend that budget, so a CRM
// lookup may wait up to one full window before Twenty is asked at all.
const CRM_BUDGET_TIMEOUT = 75_000;

function browserKey(projectName) {
  if (projectName.startsWith("chromium")) return "CHROMIUM";
  if (projectName.startsWith("firefox")) return "FIREFOX";
  if (projectName.startsWith("webkit")) return "WEBKIT";
  throw new Error(`Unbekannte Browserengine: ${projectName}`);
}

function adminSession(projectName) {
  const value = process.env[`KLARA_${browserKey(projectName)}_SESSION`];
  if (!value) throw new Error(`Klara session missing for ${projectName}`);
  return value;
}

function staleAdminSession(projectName) {
  const value = process.env[`KLARA_${browserKey(projectName)}_STALE_SESSION`];
  if (!value) {
    throw new Error(`Expired Klara session missing for ${projectName}`);
  }
  return value;
}

function sessionCookie(value) {
  return {
    name: "__Host-leonaid_session",
    value,
    url: baseUrl,
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
  };
}

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
  return new Set(
    ((await response.json()).messages ?? [])
      .map((message) => message.ID)
      .filter((id) => typeof id === "string"),
  );
}

async function waitForCode(request, recipient, previousIds) {
  let code;
  await expect
    .poll(
      async () => {
        const response = await request.get(`${mailpitBaseUrl}/api/v1/messages`);
        if (!response.ok()) return "mailpit-unavailable";
        for (const summary of (await response.json()).messages ?? []) {
          if (
            previousIds.has(summary.ID) ||
            !recipientAddresses(summary.To).has(recipient)
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
        message: `echte Mailpit-Mail an ${recipient}`,
        timeout: 30_000,
        intervals: [100, 200, 400],
      },
    )
    .toBe("ready");
  return code;
}

async function expectAccessible(page) {
  const result = await analyzeAccessibility(page);
  expect(
    result.violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
}

async function submitPublicOrder(page, identity) {
  await page.goto(`${baseUrl}/krapfentaxi`);
  await page.getByRole("link", { name: "Jetzt bestellen" }).click();
  const form = page.locator("[data-order-form]");
  await expect(form).toBeVisible();
  await form.locator('input[name="quantity"]').fill("1");
  await form.locator('input[name="companyName"]').fill(identity.company);
  await form.locator('input[name="givenName"]').fill("Jona");
  await form.locator('input[name="familyName"]').fill(identity.familyName);
  await form.locator('input[name="email"]').fill(identity.email);
  await form.locator('input[name="phone"]').fill("+49 821 122122");
  await form
    .locator('input[name="deliveryRecipientName"]')
    .fill(identity.company);
  await form.locator('input[name="deliveryStreetLine1"]').fill("Löwenweg 12");
  await form.locator('input[name="deliveryPostalCode"]').fill("86150");
  await form.locator('input[name="deliveryCity"]').fill("Augsburg");
  await form.locator('input[name="privacyAcknowledged"]').check();
  await form.locator('input[name="bindingOrderConfirmed"]').check();
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
  const publicReference = (
    await success.locator("[data-order-reference]").textContent()
  )?.trim();
  expect(publicReference).toMatch(/^LA-[A-F0-9]{32}$/);
  return { publicReference };
}

test("complete Krapfentaxi journey without database intervention", async ({
  browser,
}, testInfo) => {
  const engine = browserKey(testInfo.project.name).toLowerCase();
  const slug = `${round}-${engine}`;
  const identity = {
    company: `Golden Journey ${slug} GmbH`,
    displayName: `Jona ${slug}`,
    email: `journey-${slug}@leonaid.invalid`,
    familyName: `Journey-${slug}`,
  };
  let adminContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await adminContext.addCookies([
    sessionCookie(adminSession(testInfo.project.name)),
  ]);
  let adminPage = await adminContext.newPage();
  const pageErrors = [];
  adminPage.on("pageerror", (error) => pageErrors.push(error.message));

  const adminIdentity = await adminContext.request.get(
    `${baseUrl}/api/v1/identity/me`,
  );
  expect(adminIdentity.status()).toBe(200);
  expect((await adminIdentity.json()).displayName).toBe("Klara Kern");
  const invitationOptions = await adminContext.request.get(
    `${baseUrl}/api/v1/invitations/options`,
  );
  expect(invitationOptions.status()).toBe(200);
  const invitationMailIds = await messageIds(adminContext.request);
  await adminPage.goto(`${baseUrl}/admin/members`);
  await expect(adminPage).toHaveURL(`${baseUrl}/admin/members`);
  await expect(adminPage.getByTestId("display-name")).toHaveText("Klara Kern");
  const inviteDialog = await openInviteDialog(adminPage);
  await inviteDialog
    .getByRole("textbox", { name: "E-Mail-Adresse" })
    .fill(identity.email);
  await inviteDialog
    .getByRole("textbox", { name: "Name", exact: true })
    .fill(identity.displayName);
  await inviteDialog.getByTestId("invite-role").selectOption("acquirer");
  await inviteDialog.getByTestId("invite-submit").click();
  await expect(inviteDialog).toBeHidden();
  await expect(
    toast(adminPage, `Einladung an ${identity.email} gesendet.`),
  ).toBeVisible();
  const invitationCode = await waitForCode(
    adminContext.request,
    identity.email,
    invitationMailIds,
  );

  const memberContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
    // The journey verifies persistence; animated scrolling can move a Firefox
    // mobile-viewport target between its actionability check and the click.
    reducedMotion: "reduce",
    serviceWorkers: "block",
  });
  const memberPage = await memberContext.newPage();
  memberPage.on("pageerror", (error) => pageErrors.push(error.message));
  await memberPage.goto(`${baseUrl}/invite`);
  await memberPage.locator("#accept-email").fill(identity.email);
  await memberPage.locator("#accept-code").fill(invitationCode);
  await memberPage.getByTestId("accept-submit").click();
  await expect(memberPage.locator("#accept-status")).toContainText(
    "Krapfentaxi 2026",
  );
  await memberPage.getByRole("link", { name: "Zum Arbeitsbereich" }).click();
  await expect(memberPage.getByTestId("display-name")).toHaveText(
    identity.displayName,
  );
  const forbiddenOperations = await memberContext.request.get(
    `${baseUrl}/api/v1/admin/operations`,
  );
  expect(forbiddenOperations.status()).toBe(403);
  const forbiddenInvoices = await memberContext.request.get(
    `${baseUrl}/api/v1/actions/20000000-0000-4000-8000-000000000001/invoices`,
  );
  expect(forbiddenInvoices.status()).toBe(403);

  await memberPage.goto(`${baseUrl}/app/sponsors?view=new`);
  await memberPage.getByTestId("sponsor-company").fill(identity.company);
  await memberPage.locator("#sponsor-given-name").fill("Jona");
  await memberPage.locator("#sponsor-family-name").fill(identity.familyName);
  await memberPage.locator("#sponsor-email").fill(identity.email);
  await memberPage.locator("#sponsor-street").fill("Löwenweg 12");
  await memberPage.locator("#sponsor-postal-code").fill("86150");
  await memberPage.locator("#sponsor-city").fill("Augsburg");
  await memberPage.getByTestId("sponsor-preview").click();
  await expect(
    memberPage.getByRole("heading", {
      name: "Kein gleichnamiger Sponsor gefunden",
    }),
  ).toBeVisible({ timeout: CRM_BUDGET_TIMEOUT });
  const resolutionPromise = memberPage.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/acquisition/sponsor-match/resolve"),
    { timeout: CRM_BUDGET_TIMEOUT },
  );
  await memberPage.getByTestId("sponsor-resolve").click();
  const resolutionResponse = await resolutionPromise;
  expect(resolutionResponse.status()).toBe(201);
  const resolution = await resolutionResponse.json();
  expect(resolution).toMatchObject({
    assignmentCreated: true,
    outcome: "created",
  });

  await memberPage.goto(`${baseUrl}/app/sponsors`);
  const sponsorRow = memberPage
    .getByTestId("sponsor-row")
    .filter({ hasText: identity.company });
  await expect(sponsorRow).toHaveCount(1);
  await expect(sponsorRow.getByTestId("co-assignees")).toHaveCount(0);
  // Prototype: the sponsor's detail records the contact in a sheet.
  await sponsorRow.click();
  await memberPage.getByTestId("contact-open").click();
  const contactSheet = memberPage.getByRole("dialog", {
    name: `Kontakt mit ${identity.company}`,
  });
  await contactSheet.getByRole("button", { name: "Persönlich" }).click();
  await contactSheet.getByText("Interessiert", { exact: true }).click();
  await contactSheet
    .getByLabel("Notiz")
    .fill(`Golden Journey ${slug}: Bedarf besprochen.`);
  expect(
    await memberPage
      .locator("#activity-form")
      .evaluate((form) => form.checkValidity()),
  ).toBe(true);
  const activityResponse = memberPage.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/acquisition/activities"),
    { timeout: CRM_BUDGET_TIMEOUT },
  );
  await memberPage.getByTestId("activity-submit").click();
  expect((await activityResponse).status()).toBe(201);
  await expect(contactSheet).toBeHidden();
  await expect(memberPage.getByTestId("activity-entry").first()).toContainText(
    "Bedarf besprochen.",
  );

  // The order starts on the sponsor and runs through three steps.
  await memberPage.getByTestId("order-open").click();
  await memberPage.getByTestId("commitment-quantity").fill("2");
  await memberPage.getByRole("button", { name: "Weiter" }).click();
  await memberPage.getByTestId("commitment-street").fill("Löwenweg 12");
  await memberPage.locator("#commitment-postal-code").fill("86150");
  await memberPage.locator("#commitment-city").fill("Augsburg");
  await memberPage.locator("#commitment-email").fill(identity.email);
  await memberPage.getByRole("button", { name: "Weiter" }).click();
  const commitmentPromise = memberPage.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes("/commitments"),
  );
  await memberPage.getByTestId("commitment-save-ready").click();
  const commitmentResponse = await commitmentPromise;
  expect(commitmentResponse.status()).toBe(201);
  const commitment = await commitmentResponse.json();
  await expect(memberPage.getByTestId("commitment-success")).toContainText(
    "Bestellung erfasst",
  );

  const publicContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  const publicPage = await publicContext.newPage();
  const publicOrder = await submitPublicOrder(publicPage, identity);

  await memberPage.goto(`${baseUrl}/app/activities`);
  const feedEntry = memberPage
    .getByTestId("activity-feed-entry")
    .filter({ hasText: identity.company });
  await expect(feedEntry).toHaveCount(1);
  await expect(feedEntry).toContainText("1 Box");

  await adminContext.close();
  adminContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await adminContext.addCookies([
    sessionCookie(staleAdminSession(testInfo.project.name)),
  ]);
  adminPage = await adminContext.newPage();
  adminPage.on("pageerror", (error) => pageErrors.push(error.message));
  await adminPage.goto(`${baseUrl}/admin/orders?invoice=${commitment.id}`);
  await expect(adminPage.getByTestId("invoice-review")).toContainText(
    identity.company,
  );
  const freshMailIds = await messageIds(adminContext.request);
  await adminPage.getByTestId("issue-invoice").click();
  await adminPage.waitForURL(/\/fresh-login\?returnTo=/);
  await adminPage.getByTestId("request-login").click();
  const freshCode = await waitForCode(
    adminContext.request,
    process.env[`KLARA_${browserKey(testInfo.project.name)}_EMAIL`],
    freshMailIds,
  );
  await adminPage.locator("#login-code").fill(freshCode);
  await adminPage.getByTestId("complete-login").click();
  await adminPage.waitForURL(
    new RegExp(`/admin/orders\\?invoice=${commitment.id}`),
  );
  await adminPage.getByTestId("issue-invoice").click();
  const invoiceConfirmation = adminPage.getByText(
    /Rechnung KT[0-9]{2}-[0-9]{4} ist verbindlich freigegeben\./,
  );
  await expect(invoiceConfirmation).toBeVisible();
  const invoiceNumber = (await invoiceConfirmation.textContent())?.match(
    /Rechnung (KT[0-9]{2}-[0-9]{4})/,
  )?.[1];
  expect(invoiceNumber).toMatch(/^KT[0-9]{2}-[0-9]{4}$/);

  await adminPage.goto(`${baseUrl}/admin/invoices`);
  const invoiceLink = adminPage
    .locator(".listview .row-link")
    .filter({ hasText: identity.company });
  await expect(invoiceLink).toBeVisible();
  const invoiceId = await invoiceLink
    .locator("[data-invoice-row]")
    .getAttribute("data-invoice-row");
  expect(invoiceId).toMatch(/^[0-9a-f-]{36}$/);
  const invoiceRow = await openInvoice(adminPage, { id: invoiceId });
  await expect
    .poll(
      async () =>
        (await invoiceRow
          .getByTestId("invoice-document")
          .getAttribute("data-state")) ?? "missing",
      { timeout: 30_000, intervals: [100, 200, 400] },
    )
    .toBe("available");
  const downloadPromise = adminPage.waitForEvent("download");
  await invoiceRow.getByTestId("download-document").click();
  const download = await downloadPromise;
  await download.saveAs(
    `${artifactDirectory}/golden-${slug}-${invoiceNumber}.pdf`,
  );
  await invoiceRow.getByTestId("send-invoice").click();
  await expect
    .poll(
      async () =>
        (await invoiceRow
          .getByTestId("invoice-delivery")
          .getAttribute("data-state")) ?? "missing",
      { timeout: 30_000, intervals: [100, 200, 400] },
    )
    .toBe("sent");

  await invoiceRow.getByTestId("open-payment-form").click();
  const paymentDialog = adminPage.getByRole("dialog", {
    name: /Zahlung für .* erfassen/,
  });
  await paymentDialog.getByTestId("payment-amount").fill("72.00");
  // The club's day (Berlin), as UI and server use it; the UTC day is still
  // yesterday between 00:00 and 01:00/02:00 in Berlin.
  const berlinToday = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Europe/Berlin",
  }).format(new Date());
  await expect(paymentDialog.getByTestId("payment-date")).toHaveValue(
    berlinToday,
  );
  await paymentDialog.getByTestId("payment-date").fill(berlinToday);
  await paymentDialog
    .getByTestId("payment-reference")
    .fill(`GOLDEN-${slug.toUpperCase()}`);
  await paymentDialog.getByTestId("record-payment").click();
  await expect(paymentDialog).toBeHidden();
  await expect(invoiceRow).toHaveAttribute("data-settlement", "paid");

  await adminPage.goto(
    `${baseUrl}/admin/?action=20000000-0000-4000-8000-000000000001`,
  );
  await expect(adminPage.getByTestId("admin-dashboard-metrics")).toContainText(
    "Bestellungen",
  );
  await expectAccessible(adminPage);
  await expectAccessible(memberPage);
  expect(pageErrors).toEqual([]);

  await adminPage.screenshot({
    path: `${artifactDirectory}/golden-${slug}-admin.png`,
    fullPage: true,
  });
  await memberPage.screenshot({
    path: `${artifactDirectory}/golden-${slug}-member.png`,
    fullPage: true,
  });
  await writeFile(
    `${artifactDirectory}/golden-${slug}.json`,
    `${JSON.stringify(
      {
        browser: engine,
        commitmentId: commitment.id,
        company: identity.company,
        invoiceId,
        invoiceNumber,
        partyTwentyId: resolution.twentyId,
        publicReference: publicOrder.publicReference,
        round,
      },
      null,
      2,
    )}\n`,
  );

  await publicContext.close();
  await memberContext.close();
  await adminContext.close();
});
