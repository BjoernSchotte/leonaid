import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const mailpitBaseUrl = process.env.LEONAID_E2E_MAILPIT_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const email = "klara.kern@leonaid.invalid";

if (!baseUrl || !mailpitBaseUrl || !artifactDirectory) {
  throw new Error("POC-042 Browserumgebung ist unvollständig");
}

test.setTimeout(60_000);

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
        message: "echte Mailpit-Mail mit Login-Code",
        timeout: 30_000,
        intervals: [100, 200, 400],
      },
    )
    .toBe("ready");
  return code;
}

test("Login, normale Arbeit, Fresh Login, Adminaktion und Logout", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await context.newPage();
  try {
    const loginMailIds = await messageIds(context.request);
    await page.goto(
      `${baseUrl}/login?returnTo=${encodeURIComponent("/admin/members")}`,
    );
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Bei LeonAid anmelden",
    );
    await page.locator("#login-email").fill(email);
    await page.locator('[data-testid="request-login"]').click();
    await expect(page.locator("#complete-login-form")).toBeVisible();
    const loginCode = await waitForCode(context.request, loginMailIds);
    expect(loginCode).toMatch(/^[0-9]{6}$/);
    await page.locator("#login-code").fill(loginCode);
    await page.locator('[data-testid="complete-login"]').click();
    await page.waitForURL(`${baseUrl}/admin/members`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Klara Kern",
    );
    await expect(page.locator('[data-testid="invite-action"]')).toBeEnabled();

    const cookies = await context.cookies(baseUrl);
    const session = cookies.find(
      (cookie) => cookie.name === "__Host-leonaid_session",
    );
    expect(session).toBeDefined();
    expect(session.httpOnly).toBe(true);
    expect(session.secure).toBe(true);
    expect(session.sameSite).toBe("Lax");
    expect(session.domain).toBe("proxy");
    expect(session.path).toBe("/");
    expect(session.expires).toBeGreaterThan(Date.now() / 1000 + 89 * 86_400);

    const normalAccess = await context.request.get(
      `${baseUrl}/api/v1/identity/me`,
    );
    expect(normalAccess.status()).toBe(200);
    expect((await normalAccess.json()).displayName).toBe("Klara Kern");

    await expect
      .poll(
        async () =>
          (
            await context.request.get(`${baseUrl}/api/v1/auth/fresh/status`)
          ).status(),
        {
          message: "konfiguriertes Fresh-Login-Fenster läuft ab",
          timeout: 15_000,
          intervals: [200, 400],
        },
      )
      .toBe(401);

    const freshMailIds = await messageIds(context.request);
    await page.goto(
      `${baseUrl}/fresh-login?returnTo=${encodeURIComponent("/admin/members")}`,
    );
    await page.locator('[data-testid="request-login"]').click();
    await expect(page.locator("#complete-login-form")).toBeVisible();
    const freshCode = await waitForCode(context.request, freshMailIds);
    await page.locator("#login-code").fill(freshCode);
    await page.locator('[data-testid="complete-login"]').click();
    await page.waitForURL(`${baseUrl}/admin/members`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Klara Kern",
    );

    await page
      .getByRole("textbox", { name: "Name des Mitglieds" })
      .fill("E2E Session Sponsor");
    await page
      .getByRole("textbox", { name: "Login-E-Mail" })
      .fill("e2e-session@leonaid.invalid");
    await page.locator('[data-testid="invite-submit"]').click();
    await expect(page.locator("#invitation-status")).toContainText(
      "Einladung ist unterwegs",
    );
    await page.screenshot({
      path: `${artifactDirectory}/session-fresh-admin.png`,
      fullPage: true,
    });

    await page.locator('[data-testid="logout"]').click();
    await page.waitForURL(`${baseUrl}/login`);
    const afterLogout = await context.request.get(
      `${baseUrl}/api/v1/identity/me`,
    );
    expect(afterLogout.status()).toBe(401);
    expect(
      (await context.cookies(baseUrl)).some(
        (cookie) => cookie.name === "__Host-leonaid_session",
      ),
    ).toBe(false);
    await page.screenshot({
      path: `${artifactDirectory}/session-login.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
