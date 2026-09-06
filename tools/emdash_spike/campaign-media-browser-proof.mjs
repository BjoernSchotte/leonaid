import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const action = "20000000-0000-4000-8000-000000000001";
const state = JSON.parse(
  await readFile("/proof/media-http-state.json", "utf8"),
);
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
    await page.getByRole("heading", { name: "Bei LeonAid anmelden" }).waitFor();
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
    const list = await json(root);
    const entry = list.items.find((item) => item.data.action_id === action);
    assert.ok(entry);
    const apiPath = `${root}/${entry.id}`;
    await page.goto(`${origin}${editor}/${entry.id}`);
    if ((await json("/_emdash/api/auth/me")).isFirstLogin) {
      await page
        .getByRole("button", { name: "Get Started", exact: true })
        .click();
    }
    await expect(page.locator("#field-title")).toBeVisible();
    const field = page.locator("#field-hero_image");
    await expect(field).toBeVisible();
    const nativeSave = () =>
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === apiPath &&
          response.request().method() === "PUT",
      );
    if ((await json(apiPath)).item.data.hero_image) {
      const removed = nativeSave();
      await field
        .getByRole("button", { name: "Remove image", exact: true })
        .click();
      assert.equal((await removed).status(), 200);
      await expect(
        page.getByRole("button", { name: "Saved", exact: true }),
      ).toBeVisible();
    }
    const fetched = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/_emdash/api/media" &&
        response.request().method() === "GET",
    );
    await field
      .getByRole("button", { name: "Select image", exact: true })
      .click();
    const scoped = await fetched;
    assert.equal(
      scoped.status(),
      200,
      `native picker query keys=${[...new URL(scoped.url()).searchParams.keys()].join(",")} mimeType=${new URL(scoped.url()).searchParams.get("mimeType")}`,
    );
    assert.equal(new URL(scoped.url()).searchParams.get("campaign"), action);
    const items = (await scoped.json()).data.items;
    assert.ok(items.some((item) => item.id === state.ready.id));
    assert.ok(items.every((item) => item.id !== state.foreign.id));
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("Insert from URL", { exact: true }),
    ).toHaveCount(0);
    await expect(
      dialog.locator('img[src*="/_emdash/api/media/file/"]').first(),
    ).toBeVisible();
    await expect
      .poll(() =>
        dialog
          .locator('img[src*="/_emdash/api/media/file/"]')
          .first()
          .evaluate((img) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    // Reuse actual private fixture bytes, then upload through the native file
    // input. No API writes, request interception or injected React state.
    const bytes = await context.request.get(
      `${origin}/_emdash/api/media/file/${state.ready.storageKey}`,
    );
    assert.equal(bytes.status(), 200);
    const filename = `native-${name}-campaign.png`;
    const confirmed = page.waitForResponse(
      (response) =>
        /\/_emdash\/api\/media\/[0-9A-Z]+\/confirm$/.test(
          new URL(response.url()).pathname,
        ) && response.request().method() === "POST",
    );
    await dialog.getByLabel("Upload file", { exact: true }).setInputFiles({
      name: filename,
      mimeType: "image/png",
      buffer: await bytes.body(),
    });
    const confirmation = await confirmed;
    assert.equal(confirmation.status(), 200);
    const uploaded = (await confirmation.json()).data.item;
    assert.ok(uploaded.storageKey.startsWith(`campaigns/${action}/`));
    const saved = nativeSave();
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    assert.equal((await saved).status(), 200);
    await expect(dialog).toHaveCount(0);
    await page.reload();
    await expect
      .poll(() =>
        field
          .locator("img")
          .evaluate((img) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    assert.equal((await json(apiPath)).item.data.hero_image.id, uploaded.id);
    const published = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `${apiPath}/publish` &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    assert.equal((await published).status(), 200);
    await expect(
      page.getByRole("button", { name: /^Unpublish / }),
    ).toBeVisible();
    const live = (await json(apiPath)).item;
    assert.equal(live.status, "published");
    assert.equal(live.draftRevisionId, null);
    assert.ok(live.liveRevisionId);
    assert.equal(live.data.hero_image.id, uploaded.id);
    assert.equal(
      (await json(`/_emdash/api/revisions/${live.liveRevisionId}`)).item.data
        .hero_image.id,
      uploaded.id,
    );
    await coreLogout(context, page, editor, root);
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
      `campaign-media-browser: ${name}: actual SMTP Core login, scoped native picker/list/thumbnail, native upload/insert/save/reload/publish and private preview denied after logout`,
    );
  } finally {
    await browser.close();
  }
}
