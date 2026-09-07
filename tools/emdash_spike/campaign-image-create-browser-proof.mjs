import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const state = JSON.parse(
  await readFile("/proof/media-http-state.json", "utf8"),
);
for (const [index, [name, engine]] of Object.entries({
  chromium,
  firefox,
  webkit,
}).entries()) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      locale: "en-US",
      viewport: { width: 1440, height: 1000 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const action = `20000000-0000-4000-8000-${String(43 + index).padStart(12, "0")}`;
    const handoff = `/_emdash/admin/campaigns/${action}`;
    const newPath = `${editor}/new?campaign=${action}`;
    await page.goto(origin + handoff);
    await page.getByRole("heading", { name: "Bei LeonAid anmelden" }).waitFor();
    await browserLogin(
      context,
      page,
      newPath,
      false,
      "klara.kern@leonaid.invalid",
    );
    await page.waitForURL(
      (url) =>
        url.pathname === `${editor}/new` &&
        url.searchParams.get("campaign") === action,
    );
    const json = async (path) => {
      const response = await context.request.get(origin + path);
      assert.equal(response.status(), 200);
      return (await response.json()).data;
    };
    const before = await json(root);
    assert.ok(before.items.every((item) => item.data.action_id !== action));
    await expect(page.locator("#field-action_id")).toHaveValue(action);
    const title = `Native ${name} image campaign`;
    await page.locator("#field-title").fill(title);
    await page
      .locator("#field-hero_title")
      .fill("A new campaign with an image");
    const mediaList = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/_emdash/api/media" &&
        url.searchParams.get("campaign") === action
      );
    });
    await page
      .locator("#field-hero_image")
      .getByRole("button", { name: "Select image", exact: true })
      .click();
    const listed = await mediaList;
    assert.equal(listed.status(), 200);
    assert.deepEqual((await listed.json()).data.items, []);
    const dialog = page.getByRole("dialog");
    const fixture = await context.request.get(
      `${origin}/_emdash/api/media/file/${state.ready.storageKey}`,
    );
    assert.equal(fixture.status(), 200);
    const confirmed = page.waitForResponse(
      (response) =>
        /\/_emdash\/api\/media\/[0-9A-Z]+\/confirm$/.test(
          new URL(response.url()).pathname,
        ) && response.request().method() === "POST",
    );
    const filename = `new-${name}-campaign.png`;
    await dialog.getByLabel("Upload file", { exact: true }).setInputFiles({
      name: filename,
      mimeType: "image/png",
      buffer: await fixture.body(),
    });
    const confirmation = await confirmed;
    assert.equal(confirmation.status(), 200);
    const uploaded = (await confirmation.json()).data.item;
    assert.ok(uploaded.storageKey.startsWith(`campaigns/${action}/`));
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page
      .locator("#field-social_image")
      .getByRole("button", { name: "Select image", exact: true })
      .click();
    await dialog.getByRole("button", { name: filename, exact: true }).click();
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    // Uploading for a Core action must not silently create its CMS record.
    assert.deepEqual(await json(root), before);
    const createdResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === root &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const created = await createdResponse;
    assert.equal(created.status(), 201);
    const item = (await created.json()).data.item;
    assert.equal(item.data.action_id, action);
    assert.equal(item.data.title, title);
    assert.equal(item.data.hero_image.id, uploaded.id);
    assert.equal(item.data.social_image.id, uploaded.id);
    assert.equal(item.status, "draft");
    assert.equal(item.liveRevisionId, null);
    assert.equal(item.authorId, (await json("/_emdash/api/auth/me")).id);
    await page.waitForURL((url) => url.pathname === `${editor}/${item.id}`);
    await page.reload();
    await expect(page.locator("#field-title")).toHaveValue(title);
    for (const field of ["hero_image", "social_image"]) {
      await expect
        .poll(() =>
          page
            .locator(`#field-${field} img`)
            .evaluate((img) => img.complete && img.naturalWidth > 0),
        )
        .toBe(true);
      assert.equal(
        (await json(`${root}/${item.id}`)).item.data[field].id,
        uploaded.id,
      );
    }
    const after = await json(root);
    assert.equal(after.total, before.total + 1);
    assert.equal(
      after.items.filter((entry) => entry.data.action_id === action).length,
      1,
    );
    const resolved = await context.request.get(origin + handoff, {
      maxRedirects: 0,
    });
    assert.equal(resolved.status(), 303);
    assert.equal(resolved.headers().location, `${editor}/${item.id}`);
    await coreLogout(context, page, handoff, root);
    assert.equal(
      (
        await context.request.get(
          `${origin}/_emdash/api/media/file/${encodeURIComponent(uploaded.storageKey)}`,
        )
      ).status(),
      401,
    );
    await context.close();
    console.log(
      `campaign-image-create-browser: ${name}: actual SMTP Core login and action handoff; empty scoped picker, native upload and hero/social selection before creation; explicit Save created one attributed draft; reload decoded private previews; logout denied media`,
    );
  } finally {
    await browser.close();
  }
}
