// Admin host and public host with the real services behind the generated
// Caddyfile.split (specs/multi-domain stage 1, §14 browser row). Run by
// tools/multi_host/test.sh; the routing table itself is proven by
// tools/proxy/routing-test.sh.
import { expect, test } from "./csp-guard.mjs";

const adminUrl = process.env.LEONAID_E2E_ADMIN_URL;
const publicUrl = process.env.LEONAID_E2E_PUBLIC_URL;
const mailpitUrl = process.env.LEONAID_E2E_MAILPIT_URL;
// Golden charity admin of Krapfentaxi (tests/fixtures/golden/v1).
const charityAdminEmail = "klara.kern@leonaid.invalid";
const systemAdminEmail = "system-admin@leonaid.invalid";
// Golden charity admin of another action; tools/multi_host/test.sh adds an
// acquirer role in Krapfentaxi, so Felix has roles in both apps.
const bothAppsEmail = "felix.fremd@leonaid.invalid";
const sessions = {
  admin: process.env.FINN_SESSION,
  acquirer: process.env.ANNA_SESSION,
};

if (
  !adminUrl ||
  !publicUrl ||
  !mailpitUrl ||
  !sessions.admin ||
  !sessions.acquirer
) {
  throw new Error(
    "LEONAID_E2E_ADMIN_URL, LEONAID_E2E_PUBLIC_URL, LEONAID_E2E_MAILPIT_URL, FINN_SESSION and ANNA_SESSION are required",
  );
}

function addressesOf(value) {
  if (typeof value === "string") return [value.toLowerCase()];
  if (Array.isArray(value)) return value.flatMap(addressesOf);
  if (value && typeof value === "object")
    return Object.values(value).flatMap(addressesOf);
  return [];
}

/** The newest real login mail to the recipient, read from Mailpit. */
async function loginLink(request, previous, recipient) {
  let link;
  await expect
    .poll(
      async () => {
        const list = await request.get(`${mailpitUrl}/api/v1/messages`);
        if (!list.ok()) return "mailpit-unavailable";
        for (const summary of (await list.json()).messages ?? []) {
          if (previous.has(summary.ID)) continue;
          if (!addressesOf(summary.To).includes(recipient)) continue;
          const detail = await request.get(
            `${mailpitUrl}/api/v1/message/${summary.ID}`,
          );
          const text = (await detail.json()).Text ?? "";
          const match = text.match(/https:\/\/\S+\/login\?token=\S+/);
          if (match) {
            link = match[0];
            return "ready";
          }
        }
        return "pending";
      },
      { message: "Login-Mail in Mailpit", timeout: 30_000 },
    )
    .toBe("ready");
  return link;
}

/** The six-digit code of the newest login mail to the recipient. */
async function loginCode(request, previous, recipient) {
  let code;
  await expect
    .poll(
      async () => {
        const list = await request.get(`${mailpitUrl}/api/v1/messages`);
        if (!list.ok()) return "mailpit-unavailable";
        for (const summary of (await list.json()).messages ?? []) {
          if (previous.has(summary.ID)) continue;
          if (!addressesOf(summary.To).includes(recipient)) continue;
          const detail = await request.get(
            `${mailpitUrl}/api/v1/message/${summary.ID}`,
          );
          const match = ((await detail.json()).Text ?? "").match(
            /Code (\d{6}) /,
          );
          if (match) {
            code = match[1];
            return "ready";
          }
        }
        return "pending";
      },
      { message: "Login-Code in Mailpit", timeout: 30_000 },
    )
    .toBe("ready");
  return code;
}

/**
 * Signs in on the sign-in page the browser shows with the mailed code, the
 * way a member types it: the page keeps its returnTo.
 */
async function signInWithCode(page, email) {
  await expect(page.locator("#login-email")).toBeVisible();
  const previous = await mailIds(page.request);
  await page.locator("#login-email").fill(email);
  await page.locator('[data-testid="request-login"]').click();
  await expect(page.locator("#complete-login-form")).toBeVisible();
  await page
    .locator("#login-code")
    .fill(await loginCode(page.request, previous, email));
  await page.locator('[data-testid="complete-login"]').click();
}

async function mailIds(request) {
  const list = await request.get(`${mailpitUrl}/api/v1/messages`);
  expect(list.ok()).toBeTruthy();
  return new Set(((await list.json()).messages ?? []).map((item) => item.ID));
}

test.use({ ignoreHTTPSErrors: true });

async function signedIn(browser, persona) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: sessions[persona],
      url: adminUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  return context;
}

// Host routing, refusals, origins and the start area are server answers:
// HTTP requests against the real proxy, no browser (E-026).
test("the split proxy routes, refuses and redirects per host", async ({
  request,
}) => {
  const get = (url, headers = {}) =>
    request.get(url, { headers, maxRedirects: 0 });
  for (const path of ["/", "/krapfentaxi", "/impressum"]) {
    const response = await get(`${publicUrl}${path}`);
    expect(response.status(), path).toBe(200);
    // The session belongs to the admin host: one static sign-in link.
    expect(await response.text(), path).toMatch(
      new RegExp(
        `<a [^>]*data-admin-host-link[^>]*href="${adminUrl}/"[^>]*>\\s*Mitgliederbereich`,
      ),
    );
  }
  // Astro trusts the public host: canonical names it, not localhost.
  const page = await (await get(`${publicUrl}/krapfentaxi`)).text();
  const canonical = page.match(/<link [^>]*rel="canonical"[^>]*href="([^"]+)"/);
  expect(new URL(canonical?.[1] ?? "").origin).toBe(publicUrl);

  // Public forms reach their own host's API and order action: validation
  // errors prove that Core CSRF (public origin) and Astro checkOrigin
  // (public host in allowedDomains, else 403) accepted the origin.
  const inbox = await request.post(`${publicUrl}/api/v1/public/inbox-cases`, {
    headers: { Origin: publicUrl, "Content-Type": "application/json" },
    data: "{}",
  });
  expect(inbox.status()).toBe(422);
  expect((await inbox.json()).error?.code).not.toBe("csrf_rejected");
  const order = await request.post(`${publicUrl}/_actions/createPublicOrder/`, {
    headers: { Origin: publicUrl },
    multipart: { alias: "krapfentaxi" },
  });
  expect([400, 415]).toContain(order.status());
  // The member API does not exist on the public host.
  expect((await get(`${publicUrl}/api/v1/identity/me`)).status()).toBe(404);

  // Member paths move to the admin host, campaign pages to the public host.
  for (const [from, to] of [
    [publicUrl, adminUrl, "/admin/"],
    [publicUrl, adminUrl, "/app/"],
    [publicUrl, adminUrl, "/login?returnTo=%2Fadmin%2F"],
    [adminUrl, publicUrl, "/krapfentaxi"],
  ].map(([source, target, path]) => [source + path, target + path])) {
    const response = await get(from);
    expect(response.status(), from).toBe(308);
    expect(response.headers().location, from).toBe(to);
  }
  // The admin host refuses public order actions.
  const refused = await request.post(
    `${adminUrl}/impressum?_action=createPublicOrder`,
    {
      headers: {
        Origin: adminUrl,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      data: "a=1",
    },
  );
  expect(refused.status()).toBe(404);

  // Core computes the start area and refuses one without a role for it.
  const acquirer = {
    Cookie: `__Host-leonaid_session=${sessions.acquirer}`,
    Origin: adminUrl,
  };
  const identity = await get(`${adminUrl}/api/v1/identity/me`, acquirer);
  expect((await identity.json()).landingPath).toBe("/app/");
  const surface = await request.put(
    `${adminUrl}/api/v1/identity/me/preferred-surface`,
    { headers: acquirer, data: { surface: "web" } },
  );
  expect(surface.status()).toBe(409);
  expect((await surface.json()).error?.code).toBe(
    "preferred_surface_unavailable",
  );
});

test("public pages send no identity request from the browser", async ({
  page,
}) => {
  const identityRequests = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/identity/")) {
      identityRequests.push(request.url());
    }
  });
  for (const path of ["/", "/krapfentaxi", "/impressum"]) {
    await page.goto(`${publicUrl}${path}`);
    await page.waitForLoadState("networkidle");
  }
  expect(identityRequests).toEqual([]);
});

// @webkit: WebKit cookie handling (ITP) is the risk for the host-only session.
test("each persona lands in its area on the admin host @webkit", async ({
  browser,
}) => {
  for (const [persona, area] of [
    ["admin", "/admin/"],
    ["acquirer", "/app/"],
  ]) {
    const context = await signedIn(browser, persona);
    const member = await context.newPage();
    await member.goto(`${adminUrl}/`);
    await member.waitForURL((url) => url.pathname.startsWith(area));
    expect(new URL(member.url()).origin).toBe(adminUrl);
    // The session cookie stays host-only on the admin host.
    const cookies = await context.cookies(publicUrl);
    expect(cookies.map((cookie) => cookie.name)).not.toContain(
      "__Host-leonaid_session",
    );
    await context.close();
  }
});

test("a magic link signs in on the admin host and a survey saves on the public host", async ({
  browser,
  browserName,
}) => {
  // One engine is enough for the cross-host mail and survey flow.
  test.skip(browserName !== "chromium", "chromium proves the flow");
  const admin = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await admin.newPage();
  const previous = await mailIds(admin.request);
  await page.goto(
    `${adminUrl}/login?returnTo=${encodeURIComponent("/admin/surveys/new")}`,
  );
  await page.locator("#login-email").fill(charityAdminEmail);
  await page.locator('[data-testid="request-login"]').click();
  await expect(page.locator("#complete-login-form")).toBeVisible();
  // The member mail links the admin host (LinkBuilder.admin_url).
  const link = await loginLink(admin.request, previous, charityAdminEmail);
  expect(new URL(link).origin).toBe(adminUrl);
  await page.goto(link);
  await page.locator('[data-testid="complete-login"]').click();
  // The mailed link carries no returnTo: the member lands in the admin app.
  await page.waitForURL((url) => url.pathname.startsWith("/admin/"));
  expect(new URL(page.url()).origin).toBe(adminUrl);
  await page.goto(`${adminUrl}/admin/surveys/new`);

  await page
    .getByLabel("Titel der Umfrage", { exact: true })
    .fill("Mehrere Hosts");
  await page
    .getByLabel("Fragebogenvorlage", { exact: true })
    .selectOption("krapfentaxi");
  await page
    .getByRole("button", { name: "Umfrage erstellen", exact: true })
    .click();
  const editor = page.getByRole("region", { name: "Fragebogen bearbeiten" });
  await expect(editor).toBeVisible();
  const surveyId = page.url().split("/").at(-1);
  await editor
    .getByRole("button", { name: "Veröffentlichen", exact: true })
    .click();
  await expect(page.locator("[data-survey-status]")).toHaveAttribute(
    "data-survey-status",
    "active",
  );

  // The survey runs on the public host; its API calls stay on that host.
  const respondent = await browser.newContext({ ignoreHTTPSErrors: true });
  const survey = await respondent.newPage();
  await survey.goto(`${publicUrl}/surveys/${surveyId}`);
  expect(new URL(survey.url()).origin).toBe(publicUrl);
  await survey
    .getByRole("button", { name: "Umfrage beginnen", exact: true })
    .click();
  const rating = survey.locator("[data-name=delivery_rating]");
  await expect(async () => {
    const dropdown = rating.getByRole("combobox");
    if (await dropdown.isVisible()) {
      await dropdown.click({ timeout: 1000 });
      await survey
        .getByRole("option", { name: "5", exact: true })
        .click({ timeout: 1000 });
    } else {
      const radio = rating.locator('input[type=radio][value="5"]');
      await radio.press("Space", { timeout: 1000 });
      await expect(radio).toBeChecked({ timeout: 1000 });
    }
  }).toPass({ timeout: 15_000, intervals: [100, 250] });
  await survey.getByRole("button", { name: "Weiter", exact: true }).click();
  await survey
    .locator("[data-name=notes] textarea")
    .fill("Gespeichert über den öffentlichen Host");
  await expect(survey.locator("[data-save-state]")).toHaveAttribute(
    "data-save-state",
    "saved",
  );
  // Participation cookies are host-only cookies of the public host: the
  // __Host- prefix forbids a Domain attribute, so no sibling (the admin
  // host) ever receives them.
  const surveyCookies = (await respondent.cookies()).filter((cookie) =>
    cookie.name.startsWith("__Host-survey_"),
  );
  expect(surveyCookies.length).toBeGreaterThan(0);
  for (const cookie of surveyCookies) {
    expect(cookie.domain).toBe(new URL(publicUrl).hostname);
    expect(cookie.secure).toBe(true);
  }
  await respondent.close();
  await admin.close();
});

test("a full sign-in lands on the deep link, else on the landing path", async ({
  browser,
  browserName,
}) => {
  test.skip(browserName !== "chromium", "chromium proves the flow");
  // Deep link first: the admin app sends the signed-out member to the login
  // with returnTo, and the login brings them back to exactly that page.
  const deep = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await deep.newPage();
  await page.goto(`${adminUrl}/admin/orders?commitment=c1`);
  await page.waitForURL((url) => url.pathname === "/login");
  await signInWithCode(page, systemAdminEmail);
  await page.waitForURL(
    (url) =>
      url.pathname === "/admin/orders" &&
      url.searchParams.get("commitment") === "c1",
  );
  expect(new URL(page.url()).origin).toBe(adminUrl);
  await deep.close();

  // No deep link: `/` of the admin host signs in and Core's landing path
  // decides; a system admin starts on the system page.
  const entry = await browser.newContext({ ignoreHTTPSErrors: true });
  const start = await entry.newPage();
  await start.goto(`${adminUrl}/`);
  await start.waitForURL((url) => url.pathname === "/login");
  await signInWithCode(start, systemAdminEmail);
  await start.waitForURL((url) => url.pathname === "/admin/system");
  expect(new URL(start.url()).origin).toBe(adminUrl);
  await entry.close();
});

test("a member with both apps chooses the admin app and returns to the default", async ({
  browser,
  browserName,
}) => {
  test.skip(browserName !== "chromium", "chromium proves the flow");
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  const landsOn = async (path) => {
    await page.goto(`${adminUrl}/`);
    await page.waitForURL((url) => url.pathname.startsWith(path));
  };
  const stored = (surface) =>
    page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/v1/identity/me/preferred-surface") &&
        response.request().method() === "PUT" &&
        response.request().postDataJSON()?.surface === surface &&
        response.status() === 200,
    );
  await page.goto(`${adminUrl}/`);
  await page.waitForURL((url) => url.pathname === "/login");
  await signInWithCode(page, bothAppsEmail);
  // The acquirer role makes the PWA the default start area.
  await page.waitForURL((url) => url.pathname.startsWith("/app/"));

  // The admin app offers itself in the command palette.
  await page.goto(`${adminUrl}/admin/`);
  await expect(page.locator("dialog.palette")).toBeAttached();
  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "Befehlspalette" });
  await expect(palette).toBeVisible();
  await palette.getByRole("combobox").fill("Startbereich");
  const web = stored("web");
  await palette
    .getByRole("option", { name: "Verwaltung als Startbereich verwenden" })
    .click();
  await web;
  await landsOn("/admin/");

  // The PWA offers both: itself and the default rule.
  await page.goto(`${adminUrl}/app/`);
  await page.getByRole("button", { name: "Mehr" }).click();
  const surfaces = page
    .getByRole("dialog", { name: "Mehr" })
    .getByTestId("pwa-surfaces");
  await expect(
    surfaces.getByRole("button", {
      name: "Akquise-App als Startbereich verwenden",
    }),
  ).toBeVisible();
  const reset = stored(null);
  await surfaces
    .getByRole("button", { name: "Standard-Startbereich verwenden" })
    .click();
  await reset;
  await landsOn("/app/");
  await context.close();
});
