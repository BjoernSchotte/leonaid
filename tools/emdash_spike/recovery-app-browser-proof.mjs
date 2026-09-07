import assert from "node:assert/strict";
import { access, writeFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const path = "/campaigns/krapfentaxi-2026/";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const action = "20000000-0000-4000-8000-000000000001";
let expectedDraft = "Private follow-up webkit";
function stablePublicHtml(html) {
  const command =
    /(<input type="hidden" name="commandId" value=")[0-9a-f-]{36}("\s*\/?>)/g;
  const token =
    /(<input type="hidden" name="accessToken" value=")([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)("\s*\/?>)/g;
  assert.equal([...html.matchAll(command)].length, 1);
  assert.equal([...html.matchAll(token)].length, 1);
  return html
    .replace(command, "$1COMMAND_ID$2")
    .replace(token, (_match, prefix, encoded, _signature, suffix) => {
      // Core issues a newly timed HMAC token for each public page request.
      // Preserve all non-time claims and the lifetime in the comparison.
      const { issuedAt, expiresAt, ...claims } = JSON.parse(
        Buffer.from(encoded, "base64url").toString("utf8"),
      );
      assert.ok(Number.isSafeInteger(issuedAt));
      assert.ok(Number.isSafeInteger(expiresAt) && expiresAt > issuedAt);
      assert.equal(claims.actionId, action);
      return (
        prefix +
        Buffer.from(
          JSON.stringify({
            ...claims,
            lifetime: expiresAt - issuedAt,
          }),
        ).toString("base64url") +
        suffix
      );
    });
}
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
    const visitor = await anonymous.newPage();
    assert.equal((await visitor.goto(origin + path)).status(), 200);
    await expect(
      visitor.getByRole("heading", {
        name: "Published imported campaign webkit",
        exact: true,
      }),
    ).toBeVisible();
    await expect(visitor.locator("[data-order-form]")).toHaveCount(1);
    await expect(visitor.locator(".taxi-hero__image")).toHaveCount(1);
    await expect(visitor.locator(".taxi-hero__logo")).toHaveCount(1);
    await expect(visitor.locator(".taxi-bakery__logo img")).toHaveCount(1);
    for (const image of await visitor
      .locator(".taxi-hero img, .taxi-bakery__logo img")
      .all()) {
      await image.scrollIntoViewIfNeeded();
      await expect
        .poll(() =>
          image.evaluate((img) => img.complete && img.naturalWidth > 0),
        )
        .toBe(true);
    }
    assert.equal((await anonymous.cookies()).length, 0);
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
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
    const listing = await context.request.get(origin + root);
    assert.equal(listing.status(), 200);
    const items = (await listing.json()).data.items;
    assert.ok(items.length > 0);
    assert.ok(items.every((item) => item.data.action_id === action));
    const entry = items.find((item) => item.data.action_id === action);
    const api = `${root}/${entry.id}`;
    const before = await context.request.get(origin + api);
    const detail = (await before.json()).data.item;
    assert.ok(detail.draftRevisionId);
    await page.goto(`${origin}${editor}/${entry.id}`);
    await expect(page.locator("#field-story_title")).toHaveValue(expectedDraft);
    const marker = `Restored private draft ${name}`;
    const saved = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === api &&
        response.request().method() === "PUT",
    );
    await page.locator("#field-story_title").fill(marker);
    await page.locator("#field-title").click();
    assert.equal((await saved).status(), 200);
    await expect(
      page.getByRole("button", { name: "Saved", exact: true }),
    ).toBeVisible();
    const published = await anonymous.request.get(origin + path);
    assert.equal(published.status(), 200);
    const html = await published.text();
    assert.ok(html.includes("Published imported campaign webkit"));
    assert.ok(!html.includes(marker));
    expectedDraft = marker;
    const retainedResponse = (
      await (await context.request.get(origin + api)).json()
    ).data;
    const retained = retainedResponse.item;
    assert.equal(typeof retainedResponse._rev, "string");
    assert.ok(retainedResponse._rev.length > 0);
    const authorizedMarker = `Restored authorized edit ${name}`;
    const edit = {
      _rev: retainedResponse._rev,
      data: { ...retained.data, story_title: authorizedMarker },
    };
    const sessionBefore = await context.cookies();
    const waitForOperator = async (phase) => {
      await expect
        .poll(
          async () => {
            try {
              await access(`/recovery-control/${name}-${phase}`);
              return true;
            } catch {
              return false;
            }
          },
          { timeout: 90000, intervals: [100, 200, 400] },
        )
        .toBe(true);
    };
    await writeFile(`/recovery-control/${name}-ready`, "ready", { flag: "wx" });
    await waitForOperator("revoked");
    assert.equal(
      (await context.request.get(origin + "/api/v1/identity/me")).status(),
      200,
    );
    assert.equal((await context.request.get(origin + api)).status(), 404);
    assert.equal(
      (
        await context.request.get(
          `${origin}/_emdash/api/revisions/${retained.draftRevisionId}`,
        )
      ).status(),
      404,
    );
    const headers = {
      Origin: origin,
      "Sec-Fetch-Site": "same-origin",
      "X-EmDash-Request": "1",
    };
    assert.equal(
      (
        await context.request.put(origin + api, {
          headers,
          data: edit,
        })
      ).status(),
      404,
    );
    assert.equal(
      (
        await context.request.post(`${origin}${api}/publish`, {
          headers,
          data: {},
        })
      ).status(),
      404,
    );
    await writeFile(`/recovery-control/${name}-denied`, "denied", {
      flag: "wx",
    });
    await waitForOperator("restored");
    const allowedAgain = await context.request.get(origin + api);
    assert.equal(allowedAgain.status(), 200);
    assert.ok(
      JSON.stringify((await allowedAgain.json()).data.item) ===
        JSON.stringify(retained),
    );
    assert.ok(
      JSON.stringify(await context.cookies()) === JSON.stringify(sessionBefore),
    );
    // Replay the identical previously denied request after regrant. This must
    // succeed, proving denial was authority-based, not CSRF or invalid input.
    assert.equal(
      (
        await context.request.put(origin + api, { headers, data: edit })
      ).status(),
      200,
    );
    expectedDraft = authorizedMarker;
    assert.ok(
      stablePublicHtml(
        await (await anonymous.request.get(origin + path)).text(),
      ) === stablePublicHtml(html),
      "Published HTML changed beyond per-request order command ID and token timing/signature",
    );
    console.log(
      `recovery-authority ${name}: same valid Core session loses item/revision/write/publish access on membership expiry; regrant reveals unchanged draft and accepts identical write; public content unchanged`,
    );
    await coreLogout(context, page, editor, root);
    await context.close();
    await anonymous.close();
    console.log(
      `recovery-app ${name}: actual restored Core SMTP login, scoped CMS listing, retained/editable draft, published media and logout denial passed`,
    );
  } finally {
    await browser.close();
  }
}
