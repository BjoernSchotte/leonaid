import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const revoked = process.argv.includes("--revoked");
const guardUnavailable = process.argv.includes("--guard-unavailable");
async function call(
  path,
  status,
  {
    token = tokens.system,
    method = "GET",
    origin = "https://proxy:8443",
    extra = {},
    body,
    marker = true,
  } = {},
) {
  const encoded = body === undefined ? undefined : JSON.stringify(body);
  const response = await new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          ...(token ? { Cookie: `__Host-leonaid_session=${token}` } : {}),
          Origin: origin,
          ...(marker ? { "X-EmDash-Request": "1" } : {}),
          ...(encoded
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(encoded),
              }
            : {}),
          ...extra,
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(6000, () => req.destroy(new Error("CMS HTTP deadline")));
    req.on("error", reject);
    req.end(encoded);
  });
  assert.equal(response.status, status, `${method} ${path}: unexpected status`);
  assert.equal(response.headers["cache-control"], "no-store");
  assert.equal(response.headers["set-cookie"], undefined);
  return response.headers["content-type"]?.includes("application/json")
    ? JSON.parse(response.body)
    : null;
}
const root = "/_emdash/api/content/campaign_pages";
if (guardUnavailable) {
  await call(root, 503);
  await call(`${root}/00000000000000000000000000`, 503, {
    method: "PUT",
    body: { _rev: "synthetic", data: { title: "denied" } },
  });
} else if (revoked) {
  await call(root, 401);
  await call(`${root}/00000000000000000000000000`, 401, {
    method: "PUT",
    body: { _rev: "synthetic", data: { title: "denied" } },
  });
} else {
  const result = await call(root, 200);
  assert.equal(result.data.total, 4);
  assert.equal(result.data.items.length, 4);
  for (const entry of result.data.items) {
    const path = `${root}/${entry.id}`;
    const item = await call(path, 200);
    assert.equal(item.data.item.id, entry.id);
    const revisions = await call(`${path}/revisions`, 200);
    assert.ok(revisions.data.total > 0);
    const draft = revisions.data.items.find(
      (revision) => revision.id === item.data.item.draftRevisionId,
    );
    assert.ok(draft);
    assert.equal(item.data.item.data.title, draft.data.title);
    assert.equal(item.data.item.liveData.title, entry.data.title);
    assert.notEqual(item.data.item.data.title, item.data.item.liveData.title);
    for (const revision of revisions.data.items) {
      const detail = await call(`/_emdash/api/revisions/${revision.id}`, 200);
      assert.equal(detail.data.item.entryId, entry.id);
      await call(`/_emdash/api/revisions/${revision.id}`, 401, { token: null });
      await call(`/_emdash/api/revisions/${revision.id}`, 403, {
        token: tokens.charity,
      });
    }
    await call(path, 401, { token: null });
    await call(path, 403, { token: tokens.charity });
  }
  const entry = result.data.items[0];
  const path = `${root}/${entry.id}`;
  const before = await call(path, 200);
  const revisionsBefore = await call(`${path}/revisions`, 200);
  const body = {
    _rev: before.data._rev,
    data: {
      title: `${entry.data.title} HTTP edit`,
      action_id: entry.data.action_id,
    },
  };
  for (const options of [
    { token: null },
    { token: tokens.charity },
    { origin: "https://attacker.invalid" },
    { marker: false },
  ])
    await call(path, options.token === null ? 401 : 403, {
      method: "PUT",
      body,
      ...options,
    });
  await call(path, 403, {
    method: "PUT",
    body: {
      ...body,
      data: { ...body.data, action_id: "20000000-0000-4000-8000-000000000099" },
    },
  });
  await call(path, 400, {
    method: "PUT",
    body: { ...body, status: "published" },
  });
  await call(path, 403, {
    method: "PUT",
    body: { ...body, status: "draft" },
  });
  await call(path, 403, { method: "PUT", body: { data: body.data } });
  assert.equal(
    (await call(`${path}/revisions`, 200)).data.total,
    revisionsBefore.data.total,
  );
  const edited = await call(path, 200, { method: "PUT", body });
  assert.equal(edited.data.item.data.title, body.data.title);
  const after = await call(path, 200);
  assert.equal(after.data.item.data.title, body.data.title);
  assert.equal(after.data.item.liveData.title, entry.data.title);
  assert.equal(after.data.item.status, "published");
  assert.equal(
    (await call(`${path}/revisions`, 200)).data.total,
    revisionsBefore.data.total + 1,
  );
  await call(path, 409, {
    method: "PUT",
    body: { ...body, data: { title: "stale revision must not write" } },
  });
  assert.equal(
    (await call(`${path}/revisions`, 200)).data.total,
    revisionsBefore.data.total + 1,
  );
  assert.equal((await call(path, 200)).data.item.data.title, body.data.title);
  const missing = await call(`${root}/00000000000000000000000000`, 404);
  // Upstream includes the ID in its message. This static envelope verifies
  // that the request-local wrapper actually ran, not just the upstream reader.
  assert.equal(missing.error.message, "Content not found");
  await call("/_emdash/api/revisions/00000000000000000000000000", 404);
  await call(root, 401, { token: null });
  await call(root, 403, { token: tokens.charity });
  await call(root, 403, { origin: "https://attacker.invalid" });
  await call(root, 503, {
    extra: { Authorization: "Bearer synthetic-denied" },
  });
  for (const method of ["POST", "PUT", "DELETE", "HEAD", "OPTIONS"]) {
    await call(root, 503, { method });
  }
}
console.log(
  `campaign-runtime: ${guardUnavailable ? "disabled binding guard fails closed" : revoked ? "revocation" : "real Core session, TLS, list/item/revision routes and denied actors"} passed`,
);
