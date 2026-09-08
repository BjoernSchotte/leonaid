import assert from "node:assert/strict";
import { isDeepStrictEqual } from "node:util";
import { readFile, mkdtemp, writeFile, chmod, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { request } from "node:https";
import { sql } from "kysely";
import { ContentRepository, MediaRepository, SchemaRegistry } from "emdash";
import { createStorage } from "emdash/storage/s3";
import { installCampaignSchema } from "../../apps/campaign-site/src/install-campaign-schema.mjs";
import { installCampaignBindings } from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import { installCampaignMedia } from "../../apps/campaign-site/src/auth/campaign-media.mjs";
import { krapfentaxiImportContext } from "./krapfentaxi-import-context.mjs";
import { importKrapfentaxi } from "./krapfentaxi-import.mjs";
import { importRecoveryState } from "./import-recovery-state.mjs";

const sessions = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const context = krapfentaxiImportContext(sessions.system, "krapfentaxi-2026");
const { database } = context;
const storage = createStorage({});
const keys = async () =>
  (await storage.list()).files.map((item) => item.key).sort();
const rows = (table, field) =>
  database.selectFrom(table).selectAll().orderBy(field).execute();
const snapshot = async () => ({
  content: await rows("ec_campaign_pages", "id"),
  revisions: await rows("revisions", "id"),
  media: await rows("media", "id"),
  bindings: await rows("leonaid_campaign_media", "media_id"),
  attempts: await rows("_emdash_media_upload_attempts", "storage_key"),
  // EmDash's independent scheduler writes this heartbeat while the real CMS
  // is running. It is not importer state; retain every other option exactly.
  options: (await rows("options", "name")).filter(
    ({ name }) => name !== "system:scheduler:last_completed_at",
  ),
  fields: await rows("_emdash_fields", "id"),
  journal: (
    await sql`SELECT to_regclass('public.leonaid_krapfentaxi_import') AS relation`.execute(
      database,
    )
  ).rows[0].relation
    ? await rows("leonaid_krapfentaxi_import", "action_id")
    : null,
  objects: await keys(),
});
const assertSnapshot = async (expected) =>
  assert.equal(
    isDeepStrictEqual(await snapshot(), expected),
    true,
    "import state changed; row values intentionally withheld",
  );
const run = (mode = "apply", checkpoint) =>
  importKrapfentaxi({ ...context, mode, checkpoint });
const killAtDurableCheckpoint = async (phase) => {
  const child = spawn(
    process.execPath,
    ["tools/emdash_spike/krapfentaxi-import-kill-child.mjs", phase],
    { stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "";
  let errors = false;
  let ended = false;
  const closed = new Promise((resolve) => {
    child.on("error", () => {
      errors = true;
    });
    child.on("close", (code, signal) => {
      ended = true;
      resolve({ code, signal });
    });
  });
  child.stdout.on("data", (chunk) => {
    output += chunk.toString();
    if (output.length > 128) child.kill("SIGKILL");
  });
  child.stderr.on("data", () => {
    errors = true;
  });
  try {
    const deadline = Date.now() + 30000;
    while (!ended && output !== "durable-checkpoint\n" && Date.now() < deadline)
      await new Promise((resolve) => setTimeout(resolve, 25));
    assert.ok(!ended && !errors, "import child must reach its checkpoint");
    assert.equal(output, "durable-checkpoint\n");
    await assert.rejects(run(), /krapfentaxi_import_busy/);
    assert.equal(child.kill("SIGKILL"), true);
    const result = await closed;
    assert.equal(result.code, null);
    assert.equal(result.signal, "SIGKILL");
    assert.equal(errors, false);
    // The killed process cannot run finally/unlock. Prove PostgreSQL releases
    // its session lock before continuing with the actual recovery operation.
    const target = await context.resolveTarget();
    let released = false;
    const releaseDeadline = Date.now() + 10000;
    while (!released && Date.now() < releaseDeadline) {
      released = await database.connection().execute(async (connection) => {
        const lock =
          await sql`SELECT pg_try_advisory_lock(hashtextextended(${target.action.id},724381916)) AS acquired`.execute(
            connection,
          );
        if (!lock.rows[0].acquired) return false;
        await sql`SELECT pg_advisory_unlock(hashtextextended(${target.action.id},724381916))`.execute(
          connection,
        );
        return true;
      });
      if (!released) await new Promise((resolve) => setTimeout(resolve, 25));
    }
    assert.equal(released, true, "killed import must release its session lock");
    console.log(
      `krapfentaxi-import: actual SIGKILL after ${phase}; concurrent importer denied and session lock released`,
    );
  } finally {
    if (!ended) child.kill("SIGKILL");
    await closed;
  }
};
async function prove() {
  try {
    await installCampaignSchema(database);
    await installCampaignBindings(database);
    await installCampaignMedia(database);
    const target = await context.resolveTarget();
    const existing = await new ContentRepository(database).create({
      type: "campaign_pages",
      slug: target.action.id,
      status: "draft",
      authorId: target.authorId,
      data: {
        action_id: target.action.id,
        title: "Existing editorial work must survive",
      },
    });
    const occupied = await snapshot();
    await assert.rejects(
      run("dry-run"),
      /krapfentaxi_import_existing_editorial_content/,
    );
    await assert.rejects(
      run(),
      /krapfentaxi_import_existing_editorial_content/,
    );
    await assertSnapshot(occupied);
    // Delete only the synthetic row just created in this isolated empty fixture.
    await database
      .deleteFrom("ec_campaign_pages")
      .where("id", "=", existing.id)
      .execute();
    const registry = new SchemaRegistry(database);
    await registry.updateField("campaign_pages", "hero_summary", {
      validation: { maxLength: 1201 },
    });
    const drifted = await snapshot();
    await assert.rejects(run("dry-run"), /campaign_schema_drift/);
    await assertSnapshot(drifted);
    await registry.updateField("campaign_pages", "hero_summary", {
      validation: { maxLength: 1200 },
    });
    const before = await snapshot();
    // Real SQL negative control: excluding one heartbeat must not suppress
    // unexpected changes to any other persisted option.
    const optionProbe = "leonaid:import-proof-unexpected-option";
    await database
      .insertInto("options")
      .values({ name: optionProbe, value: "true" })
      .execute();
    try {
      assert.equal(isDeepStrictEqual(await snapshot(), before), false);
    } finally {
      await database
        .deleteFrom("options")
        .where("name", "=", optionProbe)
        .execute();
    }
    await assertSnapshot(before);
    const preview = await run("dry-run");
    assert.equal(preview.state, "create");
    assert.equal(preview.assets, 3);
    await assertSnapshot(before);
    const privateDirectory = await mkdtemp(
      join(tmpdir(), "leonaid-import-cli-"),
    );
    try {
      const sessionFile = join(privateDirectory, "session");
      await writeFile(sessionFile, sessions.system, { mode: 0o600 });
      const cli = () =>
        spawnSync(
          process.execPath,
          [
            "tools/emdash_spike/krapfentaxi-import-cli.mjs",
            "dry-run",
            "krapfentaxi-2026",
            sessionFile,
          ],
          {
            encoding: "utf8",
            timeout: 30000,
            maxBuffer: 65536,
          },
        );
      const accepted = cli();
      assert.equal(accepted.status, 0, "operator CLI dry run must succeed");
      assert.deepEqual(JSON.parse(accepted.stdout), preview);
      assert.equal(accepted.stderr, "");
      await assertSnapshot(before);
      await chmod(sessionFile, 0o644);
      const denied = cli();
      assert.equal(denied.status, 1);
      assert.equal(denied.stdout, "");
      assert.equal(
        denied.stderr,
        "krapfentaxi-import: denied or unavailable; no automatic overwrite or publication; inspect private operator state before retrying\n",
      );
      await assertSnapshot(before);
    } finally {
      await rm(privateDirectory, { recursive: true, force: true });
    }
    await killAtDurableCheckpoint("reserved");
    assert.equal((await rows("media", "id")).length, 1);
    const firstId = (await rows("media", "id"))[0].id;
    assert.deepEqual(await keys(), []);
    const afterReserve = await snapshot();
    assert.equal((await run("dry-run")).state, "resume");
    await assertSnapshot(afterReserve);

    await killAtDurableCheckpoint("ready");
    assert.equal((await rows("media", "id")).length, 1);
    assert.equal(
      (await new MediaRepository(database).findById(firstId)).status,
      "ready",
    );
    assert.equal((await keys()).length, 1);

    if (process.argv.includes("--prepare-recovery")) {
      const state = await importRecoveryState(database, storage);
      assert.equal(state.tables.ec_campaign_pages.length, 0);
      assert.equal(state.tables.revisions.length, 0);
      assert.equal(state.tables.leonaid_krapfentaxi_import.length, 1);
      assert.equal(state.tables.leonaid_krapfentaxi_import[0].content_id, null);
      await writeFile("/proof/import-recovery.json", JSON.stringify(state), {
        mode: 0o600,
      });
      console.log(
        "import-recovery: actual killed import left one ready original asset and an incomplete journal for backup; no page or publication",
      );
      return;
    }

    // Real PostgreSQL failure at final page creation: all three ready assets and
    // the resumable journal survive, but no partial content/revision is committed.
    await sql`CREATE FUNCTION public.synthetic_import_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic_import_failure'; END; $$`.execute(
      database,
    );
    await sql`CREATE TRIGGER synthetic_import_failure BEFORE INSERT ON public.ec_campaign_pages FOR EACH ROW EXECUTE FUNCTION public.synthetic_import_failure()`.execute(
      database,
    );
    try {
      await assert.rejects(run());
    } finally {
      await sql`DROP TRIGGER synthetic_import_failure ON public.ec_campaign_pages`.execute(
        database,
      );
      await sql`DROP FUNCTION public.synthetic_import_failure()`.execute(
        database,
      );
    }
    assert.equal((await rows("ec_campaign_pages", "id")).length, 0);
    assert.equal((await rows("revisions", "id")).length, 0);
    assert.equal((await rows("media", "id")).length, 3);
    assert.equal((await keys()).length, 3);
    assert.equal(
      (await rows("leonaid_krapfentaxi_import", "action_id"))[0].content_id,
      null,
    );
    const readyKeys = await keys();
    // Simulate loss of the success reply AFTER the actual commit.
    await assert.rejects(
      run("apply", async (phase) => {
        if (phase === "complete") throw new Error("synthetic_reply_lost");
      }),
      /synthetic_reply_lost/,
    );
    const committed = await snapshot();
    const repeated = await run();
    assert.equal(repeated.state, "preserved");
    await assertSnapshot(committed);
    assert.deepEqual(await keys(), readyKeys);
    const repository = new ContentRepository(database);
    const item = await repository.findById(
      "campaign_pages",
      repeated.contentId,
    );
    assert.equal(item.status, "draft");
    assert.equal(item.data.action_id, target.action.id);
    assert.equal(item.authorId, target.authorId);
    assert.equal(item.data.theme, "krapfentaxi");
    assert.equal(item.data.hero_image.id, firstId);
    assert.equal(
      item.data.partners[0].name,
      "Unsere Krapfenbäckerei:\nRösner Backstube.",
    );
    await repository.updateDraftAware("campaign_pages", item.id, {
      data: { story_title: "Preserve later editorial changes" },
    });
    const edited = await snapshot();
    assert.equal((await run()).state, "preserved");
    assert.equal((await run("dry-run")).state, "preserved");
    await assertSnapshot(edited);
    const repeatDirectory = await mkdtemp(
      join(tmpdir(), "leonaid-import-repeat-"),
    );
    try {
      const sessionFile = join(repeatDirectory, "session");
      await writeFile(sessionFile, sessions.system, { mode: 0o600 });
      const cli = spawnSync(
        process.execPath,
        [
          "tools/emdash_spike/krapfentaxi-import-cli.mjs",
          "apply",
          "krapfentaxi-2026",
          sessionFile,
        ],
        {
          encoding: "utf8",
          timeout: 30000,
          maxBuffer: 65536,
        },
      );
      assert.equal(
        cli.status,
        0,
        "explicit CLI apply must preserve a completed import",
      );
      assert.equal(JSON.parse(cli.stdout).state, "preserved");
      assert.equal(cli.stderr, "");
      await assertSnapshot(edited);
    } finally {
      await rm(repeatDirectory, { recursive: true, force: true });
    }
    const persistentFacts = (action) => {
      const copy = structuredClone(action);
      if (copy.orderForm) delete copy.orderForm.accessToken;
      return copy;
    };
    assert.equal(
      isDeepStrictEqual(
        persistentFacts((await context.resolveTarget()).action),
        persistentFacts(target.action),
      ),
      true,
      "Core business facts must remain unchanged; per-request order capabilities are deliberately excluded",
    );
    for (const key of await keys()) {
      const anonymous = await fetch(
        `${process.env.S3_ENDPOINT}/${process.env.S3_BUCKET}/${key}`,
        { signal: AbortSignal.timeout(5000) },
      );
      await anonymous.body?.cancel();
      assert.equal(anonymous.status, 403);
    }

    // A real Core logout invalidates the operator's session too.
    const ca = await readFile("/proof/root.crt");
    for (const path of [
      "/campaigns/krapfentaxi-2026/",
      `/campaigns/krapfentaxi-2026/media/${firstId}`,
    ]) {
      const hidden = await new Promise((resolve, reject) => {
        const req = request(
          new URL(path, "https://proxy:8443"),
          { ca },
          (response) => {
            response.resume();
            response.on("end", () => resolve(response.statusCode));
          },
        );
        req.setTimeout(10000, () =>
          req.destroy(new Error("draft_probe_timeout")),
        );
        req.on("error", reject);
        req.end();
      });
      assert.equal(hidden, 404);
    }
    const status = await new Promise((resolve, reject) => {
      const req = request(
        "https://proxy:8443/api/v1/auth/logout",
        {
          ca,
          method: "POST",
          headers: {
            Origin: "https://proxy:8443",
            Cookie: `__Host-leonaid_session=${sessions.system}`,
          },
        },
        (response) => {
          response.resume();
          response.on("end", () => resolve(response.statusCode));
        },
      );
      req.setTimeout(10000, () =>
        req.destroy(new Error("synthetic_logout_timeout")),
      );
      req.on("error", reject);
      req.end();
    });
    assert.equal(status, 200);
    await assert.rejects(run(), /identity_denied/);
    await assertSnapshot(edited);
    console.log(
      "krapfentaxi-import: OK: actual Core target/identity, read-only dry run, atomic journal/media reservation, actual SIGKILL at reserved/ready checkpoints and resume with same IDs, concurrent importer exclusion, actual PostgreSQL final-write rollback, private original RustFS assets, draft-only create, lost-success-reply recovery, preservation of editor changes and real Core logout denial; restored-journal resume remains a separate gate",
    );
  } finally {
    await database.destroy();
  }
}
await prove();
