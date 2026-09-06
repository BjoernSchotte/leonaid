import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { request } from "node:https";
import { createHash } from "node:crypto";
import sharp from "sharp";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const root = "/_emdash/api/media";
const a = "20000000-0000-4000-8000-000000000001";
const b = "20000000-0000-4000-8000-000000000003";
const image = await sharp({
  create: { width: 6, height: 4, channels: 3, background: "#a94060" },
})
  .png()
  .withMetadata()
  .toBuffer();
const statePath = "/proof/media-http-state.json";
async function call(
  actor,
  path,
  status = 200,
  method = "GET",
  body,
  options = {},
) {
  const bytes =
    body === undefined
      ? undefined
      : Buffer.isBuffer(body)
        ? body
        : Buffer.from(JSON.stringify(body));
  const result = await new Promise((resolve, reject) => {
    const headers = {
      ...(tokens[actor]
        ? { Cookie: `__Host-leonaid_session=${tokens[actor]}` }
        : {}),
      Origin: "https://proxy:8443",
      "X-EmDash-Request": "1",
      ...(bytes
        ? {
            "Content-Type": Buffer.isBuffer(body)
              ? "image/png"
              : "application/json",
            "Content-Length": bytes.length,
          }
        : {}),
      ...options.headers,
    };
    for (const key of Object.keys(headers))
      if (headers[key] === null) delete headers[key];
    const req = request(
      new URL(path, "https://proxy:8443"),
      { ca, servername: "proxy", method, headers },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("error", reject);
        response.on("end", () => {
          resolve({
            status: response.statusCode,
            headers: response.headers,
            bytes: Buffer.concat(chunks),
          });
          if (options.slow) req.destroy();
        });
      },
    );
    req.setTimeout(20_000, () =>
      req.destroy(new Error(`media_http_deadline: ${method} ${path}`)),
    );
    req.on("error", reject);
    if (options.slow) req.write(bytes.subarray(0, 1));
    else req.end(bytes);
  });
  assert.equal(result.status, status, `${actor} ${method} ${path}`);
  assert.equal(result.headers["cache-control"], "no-store");
  assert.equal(result.headers["set-cookie"], undefined);
  return {
    ...result,
    json: result.headers["content-type"]?.includes("application/json")
      ? JSON.parse(result.bytes.toString())
      : null,
  };
}
const reserve = async (actor, action, filename, bytes = image) =>
  (
    await call(actor, `${root}/upload-url?campaign=${action}`, 200, "POST", {
      filename,
      contentType: "image/png",
      size: bytes.length,
      contentHash: `sha1:${createHash("sha1").update(bytes).digest("hex")}`,
    })
  ).json.data;
const get = async (actor, id) =>
  (await call(actor, `${root}/${id}`)).json.data.item;
const list = async (actor, action) =>
  (await call(actor, `${root}?campaign=${action}`)).json.data;
const stage = async (actor, reservation, bytes = image) =>
  call(actor, reservation.uploadUrl, 200, "PUT", bytes);
const confirm = async (actor, id, status = 200, metadata = {}) =>
  call(actor, `${root}/${id}/confirm`, status, "POST", metadata);
const mode = process.argv[2];
if (mode) {
  const state = JSON.parse(await readFile(statePath, "utf8"));
  if (mode === "--confirm-failure") {
    const before = await get("charity", state.failure.mediaId);
    assert.equal(before.status, "pending");
    await confirm("charity", state.failure.mediaId, 503);
    assert.deepEqual(await get("charity", state.failure.mediaId), before);
  } else if (mode === "--confirm-retry") {
    const ready = (await confirm("charity", state.failure.mediaId)).json.data
      .item;
    assert.equal(ready.status, "ready");
    assert.deepEqual([ready.width, ready.height], [6, 4]);
  } else if (mode === "--tampered") {
    const before = await get("charity", state.tamper.mediaId);
    await confirm("charity", state.tamper.mediaId, 503);
    assert.deepEqual(await get("charity", state.tamper.mediaId), before);
  } else if (mode === "--storage-down") {
    const start = Date.now();
    await call("charity", state.ready.url, 503);
    await confirm("charity", state.ready.id, 503);
    assert.ok(Date.now() - start < 15_000);
    assert.equal((await get("charity", state.ready.id)).status, "ready");
  } else if (mode === "--retained") {
    const file = await call("charity", state.ready.url);
    assert.equal(
      createHash("sha256").update(file.bytes).digest("hex"),
      state.ready.contentHash,
    );
    assert.equal((await get("charity_b", state.foreign.id)).status, "ready");
  } else if (mode === "--revoked") {
    const before = await get("system", state.ready.id);
    for (const path of [
      `${root}?campaign=${a}`,
      `${root}/${state.ready.id}`,
      state.ready.url,
    ])
      await call("charity", path, 403);
    await call("charity", state.failure.uploadUrl, 403, "PUT", image);
    await confirm("charity", state.ready.id, 403);
    await call("charity", `${root}/upload-url?campaign=${a}`, 403, "POST", {
      filename: "revoked.png",
      contentType: "image/png",
      size: image.length,
    });
    assert.deepEqual(await get("system", state.ready.id), before);
    assert.equal((await get("charity_b", state.foreign.id)).status, "ready");
  } else if (mode === "--core-down") {
    const start = Date.now();
    for (const path of [
      `${root}?campaign=${a}`,
      `${root}/${state.ready.id}`,
      state.ready.url,
    ])
      await call("system", path, 503);
    assert.ok(Date.now() - start < 15_000);
  } else throw new Error("unknown_media_proof_mode");
  console.log(
    `campaign-media-http: ${mode} passed against actual dependencies`,
  );
} else {
  for (const actor of ["anonymous", "finance"])
    await call(
      actor,
      `${root}?campaign=${a}`,
      actor === "anonymous" ? 401 : 403,
    );
  await call("anonymous", `${root}?campaign=${a}`, 401, "GET", undefined, {
    headers: { "X-Forwarded-User": "system", "X-LeonAid-Role": "system_admin" },
  });
  await call("charity", `${root}?campaign=${b}`, 403);
  await call("charity", root, 403);
  await call("charity", `${root}?campaign=${a}&campaign=${b}`, 403);
  await call("charity", `${root}?campaign=${a}&folderId=global`, 400);
  const own = await reserve("charity", a, "synthetic-retained.png");
  const foreign = await reserve("charity_b", b, "synthetic-retained.png");
  assert.notEqual(own.mediaId, foreign.mediaId);
  assert.notEqual(own.storageKey, foreign.storageKey);
  assert.ok(
    own.uploadUrl.startsWith(`${root}/`) && !own.uploadUrl.includes("http"),
  );
  assert.deepEqual(Object.keys(own.headers).sort(), [
    "Content-Type",
    "X-EmDash-Request",
  ]);
  assert.equal((await get("charity", own.mediaId)).status, "pending");
  assert.equal((await list("charity", a)).totalCount, 0);
  await confirm("charity", own.mediaId, 409);
  await stage("charity", own);
  const pending = await get("charity", own.mediaId);
  assert.equal(pending.status, "pending");
  assert.notEqual(pending.storageKey, own.storageKey);
  await call("charity", pending.url, 404);
  await call("anonymous", pending.url, 401);
  const ready = (
    await confirm("charity", own.mediaId, 200, {
      size: image.length,
      width: 99,
      height: 98,
    })
  ).json.data.item;
  assert.equal(ready.status, "ready");
  assert.deepEqual([ready.width, ready.height], [6, 4]);
  assert.equal(
    (await confirm("charity", own.mediaId)).json.data.item.id,
    own.mediaId,
  );
  const delivered = await call("charity", ready.url);
  assert.equal(delivered.headers["content-type"], "image/png");
  assert.equal(delivered.headers["x-content-type-options"], "nosniff");
  assert.equal(
    createHash("sha256").update(delivered.bytes).digest("hex"),
    ready.contentHash,
  );
  const decoded = await sharp(delivered.bytes).metadata();
  assert.ok(!decoded.exif && !decoded.icc && !decoded.xmp);
  await stage("charity_b", foreign);
  const foreignReady = (await confirm("charity_b", foreign.mediaId)).json.data
    .item;
  assert.notEqual(ready.id, foreignReady.id);
  assert.equal(ready.contentHash, foreignReady.contentHash);
  assert.deepEqual(
    (await list("charity", a)).items.map((item) => item.id),
    [ready.id],
  );
  assert.deepEqual(
    (await list("charity_b", b)).items.map((item) => item.id),
    [foreignReady.id],
  );
  const missing = `${root}/01K00000000000000000000999`;
  assert.deepEqual(
    (await call("charity", `${root}/${foreignReady.id}`, 404)).json,
    (await call("charity", missing, 404)).json,
  );
  await call("charity", foreignReady.url, 404);
  await confirm("charity", foreignReady.id, 404);
  await call("charity", foreign.uploadUrl, 404, "PUT", image);
  assert.deepEqual(await get("charity_b", foreignReady.id), foreignReady);
  await call("charity", own.uploadUrl, 409, "PUT", image);
  await call("charity", ready.url, 403, "GET", undefined, {
    headers: { Origin: "https://foreign.invalid" },
  });
  await call("charity", own.uploadUrl, 403, "PUT", image, {
    headers: { "X-EmDash-Request": null },
  });
  await call("charity", `${root}/upload-url?campaign=${a}`, 400, "POST", {
    filename: "../bad.svg",
    contentType: "image/svg+xml",
    size: 10,
  });
  const invalid = await reserve(
    "charity",
    a,
    "synthetic-invalid.png",
    Buffer.from("<svg>not a raster</svg>"),
  );
  const invalidBefore = await get("charity", invalid.mediaId);
  await call(
    "charity",
    invalid.uploadUrl,
    400,
    "PUT",
    Buffer.from("<svg>not a raster</svg>"),
  );
  assert.deepEqual(await get("charity", invalid.mediaId), invalidBefore);
  const slow = await reserve("charity", a, "synthetic-slow.png");
  const start = Date.now();
  console.log(
    "campaign-media-http: starting actual slow-body and chunked-size checks",
  );
  await call("charity", slow.uploadUrl, 408, "PUT", image, { slow: true });
  assert.ok(Date.now() - start >= 4500 && Date.now() - start < 15_000);
  await call(
    "charity",
    slow.uploadUrl,
    413,
    "PUT",
    Buffer.alloc(8 * 1024 * 1024 + 1),
    { headers: { "Content-Length": null, "Transfer-Encoding": "chunked" } },
  );
  assert.equal((await get("charity", slow.mediaId)).contentHash, null);
  const failure = await reserve("charity", a, "synthetic-confirm-failure.png");
  await stage("charity", failure);
  const tamper = await reserve("charity", a, "synthetic-tamper.png");
  await stage("charity", tamper);
  const pagesRoot = "/_emdash/api/content/campaign_pages";
  const page = (await call("charity", pagesRoot)).json.data.items.find(
    (item) => item.data.action_id === a,
  );
  assert.ok(page);
  const pagePath = `${pagesRoot}/${page.id}`;
  const readPage = async () => (await call("charity", pagePath)).json.data;
  const history = async () =>
    (await call("charity", `${pagePath}/revisions`)).json.data;
  const original = await readPage();
  const originalHistory = await history();
  const ownReference = {
    id: ready.id,
    provider: "local",
    alt: "Synthetic hero",
    width: ready.width,
    height: ready.height,
    filename: ready.filename,
    mimeType: ready.mimeType,
    meta: { storageKey: ready.storageKey },
  };
  for (const changes of [
    { hero_image: { id: foreignReady.id } },
    { social_image: { id: foreignReady.id } },
    {
      partners: [
        { name: "Denied foreign logo", logo: { id: foreignReady.id } },
      ],
    },
    { hero_image: { id: failure.mediaId } },
    {
      hero_image: {
        ...ownReference,
        meta: { storageKey: foreignReady.storageKey },
      },
    },
    { hero_image: { ...ownReference, width: 99 } },
    { hero_image: { ...ownReference, provider: "external" } },
    { hero_image: { ...ownReference, src: "https://example.invalid/tracker" } },
    { hero_image: { ...ownReference, darkVariant: { id: foreignReady.id } } },
  ]) {
    await call("charity", pagePath, 403, "PUT", {
      _rev: original._rev,
      data: { ...original.item.data, ...changes },
    });
    assert.deepEqual(await readPage(), original);
    assert.deepEqual(await history(), originalHistory);
  }
  const edited = (
    await call("charity", pagePath, 200, "PUT", {
      _rev: original._rev,
      data: {
        ...original.item.data,
        hero_image: ownReference,
        social_image: { id: ready.id },
        partners: [{ name: "Own logo", logo: ownReference }],
      },
    })
  ).json.data;
  assert.equal(edited.item.data.hero_image.id, ready.id);
  assert.equal((await readPage()).item.data.partners[0].logo.id, ready.id);
  const savedRevision = (await history()).items.find(
    (revision) => revision.id === edited.item.draftRevisionId,
  );
  assert.equal(savedRevision.data.hero_image.id, ready.id);
  await call("charity", `${pagePath}/publish`, 200, "POST", {});
  const published = await readPage();
  assert.equal(published.item.status, "published");
  const cleared = (
    await call("charity", pagePath, 200, "PUT", {
      _rev: published._rev,
      data: {
        ...published.item.data,
        hero_image: null,
        social_image: null,
        partners: [],
      },
    })
  ).json.data;
  assert.equal(cleared.item.data.hero_image, null);
  const restored = (
    await call(
      "charity",
      `/_emdash/api/revisions/${savedRevision.id}/restore`,
      200,
      "POST",
      {},
    )
  ).json.data;
  assert.equal(restored.item.data.hero_image.id, ready.id);
  const compared = (await call("charity", `${pagePath}/compare`)).json.data;
  assert.equal(compared.draft.hero_image.id, ready.id);
  await call("charity_b", pagePath, 404);
  console.log(
    "campaign-media-references: real HTTPS native fields, nested logo, private revisions, publish/clear/restore/compare passed; foreign/pending/provider/path/dimension injection left content and history unchanged",
  );
  for (const [path, method] of [
    [root, "POST"],
    [`${root}/${ready.id}`, "PUT"],
    [`${root}/${ready.id}`, "DELETE"],
    [`${root}/${ready.id}/usage`, "GET"],
    [`${root}/folders`, "GET"],
    ["/_emdash/image", "GET"],
  ])
    await call("charity", path, 503, method, method === "GET" ? undefined : {});
  await writeFile(
    statePath,
    JSON.stringify({ ready, foreign: foreignReady, failure, tamper }),
  );
  console.log(
    "campaign-media-http: actual TLS/Core/Node/EmDash/RustFS native reserve/PUT/confirm/private-file protocol passed for two Charity actors; scoped IDs/hash/listing, server-derived dimensions, malformed/slow/oversize denial, CSRF, anonymous/foreign privacy and closed alternate routes proved. Browser field UX and public delivery remain pending.",
  );
}
