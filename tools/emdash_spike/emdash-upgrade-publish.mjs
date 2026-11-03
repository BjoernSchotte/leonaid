import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";

// Legacy phase of the EmDash upgrade proof: publish the imported Krapfentaxi
// draft through the real CMS HTTP API of the legacy release, as the System
// Admin, so the upgrade starts from published content with a live revision.
// The importer logs its operator session out; use fresh sessions.
const tokens = JSON.parse(
  await readFile("/proof/emdash-upgrade-sessions.json", "utf8"),
);
const ca = await readFile("/proof/root.crt");
const origin = "https://proxy:8443";
const root = "/_emdash/api/content/campaign_pages";

function call(path, method = "GET") {
  return new Promise((resolve, reject) => {
    const req = request(
      new URL(path, origin),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          Cookie: `__Host-leonaid_session=${tokens.system}`,
          Origin: origin,
          "X-EmDash-Request": "1",
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () => {
          const body = Buffer.concat(chunks).toString();
          resolve({
            status: response.statusCode,
            json: response.headers["content-type"]?.includes("application/json")
              ? JSON.parse(body)
              : null,
          });
        });
      },
    );
    req.setTimeout(10_000, () => req.destroy(new Error("CMS HTTP deadline")));
    req.on("error", reject);
    req.end();
  });
}

const list = await call(root);
assert.equal(list.status, 200);
const items = list.json.data.items;
assert.equal(items.length, 1, "exactly the imported campaign page");
const [entry] = items;
assert.ok(entry.draftRevisionId || entry.status !== "published");
const published = await call(`${root}/${entry.id}/publish`, "POST");
assert.equal(published.status, 200);
const after = await call(`${root}/${entry.id}`);
assert.equal(after.status, 200);
assert.equal(after.json.data.item.status, "published");
assert.equal(after.json.data.item.draftRevisionId, null);
assert.ok(after.json.data.item.liveRevisionId);
console.log(
  "emdash-upgrade: legacy release published the imported campaign through its HTTP API",
);
