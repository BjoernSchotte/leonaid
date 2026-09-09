import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { campaignStorage } from "../../apps/campaign-site/src/auth/campaign-media-io.mjs";

// Operator-only fault injection into this invocation's synthetic object.
// The anonymous HTTP probe remains on Edge and has no database/S3 credentials.
const mode = process.argv[2];
assert.ok(["bytes", "mime", "missing", "restore"].includes(mode));
const state = JSON.parse(await readFile("/proof/public-media.json", "utf8"));
const original = await readFile("/proof/public-media.png");
assert.match(state.id, /^[0-9A-HJKMNP-TV-Z]{26}$/);
assert.equal(createHash("sha256").update(original).digest("hex"), state.hash);
const database = new Kysely({
  dialect: createDialect({
    host: "core-postgres",
    database: "emdash",
    user: "emdash",
    password: process.env.CMS_POSTGRES_PASSWORD,
  }),
});
try {
  const snapshot = async () => ({
    media: await database
      .selectFrom("media")
      .selectAll()
      .orderBy("id")
      .execute(),
    bindings: await database
      .selectFrom("leonaid_campaign_media")
      .selectAll()
      .orderBy("media_id")
      .execute(),
    content: await database
      .selectFrom("ec_campaign_pages")
      .selectAll()
      .orderBy("id")
      .execute(),
    revisions: await database
      .selectFrom("revisions")
      .selectAll()
      .orderBy("id")
      .execute(),
  });
  const before = await snapshot();
  const row = before.media.find((item) => item.id === state.id);
  assert.ok(row);
  assert.equal(row.filename, "synthetic-public.png");
  assert.equal(row.status, "ready");
  assert.equal(row.content_hash, state.hash);
  assert.equal(
    before.bindings.find((item) => item.media_id === state.id)?.action_id,
    "20000000-0000-4000-8000-000000000001",
  );
  assert.match(
    row.storage_key,
    /^campaigns\/20000000-0000-4000-8000-000000000001\/[0-9a-f-]{36}\.png$/,
  );
  const storage = campaignStorage();
  if (mode === "missing") await storage.delete(row.storage_key);
  else {
    const body = Buffer.from(original);
    // Preserve length and MIME to require hash verification, not a size check.
    if (mode === "bytes") body[body.length - 1] ^= 1;
    await storage.upload({
      key: row.storage_key,
      body,
      contentType: mode === "mime" ? "text/html" : "image/png",
    });
    const actual = await storage.download(row.storage_key);
    assert.deepEqual(actual.bytes, body);
    assert.equal(
      actual.contentType,
      mode === "mime" ? "text/html" : "image/png",
    );
  }
  assert.deepEqual(await snapshot(), before);
  console.log(
    `public-media-storage: ${mode}; synthetic object changed, SQL/content/revisions unchanged`,
  );
} finally {
  await database.destroy();
}
