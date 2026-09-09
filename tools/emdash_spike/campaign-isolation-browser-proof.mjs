import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const origin = "https://proxy:8443";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const actor of ["charity", "charity_b"]) {
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        locale: "en-US",
      });
      const cookie = (value) => ({
        name: "__Host-leonaid_session",
        value,
        domain: "proxy",
        path: "/",
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      });
      await context.addCookies([cookie(tokens.system)]);
      const response = await context.request.get(origin + root);
      assert.equal(response.status(), 200);
      const all = (await response.json()).data.items;
      await context.clearCookies();
      await context.addCookies([cookie(tokens[actor])]);
      const mine = await context.request.get(origin + root);
      assert.equal(mine.status(), 200);
      const own = (await mine.json()).data.items;
      const ownIds = new Set(own.map((item) => item.id));
      const foreign = all.filter((item) => !ownIds.has(item.id));
      assert.ok(own.length && foreign.length);
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      await page.goto(origin + "/_emdash/admin/");
      await page.waitForURL((url) => url.pathname === editor);
      const identity = await context.request.get(
        origin + "/_emdash/api/auth/me",
      );
      if ((await identity.json()).data.isFirstLogin)
        await page
          .getByRole("button", { name: "Get Started", exact: true })
          .click();
      for (const entry of own)
        await expect(
          page.locator(`a[href^="${editor}/${entry.id}"]`).first(),
        ).toBeVisible();
      for (const entry of foreign)
        await expect(
          page.locator(`a[href^="${editor}/${entry.id}"]`),
        ).toHaveCount(0);
      for (const entry of foreign) {
        const denied = page.waitForResponse(
          (result) =>
            new URL(result.url()).pathname === `${root}/${entry.id}` &&
            result.request().method() === "GET",
        );
        await page.goto(origin + `${editor}/${entry.id}`);
        assert.equal((await denied).status(), 404);
        await expect(page.locator("#field-title")).toHaveCount(0);
      }
      assert.equal(
        (await context.request.get(origin + "/_emdash/api/dashboard")).status(),
        403,
      );
      for (const path of [
        "/_emdash/admin/settings",
        "/_emdash/admin/users",
        "/_emdash/admin/media",
      ])
        assert.equal((await page.goto(origin + path)).status(), 503);
      await context.close();
      console.log(
        `campaign-isolation-browser: ${name} ${actor}: scoped native list, foreign editor API denial and closed global navigation`,
      );
    }
  } finally {
    await browser.close();
  }
}
