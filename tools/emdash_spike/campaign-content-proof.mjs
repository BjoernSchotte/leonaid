import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import pg from "pg";
import { Kysely } from "kysely";
import { createDialect } from "emdash/db/postgres";
import { runMigrations } from "emdash/db";
import { applySeed } from "emdash/seed";
import { ContentRepository } from "emdash";
import { provisionPostgres } from "./provision-postgres.mjs";
import {
  listCampaignContent,
  getCampaignContent,
  listCampaignRevisions,
  getCampaignRevision,
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
const actor = (id) => ({
  globalRoles: [],
  actionMemberships: [{ actionId: id, role: "charity_admin" }],
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
        campaign_pages: [a, a, b, b].map((action, index) => ({
          id: `entry-${index}`,
          slug: `entry-${index}`,
          status: "draft",
          data: {
            action_id: action,
            title: `${action === a ? "alpha" : "bravo"} story ${index}`,
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
  const repository = new ContentRepository(database);
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
    const foreign = actor(entry.data.action_id === a ? b : a);
    const own = await getCampaignContent(
      database,
      owner,
      "campaign_pages",
      entry.id,
    );
    assert.equal(own.success, true);
    assert.equal(own.data.item.id, entry.id);
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
  for (const action of [a, b]) {
    const profile = actor(action);
    const first = await list(profile, { limit: 1 });
    assert.equal(first.total, 2);
    assert.equal(first.items.length, 1);
    assert.equal(first.items[0].data.action_id, action);
    assert.ok(first.nextCursor);
    const second = await list(profile, { limit: 1, cursor: first.nextCursor });
    assert.equal(second.total, 2);
    assert.equal(second.items.length, 1);
    assert.equal(second.items[0].data.action_id, action);
    assert.notEqual(second.items[0].id, first.items[0].id);
    const hostile = await list(profile, {
      fieldFilters: { action_id: action === a ? b : a },
    });
    assert.equal(hostile.total, 2);
    assert.ok(hostile.items.every((item) => item.data.action_id === action));
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
  console.log(
    "campaign-content: real PostgreSQL/EmDash two-campaign lists, counts, cursors, search, hostile filters, item reads and revision reads passed; HTTP admission remains closed",
  );
} finally {
  await database.destroy();
}
