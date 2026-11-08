import { expect, test } from "./csp-guard.mjs";

// Browser part of account status (R31, specs/multi-domain): a session that a
// status change ended keeps the "Bitte erneut anmelden" notice instead of a
// silent redirect. The server side (suspension revokes every session,
// reactivation revives none, no login challenge while suspended) is proven by
// tools/identity/contract.py, which ended this session before the browser run.
const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const revokedSession = process.env.ANNA_OLD_SESSION;

if (!baseUrl || !revokedSession) {
  throw new Error("PILOT-011 browser environment is incomplete");
}

test("an ended session keeps the sign-in notice with its return path", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: revokedSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  try {
    const page = await context.newPage();
    const denied = await context.request.get(`${baseUrl}/api/v1/identity/me`);
    expect(denied.status()).toBe(401);
    await page.goto(`${baseUrl}/app/sponsors`);
    await expect(
      page.getByRole("heading", { name: "Bitte erneut anmelden" }),
    ).toBeVisible();
    await expect(page).toHaveURL(`${baseUrl}/app/sponsors`);
    await expect(
      page.getByRole("link", { name: "Zur Anmeldung" }),
    ).toHaveAttribute("href", "/login?returnTo=%2Fapp%2Fsponsors");
  } finally {
    await context.close();
  }
});
