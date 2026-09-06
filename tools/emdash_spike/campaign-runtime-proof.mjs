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
  } = {},
) {
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
    req.end();
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
} else if (revoked) {
  await call(root, 401);
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
