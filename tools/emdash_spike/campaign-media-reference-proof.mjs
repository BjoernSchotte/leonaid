import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";
import pg from "pg";
import sharp from "sharp";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const media = JSON.parse(
  await readFile("/proof/media-http-state.json", "utf8"),
);
const ca = await readFile("/proof/root.crt");
const pool = new pg.Pool({
  max: 2,
  connectionTimeoutMillis: 2000,
  query_timeout: 3000,
});
const root = "/_emdash/api/content/campaign_pages";
const action = "20000000-0000-4000-8000-000000000001";
const newAction = "20000000-0000-4000-8000-000000000041";
async function call(actor, path, status = 200, method = "GET", body) {
  const bytes =
    body === undefined
      ? undefined
      : Buffer.isBuffer(body)
        ? body
        : Buffer.from(JSON.stringify(body));
  const response = await new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          Cookie: `__Host-leonaid_session=${tokens[actor]}`,
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
        },
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("error", reject);
        res.on("end", () =>
          resolve({
            status: res.statusCode,
            headers: res.headers,
            text: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(15000, () =>
      req.destroy(new Error("reference_proof_timeout")),
    );
    req.on("error", reject);
    req.end(bytes);
  });
  assert.equal(response.status, status, `${actor} ${method} ${path}`);
  assert.equal(response.headers["cache-control"], "no-store");
  assert.equal(response.headers["set-cookie"], undefined);
  if (status === 403) {
    assert.ok(!response.text.includes(media.foreign.id));
    assert.ok(!response.text.includes(media.foreign.storageKey));
  }
  return JSON.parse(response.text).data;
}

try {
  // Even two actions belonging to the SAME Charity actor cannot share a media
  // binding. Rejected creation must not consume the new campaign's unique slot.
  const initial = await call("charity", root);
  const create = {
    data: {
      action_id: newAction,
      title: "Synthetic image creation",
      hero_image: { id: media.ready.id },
    },
  };
  await call("charity", root, 403, "POST", create);
  await call("system", root, 403, "POST", create);
  assert.deepEqual(await call("charity", root), initial);
  const image = await sharp({
    create: { width: 5, height: 3, channels: 3, background: "blue" },
  })
    .png()
    .toBuffer();
  const reserved = await call(
    "charity",
    `/_emdash/api/media/upload-url?campaign=${newAction}`,
    200,
    "POST",
    {
      filename: "synthetic-created-reference.png",
      contentType: "image/png",
      size: image.length,
    },
  );
  await call("charity", reserved.uploadUrl, 200, "PUT", image);
  await call(
    "charity",
    `/_emdash/api/media/${reserved.mediaId}/confirm`,
    200,
    "POST",
    {},
  );
  create.data.hero_image = { id: reserved.mediaId };
  const created = await call("charity", root, 201, "POST", create);
  assert.equal(created.item.status, "draft");
  assert.equal(created.item.data.hero_image.id, reserved.mediaId);
  assert.equal(
    (await call("charity", `${root}/${created.item.id}`)).item.data.hero_image
      .id,
    reserved.mediaId,
  );
  await call("charity_b", `${root}/${created.item.id}`, 404);

  const page = initial.items.find((item) => item.data.action_id === action);
  const pagePath = `${root}/${page.id}`;
  const original = await call("charity", pagePath);
  const revisionId = original.item.draftRevisionId;
  assert.ok(revisionId);
  const snapshot = async () => ({
    entries: (
      await pool.query("SELECT * FROM public.ec_campaign_pages ORDER BY id")
    ).rows,
    revisions: (await pool.query("SELECT * FROM public.revisions ORDER BY id"))
      .rows,
    media: (await pool.query("SELECT * FROM public.media ORDER BY id")).rows,
  });
  const before = await snapshot();
  const stored = before.revisions.find(
    (revision) => revision.id === revisionId,
  );
  assert.ok(stored);
  const data =
    typeof stored.data === "string" ? JSON.parse(stored.data) : stored.data;
  const poisoned = {
    ...data,
    hero_image: {
      id: media.foreign.id,
      provider: "local",
      meta: { storageKey: media.foreign.storageKey },
    },
  };
  // Actual stored-revision corruption, not an HTTP stub. Keep the immutable
  // parent/action intact so media-reference checks are the protection under test.
  await pool.query("UPDATE public.revisions SET data=$1 WHERE id=$2", [
    JSON.stringify(poisoned),
    revisionId,
  ]);
  try {
    const corrupt = await snapshot();
    for (const actor of ["charity", "system"]) {
      for (const [path, method] of [
        [pagePath, "GET"],
        [`${pagePath}/revisions`, "GET"],
        [`/_emdash/api/revisions/${revisionId}`, "GET"],
        [`${pagePath}/compare`, "GET"],
        [`/_emdash/api/revisions/${revisionId}/restore`, "POST"],
        [`${pagePath}/publish`, "POST"],
      ])
        await call(
          actor,
          path,
          403,
          method,
          method === "POST" ? {} : undefined,
        );
    }
    assert.deepEqual(await snapshot(), corrupt);
    assert.equal(
      (await call("charity_b", `/_emdash/api/media/${media.foreign.id}`)).item
        .id,
      media.foreign.id,
    );
  } finally {
    await pool.query("UPDATE public.revisions SET data=$1 WHERE id=$2", [
      stored.data,
      revisionId,
    ]);
  }
  assert.deepEqual(await snapshot(), before);
  assert.deepEqual(await call("charity", pagePath), original);
  console.log(
    "campaign-media-reference-storage: OK: same-actor cross-action and System Admin foreign-image creation denied without consuming binding; actual native image creation succeeded; real poisoned revision cannot be read, compared, restored or published by either admin role; SQL/media unchanged and explicit fixture restore recovered access",
  );
} finally {
  await pool.end();
}
