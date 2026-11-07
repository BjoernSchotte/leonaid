// Admin host and public host with the real services behind the generated
// Caddyfile.split (specs/multi-domain stage 1, §14 browser row). Run by
// tools/multi_host/test.sh; the routing table itself is proven by
// tools/proxy/routing-test.sh.
import { expect, test } from "./csp-guard.mjs";

const adminUrl = process.env.LEONAID_E2E_ADMIN_URL;
const publicUrl = process.env.LEONAID_E2E_PUBLIC_URL;
const sessions = {
  admin: process.env.FINN_SESSION,
  acquirer: process.env.ANNA_SESSION,
};

if (!adminUrl || !publicUrl || !sessions.admin || !sessions.acquirer) {
  throw new Error(
    "LEONAID_E2E_ADMIN_URL, LEONAID_E2E_PUBLIC_URL, FINN_SESSION and ANNA_SESSION are required",
  );
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

test("the public host serves public pages without any identity request", async ({
  page,
}) => {
  const identityRequests = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/identity/")) {
      identityRequests.push(request.url());
    }
  });
  for (const path of ["/", "/krapfentaxi", "/impressum"]) {
    const response = await page.goto(`${publicUrl}${path}`);
    expect(response?.status()).toBe(200);
    expect(new URL(page.url()).origin).toBe(publicUrl);
    // The session belongs to the admin host: one static sign-in link.
    const link = page.locator("[data-admin-host-link]");
    await expect(link).toHaveText("Anmelden");
    await expect(link).toHaveAttribute("href", `${adminUrl}/`);
  }
  await page.goto(`${publicUrl}/krapfentaxi`);
  // Astro trusts the public host: canonical names it, not localhost.
  const canonical = await page
    .locator('link[rel="canonical"]')
    .getAttribute("href");
  expect(new URL(canonical ?? "").origin).toBe(publicUrl);
  await page.waitForLoadState("networkidle");
  expect(identityRequests).toEqual([]);
});

test("public forms reach their own host's API and order action", async ({
  page,
}) => {
  await page.goto(`${publicUrl}/krapfentaxi`);
  const results = await page.evaluate(async () => {
    const inbox = await fetch("/api/v1/public/inbox-cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const form = new FormData();
    form.set("alias", "krapfentaxi");
    const order = await fetch("/_actions/createPublicOrder/", {
      method: "POST",
      body: form,
    });
    const member = await fetch("/api/v1/identity/me");
    return {
      inbox: inbox.status,
      inboxCode: (await inbox.json()).error?.code,
      order: order.status,
      member: member.status,
    };
  });
  // Validation errors prove that Core CSRF (public origin) and Astro
  // checkOrigin (public host in allowedDomains, else 403) accepted them.
  expect(results.inbox).toBe(422);
  expect(results.inboxCode).not.toBe("csrf_rejected");
  expect([400, 415]).toContain(results.order);
  // The member API does not exist on the public host.
  expect(results.member).toBe(404);
});

test("member paths move to the admin host and sign-in works there", async ({
  browser,
  page,
}) => {
  for (const path of ["/admin/", "/app/", "/login?returnTo=%2Fadmin%2F"]) {
    await page.goto(`${publicUrl}${path}`);
    expect(new URL(page.url()).origin).toBe(adminUrl);
  }
  // The sign-in page on the admin host loads its own styles and scripts.
  const login = await page.goto(`${adminUrl}/login`);
  expect(login?.status()).toBe(200);
  await expect(page.locator("form").first()).toBeVisible();

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

test("the admin host refuses public order actions and sends campaign pages away", async ({
  page,
}) => {
  await page.goto(`${adminUrl}/impressum`);
  const status = await page.evaluate(async () => {
    const response = await fetch("/impressum?_action=createPublicOrder", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "a=1",
    });
    return response.status;
  });
  expect(status).toBe(404);
  await page.goto(`${adminUrl}/krapfentaxi`);
  expect(new URL(page.url()).origin).toBe(publicUrl);
});

test("the admin host entry signs in first and keeps deep links", async ({
  browser,
  page,
}) => {
  // Signed out: `/` asks for the login, a deep link survives it (§6.7).
  await page.goto(`${adminUrl}/`);
  expect(new URL(page.url()).pathname).toBe("/login");
  await page.goto(`${adminUrl}/admin/orders?commitment=c1`);
  await page.waitForURL((url) => url.pathname === "/login");
  expect(new URL(page.url()).searchParams.get("returnTo")).toBe(
    "/admin/orders?commitment=c1",
  );

  // Core computes the start area and refuses one without a role for it.
  const context = await signedIn(browser, "acquirer");
  const member = await context.newPage();
  await member.goto(`${adminUrl}/`);
  await member.waitForURL((url) => url.pathname.startsWith("/app/"));
  const result = await member.evaluate(async () => {
    const identity = await (await fetch("/api/v1/identity/me")).json();
    const refused = await fetch("/api/v1/identity/me/preferred-surface", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ surface: "web" }),
    });
    return {
      landingPath: identity.landingPath,
      refused: refused.status,
      code: (await refused.json()).error?.code,
    };
  });
  expect(result).toEqual({
    landingPath: "/app/",
    refused: 409,
    code: "preferred_surface_unavailable",
  });
  await context.close();
});
