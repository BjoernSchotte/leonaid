import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";
import { observeMediaUpload } from "./media-upload-observer.mjs";
import { normalizeCampaignImage } from "../../apps/campaign-site/src/auth/campaign-image.mjs";

const mode = process.argv[2];
assert.ok(["--changed", "--restored"].includes(mode));
const origin = "https://proxy:8443";
const canonical = "/campaigns/krapfentaxi-2026/";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const action = "20000000-0000-4000-8000-000000000001";
const newTitle = "Published after recovery point";
const newDraft = "Private after recovery point";
const oldTitle = "Published imported campaign webkit";
const witnessFile = "/proof/cutover-witness.json";
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
let witness;

if (mode === "--changed") {
  const replacement = await readFile(
    "apps/public/src/assets/krapfentaxi/hero.webp",
  );
  // Uploads intentionally re-encode raster images to discard private metadata
  // and appended bytes. Public delivery must match the normalized upload, not
  // the original fixture; retain an exact byte-integrity assertion.
  const expectedImage = await normalizeCampaignImage(replacement, "image/webp");
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
    const page = await context.newPage();
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
    const item = (await json(root)).items.find(
      (entry) => entry.data.action_id === action,
    );
    assert.ok(item);
    const api = `${root}/${item.id}`;
    const original = (await json(api)).item;
    assert.equal(original.data.story_title, "Private follow-up webkit");
    assert.ok(original.draftRevisionId);
    const publicHtml = async () => {
      const response = await anonymous.request.get(origin + canonical);
      assert.equal(response.status(), 200);
      assert.equal(response.headers()["cache-control"], "no-store");
      return response.text();
    };
    assert.ok((await publicHtml()).includes(oldTitle));
    const media = [];
    for (const reference of [
      original.data.hero_image,
      original.data.brand_logo,
      original.data.partners[0].logo,
    ]) {
      const id = reference.id;
      const response = await anonymous.request.get(
        `${origin}${canonical}media/${id}`,
      );
      assert.equal(response.status(), 200);
      media.push({ id, sha256: hash(await response.body()) });
    }
    witness = {
      itemId: item.id,
      originalData: original.data,
      draftRevisionId: original.draftRevisionId,
      media,
    };
    await page.goto(`${origin}${editor}/${item.id}`);
    const changeText = async (text) => {
      const saved = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === api &&
          response.request().method() === "PUT",
      );
      await page.locator("#field-story_title").fill(text);
      await page.locator("#field-title").click();
      assert.equal((await saved).status(), 200);
      await expect(
        page.getByRole("button", { name: "Saved", exact: true }),
      ).toBeVisible();
    };
    await changeText(newTitle);
    const field = page.locator("#field-hero_image");
    const removed = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === api &&
        response.request().method() === "PUT",
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
      (response) =>
        /\/_emdash\/api\/media\/[0-9A-Z]+\/confirm$/.test(
          new URL(response.url()).pathname,
        ) && response.request().method() === "POST",
    );
    try {
      const [confirmation] = await Promise.all([
        confirmed,
        dialog.getByLabel("Upload file", { exact: true }).setInputFiles({
          name: "post-recovery-point.webp",
          mimeType: "image/webp",
          buffer: replacement,
        }),
      ]);
      assert.equal(confirmation.status(), 200);
    } finally {
      stopUploadObservation();
    }
    const inserted = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === api &&
        response.request().method() === "PUT",
    );
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    assert.equal((await inserted).status(), 200);
    witness.newHero = (await json(api)).item.data.hero_image.id;
    assert.notEqual(witness.newHero, original.data.hero_image.id);
    const draftHtml = await publicHtml();
    assert.ok(draftHtml.includes(oldTitle) && !draftHtml.includes(newTitle));
    assert.ok(!draftHtml.includes(witness.newHero));
    const published = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `${api}/publish` &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    assert.equal((await published).status(), 200);
    const changed = await publicHtml();
    assert.ok(changed.includes(newTitle) && changed.includes(witness.newHero));
    const newMedia = await anonymous.request.get(
      `${origin}${canonical}media/${witness.newHero}`,
    );
    assert.equal(newMedia.status(), 200);
    assert.equal(hash(await newMedia.body()), expectedImage.contentHash);
    await changeText(newDraft);
    assert.ok(!(await publicHtml()).includes(newDraft));
    await writeFile(witnessFile, JSON.stringify(witness), {
      flag: "wx",
      mode: 0o600,
    });
    await coreLogout(context, page, editor, root);
  } finally {
    await browser.close();
  }
} else {
  witness = JSON.parse(await readFile(witnessFile, "utf8"));
}

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
        origin + (mode === "--changed" ? "/krapfentaxi" : canonical),
      );
      assert.equal(response.status(), 200);
      assert.equal(page.url(), origin + canonical);
      if (mode === "--changed") {
        const redirected = response.request().redirectedFrom();
        assert.equal(redirected.url(), origin + "/krapfentaxi");
        assert.equal(redirected.redirectedFrom(), null);
      }
      await expect(
        page.getByRole("heading", {
          name: mode === "--changed" ? newTitle : oldTitle,
          exact: true,
        }),
      ).toBeVisible();
      assert.ok(!(await page.locator("body").textContent()).includes(newDraft));
      await expect(page.locator("[data-order-form]")).toHaveCount(1);
      await expect(page.locator("body")).toHaveClass("taxi-site");
      for (const image of await page
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
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
      assert.equal((await context.cookies()).length, 0);
      if (mode === "--restored") {
        for (const { id, sha256 } of witness.media) {
          const media = await context.request.get(
            `${origin}${canonical}media/${id}`,
          );
          assert.equal(media.status(), 200);
          assert.equal(hash(await media.body()), sha256);
        }
        assert.equal(
          (
            await context.request.get(
              `${origin}${canonical}media/${witness.newHero}`,
            )
          ).status(),
          404,
        );
        const legacy = await context.request.get(origin + "/krapfentaxi");
        assert.equal(legacy.status(), 200);
        assert.ok((await legacy.text()).includes("data-order-form"));
        assert.equal(legacy.headers().location, undefined);
      }
      await page.screenshot({
        path: `/visual-proof/${mode.slice(2)}-${name}-${javaScriptEnabled ? "desktop" : "mobile"}.png`,
        fullPage: true,
      });
      await context.close();
    }
    if (mode === "--restored") {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      const page = await context.newPage();
      await page.goto(origin + editor);
      await browserLogin(
        context,
        page,
        editor,
        false,
        "klara.kern@leonaid.invalid",
      );
      const response = await context.request.get(
        `${origin}${root}/${witness.itemId}`,
      );
      assert.equal(response.status(), 200);
      const item = (await response.json()).data.item;
      assert.deepEqual(item.data, witness.originalData);
      assert.equal(item.draftRevisionId, witness.draftRevisionId);
      await page.goto(`${origin}${editor}/${witness.itemId}`);
      await expect(page.locator("#field-story_title")).toHaveValue(
        "Private follow-up webkit",
      );
      assert.equal(
        (
          await context.request.get(
            `${origin}/_emdash/api/media/${witness.newHero}`,
          )
        ).status(),
        404,
      );
      await coreLogout(context, page, editor, root);
      await context.close();
    }
    console.log(
      `cutover-browser ${name}: ${mode.slice(2)} native/JS campaign rendering, exact media and private draft boundary passed`,
    );
  } finally {
    await browser.close();
  }
}
