import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { Kysely, sql } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { applySeed } from "emdash/seed";
import { ContentRepository } from "emdash";
import { authorizeCampaignUpdate } from "../../apps/campaign-site/src/auth/campaign-update.mjs";
import {
  installCampaignBindings,
  requireCampaignBindings,
} from "../../apps/campaign-site/src/auth/campaign-bindings.mjs";
import { provisionPostgres } from "./provision-postgres.mjs";
import { proveCampaignCreate } from "./campaign-create-proof.mjs";
import {
  listCampaignContent,
  getCampaignContent,
  listCampaignRevisions,
  getCampaignRevision,
  compareCampaignContent,
} from "../../apps/campaign-site/src/auth/campaign-content.mjs";

const admin = new pg.Pool({ connectionTimeoutMillis: 3000 });
const password = randomBytes(32).toString("hex");
try {
  await provisionPostgres({
    admin,
    coreDatabase: "leonaid",
    coreRole: "leonaid",
    password,
  });
} finally {
  await admin.end();
}
const database = new Kysely({
  dialect: createDialect({
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password,
  }),
});
const a = "20000000-0000-4000-8000-000000000001";
const b = "20000000-0000-4000-8000-000000000002";
const a2 = "20000000-0000-4000-8000-000000000011";
const b2 = "20000000-0000-4000-8000-000000000012";
const group = (id) => ([a, a2].includes(id) ? [a, a2] : [b, b2]);
const actor = (id) => ({
  globalRoles: [],
  actionMemberships: group(id).map((actionId) => ({
    actionId,
    role: "charity_admin",
  })),
});
const system = { globalRoles: ["system_admin"], actionMemberships: [] };
try {
  await runMigrations(database);
  const seed = await applySeed(
    database,
    {
      version: "1",
      collections: [
        {
          slug: "campaign_pages",
          label: "Campaign pages",
          titleField: "title",
          supports: ["drafts", "revisions"],
          fields: [
            {
              slug: "action_id",
              label: "Core action",
              type: "string",
              required: true,
              indexed: true,
            },
            { slug: "title", label: "Title", type: "text", searchable: true },
          ],
        },
      ],
      content: {
        campaign_pages: [a, a2, b, b2].map((action, index) => ({
          id: `entry-${index}`,
          slug: `entry-${index}`,
          status: "draft",
          data: {
            action_id: action,
            title: `${group(action).includes(a) ? "alpha" : "bravo"} story ${index}`,
          },
        })),
      },
    },
    { includeContent: true, onConflict: "error" },
  );
  assert.equal(seed.content.created, 4);
  const list = async (profile, parameters = {}) => {
    const result = await listCampaignContent(
      database,
      profile,
      "campaign_pages",
      parameters,
    );
    assert.equal(result.success, true, JSON.stringify(result));
    return result.data;
  };
  assert.equal((await list(system)).total, 4);
  const entries = (await list(system)).items;
  await assert.rejects(
    requireCampaignBindings(database),
    /campaign_binding_guard_mismatch/,
  );
  const original = entries[0];
  await sql`UPDATE ec_campaign_pages SET action_id='invalid' WHERE id=${original.id}`.execute(
    database,
  );
  await assert.rejects(
    installCampaignBindings(database),
    /campaign_binding_existing_data_invalid/,
  );
  await sql`UPDATE ec_campaign_pages SET action_id=${original.data.action_id} WHERE id=${original.id}`.execute(
    database,
  );
  const duplicate = entries[1];
  await sql`UPDATE ec_campaign_pages SET action_id=${original.data.action_id}
    WHERE id=${duplicate.id}`.execute(database);
  await assert.rejects(
    installCampaignBindings(database),
    /campaign_binding_existing_duplicates/,
  );
  assert.equal(
    (
      await sql`SELECT count(*)::integer AS count FROM ec_campaign_pages
    WHERE action_id=${original.data.action_id}`.execute(database)
    ).rows[0].count,
    2,
  );
  assert.equal(
    (
      await database
        .selectFrom("options")
        .selectAll()
        .where("name", "=", "leonaid:campaign_binding_version")
        .execute()
    ).length,
    0,
  );
  // Only the fixture restores its deliberately corrupted row; the installer
  // must not select a winner, delete content or rewrite existing bindings.
  await sql`UPDATE ec_campaign_pages SET action_id=${duplicate.data.action_id}
    WHERE id=${duplicate.id}`.execute(database);
  await installCampaignBindings(database);
  await installCampaignBindings(database);
  await requireCampaignBindings(database);
  await assert.rejects(
    sql`UPDATE ec_campaign_pages SET action_id=${original.data.action_id === a ? b : a} WHERE id=${original.id}`.execute(
      database,
    ),
    { code: "23514", message: "campaign_binding_immutable" },
  );
  await assert.rejects(
    sql`UPDATE ec_campaign_pages SET id='00000000000000000000000000' WHERE id=${original.id}`.execute(
      database,
    ),
    { code: "23514", message: "campaign_binding_immutable" },
  );
  await assert.rejects(
    sql`UPDATE ec_campaign_pages SET action_id='invalid' WHERE id=${original.id}`.execute(
      database,
    ),
    { code: "23514", message: "campaign_binding_invalid" },
  );
  const repository = new ContentRepository(database);
  await assert.rejects(
    repository.create({
      type: "campaign_pages",
      slug: "invalid-binding",
      data: { action_id: "invalid", title: "denied" },
    }),
    { code: "23514", message: "campaign_binding_invalid" },
  );
  await assert.rejects(
    sql`INSERT INTO revisions (id, collection, entry_id, data)
      VALUES ('00000000000000000000000001', 'campaign_pages', ${original.id}, '{}')`.execute(
      database,
    ),
    { code: "23514", message: "campaign_revision_binding_invalid" },
  );
  for (const entry of entries) {
    await repository.updateDraftAware("campaign_pages", entry.id, {
      data: { title: `${entry.data.title} revised` },
    });
  }
  const missing = await getCampaignContent(
    database,
    actor(a),
    "campaign_pages",
    "00000000000000000000000000",
  );
  assert.equal(missing.error.code, "NOT_FOUND");
  assert.deepEqual(
    await getCampaignRevision(database, actor(a), "00000000000000000000000000"),
    missing,
  );
  assert.deepEqual(
    await getCampaignContent(database, actor(a), "campaign_pages", "entry-0"),
    missing,
  );
  for (const entry of entries) {
    const owner = actor(entry.data.action_id);
    const foreign = actor(group(entry.data.action_id).includes(a) ? b : a);
    const own = await getCampaignContent(
      database,
      owner,
      "campaign_pages",
      entry.id,
    );
    assert.equal(own.success, true);
    assert.equal(own.data.item.id, entry.id);
    const comparison = await compareCampaignContent(
      database,
      owner,
      "campaign_pages",
      entry.id,
    );
    assert.equal(comparison.success, true);
    assert.equal(comparison.data.draft.action_id, entry.data.action_id);
    assert.deepEqual(
      await compareCampaignContent(
        database,
        foreign,
        "campaign_pages",
        entry.id,
      ),
      missing,
    );
    const update = {
      _rev: own.data._rev,
      data: { title: "allowed draft edit", action_id: entry.data.action_id },
    };
    assert.equal(
      await authorizeCampaignUpdate(
        database,
        owner,
        "campaign_pages",
        entry.id,
        update,
      ),
      null,
    );
    assert.deepEqual(
      await authorizeCampaignUpdate(
        database,
        foreign,
        "campaign_pages",
        entry.id,
        update,
      ),
      missing,
    );
    assert.equal(
      (
        await authorizeCampaignUpdate(
          database,
          owner,
          "campaign_pages",
          entry.id,
          {
            ...update,
            data: {
              ...update.data,
              action_id: entry.data.action_id === a ? b : a,
            },
          },
        )
      ).error.code,
      "FORBIDDEN",
    );
    assert.deepEqual(
      await getCampaignContent(database, foreign, "campaign_pages", entry.id),
      missing,
    );
    const revisions = await listCampaignRevisions(
      database,
      owner,
      "campaign_pages",
      entry.id,
    );
    assert.equal(revisions.success, true);
    assert.ok(revisions.data.total > 0);
    assert.deepEqual(
      await listCampaignRevisions(
        database,
        foreign,
        "campaign_pages",
        entry.id,
      ),
      missing,
    );
    for (const revision of revisions.data.items) {
      await assert.rejects(
        sql`UPDATE revisions SET data=${JSON.stringify({ action_id: entry.data.action_id === a ? b : a })} WHERE id=${revision.id}`.execute(
          database,
        ),
        { code: "23514", message: "campaign_revision_binding_invalid" },
      );
      await assert.rejects(
        sql`UPDATE revisions SET entry_id='00000000000000000000000000' WHERE id=${revision.id}`.execute(
          database,
        ),
        { code: "23514", message: "campaign_revision_parent_immutable" },
      );
      await assert.rejects(
        sql`UPDATE revisions SET collection='other' WHERE id=${revision.id}`.execute(
          database,
        ),
        { code: "23514", message: "campaign_revision_parent_immutable" },
      );
      const ownRevision = await getCampaignRevision(
        database,
        owner,
        revision.id,
      );
      assert.equal(ownRevision.success, true);
      assert.equal(ownRevision.data.item.entryId, entry.id);
      assert.deepEqual(
        await getCampaignRevision(database, foreign, revision.id),
        missing,
      );
      assert.equal(
        (await getCampaignRevision(database, system, revision.id)).success,
        true,
      );
    }
  }
  const pointerOwner = await getCampaignContent(
    database,
    system,
    "campaign_pages",
    entries[0].id,
  );
  const pointerOther = await getCampaignContent(
    database,
    system,
    "campaign_pages",
    entries[1].id,
  );
  await sql`UPDATE ec_campaign_pages SET draft_revision_id=${pointerOther.data.item.draftRevisionId}
    WHERE id=${entries[0].id}`.execute(database);
  try {
    assert.deepEqual(
      await compareCampaignContent(
        database,
        system,
        "campaign_pages",
        entries[0].id,
      ),
      missing,
    );
  } finally {
    await sql`UPDATE ec_campaign_pages SET draft_revision_id=${pointerOwner.data.item.draftRevisionId}
      WHERE id=${entries[0].id}`.execute(database);
  }
  for (const action of [a, b]) {
    const profile = actor(action);
    const first = await list(profile, { limit: 1 });
    assert.equal(first.total, 2);
    assert.equal(first.items.length, 1);
    assert.ok(group(action).includes(first.items[0].data.action_id));
    assert.ok(first.nextCursor);
    const second = await list(profile, { limit: 1, cursor: first.nextCursor });
    assert.equal(second.total, 2);
    assert.equal(second.items.length, 1);
    assert.ok(group(action).includes(second.items[0].data.action_id));
    assert.notEqual(second.items[0].id, first.items[0].id);
    const hostile = await list(profile, {
      fieldFilters: { action_id: action === a ? b : a },
    });
    assert.equal(hostile.total, 2);
    assert.ok(
      hostile.items.every((item) =>
        group(action).includes(item.data.action_id),
      ),
    );
    const search = await list(profile, { q: action === a ? "bravo" : "alpha" });
    assert.equal(search.total, 0);
    assert.deepEqual(search.items, []);
  }
  await assert.rejects(
    list({ globalRoles: [], actionMemberships: [] }),
    /campaign_access_denied/,
  );
  await assert.rejects(
    list({
      globalRoles: [],
      actionMemberships: [{ actionId: a, role: "driver" }],
    }),
    /campaign_access_denied/,
  );
  await assert.rejects(
    database.transaction().execute(async (transaction) => {
      await sql`ALTER TABLE ec_campaign_pages DISABLE TRIGGER leonaid_campaign_binding`.execute(
        transaction,
      );
      await assert.rejects(
        requireCampaignBindings(transaction),
        /campaign_binding_guard_mismatch/,
      );
      throw new Error("rollback_guard_drift_probe");
    }),
    /rollback_guard_drift_probe/,
  );
  await requireCampaignBindings(database);
  await assert.rejects(
    database.transaction().execute(async (transaction) => {
      await sql`CREATE OR REPLACE FUNCTION public.leonaid_campaign_binding() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog
        AS 'BEGIN RETURN NEW; END;'`.execute(transaction);
      await assert.rejects(
        requireCampaignBindings(transaction),
        /campaign_binding_guard_mismatch/,
      );
      throw new Error("rollback_guard_source_probe");
    }),
    /rollback_guard_source_probe/,
  );
  await requireCampaignBindings(database);
  console.log(
    "campaign-content: real PostgreSQL/EmDash scoped reads, immutable content/revision bindings, invalid existing data and disabled-guard denial passed; Charity admission remains closed",
  );
  const concurrentAction = "20000000-0000-4000-8000-000000000099";
  const attempts = await Promise.allSettled(
    Array.from({ length: 4 }, (_, index) =>
      sql`INSERT INTO ec_campaign_pages (id, slug, action_id, title)
      VALUES (${`0000000000000000000000009${index}`}, ${`unique-race-${index}`},
        ${concurrentAction}, 'Synthetic direct database race')`.execute(
        database,
      ),
    ),
  );
  assert.equal(
    attempts.filter((result) => result.status === "fulfilled").length,
    1,
  );
  const rejected = attempts.filter((result) => result.status === "rejected");
  assert.equal(rejected.length, 3);
  for (const result of rejected) {
    assert.equal(result.reason.code, "23505");
    assert.equal(result.reason.constraint, "leonaid_campaign_action_unique");
  }
  await sql`UPDATE ec_campaign_pages SET deleted_at='2026-09-06T00:00:00Z'
    WHERE action_id=${concurrentAction}`.execute(database);
  await assert.rejects(
    sql`INSERT INTO ec_campaign_pages (id, slug, locale, action_id, title)
    VALUES ('00000000000000000000000098', 'different-slug', 'de', ${concurrentAction},
      'Trashed binding remains reserved across locales')`.execute(database),
    { code: "23505", constraint: "leonaid_campaign_action_unique" },
  );
  for (const replacement of [
    null,
    "ALTER TABLE public.ec_campaign_pages ADD CONSTRAINT leonaid_campaign_action_unique UNIQUE (action_id) DEFERRABLE",
    "ALTER TABLE public.ec_campaign_pages ADD CONSTRAINT leonaid_campaign_action_unique UNIQUE (action_id, id)",
  ]) {
    await assert.rejects(
      database.transaction().execute(async (transaction) => {
        await sql`ALTER TABLE public.ec_campaign_pages DROP CONSTRAINT leonaid_campaign_action_unique`.execute(
          transaction,
        );
        if (replacement) await sql.raw(replacement).execute(transaction);
        await assert.rejects(
          requireCampaignBindings(transaction),
          /campaign_binding_unique_mismatch/,
        );
        throw new Error("rollback_unique_drift_probe");
      }),
      /rollback_unique_drift_probe/,
    );
    await requireCampaignBindings(database);
  }
  console.log(
    "campaign-content: database-wide concurrent uniqueness, trash/locale reservation and missing/deferred/composite constraint denial passed",
  );
  await proveCampaignCreate(database, {
    host: process.env.PGHOST,
    user: "emdash",
    database: "emdash",
    password,
  });
} finally {
  await database.destroy();
}
