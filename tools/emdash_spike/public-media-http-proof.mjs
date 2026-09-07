import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import { request } from "node:https";
import { createHash } from "node:crypto";
import sharp from "sharp";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const a = "20000000-0000-4000-8000-000000000001";
const b = "20000000-0000-4000-8000-000000000003";
const pagePath = "/campaigns/krapfentaxi-2026/";
const url = (id) => `${pagePath}media/${id}`;
async function call(
  path,
  status = 200,
  { admin = false, method = "GET", body, headers = {} } = {},
) {
  const bytes =
    body === undefined
      ? undefined
      : Buffer.isBuffer(body)
        ? body
        : Buffer.from(JSON.stringify(body));
  const result = await new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          ...(admin
            ? {
                Cookie: `__Host-leonaid_session=${tokens.system}`,
                Origin: "https://proxy:8443",
                "X-EmDash-Request": "1",
              }
            : {}),
          ...(bytes
            ? {
                "Content-Type": Buffer.isBuffer(body)
                  ? "image/png"
                  : "application/json",
                "Content-Length": bytes.length,
              }
            : {}),
          ...headers,
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("error", reject);
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            bytes: Buffer.concat(chunks),
          }),
        );
      },
    );
    req.setTimeout(20000, () =>
      req.destroy(new Error("public_media_deadline")),
    );
    req.on("error", reject);
    req.end(bytes);
  });
  assert.equal(result.status, status, `public media ${method} status`);
  assert.equal(result.headers["cache-control"], "no-store");
  assert.equal(result.headers["set-cookie"], undefined);
  return {
    ...result,
    json: result.headers["content-type"]?.includes("application/json")
      ? JSON.parse(result.bytes.toString())
      : null,
  };
}
const statePath = "/proof/public-media.json";
if (
  process.argv.includes("--inactive") ||
  process.argv.includes("--unavailable") ||
  process.argv.includes("--ready")
) {
  const state = JSON.parse(await readFile(statePath, "utf8"));
  const expected = process.argv.includes("--ready")
    ? 200
    : process.argv.includes("--inactive")
      ? 404
      : 503;
  const denied = await call(state.url, expected);
  if (expected === 200)
    assert.equal(
      createHash("sha256").update(denied.bytes).digest("hex"),
      state.hash,
    );
  else assert.notEqual(denied.headers["content-type"], "image/png");
} else {
  const png = await sharp({
    create: { width: 640, height: 360, channels: 3, background: "#00338d" },
  })
    .png()
    .toBuffer();
  const upload = async (action, complete = true) => {
    const reserved = (
      await call(`/_emdash/api/media/upload-url?campaign=${action}`, 200, {
        admin: true,
        method: "POST",
        body: {
          filename: "synthetic-public.png",
          contentType: "image/png",
          size: png.length,
        },
      })
    ).json.data;
    if (!complete) return { id: reserved.mediaId };
    await call(reserved.uploadUrl, 200, {
      admin: true,
      method: "PUT",
      body: png,
    });
    return (
      await call(`/_emdash/api/media/${reserved.mediaId}/confirm`, 200, {
        admin: true,
        method: "POST",
        body: {},
      })
    ).json.data.item;
  };
  const first = await upload(a);
  const second = await upload(a);
  const foreign = await upload(b);
  const pending = await upload(a, false);
  assert.notEqual(first.id, second.id);
  assert.notEqual(first.id, foreign.id);
  for (const item of [first, second, foreign, pending])
    await call(url(item.id), 404);
  const root = "/_emdash/api/content/campaign_pages";
  const listing = (await call(root, 200, { admin: true })).json;
  const entry = listing.data.items.find((item) => item.data.action_id === a);
  const editor = `${root}/${entry.id}`;
  const reference = (item) => ({
    id: item.id,
    alt: "Synthetisches blaues Kampagnenbild",
    width: item.width,
    height: item.height,
  });
  const update = async (item) => {
    const current = (await call(editor, 200, { admin: true })).json;
    await call(editor, 200, {
      admin: true,
      method: "PUT",
      body: {
        _rev: current.data._rev,
        data: {
          title: current.data.item.data.title,
          hero_image: reference(item),
          social_image: reference(item),
          partners: [{ name: "Synthetic partner", logo: reference(item) }],
        },
      },
    });
  };
  await update(first);
  await call(url(first.id), 404);
  await call(`${editor}/publish`, 200, { admin: true, method: "POST" });
  const live = await call(url(first.id));
  assert.equal(live.headers["content-type"], "image/png");
  assert.equal(live.headers["x-content-type-options"], "nosniff");
  // Caddy adds the common site policy. Both independently enforced policies
  // survive the proxy; the image-specific policy must remain a complete entry.
  assert.ok(
    live.headers["content-security-policy"]
      .split(",")
      .map((policy) => policy.trim())
      .includes("sandbox; default-src 'none'"),
  );
  assert.equal(
    createHash("sha256").update(live.bytes).digest("hex"),
    first.contentHash,
  );
  const head = await call(url(first.id), 200, { method: "HEAD" });
  assert.equal(head.bytes.length, 0);
  assert.equal(head.headers["content-length"], String(live.bytes.length));
  assert.equal(
    (
      await call(url(first.id), 200, {
        headers: { "If-None-Match": '"arbitrary"', Range: "bytes=0-9" },
      })
    ).bytes.length,
    live.bytes.length,
  );
  await call(url(first.id), 405, { method: "POST" });
  await call(url(first.id) + "?_preview=synthetic", 403);
  await update(second);
  await call(url(second.id), 404);
  assert.deepEqual((await call(url(first.id))).bytes, live.bytes);
  await call(`${editor}/publish`, 200, { admin: true, method: "POST" });
  await call(url(first.id), 404);
  await call(url(second.id));
  await call(url(foreign.id), 404);
  await call(`/campaigns/krapfentaxi-nord-2026/media/${second.id}`, 404);
  await call(`${editor}/unpublish`, 200, { admin: true, method: "POST" });
  await call(url(second.id), 404);
  await call(`${editor}/publish`, 200, { admin: true, method: "POST" });
  await call(url(second.id));
  const html = (await call(pagePath)).bytes.toString();
  assert.ok(html.includes(url(second.id)));
  assert.ok(!html.includes(url(first.id)));
  assert.ok(!html.includes(first.storageKey));
  assert.ok(!html.includes("/_emdash/api/media/file/"));
  await writeFile(
    statePath,
    JSON.stringify({
      url: url(second.id),
      id: second.id,
      width: second.width,
      height: second.height,
      hash: second.contentHash,
    }),
  );
  await writeFile("/proof/public-media.png", png);
}
console.log(
  "public-media-http: real private RustFS image/publication checks passed for selected state; concurrent withdrawal races, fresh backup restore and complete resource budgets remain pending",
);
