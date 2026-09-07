import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { ContentRepository } from "emdash";
import { createStorage } from "emdash/storage/s3";
import { krapfentaxiImportContext } from "./krapfentaxi-import-context.mjs";
import { importKrapfentaxi } from "./krapfentaxi-import.mjs";
import { importRecoveryState } from "./import-recovery-state.mjs";

const expected = JSON.parse(
  await readFile("/proof/import-recovery.json", "utf8"),
);
const sessions = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const context = krapfentaxiImportContext(sessions.system, "krapfentaxi-2026");
const storage = createStorage({});
const snapshot = () => importRecoveryState(context.database, storage);
const unchanged = async (state) =>
  assert.ok(
    JSON.stringify(await snapshot()) === JSON.stringify(state),
    "private importer recovery state must remain unchanged",
  );
try {
  // No schema installation or reseeding: inspect the actual restored tables
  // and original object bytes before allowing the importer to change anything.
  await unchanged(expected);
  assert.equal(expected.tables.media.length, 1);
  assert.equal(expected.objects.length, 1);
  assert.equal(expected.tables.ec_campaign_pages.length, 0);
  assert.equal(expected.tables.leonaid_krapfentaxi_import[0].content_id, null);
  const firstId = expected.tables.media[0].id;
  const preview = await importKrapfentaxi({ ...context, mode: "dry-run" });
  assert.equal(preview.state, "resume");
  await unchanged(expected);
  const result = await importKrapfentaxi({ ...context, mode: "apply" });
  const resumed = await snapshot();
  assert.equal(resumed.tables.ec_campaign_pages.length, 1);
  assert.equal(resumed.tables.media.length, 3);
  assert.equal(resumed.objects.length, 3);
  assert.equal(resumed.tables.leonaid_krapfentaxi_import.length, 1);
  assert.equal(
    resumed.tables.leonaid_krapfentaxi_import[0].content_id,
    result.contentId,
  );
  assert.ok(
    resumed.objects.some(
      (object) =>
        object.key === expected.objects[0].key &&
        object.hash === expected.objects[0].hash,
    ),
  );
  const repository = new ContentRepository(context.database);
  const item = await repository.findById("campaign_pages", result.contentId);
  assert.equal(item.status, "draft");
  assert.equal(item.data.hero_image.id, firstId);
  assert.equal(
    item.data.action_id,
    expected.tables.leonaid_krapfentaxi_import[0].action_id,
  );
  assert.equal(
    (await importKrapfentaxi({ ...context, mode: "apply" })).state,
    "preserved",
  );
  await unchanged(resumed);
  await repository.updateDraftAware("campaign_pages", item.id, {
    data: { story_title: "Preserve editorial changes after journal recovery" },
  });
  const edited = await snapshot();
  assert.equal(
    (await importKrapfentaxi({ ...context, mode: "apply" })).state,
    "preserved",
  );
  await unchanged(edited);
  console.log(
    "import-recovery: restored incomplete journal, media rows and original bytes match; read-only dry run resumes; actual apply retains original hero ID/bytes, completes exactly one draft/three media, and repeated apply preserves later edits",
  );
} finally {
  await context.database.destroy();
}
