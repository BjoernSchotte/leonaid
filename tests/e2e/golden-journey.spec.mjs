import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const mailpitBaseUrl = process.env.LEONAID_E2E_MAILPIT_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const round = process.env.LEONAID_GOLDEN_JOURNEY_ROUND;

if (!baseUrl || !mailpitBaseUrl || !artifactDirectory || !round) {
  throw new Error("POC-122 Browserumgebung ist unvollständig");
}

test.setTimeout(180_000);

function browserKey(projectName) {
  if (projectName.startsWith("chromium")) return "CHROMIUM";
  if (projectName.startsWith("firefox")) return "FIREFOX";
  if (projectName.startsWith("webkit")) return "WEBKIT";
  throw new Error(`Unbekannte Browserengine: ${projectName}`);
}

function adminSession(projectName) {
  const value = process.env[`KLARA_${browserKey(projectName)}_SESSION`];
  if (!value) throw new Error(`Klara-Sitzung fehlt für ${projectName}`);
  return value;
}

function staleAdminSession(projectName) {
  const value = process.env[`KLARA_${browserKey(projectName)}_STALE_SESSION`];
  if (!value) {
    throw new Error(`Abgelaufene Klara-Sitzung fehlt für ${projectName}`);
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
  const result = await new AxeBuilder({ page }).analyze();
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

test("vollständige Krapfentaxi-Journey ohne Datenbankeingriff", async ({
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
  await expect(adminPage.getByTestId("invite-action")).toBeEnabled();
  await adminPage
    .getByRole("textbox", { name: "Name des Mitglieds" })
    .fill(identity.displayName);
  await adminPage
    .getByRole("textbox", { name: "Login-E-Mail" })
    .fill(identity.email);
  await adminPage.getByTestId("invite-role").selectOption("acquirer");
  await adminPage.getByTestId("invite-submit").click();
  await expect(adminPage.locator("#invitation-status")).toContainText(
    "Einladung ist unterwegs",
  );
  const invitationCode = await waitForCode(
    adminContext.request,
    identity.email,
    invitationMailIds,
  );

  const memberContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
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

  await memberPage.goto(`${baseUrl}/app/sponsors`);
  await memberPage.getByRole("tab", { name: "Sponsor erfassen" }).click();
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
  ).toBeVisible();
  const resolutionPromise = memberPage.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/acquisition/sponsor-match/resolve"),
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
  await sponsorRow.getByRole("link", { name: "Aktivität" }).click();
  await expect(memberPage.getByTestId("activity-party")).toContainText(
    identity.company,
  );
  await memberPage.locator("#activity-channel").selectOption("in_person");
  await memberPage.locator("#activity-outcome").selectOption("interested");
  await memberPage
    .locator("#activity-note")
    .fill(`Golden Journey ${slug}: Bedarf besprochen.`);
  await memberPage.getByTestId("activity-submit").click();
  await expect(memberPage.locator("#activity-status")).toContainText(
    "wurde gespeichert",
  );

  await memberPage.goto(`${baseUrl}/app/sponsors`);
  const refreshedSponsor = memberPage
    .getByTestId("sponsor-row")
    .filter({ hasText: identity.company });
  await refreshedSponsor.getByRole("link", { name: "Bestellung" }).click();
  await memberPage.getByTestId("commitment-quantity").fill("2");
  await memberPage.getByTestId("commitment-street").fill("Löwenweg 12");
  await memberPage.locator("#commitment-postal-code").fill("86150");
  await memberPage.locator("#commitment-city").fill("Augsburg");
  await memberPage.locator("#commitment-email").fill(identity.email);
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
    "Bereit für die Prüfung",
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
    "klara.kern@leonaid.invalid",
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
  const invoiceRow = adminPage
    .getByTestId("invoice-row")
    .filter({ hasText: identity.company });
  await expect(invoiceRow).toBeVisible();
  const invoiceId = await invoiceRow.getAttribute("data-invoice-id");
  expect(invoiceId).toMatch(/^[0-9a-f-]{36}$/);
  await invoiceRow.locator("summary").click();
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
  await invoiceRow.getByTestId("payment-amount").fill("72.00");
  await invoiceRow
    .getByTestId("payment-date")
    .fill(new Date().toISOString().slice(0, 10));
  await invoiceRow
    .getByTestId("payment-reference")
    .fill(`GOLDEN-${slug.toUpperCase()}`);
  await invoiceRow.getByTestId("record-payment").click();
  await expect(invoiceRow.getByTestId("invoice-settlement")).toHaveAttribute(
    "data-state",
    "paid",
  );

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
