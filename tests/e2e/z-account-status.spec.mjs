import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const mailpitBaseUrl = process.env.LEONAID_E2E_MAILPIT_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const staleSystemSession = process.env.SYSTEM_STALE_SESSION;
const annaSession = process.env.ANNA_SESSION;
const systemEmail = "system-admin@leonaid.invalid";
const annaEmail = "anna.akquise@leonaid.invalid";
const annaId = "10000000-0000-4000-8000-000000000002";

if (
  !baseUrl ||
  !mailpitBaseUrl ||
  !artifactDirectory ||
  !staleSystemSession ||
  !annaSession
) {
  throw new Error("PILOT-011 Browserumgebung ist unvollständig");
}

test.setTimeout(90_000);

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

async function waitForCode(request, previousIds, recipientEmail) {
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
            !recipientAddresses(summary.To).has(recipientEmail)
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
        message: `echte Login-Mail an ${recipientEmail}`,
        timeout: 30_000,
        intervals: [100, 200, 400],
      },
    )
    .toBe("ready");
  return code;
}

async function addSessionCookie(context, token) {
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

async function selectAnna(page) {
  await page
    .getByRole("searchbox", { name: "Mitglied suchen" })
    .fill("Anna Akquise");
  await page.getByRole("button", { name: "Suchen" }).click();
  await expect(page.getByTestId("member-card")).toHaveCount(1);
  await page.getByTestId("member-card").click();
  await expect(
    page.getByTestId("member-detail").getByRole("heading", {
      name: "Anna Akquise",
    }),
  ).toBeVisible();
}

async function confirmStatus(page, label) {
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: label }).click();
}

async function restoreAnnaIfSuspended(request) {
  const detail = await request.get(`${baseUrl}/api/v1/admin/members/${annaId}`);
  if (!detail.ok()) return;
  const member = await detail.json();
  if (member.status !== "suspended") return;

  const response = await request.patch(
    `${baseUrl}/api/v1/admin/members/${annaId}/status`,
    {
      headers: {
        "Idempotency-Key": `pilot011:e2e:cleanup:${crypto.randomUUID()}`,
      },
      data: {
        status: "active",
        expectedRevision: member.revision,
      },
    },
  );
  expect(response.ok()).toBeTruthy();
}

test("Fresh Login sperrt alle alten Sessions und Reaktivierung verlangt neue Anmeldung", async ({
  browser,
}) => {
  const systemContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  const oldAnnaContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await addSessionCookie(systemContext, staleSystemSession);
  await addSessionCookie(oldAnnaContext, annaSession);
  const systemPage = await systemContext.newPage();
  const oldAnnaPage = await oldAnnaContext.newPage();
  let newAnnaContext;

  try {
    await oldAnnaPage.goto(`${baseUrl}/app/`);
    await expect(
      oldAnnaPage.getByRole("heading", { name: "Guten Tag, Anna." }),
    ).toBeVisible();

    await systemPage.goto(`${baseUrl}/admin/members`);
    await selectAnna(systemPage);
    await expect(systemPage.getByTestId("member-detail-status")).toHaveText(
      "Aktiv",
    );
    await expect(
      systemPage
        .getByTestId("member-detail")
        .getByText("1 Sitzung", { exact: true }),
    ).toBeVisible();

    await systemPage.getByTestId("member-status-suspend").click();
    await expect(systemPage.getByRole("alertdialog")).toContainText(
      "Anna Akquise verliert sofort den Zugriff",
    );
    await expect(systemPage.getByRole("alertdialog")).toContainText(
      "Die aktive Sitzung wird unwiderruflich beendet",
    );
    await confirmStatus(systemPage, "Zugang sperren");
    await systemPage.waitForURL(/\/fresh-login\?returnTo=/);

    const freshMailIds = await messageIds(systemContext.request);
    await systemPage.getByTestId("request-login").click();
    await expect(systemPage.locator("#complete-login-form")).toBeVisible();
    const freshCode = await waitForCode(
      systemContext.request,
      freshMailIds,
      systemEmail,
    );
    await systemPage.locator("#login-code").fill(freshCode);
    await systemPage.getByTestId("complete-login").click();
    await systemPage.waitForURL(`${baseUrl}/admin/members`);

    await selectAnna(systemPage);
    await systemPage.getByTestId("member-status-suspend").click();
    await confirmStatus(systemPage, "Zugang sperren");
    await expect(systemPage.getByTestId("member-status-success")).toContainText(
      "1 Sitzung wurde sofort beendet",
    );
    await expect(systemPage.getByTestId("member-detail-status")).toHaveText(
      "Gesperrt",
    );
    await systemPage.screenshot({
      path: `${artifactDirectory}/account-status-suspended.png`,
      fullPage: true,
    });

    const deniedOldSession = await oldAnnaContext.request.get(
      `${baseUrl}/api/v1/identity/me`,
    );
    expect(deniedOldSession.status()).toBe(401);
    await oldAnnaPage.goto(`${baseUrl}/app/`);
    await expect(
      oldAnnaPage.getByRole("heading", { name: "Bitte erneut anmelden" }),
    ).toBeVisible();

    await systemPage.getByTestId("member-status-reactivate").click();
    await expect(systemPage.getByRole("alertdialog")).toContainText(
      "Alte Sitzungen bleiben beendet",
    );
    await confirmStatus(systemPage, "Zugang reaktivieren");
    await expect(systemPage.getByTestId("member-status-success")).toContainText(
      "Für den nächsten Zugriff ist eine neue Anmeldung erforderlich",
    );
    await expect(systemPage.getByTestId("member-detail-status")).toHaveText(
      "Aktiv",
    );
    expect(
      (
        await oldAnnaContext.request.get(`${baseUrl}/api/v1/identity/me`)
      ).status(),
    ).toBe(401);

    const accessibility = await new AxeBuilder({ page: systemPage }).analyze();
    expect(
      accessibility.violations.filter((violation) =>
        ["critical", "serious"].includes(violation.impact ?? ""),
      ),
    ).toEqual([]);
    await systemPage.screenshot({
      path: `${artifactDirectory}/account-status-reactivated.png`,
      fullPage: true,
    });

    newAnnaContext = await browser.newContext({
      viewport: { width: 390, height: 844 },
      ignoreHTTPSErrors: true,
    });
    const newAnnaPage = await newAnnaContext.newPage();
    const loginMailIds = await messageIds(newAnnaContext.request);
    await newAnnaPage.goto(`${baseUrl}/login`);
    await newAnnaPage.locator("#login-email").fill(annaEmail);
    await newAnnaPage.getByTestId("request-login").click();
    const loginCode = await waitForCode(
      newAnnaContext.request,
      loginMailIds,
      annaEmail,
    );
    await newAnnaPage.locator("#login-code").fill(loginCode);
    await newAnnaPage.getByTestId("complete-login").click();
    await newAnnaPage.waitForURL(`${baseUrl}/app/`);
    await expect(newAnnaPage.getByTestId("display-name")).toHaveText(
      "Anna Akquise",
    );
    expect(
      (
        await newAnnaContext.request.get(`${baseUrl}/api/v1/identity/me`)
      ).status(),
    ).toBe(200);
  } finally {
    await restoreAnnaIfSuspended(systemContext.request);
    await newAnnaContext?.close();
    await oldAnnaContext.close();
    await systemContext.close();
  }
});
