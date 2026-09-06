import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit } from "@playwright/test";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const origin = "https://proxy:8443";
const revoked = process.argv.includes("--revoked");
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    // The separate bootstrap HTTP proof verifies the project CA. These browser
    // contexts exercise UI/session behavior with the ephemeral local certificate.
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      locale: "en-US",
    });
    const page = await context.newPage();
    await page.goto(origin + "/_emdash/admin/");
    await page.waitForURL("**/login?returnTo=**");
    assert.equal(
      new URL(page.url()).searchParams.get("returnTo"),
      "/_emdash/admin/",
    );
    await page.getByRole("heading", { name: "Bei LeonAid anmelden" }).waitFor();
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: tokens.system,
        domain: "proxy",
        path: "/",
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    if (revoked) {
      await page.goto(origin + "/_emdash/admin/");
      await page.waitForURL("**/login?returnTo=**");
      assert.equal(
        (await context.request.get(origin + "/_emdash/api/dashboard")).status(),
        401,
      );
    } else {
      const dashboard = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/_emdash/api/dashboard" &&
          response.status() === 200,
      );
      await page.goto(origin + "/_emdash/admin/");
      await dashboard;
      await page.locator("#emdash-boot-loader").waitFor({ state: "detached" });
      assert.equal(new URL(page.url()).pathname, "/_emdash/admin/");
      assert.equal(
        (await context.request.get(origin + "/_emdash/api/manifest")).status(),
        200,
      );
      assert.equal(
        (
          await context.request.post(origin + "/_emdash/api/oauth/token")
        ).status(),
        503,
      );
      const cookies = await context.cookies();
      assert.equal(
        cookies.some(
          (cookie) =>
            cookie.name === "astro-session" || cookie.name === "emdash_session",
        ),
        false,
      );
    }
    await context.clearCookies();
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: tokens.finance,
        domain: "proxy",
        path: "/",
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    const denied = await page.goto(origin + "/_emdash/admin/");
    assert.equal(denied.status(), 403);
    await context.close();
    console.log(
      `emdash-admin-browser: OK: ${name}: ${revoked ? "revoked session redirects/denies" : "Core-session dashboard hydration and login return"}; Finance access denied`,
    );
  } finally {
    await browser.close();
  }
}
