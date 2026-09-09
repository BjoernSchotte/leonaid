import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect } from "@playwright/test";

const origin = "https://proxy:8443";
const mediaRoot = "/_emdash/api/media";
const editor = "/_emdash/admin/content/campaign_pages";
const image = await readFile("apps/public/src/assets/krapfentaxi/logo.png");
const reservation = (filename) => ({
  filename,
  contentType: "image/png",
  size: image.length,
  contentHash: `sha1:${createHash("sha1").update(image).digest("hex")}`,
  deduplicate: false,
});
async function request(context, path, status = 200, method = "GET", data) {
  assert.ok(path.startsWith("/") && !path.startsWith("//"));
  const response = await context.request.fetch(origin + path, {
    method,
    headers: {
      Origin: origin,
      "X-EmDash-Request": "1",
      ...(Buffer.isBuffer(data) ? { "Content-Type": "image/png" } : {}),
    },
    ...(data === undefined ? {} : { data }),
    maxRedirects: 0,
  });
  assert.equal(response.status(), status, `Restored surface ${method} status`);
  assert.equal(response.headers()["cache-control"], "no-store");
  assert.equal(response.headers()["set-cookie"], undefined);
  return response;
}
const json = async (...args) => (await request(...args)).json();
async function file(context, item) {
  assert.ok(item.url.startsWith(`${mediaRoot}/file/`));
  const response = await request(context, item.url);
  const bytes = await response.body();
  assert.equal(
    createHash("sha256").update(bytes).digest("hex"),
    item.contentHash,
  );
  return bytes;
}
async function upload(context, action, filename) {
  const reserved = (
    await json(
      context,
      `${mediaRoot}/upload-url?campaign=${action}`,
      200,
      "POST",
      reservation(filename),
    )
  ).data;
  await request(context, reserved.uploadUrl, 200, "PUT", image);
  const ready = (
    await json(
      context,
      `${mediaRoot}/${reserved.mediaId}/confirm`,
      200,
      "POST",
      {},
    )
  ).data.item;
  assert.equal(ready.status, "ready");
  await file(context, ready);
  return ready;
}
export async function prepareRecoveryMedia(context, action) {
  const ready = await upload(context, action, "recovery-foreign-private.png");
  return {
    id: ready.id,
    provider: "local",
    alt: "Recovery private image",
    width: ready.width,
    height: ready.height,
    filename: ready.filename,
    mimeType: ready.mimeType,
    meta: { storageKey: ready.storageKey },
  };
}
export async function proveRecoverySurfaces(
  browser,
  sessions,
  actors,
  snapshots,
  name,
) {
  const media = [];
  for (const [index, { context }] of sessions.entries()) {
    const id = snapshots[index].detail.item.data.hero_image.id;
    const item = (await json(context, `${mediaRoot}/${id}`)).data.item;
    assert.equal(item.status, "ready");
    const listing = (
      await json(context, `${mediaRoot}?campaign=${actors[index].action}`)
    ).data;
    assert.ok(listing.items.some((entry) => entry.id === id));
    media.push({ item, listing, bytes: await file(context, item) });
  }
  assert.notEqual(media[0].item.id, media[1].item.id);
  const anonymous = await browser.newContext({ ignoreHTTPSErrors: true });
  for (const [index, { context, page }] of sessions.entries()) {
    const own = snapshots[index];
    const foreign = snapshots[1 - index];
    const foreignMedia = media[1 - index].item;
    const action = actors[index].action;
    const otherAction = actors[1 - index].action;
    await request(anonymous, media[index].item.url, 401);
    const missing = await json(
      context,
      `${mediaRoot}/01K00000000000000000000999`,
      404,
    );
    assert.ok(
      JSON.stringify(
        await json(context, `${mediaRoot}/${foreignMedia.id}`, 404),
      ) === JSON.stringify(missing),
    );
    for (const path of [
      foreignMedia.url,
      `${mediaRoot}/file/${encodeURIComponent(foreignMedia.storageKey)}`,
    ]) {
      await request(context, path, 404);
    }
    await request(
      context,
      `${mediaRoot}/${foreignMedia.id}/confirm`,
      404,
      "POST",
      {},
    );
    await request(
      context,
      `${mediaRoot}/${foreignMedia.id}/upload`,
      404,
      "PUT",
      image,
    );
    await request(
      context,
      `${mediaRoot}/upload-url?campaign=${otherAction}`,
      403,
      "POST",
      reservation("forbidden-foreign.png"),
    );
    for (const path of [
      mediaRoot,
      `${mediaRoot}?campaign=${otherAction}`,
      `${mediaRoot}?campaign=${action}&campaign=${otherAction}`,
    ]) {
      await request(context, path, 403);
    }
    const q = encodeURIComponent(foreignMedia.filename);
    const positive = (
      await json(
        sessions[1 - index].context,
        `${mediaRoot}?campaign=${otherAction}&q=${q}`,
      )
    ).data;
    assert.ok(positive.items.some((item) => item.id === foreignMedia.id));
    assert.equal(
      (await json(context, `${mediaRoot}?campaign=${action}&q=${q}`)).data.items
        .length,
      0,
    );
    await request(context, own.path, 403, "PUT", {
      _rev: own.detail._rev,
      data: { ...own.detail.item.data, hero_image: { id: foreignMedia.id } },
    });
    const handoff = await request(
      context,
      `/_emdash/admin/campaigns/${action}`,
      303,
    );
    assert.equal(handoff.headers().location, `${editor}/${own.detail.item.id}`);
    for (const path of [
      `/_emdash/admin/campaigns/${otherAction}`,
      `${editor}/new?campaign=${otherAction}`,
      `${editor}/new`,
      `${editor}/new?campaign=${action}&campaign=${otherAction}`,
    ])
      await request(context, path, 403);
    assert.equal(
      (await page.goto(origin + `${editor}/${own.detail.item.id}`)).status(),
      200,
    );
    await expect(page.locator("#field-story_title")).toHaveValue(
      own.detail.item.data.story_title,
    );
    const preview = page.locator("#field-hero_image img");
    await expect(preview).toHaveCount(1);
    await expect
      .poll(() =>
        preview.evaluate((img) => img.complete && img.naturalWidth > 0),
      )
      .toBe(true);
    const denied = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === foreign.path &&
        response.request().method() === "GET",
    );
    assert.equal(
      (
        await page.goto(origin + `${editor}/${foreign.detail.item.id}`)
      ).status(),
      200,
    );
    assert.equal((await denied).status(), 404);
    await expect(page.locator("#field-title")).toHaveCount(0);
    assert.ok(!(await page.content()).includes(foreign.detail.item.data.title));
  }
  await anonymous.close();
  for (const [index, { context }] of sessions.entries()) {
    const before = media[index];
    const after = (await json(context, `${mediaRoot}/${before.item.id}`)).data
      .item;
    assert.ok(JSON.stringify(after) === JSON.stringify(before.item));
    assert.ok((await file(context, after)).equals(before.bytes));
    assert.ok(
      JSON.stringify(
        (await json(context, `${mediaRoot}?campaign=${actors[index].action}`))
          .data,
      ) === JSON.stringify(before.listing),
    );
    await upload(
      context,
      actors[index].action,
      `restored-${name}-${index}.png`,
    );
  }
  console.log(
    `recovery-surfaces ${name}: native own editor/image renders; foreign editor data, handoff/create routes, media metadata/files/search/upload/confirm and foreign image binding denied; restored private bytes unchanged and own uploads succeed`,
  );
}
