import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const phase = process.argv[2];
assert.ok(["baseline", "price", "closed", "restored"].includes(phase));
const origin = "https://proxy:8443";
const path = "/campaigns/krapfentaxi-2026/";
const action = "20000000-0000-4000-8000-000000000001";
const price = ["baseline", "restored"].includes(phase) ? 3600 : 4250;
const witness = "/proof/core-commerce-editorial.json";

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
      const response = await page.goto(origin + path, {
        waitUntil: "domcontentloaded",
      });
      assert.equal(response.status(), 200);
      assert.equal(response.headers()["cache-control"], "no-store");
      assert.equal(response.headers()["set-cookie"], undefined);
      const html = await response.text();
      assert.ok(html.includes("Published imported campaign webkit"));
      assert.ok(!html.includes("Private follow-up"));
      await expect(page.locator(".taxi-story")).toContainText(
        "Published imported campaign webkit",
      );
      await expect(page.locator("#angebote")).toContainText(
        price === 3600 ? "36,00" : "42,50",
      );
      await expect(page.locator("[data-order-form]")).toHaveCount(
        phase === "closed" ? 0 : 1,
      );
      if (phase === "closed") {
        assert.ok(!html.includes('name="accessToken"'));
        await expect(page.locator(".taxi-hero .primary-link")).toHaveAttribute(
          "href",
          "#angebote",
        );
      } else {
        await expect(
          page.locator("#quantity-70000000-0000-4000-8000-000000000001"),
        ).toHaveAttribute("data-unit-price", String(price));
        await expect(page.locator(".taxi-hero .primary-link")).toHaveAttribute(
          "href",
          "#bestellen",
        );
      }
      assert.deepEqual(await context.cookies(), []);
      await context.close();
    }
    if (name === "chromium") {
      // A real Core login can read both revisions. This probe performs no CMS
      // content mutation, publication, reseed, restart or cache invalidation.
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      const page = await context.newPage();
      const editor = "/_emdash/admin/content/campaign_pages";
      await page.goto(origin + editor);
      await browserLogin(
        context,
        page,
        editor,
        false,
        "klara.kern@leonaid.invalid",
      );
      const json = async (path) => {
        const response = await context.request.get(origin + path);
        assert.equal(response.status(), 200);
        return (await response.json()).data;
      };
      const root = "/_emdash/api/content/campaign_pages";
      const entry = (await json(root)).items.find(
        (item) => item.data.action_id === action,
      );
      assert.ok(entry);
      const api = `${root}/${entry.id}`;
      const snapshot = {
        content: await json(api),
        revisions: await json(`${api}/revisions`),
      };
      assert.equal(
        snapshot.content.item.data.story_title,
        "Private follow-up webkit",
      );
      assert.ok(snapshot.content.item.draftRevisionId);
      if (phase === "baseline") {
        await writeFile(witness, JSON.stringify(snapshot), {
          flag: "wx",
          mode: 0o600,
        });
      } else {
        assert.deepEqual(
          snapshot,
          JSON.parse(await readFile(witness, "utf8")),
          "Core commerce changes must leave all CMS content and revision metadata unchanged",
        );
      }
      await coreLogout(context, page, editor, root);
      await context.close();
    }
    console.log(
      `core-commerce: ${phase} ${name} native/mobile and JS/desktop passed`,
    );
  } finally {
    await browser.close();
  }
}
