import { createHash } from "node:crypto";

// Private operator evidence only; never print or commit returned row values.
export async function importRecoveryState(database, storage) {
  const tables = {};
  for (const [table, key] of [
    ["ec_campaign_pages", "id"],
    ["revisions", "id"],
    ["media", "id"],
    ["leonaid_campaign_media", "media_id"],
    ["_emdash_media_upload_attempts", "storage_key"],
    ["leonaid_krapfentaxi_import", "action_id"],
  ]) {
    tables[table] = await database
      .selectFrom(table)
      .selectAll()
      .orderBy(key)
      .execute();
  }
  const objects = [];
  for (const { key } of (await storage.list()).files.sort((a, b) =>
    a.key.localeCompare(b.key),
  )) {
    const stored = await storage.download(key);
    objects.push({
      key,
      hash: createHash("sha256")
        .update(Buffer.from(await new Response(stored.body).arrayBuffer()))
        .digest("hex"),
    });
  }
  return JSON.parse(JSON.stringify({ tables, objects }));
}
