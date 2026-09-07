import assert from "node:assert/strict";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const path = "/campaigns/krapfentaxi-2026/";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const action = "20000000-0000-4000-8000-000000000001";
let expectedDraft = "Private follow-up webkit";
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
    const visitor = await anonymous.newPage();
    assert.equal((await visitor.goto(origin + path)).status(), 200);
    await expect(
      visitor.getByRole("heading", {
        name: "Published imported campaign webkit",
        exact: true,
      }),
    ).toBeVisible();
    await expect(visitor.locator("[data-order-form]")).toHaveCount(1);
    await expect(visitor.locator(".taxi-hero__image")).toHaveCount(1);
    await expect(visitor.locator(".taxi-hero__logo")).toHaveCount(1);
    await expect(visitor.locator(".taxi-bakery__logo img")).toHaveCount(1);
    for (const image of await visitor
      .locator(".taxi-hero img, .taxi-bakery__logo img")
      .all()) {
      await image.scrollIntoViewIfNeeded();
      await expect
        .poll(() =>
          image.evaluate((img) => img.complete && img.naturalWidth > 0),
        )
        .toBe(true);
    }
    assert.equal((await anonymous.cookies()).length, 0);
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    await page.goto(origin + editor);
    await page.getByRole("heading", { name: "Bei LeonAid anmelden" }).waitFor();
    await browserLogin(
      context,
      page,
      editor,
      false,
      "klara.kern@leonaid.invalid",
    );
    const listing = await context.request.get(origin + root);
    assert.equal(listing.status(), 200);
    const items = (await listing.json()).data.items;
    assert.ok(items.length > 0);
    assert.ok(items.every((item) => item.data.action_id === action));
    const entry = items.find((item) => item.data.action_id === action);
    const api = `${root}/${entry.id}`;
    const before = await context.request.get(origin + api);
    const detail = (await before.json()).data.item;
    assert.ok(detail.draftRevisionId);
    await page.goto(`${origin}${editor}/${entry.id}`);
    await expect(page.locator("#field-story_title")).toHaveValue(expectedDraft);
    const marker = `Restored private draft ${name}`;
    const saved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === api &&
        response.request().method() === "PUT",
    );
    await page.locator("#field-story_title").fill(marker);
    await page.locator("#field-title").click();
    assert.equal((await saved).status(), 200);
    await expect(
      page.getByRole("button", { name: "Saved", exact: true }),
    ).toBeVisible();
    const published = await anonymous.request.get(origin + path);
    assert.equal(published.status(), 200);
    const html = await published.text();
    assert.ok(html.includes("Published imported campaign webkit"));
    assert.ok(!html.includes(marker));
    expectedDraft = marker;
    await coreLogout(context, page, editor, root);
    await context.close();
    await anonymous.close();
    console.log(
      `recovery-app ${name}: actual restored Core SMTP login, scoped CMS listing, retained/editable draft, published media and logout denial passed`,
    );
  } finally {
    await browser.close();
  }
}
