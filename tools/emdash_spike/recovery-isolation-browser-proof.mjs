import assert from "node:assert/strict";
import { chromium, firefox, webkit } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";
import {
  prepareRecoveryMedia,
  proveRecoverySurfaces,
} from "./recovery-surfaces-browser-proof.mjs";

const origin = "https://proxy:8443";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const actors = [
  {
    email: "klara.kern@leonaid.invalid",
    action: "20000000-0000-4000-8000-000000000001",
  },
  {
    email: "felix.fremd@leonaid.invalid",
    action: "20000000-0000-4000-8000-000000000003",
  },
];
const headers = { Origin: origin, "X-EmDash-Request": "1" };
const prepare = process.argv.includes("--prepare");
async function call(context, path, status = 200, method = "GET", data) {
  const response = await context.request.fetch(origin + path, {
    method,
    headers,
    ...(data === undefined ? {} : { data }),
    maxRedirects: 0,
  });
  assert.equal(
    response.status(),
    status,
    `Recovery isolation ${method} status`,
  );
  assert.equal(response.headers()["cache-control"], "no-store");
  assert.equal(response.headers()["set-cookie"], undefined);
  return response.json();
}
async function login(browser, actor) {
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();
  await page.goto(origin + editor);
  await page.getByRole("heading", { name: "Bei LeonAid anmelden" }).waitFor();
  await browserLogin(context, page, editor, false, actor.email);
  if ((await call(context, "/_emdash/api/auth/me")).data.isFirstLogin) {
    await page
      .getByRole("button", { name: "Get Started", exact: true })
      .click();
  }
  return { context, page };
}
for (const [name, engine] of Object.entries(
  prepare ? { chromium } : { chromium, firefox, webkit },
)) {
  const browser = await engine.launch({ headless: true });
  try {
    if (prepare) {
      const { context, page } = await login(browser, actors[1]);
      assert.equal((await call(context, root)).data.total, 0);
      await call(context, root, 201, "POST", {
        data: {
          action_id: actors[1].action,
          title: "Recovery foreign campaign draft",
          story_title: "Initial second campaign",
        },
      });
      const listing = (await call(context, root)).data;
      assert.equal(listing.total, 1);
      assert.equal(listing.items[0].data.action_id, actors[1].action);
      const path = `${root}/${listing.items[0].id}`;
      const initial = (await call(context, path)).data;
      const heroImage = await prepareRecoveryMedia(context, actors[1].action);
      await call(context, path, 200, "PUT", {
        _rev: initial._rev,
        data: {
          ...initial.item.data,
          story_title: "Private second campaign before backup",
          hero_image: heroImage,
        },
      });
      const item = (await call(context, path)).data.item;
      assert.ok(item.draftRevisionId);
      assert.equal(item.liveRevisionId, null);
      await coreLogout(context, page, editor, root);
      console.log(
        "recovery-isolation: second real campaign draft created through its own Core SMTP login before backup",
      );
      continue;
    }
    const sessions = [];
    for (const actor of actors) sessions.push(await login(browser, actor));
    const snapshots = [];
    for (const [index, { context }] of sessions.entries()) {
      const listing = (await call(context, root)).data;
      assert.equal(listing.total, 1);
      assert.equal(listing.items.length, 1);
      assert.equal(listing.items[0].data.action_id, actors[index].action);
      const path = `${root}/${listing.items[0].id}`;
      const detail = (await call(context, path)).data;
      assert.equal(typeof detail._rev, "string");
      const history = (await call(context, `${path}/revisions`)).data;
      assert.ok(history.items.length > 0);
      snapshots.push({ path, detail, history });
    }
    assert.equal(
      snapshots[1].detail.item.data.title,
      "Recovery foreign campaign draft",
    );
    assert.equal(
      snapshots[1].detail.item.data.story_title,
      "Private second campaign before backup",
    );
    await proveRecoverySurfaces(browser, sessions, actors, snapshots, name);
    for (const [index, { context }] of sessions.entries()) {
      const foreign = snapshots[1 - index];
      const missing = await call(
        context,
        `${root}/00000000000000000000000000`,
        404,
      );
      for (const suffix of ["", "/revisions", "/compare"]) {
        assert.ok(
          JSON.stringify(await call(context, foreign.path + suffix, 404)) ===
            JSON.stringify(missing),
        );
      }
      const query = `${root}?q=${encodeURIComponent(foreign.detail.item.data.title)}`;
      const ownerSearch = (await call(sessions[1 - index].context, query)).data;
      assert.ok(
        ownerSearch.items.some((item) => item.id === foreign.detail.item.id),
      );
      assert.equal((await call(context, query)).data.total, 0);
      const filter = encodeURIComponent(
        JSON.stringify({ action_id: actors[1 - index].action }),
      );
      const filtered = (await call(context, `${root}?fieldFilters=${filter}`))
        .data;
      assert.equal(filtered.total, 1);
      assert.ok(
        filtered.items.every(
          (item) => item.data.action_id === actors[index].action,
        ),
      );
      await call(context, foreign.path, 404, "PUT", {
        _rev: foreign.detail._rev,
        data: foreign.detail.item.data,
      });
      for (const operation of ["publish", "unpublish", "discard-draft"]) {
        await call(context, `${foreign.path}/${operation}`, 404, "POST", {});
      }
      for (const revision of foreign.history.items) {
        await call(context, `/_emdash/api/revisions/${revision.id}`, 404);
        await call(
          context,
          `/_emdash/api/revisions/${revision.id}/restore`,
          404,
          "POST",
          {},
        );
      }
      await call(context, root, 403, "POST", {
        data: {
          action_id: actors[1 - index].action,
          title: "Forbidden foreign campaign",
        },
      });
    }
    for (const [index, { context, page }] of sessions.entries()) {
      const own = snapshots[index];
      assert.ok(
        JSON.stringify((await call(context, own.path)).data) ===
          JSON.stringify(own.detail),
      );
      assert.ok(
        JSON.stringify((await call(context, `${own.path}/revisions`)).data) ===
          JSON.stringify(own.history),
      );
      // Valid revision and identical editorial payload succeed for the owner.
      await call(context, own.path, 200, "PUT", {
        _rev: own.detail._rev,
        data: own.detail.item.data,
      });
      await coreLogout(context, page, editor, root);
      await context.close();
    }
    console.log(
      `recovery-isolation ${name}: both restored Core logins, own draft access/write, hidden foreign search/filter/content/revisions and denied cross-campaign mutations; foreign records/history unchanged`,
    );
  } finally {
    await browser.close();
  }
}
