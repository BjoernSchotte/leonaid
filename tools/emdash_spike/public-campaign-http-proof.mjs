import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const path = "/campaigns/krapfentaxi-2026/";
async function call(
  pathname,
  status,
  { admin = false, method = "GET", body, extra = {} } = {},
) {
  const encoded = body === undefined ? undefined : JSON.stringify(body);
  const response = await new Promise((resolve, reject) => {
    const req = request(
      new URL(pathname, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          ...extra,
          ...(admin
            ? {
                Cookie: `__Host-leonaid_session=${tokens.system}`,
                Origin: "https://proxy:8443",
                "X-EmDash-Request": "1",
              }
            : {}),
          ...(encoded
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(encoded),
              }
            : {}),
        },
      },
      (result) => {
        const chunks = [];
        result.on("data", (chunk) => chunks.push(chunk));
        result.on("end", () =>
          resolve({
            status: result.statusCode,
            headers: result.headers,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(10000, () =>
      req.destroy(new Error("public campaign deadline")),
    );
    req.on("error", reject);
    req.end(encoded);
  });
  assert.equal(
    response.status,
    status,
    `unexpected public campaign HTTP status for ${method}; page state=${response.headers["x-leonaid-campaign-state"] ?? "absent"}`,
  );
  assert.equal(response.headers["cache-control"], "no-store");
  assert.equal(response.headers["set-cookie"], undefined);
  return response;
}

if (
  process.argv.includes("--inactive") ||
  process.argv.includes("--unavailable")
) {
  const unavailable = process.argv.includes("--unavailable");
  const response = await call(path, unavailable ? 503 : 404);
  assert.equal(
    response.headers["x-leonaid-campaign-state"],
    unavailable ? "unavailable" : "inactive",
  );
  assert.ok(!response.body.includes("PUBLIC_STORY_PROOF"));
  assert.ok(!response.body.includes("PRIVATE_DRAFT_PROOF"));
  assert.ok(!response.body.includes('href="/krapfentaxi#bestellen"'));
  assert.match(response.body, /noindex,follow/);
} else {
  const root = "/_emdash/api/content/campaign_pages";
  const listing = JSON.parse((await call(root, 200, { admin: true })).body);
  const entry = listing.data.items.find(
    (item) => item.data.action_id === "20000000-0000-4000-8000-000000000001",
  );
  assert.ok(entry);
  const editor = `${root}/${entry.id}`;
  const item = JSON.parse((await call(editor, 200, { admin: true })).body);
  await call(editor, 200, {
    admin: true,
    method: "PUT",
    body: {
      _rev: item.data._rev,
      data: {
        title: "PUBLIC_STORY_PROOF",
        hero_title: "Gemeinsam helfen vor Ort",
        hero_summary:
          "Eine synthetische Charity-Aktion für den öffentlichen Live-Nachweis.",
        body: [
          {
            _type: "block",
            _key: "p",
            style: "normal",
            children: [
              {
                _type: "span",
                _key: "s",
                text: "<script>UNTRUSTED_TEXT_PROOF</script> & gemeinsam helfen",
                marks: ["strong"],
              },
            ],
          },
        ],
        faq: [
          {
            question: "Wie kann ich helfen?",
            answer: "Über die bestehende Bestellung.",
          },
        ],
        partners: [
          {
            name: "Synthetic partner",
            website: "https://example.org/",
            description: "Gemeinsam möglich gemacht.",
          },
        ],
        seo_description: "Synthetic campaign public proof",
      },
    },
  });
  await call(`${editor}/publish`, 200, { admin: true, method: "POST" });
  const live = await call(path, 200);
  assert.match(live.body, /PUBLIC_STORY_PROOF/);
  assert.match(live.body, /&lt;script&gt;UNTRUSTED_TEXT_PROOF&lt;\/script&gt;/);
  assert.ok(!live.body.includes("<script>UNTRUSTED_TEXT_PROOF"));
  assert.match(live.body, /href="\/krapfentaxi#bestellen"/);
  assert.match(
    live.body,
    /rel="canonical" href="https:\/\/proxy:8443\/campaigns\/krapfentaxi-2026\/"/,
  );
  assert.match(live.body, /lang="de"/);
  assert.ok(!live.body.includes("accessToken"));
  assert.equal((await call(path, 200, { method: "HEAD" })).body, "");
  await call(`${path}?_preview=synthetic`, 403);
  await call(path, 403, { extra: { Cookie: "emdash-edit-mode=true" } });
  const draft = JSON.parse((await call(editor, 200, { admin: true })).body);
  await call(editor, 200, {
    admin: true,
    method: "PUT",
    body: { _rev: draft.data._rev, data: { title: "PRIVATE_DRAFT_PROOF" } },
  });
  assert.equal((await call(path, 200)).body, live.body);
  assert.equal(
    (await call(`${path}?preview=true&draft=true`, 200)).body,
    live.body,
  );
  assert.equal((await call(path, 200, { admin: true })).body, live.body);
  await call(`${editor}/unpublish`, 200, { admin: true, method: "POST" });
  const absent = await call(path, 404);
  assert.ok(!absent.body.includes("PUBLIC_STORY_PROOF"));
  await call(`${editor}/discard-draft`, 200, { admin: true, method: "POST" });
  await call(`${editor}/publish`, 200, { admin: true, method: "POST" });
  assert.match((await call(path, 200)).body, /PUBLIC_STORY_PROOF/);
  await call("/campaigns/missing-synthetic-campaign/", 404);
  await call("/campaigns/krapfentaxi-2025/", 404);
  await call(path, 405, { method: "POST" });
  const canonical = await call(path.slice(0, -1), 308);
  assert.equal(canonical.headers.location, path);
}
console.log(
  "public-campaign-http: actual TLS/anonymous no-store HTML and selected publication state passed; full media, embedded orders, migration and browser cache matrix remain pending",
);
