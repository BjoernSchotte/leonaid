import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const origin = "https://proxy:8443";
const apiRoot = "/_emdash/api/content/campaign_pages";
const editorRoot = "/_emdash/admin/content/campaign_pages";
const revoked = process.argv.includes("--revoked");
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
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
    await context.addCookies([cookie(tokens.system)]);
    if (revoked) {
      await page.goto(origin + editorRoot);
      await page.waitForURL("**/login?returnTo=**");
      assert.equal((await context.request.get(origin + apiRoot)).status(), 401);
    } else {
      const entries = await json(apiRoot);
      const entry = entries.items.find(
        (item) =>
          item.data.action_id === "20000000-0000-4000-8000-000000000001",
      );
      assert.ok(entry);
      const apiPath = `${apiRoot}/${entry.id}`;
      const editorPath = `${editorRoot}/${entry.id}`;
      const before = await json(apiPath);
      const history = await json(`${apiPath}/revisions`);
      const identity = await json("/_emdash/api/auth/me");
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
      await page.getByRole("button", { name: "Publish", exact: true }).click();
      assert.equal((await published).status(), 200);
      // Wait for the editor's publish/refetch transition, not merely receipt
      // of the HTTP response, before starting the next user edit.
      await expect(
        page.getByRole("button", { name: /^Unpublish / }),
      ).toBeVisible();
      await expect(title).toHaveValue(editedTitle);
      const live = await json(apiPath);
      assert.equal(live.item.data.title, editedTitle);
      assert.equal(live.item.draftRevisionId, null);
      assert.equal(live.item.liveRevisionId, draft.item.draftRevisionId);
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
      assert.equal(
        (await context.cookies()).some((item) =>
          ["emdash_session", "astro-session"].includes(item.name),
        ),
        false,
      );
    }
    await context.clearCookies();
    await context.addCookies([cookie(tokens.charity)]);
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
      `campaign-editor-browser: OK: ${name}: ${revoked ? "revoked editor navigation and API denied" : "native autosave/manual save, stale-tab conflict, attribution, reload, publish and private follow-up"}; Charity stays denied`,
    );
  } finally {
    await browser.close();
  }
}
