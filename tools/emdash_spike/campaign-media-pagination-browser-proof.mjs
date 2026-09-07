import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const action = "20000000-0000-4000-8000-000000000001";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const fixture = JSON.parse(
  await readFile("/proof/media-pagination.json", "utf8"),
);
const expectedIds = fixture.items
  .map((item) => item.id)
  .sort()
  .reverse();
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      locale: "en-US",
      viewport: { width: 1440, height: 1000 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
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
    const entry = (await json(root)).items.find(
      (item) => item.data.action_id === action,
    );
    assert.ok(entry);
    const path = `${root}/${entry.id}`;
    const before = (await json(path)).item.data;
    await page.goto(`${origin}${editor}/${entry.id}`);
    await page
      .locator("#field-hero_image")
      .getByRole("button", { name: "Change", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    const search = dialog.getByRole("searchbox", { name: "Search media" });
    const responseFor = (query, cursor) =>
      page.waitForResponse((response) => {
        const url = new URL(response.url());
        return (
          url.pathname === "/_emdash/api/media" &&
          response.request().method() === "GET" &&
          url.searchParams.get("campaign") === action &&
          url.searchParams.get("q") === query &&
          url.searchParams.get("cursor") === cursor
        );
      });
    const firstResponse = responseFor("page-proof-", null);
    await search.fill("page-proof-");
    const first = await firstResponse;
    assert.equal(first.status(), 200);
    const firstData = (await first.json()).data;
    assert.equal(firstData.totalCount, 101);
    assert.deepEqual(
      firstData.items.map((item) => item.id),
      expectedIds.slice(0, 100),
    );
    assert.ok(firstData.nextCursor);
    const list = dialog.getByRole("listbox", { name: "Available media" });
    await expect(list.getByRole("button")).toHaveCount(100);
    const secondResponse = responseFor("page-proof-", firstData.nextCursor);
    await dialog
      .getByRole("button", { name: "Load More", exact: true })
      .click();
    const second = await secondResponse;
    assert.equal(second.status(), 200);
    const secondData = (await second.json()).data;
    assert.equal(secondData.totalCount, 101);
    assert.deepEqual(
      secondData.items.map((item) => item.id),
      expectedIds.slice(100),
    );
    assert.ok(!secondData.nextCursor);
    await expect(list.getByRole("button")).toHaveCount(101);
    await expect(
      dialog.getByRole("button", { name: "Load More", exact: true }),
    ).toHaveCount(0);
    await expect(
      dialog.getByRole("button", {
        name: fixture.foreign.filename,
        exact: true,
      }),
    ).toHaveCount(0);
    assert.deepEqual((await json(path)).item.data, before);
    // Changing the search after loading a later page must restart at page one.
    const target = fixture.items.find((item) => item.id === expectedIds.at(-1));
    const narrowedResponse = responseFor(target.filename, null);
    await search.fill(target.filename);
    const narrowed = await narrowedResponse;
    assert.equal(narrowed.status(), 200);
    const narrowedData = (await narrowed.json()).data;
    assert.equal(narrowedData.totalCount, 1);
    assert.deepEqual(
      narrowedData.items.map((item) => item.id),
      [target.id],
    );
    await expect(list.getByRole("button")).toHaveCount(1);
    await dialog
      .getByRole("button", { name: target.filename, exact: true })
      .click();
    const saved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === path &&
        response.request().method() === "PUT",
    );
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    assert.equal((await saved).status(), 200);
    await expect(
      page.getByRole("button", { name: "Saved", exact: true }),
    ).toBeVisible();
    await page.reload();
    const after = (await json(path)).item.data;
    assert.equal(after.hero_image.id, target.id);
    assert.deepEqual({ ...after, hero_image: before.hero_image }, before);
    await expect
      .poll(() =>
        page
          .locator("#field-hero_image img")
          .evaluate((img) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    await coreLogout(context, page, editor, root);
    await context.close();
    console.log(
      `campaign-media-pagination-browser: ${name}: real 100+1 native pages, exact order/counts, foreign exclusion, search cursor reset, selection/save/reload passed`,
    );
  } finally {
    await browser.close();
  }
}
