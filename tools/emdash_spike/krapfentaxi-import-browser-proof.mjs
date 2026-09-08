import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";
import { observeMediaUpload } from "./media-upload-observer.mjs";

// Runs after the real importer, not a replacement CMS seed. All editorial
// mutations go through native controls using an actual Charity Admin login.
const origin = "https://proxy:8443";
const path = "/campaigns/krapfentaxi-2026/";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const action = "20000000-0000-4000-8000-000000000001";
// Resolve fixture IO before installing response waiters, so a missing mount
// cannot hide the actual error behind a rejected waiter during browser close.
const replacementImage = await readFile(
  "apps/public/src/assets/krapfentaxi/logo.png",
);
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
    const publicHtml = async () => {
      const response = await anonymous.request.get(origin + path);
      assert.equal(response.status(), 200);
      assert.equal(response.headers()["cache-control"], "no-store");
      return response.text();
    };
    if (name === "chromium") {
      assert.equal((await anonymous.request.get(origin + path)).status(), 404);
    }
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
    const json = async (url) => {
      const response = await context.request.get(origin + url);
      assert.equal(response.status(), 200);
      return (await response.json()).data;
    };
    const entry = (await json(root)).items.find(
      (item) => item.data.action_id === action,
    );
    assert.ok(entry);
    const api = `${root}/${entry.id}`;
    await page.goto(`${origin}${editor}/${entry.id}`);
    if ((await json("/_emdash/api/auth/me")).isFirstLogin) {
      await page
        .getByRole("button", { name: "Get Started", exact: true })
        .click();
    }
    await expect(page.locator("#field-story_title")).toBeVisible();
    const changeText = async (value) => {
      const field = page.locator("#field-story_title");
      assert.notEqual(
        await field.inputValue(),
        value,
        "Expected an actual editorial change",
      );
      try {
        const [saved] = await Promise.all([
          page.waitForResponse(
            (r) =>
              new URL(r.url()).pathname === api &&
              r.request().method() === "PUT",
          ),
          (async () => {
            await field.fill(value);
            await expect(field).toHaveValue(value);
            await page.locator("#field-title").click();
          })(),
        ]);
        assert.equal(saved.status(), 200);
      } catch (error) {
        console.log(
          `import-editor: engine=${name}; valueRetained=${(await field.inputValue()) === value}; saveEnabled=${await page
            .getByRole("button", { name: "Save", exact: true })
            .isEnabled()
            .catch(() => false)}`,
        );
        throw error;
      }
      await expect(
        page.getByRole("button", { name: "Saved", exact: true }),
      ).toBeVisible();
    };
    const publish = async () => {
      const response = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === `${api}/publish` &&
          r.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Publish", exact: true }).click();
      assert.equal((await response).status(), 200);
      assert.equal((await json(api)).item.draftRevisionId, null);
    };
    // Restore the deliberately edited importer retry fixture through the UI.
    await changeText("Freude teilen.\nGutes möglich machen.");
    await publish();
    const before = await publicHtml();
    assert.ok(before.includes("Gutes möglich machen."));
    const previousHero = (await json(api)).item.data.hero_image.id;
    const marker = `Published imported campaign ${name}`;
    await changeText(marker);
    assert.ok(!(await publicHtml()).includes(marker));
    const field = page.locator("#field-hero_image");
    const removed = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === api && r.request().method() === "PUT",
    );
    await field
      .getByRole("button", { name: "Remove image", exact: true })
      .click();
    assert.equal((await removed).status(), 200);
    await field
      .getByRole("button", { name: "Select image", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    const stopUploadObservation = observeMediaUpload(page);
    const confirmed = page.waitForResponse(
      (r) =>
        /\/_emdash\/api\/media\/[0-9A-Z]+\/confirm$/.test(
          new URL(r.url()).pathname,
        ) && r.request().method() === "POST",
    );
    try {
      const [confirmation] = await Promise.all([
        confirmed,
        dialog.getByLabel("Upload file", { exact: true }).setInputFiles({
          name: `imported-demo-${name}.png`,
          mimeType: "image/png",
          buffer: replacementImage,
        }),
      ]);
      assert.equal(confirmation.status(), 200);
    } finally {
      stopUploadObservation();
    }
    const inserted = page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === api && r.request().method() === "PUT",
    );
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    assert.equal((await inserted).status(), 200);
    const newHero = (await json(api)).item.data.hero_image.id;
    assert.notEqual(newHero, previousHero);
    // Same ordinary GET, no cache-busting query, service restart or rebuild.
    const privateDraftHtml = await publicHtml();
    assert.ok(!privateDraftHtml.includes(marker));
    assert.ok(privateDraftHtml.includes(previousHero));
    assert.ok(!privateDraftHtml.includes(newHero));
    await publish();
    const after = await publicHtml();
    assert.ok(after.includes(marker));
    assert.ok(after.includes(newHero));
    assert.notEqual(after, before);
    for (const javaScriptEnabled of [false, true]) {
      const visitor = await browser.newContext({
        ignoreHTTPSErrors: true,
        javaScriptEnabled,
        viewport: { width: javaScriptEnabled ? 1280 : 390, height: 900 },
      });
      const view = await visitor.newPage();
      assert.equal((await view.goto(origin + path)).status(), 200);
      await expect(
        view.getByRole("heading", { name: marker, exact: true }),
      ).toBeVisible();
      await expect(view.locator("body")).toHaveClass("taxi-site");
      await expect(view.locator("[data-order-form]")).toHaveCount(1);
      for (const image of await view
        .locator(".taxi-hero img, .taxi-bakery__logo img")
        .all()) {
        await image.scrollIntoViewIfNeeded();
        await expect
          .poll(() =>
            image.evaluate((img) => img.complete && img.naturalWidth > 0),
          )
          .toBe(true);
      }
      assert.equal(
        await view.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
      assert.equal((await visitor.cookies()).length, 0);
      await visitor.close();
    }
    await changeText(`Private follow-up ${name}`);
    assert.ok(!(await publicHtml()).includes(`Private follow-up ${name}`));
    assert.ok((await publicHtml()).includes(marker));
    await coreLogout(context, page, editor, root);
    await context.close();
    await anonymous.close();
    console.log(
      `krapfentaxi import browser ${name}: actual Charity login, native text/image edit, draft isolation and publication passed`,
    );
  } finally {
    await browser.close();
  }
}
