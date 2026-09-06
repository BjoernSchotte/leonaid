import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const origin = "https://proxy:8443";
const apiRoot = "/_emdash/api/content/campaign_pages";
const editorRoot = "/_emdash/admin/content/campaign_pages";
const engines = Object.entries({ chromium, firefox, webkit });
for (const [index, [name, engine]] of engines.entries()) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      locale: "en-US",
      viewport: { width: 1440, height: 1000 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const cookie = (value) => ({
      name: "__Host-leonaid_session",
      value,
      domain: "proxy",
      path: "/",
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    });
    if (process.argv.includes("--trashed")) {
      await context.addCookies([cookie(tokens.system)]);
      const response = await context.request.get(
        origin +
          "/_emdash/admin/campaigns/20000000-0000-4000-8000-000000000003",
        { maxRedirects: 0 },
      );
      assert.equal(response.status(), 409);
      assert.equal(response.headers()["cache-control"], "no-store");
      assert.deepEqual(await response.json(), {
        error: { code: "CAMPAIGN_BINDING_CONFLICT" },
      });
      console.log(
        `campaign-handoff-browser: OK: ${name}: real trashed content reserves the campaign binding`,
      );
      await context.close();
      continue;
    }
    const action = `20000000-0000-4000-8000-${String([3, 41, 42][index]).padStart(12, "0")}`;
    const newPath = editorRoot + "/new?campaign=" + action;
    const handoffPath = "/_emdash/admin/campaigns/" + action;
    await page.goto(origin + handoffPath);
    await page.waitForURL("**/login?returnTo=**");
    assert.equal(new URL(page.url()).searchParams.get("returnTo"), handoffPath);
    await page.goto(origin + newPath);
    await page.waitForURL("**/login?returnTo=**");
    assert.equal(new URL(page.url()).searchParams.get("returnTo"), newPath);
    await context.addCookies([cookie(tokens.system)]);
    const title = `Native ${name} new campaign`;
    const json = async (path) => {
      const response = await context.request.get(origin + path);
      assert.equal(response.status(), 200);
      return (await response.json()).data;
    };
    const before = await json(apiRoot);
    const resolve = async (path) => {
      const response = await context.request.get(origin + path, {
        maxRedirects: 0,
      });
      assert.equal(response.headers()["cache-control"], "no-store");
      return response;
    };
    const uncreated = await resolve(handoffPath);
    assert.equal(uncreated.status(), 303);
    assert.equal(uncreated.headers().location, newPath);
    assert.equal((await json(apiRoot)).total, before.total);
    const submit = async (status) => {
      assert.equal((await page.goto(origin + newPath)).status(), 200);
      await page.locator("#field-title").fill(title);
      await page.locator("#field-hero_title").fill("A campaign with a purpose");
      await page
        .locator("#field-hero_summary")
        .fill("Synthetic introduction from the native editor.");
      await page
        .locator("#field-seo_description")
        .fill("Synthetic campaign search description.");
      await expect(page.locator("#field-action_id")).toHaveValue(action);
      await expect(
        page.getByPlaceholder("my-post-slug", { exact: true }),
      ).toHaveValue(action);
      const pending = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === apiRoot &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Save", exact: true }).click();
      const response = await pending;
      assert.equal(response.status(), status);
      const submitted = response.request().postDataJSON();
      assert.deepEqual(submitted.data, {
        title,
        action_id: action,
        hero_title: "A campaign with a purpose",
        hero_summary: "Synthetic introduction from the native editor.",
        seo_description: "Synthetic campaign search description.",
      });
      assert.equal(submitted.slug, action);
      assert.deepEqual(submitted.bylines, []);
      return response.json();
    };
    const created = (await submit(201)).data;
    const editorPath = `${editorRoot}/${created.item.id}`;
    await page.waitForURL((url) => url.pathname === editorPath);
    await expect(page.locator("#field-title")).toHaveValue(title);
    assert.equal(created.item.status, "draft");
    assert.equal(
      created.item.authorId,
      (await json("/_emdash/api/auth/me")).id,
    );
    assert.equal((await json(apiRoot)).total, before.total + 1);
    const existing = await resolve(handoffPath);
    assert.equal(existing.status(), 303);
    assert.equal(existing.headers().location, editorPath);
    await page.goto(origin + handoffPath);
    await page.waitForURL((url) => url.pathname === editorPath);
    await expect(page.locator("#field-title")).toHaveValue(title);
    const seeded = await resolve(
      "/_emdash/admin/campaigns/20000000-0000-4000-8000-000000000001",
    );
    assert.equal(seeded.status(), 303);
    const seededEntry = before.items.find(
      (item) => item.data.action_id === "20000000-0000-4000-8000-000000000001",
    );
    assert.ok(seededEntry);
    assert.equal(seeded.headers().location, `${editorRoot}/${seededEntry.id}`);
    assert.equal(
      (
        await resolve(
          "/_emdash/admin/campaigns/20000000-0000-4000-8000-999999999999",
        )
      ).status(),
      503,
    );
    assert.equal(
      (await context.request.post(origin + handoffPath)).status(),
      503,
    );
    await submit(409);
    assert.equal((await json(apiRoot)).total, before.total + 1);
    await page.goto(origin + editorPath);
    const saved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `${apiRoot}/${created.item.id}` &&
        response.request().method() === "PUT",
    );
    await page.locator("#field-title").fill(title + " revised");
    assert.equal((await saved).status(), 200);
    await page.reload();
    await expect(page.locator("#field-title")).toHaveValue(title + " revised");
    const stored = (await json(`${apiRoot}/${created.item.id}`)).item;
    assert.equal(stored.status, "draft");
    assert.equal(stored.data.action_id, action);
    assert.equal(stored.data.hero_title, "A campaign with a purpose");
    assert.equal(
      stored.data.hero_summary,
      "Synthetic introduction from the native editor.",
    );
    assert.equal(
      stored.data.seo_description,
      "Synthetic campaign search description.",
    );
    for (const query of [
      "campaign=invalid",
      `campaign=${action}&campaign=${action}`,
      "campaign=20000000-0000-4000-8000-999999999999",
    ]) {
      const denied = await context.request.get(
        origin + editorRoot + "/new?" + query,
      );
      assert.equal(denied.status(), query.endsWith("999999999999") ? 503 : 403);
    }
    await context.clearCookies();
    await context.addCookies([cookie(tokens.finance)]);
    assert.equal((await page.goto(origin + editorRoot + "/new")).status(), 403);
    assert.equal((await page.goto(origin + newPath)).status(), 403);
    assert.equal((await page.goto(origin + handoffPath)).status(), 403);
    await context.close();
    console.log(
      `campaign-create-browser: OK: ${name}: native draft creation, canonical editor return, duplicate rejection, subsequent autosave/reload and Finance denial`,
    );
  } finally {
    await browser.close();
  }
}
