import assert from "node:assert/strict";
import { chromium, firefox, webkit } from "playwright";

// TLS certificate trust is proved separately by the Node HTTPS probe against
// the project's CA. Browser contexts here test rendering, not certificate UI.
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    for (const javaScriptEnabled of [false, true]) {
      const context = await browser.newContext({
        ignoreHTTPSErrors: true,
        javaScriptEnabled,
        viewport: { width: javaScriptEnabled ? 1280 : 390, height: 900 },
      });
      const page = await context.newPage();
      const response = await page.goto(
        "https://proxy:8443/campaigns/krapfentaxi-2026/",
      );
      assert.equal(response.status(), 200);
      assert.equal(response.headers()["cache-control"], "no-store");
      await page
        .getByRole("heading", { name: "Gemeinsam helfen vor Ort", exact: true })
        .waitFor();
      assert.equal(
        await page
          .getByRole("link", { name: "Zur Bestellung", exact: true })
          .getAttribute("href"),
        "/krapfentaxi#bestellen",
      );
      assert.equal(await page.locator("h1").count(), 1);
      assert.equal(await page.locator(".editorial script").count(), 0);
      assert.match(
        await page.locator(".editorial").textContent(),
        /<script>UNTRUSTED_TEXT_PROOF<\/script>/,
      );
      await page.getByText("Wie kann ich helfen?", { exact: true }).click();
      assert.equal(await page.locator("details[open]").count(), 1);
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
      await page.reload();
      assert.ok(!(await page.content()).includes("PRIVATE_DRAFT_PROOF"));
      assert.equal((await context.cookies()).length, 0);
      await page.evaluate(() =>
        window.scrollTo({ top: 0, behavior: "instant" }),
      );
      assert.equal(
        await page
          .locator(".skip-link")
          .evaluate((link) => link.getBoundingClientRect().bottom <= 0),
        true,
      );
      await page.keyboard.press("Tab");
      assert.equal(
        await page
          .locator(".skip-link")
          .evaluate((link) => document.activeElement === link),
        true,
      );
      await page.keyboard.press("Enter");
      assert.equal(
        await page
          .locator("#main-content")
          .evaluate((main) => document.activeElement === main),
        true,
      );
      await page.evaluate(() => {
        document.activeElement?.blur();
        window.scrollTo({ top: 0, behavior: "instant" });
      });
      if (name === "chromium")
        await page.screenshot({
          path: `/visual-proof/${javaScriptEnabled ? "desktop" : "mobile"}.png`,
          fullPage: true,
        });
      await context.close();
    }
  } finally {
    await browser.close();
  }
  console.log(
    `public-campaign-browser: ${name} anonymous desktop/mobile, JS/no-JS, escaped content, native FAQ, order handoff, repeat visit and no cookie passed`,
  );
}
