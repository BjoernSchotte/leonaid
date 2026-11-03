import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { guardCsp } from "./csp-guard.mjs";
import { confirmPublish, unpublishButton } from "./editor-actions.mjs";
import {
  browserLogin,
  browserFreshLogin,
  coreLogout,
} from "./browser-login.mjs";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const origin = "https://proxy:8443";
const apiRoot = "/_emdash/api/content/campaign_pages";
const editorRoot = "/_emdash/admin/content/campaign_pages";
const revoked = process.argv.includes("--revoked");
const login = process.argv.includes("--login");
const charity = process.argv.includes("--charity");
const loginEmail = charity ? "klara.kern@leonaid.invalid" : undefined;
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = guardCsp(await engine.launch({ headless: true }));
  try {
    // Native Node TLS proofs separately verify this unique project's CA.
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
    const json = async (path) => {
      const response = await context.request.get(origin + path);
      assert.equal(response.status(), 200);
      assert.equal(response.headers()["cache-control"], "no-store");
      return (await response.json()).data;
    };
    await page.goto(origin + editorRoot);
    await page.waitForURL("**/login?returnTo=**");
    assert.equal(new URL(page.url()).searchParams.get("returnTo"), editorRoot);
    await page.getByRole("heading", { name: "Bei LeonAid anmelden" }).waitFor();
    if (login) await browserLogin(context, page, editorRoot, false, loginEmail);
    else
      await context.addCookies([
        cookie(charity ? tokens.charity : tokens.system),
      ]);
    if (revoked) {
      await page.goto(origin + editorRoot);
      await page.waitForURL("**/login?returnTo=**");
      assert.equal((await context.request.get(origin + apiRoot)).status(), 401);
      const handoffPath =
        "/_emdash/admin/campaigns/20000000-0000-4000-8000-000000000003";
      const handoff = await context.request.get(origin + handoffPath, {
        maxRedirects: 0,
      });
      assert.equal(handoff.status(), 303);
      assert.equal(
        new URL(handoff.headers().location, origin).searchParams.get(
          "returnTo",
        ),
        handoffPath,
      );
    } else {
      const entries = await json(apiRoot);
      const entry = entries.items.find(
        (item) =>
          item.data.action_id === "20000000-0000-4000-8000-000000000001",
      );
      assert.ok(entry);
      const apiPath = `${apiRoot}/${entry.id}`;
      const editorPath = `${editorRoot}/${entry.id}`;
      if (login)
        await browserFreshLogin(context, page, editorPath, apiRoot, loginEmail);
      const before = await json(apiPath);
      const history = await json(`${apiPath}/revisions`);
      const identity = await json("/_emdash/api/auth/me");
      assert.equal(identity.role, charity ? 40 : 50);
      // The SPA itself loads content and revisions; no intercepted requests,
      // injected form state, server doubles or API writes stand in for editing.
      assert.equal((await page.goto(origin + editorPath)).status(), 200);
      if (identity.isFirstLogin) {
        const dismissed = page.waitForResponse(
          (response) =>
            new URL(response.url()).pathname === "/_emdash/api/auth/me" &&
            response.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Get Started", exact: true })
          .click();
        assert.equal((await dismissed).status(), 200);
        const current = await json("/_emdash/api/auth/me");
        assert.deepEqual(current, { ...identity, isFirstLogin: false });
      }
      const title = page.locator("#field-title");
      await expect(title).toHaveValue(before.item.data.title);
      const stalePage = await context.newPage();
      await stalePage.goto(origin + editorPath);
      await expect(stalePage.locator("#field-title")).toHaveValue(
        before.item.data.title,
      );
      const editedTitle = `Native ${name} autosaved campaign title`;
      const autosave = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === apiPath &&
          response.request().method() === "PUT",
      );
      await title.fill(editedTitle);
      const saved = await autosave;
      const submitted = saved.request().postDataJSON();
      if (saved.status() !== 200) {
        const envelope = await saved.json().catch(() => null);
        // Diagnostics contain shape and fixed protocol checks, never values,
        // identity responses, cookies, content, or arbitrary upstream messages.
        console.log("campaign-editor-browser: rejected autosave shape", {
          keys: Object.keys(submitted),
          dataKeys: Object.keys(submitted.data ?? {}),
          sameSlug: submitted.slug === before.item.slug,
          sameRevision: submitted._rev === before._rev,
          sameLocale:
            new URL(saved.url()).searchParams.get("locale") ===
            before.item.locale,
          marker: saved.request().headers()["x-emdash-request"] === "1",
          sameOrigin: saved.request().headers().origin === origin,
          errorCode: envelope?.error?.code,
        });
      }
      assert.equal(saved.status(), 200);
      assert.equal(submitted.skipRevision, true);
      assert.equal(submitted.slug, before.item.slug);
      assert.equal(submitted._rev, before._rev);
      await expect(
        page.getByRole("button", { name: "Saved", exact: true }),
      ).toBeVisible();
      const draft = await json(apiPath);
      assert.equal(draft.item.data.title, editedTitle);
      assert.equal(draft.item.liveData.title, before.item.liveData.title);
      assert.equal(draft.item.slug, before.item.slug);
      assert.equal(
        (await json(`${apiPath}/revisions`)).total,
        history.total + 1,
      );
      const revision = await json(
        `/_emdash/api/revisions/${draft.item.draftRevisionId}`,
      );
      assert.equal(revision.item.authorId, identity.id);
      const staleSave = stalePage.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === apiPath &&
          response.request().method() === "PUT",
      );
      await stalePage
        .locator("#field-title")
        .fill("Stale browser must not overwrite");
      assert.equal((await staleSave).status(), 409);
      assert.equal((await json(apiPath)).item.data.title, editedTitle);
      assert.equal(
        (await json(`${apiPath}/revisions`)).total,
        history.total + 1,
      );
      await stalePage.close();
      // Hard reload proves persistence, not only optimistic React state.
      await page.reload();
      await expect(title).toHaveValue(editedTitle);
      const published = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === `${apiPath}/publish` &&
          response.request().method() === "POST",
      );
      await confirmPublish(page);
      assert.equal((await published).status(), 200);
      // Wait for the editor's publish/refetch transition, not merely receipt
      // of the HTTP response, before starting the next user edit.
      await expect(unpublishButton(page)).toBeVisible();
      await expect(title).toHaveValue(editedTitle);
      const live = await json(apiPath);
      assert.equal(live.item.data.title, editedTitle);
      assert.equal(live.item.draftRevisionId, null);
      // EmDash 1.x saves the editor state before it publishes, so the live
      // revision is that attributed save of the autosaved draft content.
      const liveRevision = await json(
        `/_emdash/api/revisions/${live.item.liveRevisionId}`,
      );
      assert.equal(liveRevision.item.data.title, editedTitle);
      assert.equal(liveRevision.item.authorId, identity.id);
      // A later edit remains private, including after the next page load.
      const followup = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === apiPath &&
          response.request().method() === "PUT",
      );
      await title.fill(`${editedTitle} private follow-up`);
      assert.equal((await followup).status(), 200);
      await page.reload();
      await expect(title).toHaveValue(`${editedTitle} private follow-up`);
      assert.equal((await json(apiPath)).item.liveData.title, editedTitle);
      const manualSave = page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === apiPath &&
          response.request().method() === "PUT",
      );
      await title.fill(`${editedTitle} explicitly saved draft`);
      await page.getByRole("button", { name: "Save", exact: true }).click();
      const manual = await manualSave;
      assert.equal(manual.status(), 200);
      assert.notEqual(manual.request().postDataJSON().skipRevision, true);
      assert.equal(
        (await json(apiPath)).item.data.title,
        `${editedTitle} explicitly saved draft`,
      );
      assert.equal((await json(apiPath)).item.liveData.title, editedTitle);
      if (!login && !charity) {
        // Input typed while the editor's post-publish refetch is slow must
        // survive and autosave (EmDash's save-then-refetch reset and a stale
        // refetch after autosave both dropped it). The real responses are
        // only held back; their content is never changed.
        let delayRefetch = false;
        const entryReads =
          /\/_emdash\/api\/(?:content\/campaign_pages\/[0-9A-Z]{26}|revisions\/[0-9A-Z]{26})(?:\?.*)?$/;
        await context.route(entryReads, async (route) => {
          if (!delayRefetch || route.request().method() !== "GET")
            return route.continue();
          const response = await route.fetch();
          await new Promise((resolve) => setTimeout(resolve, 1500));
          await route.fulfill({ response });
        });
        for (const offset of [0, 750, 1500]) {
          delayRefetch = true;
          const publishedAgain = page.waitForResponse(
            (response) =>
              new URL(response.url()).pathname === `${apiPath}/publish` &&
              response.request().method() === "POST",
          );
          await confirmPublish(page);
          assert.equal((await publishedAgain).status(), 200);
          await page.waitForTimeout(offset);
          const typed = `${editedTitle} typed ${offset} ms after publish`;
          await title.fill(typed);
          await expect
            .poll(async () => (await json(apiPath)).item.data.title, {
              timeout: 15000,
            })
            .toBe(typed);
          await expect(title).toHaveValue(typed);
          delayRefetch = false;
        }
        await context.unroute(entryReads);
      }
      assert.equal(
        (await context.cookies()).some((item) =>
          ["emdash_session", "astro-session"].includes(item.name),
        ),
        false,
      );
    }
    if (login) {
      await coreLogout(context, page, editorRoot, apiRoot);
      console.log(
        `campaign-editor-browser: OK: ${name}: ${charity ? "Charity" : "System"} actual SMTP form login/fresh login, editor return, native editing and Core logout`,
      );
    }
    await context.clearCookies();
    await context.addCookies([cookie(tokens.finance)]);
    assert.equal((await page.goto(origin + editorRoot)).status(), 403);
    assert.equal((await context.request.get(origin + apiRoot)).status(), 403);
    assert.equal(
      (
        await page.goto(origin + editorRoot + "/00000000000000000000000000")
      ).status(),
      403,
    );
    assert.equal(
      (
        await context.request.get(origin + "/_emdash/admin/content/other")
      ).status(),
      503,
    );
    await context.close();
    console.log(
      `campaign-editor-browser: OK: ${name}: ${revoked ? "revoked editor navigation and API denied" : "native autosave/manual save, stale-tab conflict, attribution, reload, publish and private follow-up"}; Finance stays denied`,
    );
  } finally {
    await browser.close();
  }
}
