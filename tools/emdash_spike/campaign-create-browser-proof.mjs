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
    await page.goto(origin + editorRoot + "/new");
    await page.waitForURL("**/login?returnTo=**");
    assert.equal(
      new URL(page.url()).searchParams.get("returnTo"),
      editorRoot + "/new",
    );
    await context.addCookies([cookie(tokens.system)]);
    const action = `20000000-0000-4000-8000-${String([3, 41, 42][index]).padStart(12, "0")}`;
    const title = `Native ${name} new campaign`;
    const json = async (path) => {
      const response = await context.request.get(origin + path);
      assert.equal(response.status(), 200);
      return (await response.json()).data;
    };
    const before = await json(apiRoot);
    const submit = async (status) => {
      assert.equal(
        (await page.goto(origin + editorRoot + "/new")).status(),
        200,
      );
      await page.locator("#field-title").fill(title);
      await page.locator("#field-action_id").fill(action);
      await page.getByPlaceholder("my-post-slug", { exact: true }).fill(action);
      const pending = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === apiRoot &&
          response.request().method() === "POST",
      );
      await page.getByRole("button", { name: "Save", exact: true }).click();
      const response = await pending;
      assert.equal(response.status(), status);
      const submitted = response.request().postDataJSON();
      assert.deepEqual(submitted.data, { title, action_id: action });
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
    await context.clearCookies();
    await context.addCookies([cookie(tokens.charity)]);
    assert.equal((await page.goto(origin + editorRoot + "/new")).status(), 403);
    await context.close();
    console.log(
      `campaign-create-browser: OK: ${name}: native draft creation, canonical editor return, duplicate rejection, subsequent autosave/reload and Charity denial`,
    );
  } finally {
    await browser.close();
  }
}
