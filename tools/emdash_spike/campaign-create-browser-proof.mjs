import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const origin = "https://proxy:8443";
const apiRoot = "/_emdash/api/content/campaign_pages";
const editorRoot = "/_emdash/admin/content/campaign_pages";
const engines = Object.entries({ chromium, firefox, webkit });
const charity = process.argv.includes("--charity-login");
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
    const action = `20000000-0000-4000-8000-${String((charity ? [43, 44, 45] : [3, 41, 42])[index]).padStart(12, "0")}`;
    const newPath = editorRoot + "/new?campaign=" + action;
    const handoffPath = "/_emdash/admin/campaigns/" + action;
    await page.goto(origin + handoffPath);
    await page.waitForURL("**/login?returnTo=**");
    assert.equal(new URL(page.url()).searchParams.get("returnTo"), handoffPath);
    await page.goto(origin + newPath);
    await page.waitForURL("**/login?returnTo=**");
    assert.equal(new URL(page.url()).searchParams.get("returnTo"), newPath);
    if (charity)
      await browserLogin(
        context,
        page,
        newPath,
        false,
        "klara.kern@leonaid.invalid",
      );
    else await context.addCookies([cookie(tokens.system)]);
    const title = `Native ${name} new campaign`;
    const json = async (path) => {
      const response = await context.request.get(origin + path);
      assert.equal(response.status(), 200);
      return (await response.json()).data;
    };
    const before = await json(apiRoot);
    const identity = await json("/_emdash/api/auth/me");
    assert.equal(identity.role, charity ? 40 : 50);
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
    const leaveWithWarning = async (accept, navigate) => {
      const warning = page.waitForEvent("dialog").then(async (dialog) => {
        assert.equal(dialog.type(), "beforeunload");
        if (accept) await dialog.accept();
        else await dialog.dismiss();
      });
      await Promise.all([warning, navigate()]);
    };
    await page.goto(origin + editorRoot);
    await page.goto(origin + newPath);
    await expect(page.locator("#field-action_id")).toHaveValue(action);
    // Focus alone activates browser leave warnings, but is not an edit.
    await page.locator("#field-hero_title").click();
    await page.goBack();
    await page.waitForURL(origin + editorRoot);
    await page.goto(origin + newPath);
    await page.locator("#field-hero_title").fill("Unsaved navigation proof");
    await leaveWithWarning(false, () =>
      page
        .getByRole("link", { name: "Zurück zu LeonAid", exact: true })
        .click(),
    );
    assert.equal(page.url(), origin + newPath);
    await expect(page.locator("#field-hero_title")).toHaveValue(
      "Unsaved navigation proof",
    );
    await leaveWithWarning(true, () => page.goBack());
    await page.waitForURL(origin + editorRoot);
    assert.equal((await json(apiRoot)).total, before.total);
    console.log(
      `campaign-navigation-browser: OK: ${name}: untouched prefill returns; actual beforeunload cancel preserves input; confirm leaves; no draft created`,
    );
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
      charity ? 403 : 503,
    );
    assert.equal(
      (await context.request.post(origin + handoffPath)).status(),
      503,
    );
    await submit(409);
    assert.equal((await json(apiRoot)).total, before.total + 1);
    // The rejected duplicate remains an unsaved form; discard it explicitly.
    await leaveWithWarning(true, () => page.goto(origin + editorPath));
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
      assert.equal(
        denied.status(),
        query.endsWith("999999999999") && !charity ? 503 : 403,
      );
    }
    if (charity) {
      // The positive creation path above used only the actual email-code form.
      // A separate real Core actor must not discover or claim its new binding.
      const foreign = await browser.newContext({ ignoreHTTPSErrors: true });
      await foreign.addCookies([cookie(tokens.charity_b)]);
      assert.equal(
        (
          await foreign.request.get(origin + `${apiRoot}/${created.item.id}`)
        ).status(),
        404,
      );
      assert.equal(
        (
          await foreign.request.get(origin + handoffPath, { maxRedirects: 0 })
        ).status(),
        403,
      );
      assert.equal(
        (
          await foreign.request.post(origin + apiRoot, {
            headers: { Origin: origin, "X-EmDash-Request": "1" },
            data: {
              data: {
                action_id: action,
                title: "Foreign browser claim denied",
              },
            },
          })
        ).status(),
        403,
      );
      assert.deepEqual(
        (await json(`${apiRoot}/${created.item.id}`)).item,
        stored,
      );
      await foreign.close();
      await coreLogout(context, page, editorPath, apiRoot);
    }
    await context.clearCookies();
    await context.addCookies([cookie(tokens.finance)]);
    assert.equal((await page.goto(origin + editorRoot + "/new")).status(), 403);
    assert.equal((await page.goto(origin + newPath)).status(), 403);
    assert.equal((await page.goto(origin + handoffPath)).status(), 403);
    await context.close();
    console.log(
      `campaign-create-browser: OK: ${name}: ${charity ? "Charity SMTP login and Core logout; " : ""}native draft creation, canonical editor return, duplicate rejection, subsequent autosave/reload and Finance denial`,
    );
  } finally {
    await browser.close();
  }
}
