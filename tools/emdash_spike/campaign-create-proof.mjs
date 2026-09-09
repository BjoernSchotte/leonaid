import assert from "node:assert/strict";
import pg from "pg";
import { sql } from "kysely";
import { createCampaignContent } from "../../apps/campaign-site/src/auth/campaign-create.mjs";
import {
  installIdentityMapping,
  synchronizeExternalIdentity,
} from "../../apps/campaign-site/src/auth/identity-map.mjs";

export async function proveCampaignCreate(database, options) {
  const pool = new pg.Pool(options);
  try {
    await installIdentityMapping(pool);
    const systemId = "10000000-0000-4000-8000-000000000001";
    const charityId = "10000000-0000-4000-8000-000000000002";
    const mapped = await synchronizeExternalIdentity(pool, {
      coreUserId: systemId,
      email: "system@leonaid.invalid",
      name: "Synthetic system",
      role: 50,
    });
    const charityMapped = await synchronizeExternalIdentity(pool, {
      coreUserId: charityId,
      email: "charity@leonaid.invalid",
      name: "Synthetic charity",
      role: 40,
    });
    const action = "20000000-0000-4000-8000-000000000051";
    const other = "20000000-0000-4000-8000-000000000052";
    const system = {
      userId: systemId,
      globalRoles: ["system_admin"],
      actionMemberships: [],
    };
    const charity = {
      userId: charityId,
      globalRoles: [],
      actionMemberships: [{ actionId: action, role: "charity_admin" }],
    };
    const body = { data: { action_id: action, title: "  New campaign  " } };
    // Actor/action objects are pure policy inputs, not substitutes for Core HTTP.
    const create = (
      profile,
      input = body,
      resolved = { id: action },
      user = charityMapped.cmsUserId,
    ) => createCampaignContent(database, profile, resolved, user, input);
    for (const input of [
      null,
      [],
      {},
      { data: null },
      { data: [] },
      { data: { ...body.data, title: " " } },
      { data: { ...body.data, title: "x".repeat(401) } },
      { data: { ...body.data, action_id: "invalid" } },
      { data: { ...body.data, html: "untrusted" } },
      ...[
        "status",
        "slug",
        "authorId",
        "locale",
        "translationOf",
        "publishedAt",
        "createdAt",
        "seo",
        "bylines",
        "taxonomies",
      ].map((key) => ({ ...body, [key]: "untrusted" })),
    ])
      assert.equal((await create(charity, input)).error.code, "FORBIDDEN");
    assert.equal(
      (await create(charity, body, { id: other })).error.code,
      "FORBIDDEN",
    );
    assert.equal(
      (await create({ ...charity, actionMemberships: [] })).error.code,
      "FORBIDDEN",
    );
    assert.equal(
      (
        await create({
          ...charity,
          actionMemberships: [{ actionId: action, role: "driver" }],
        })
      ).error.code,
      "FORBIDDEN",
    );
    assert.equal(
      (await create(charity, body, { id: action }, mapped.cmsUserId)).error
        .code,
      "FORBIDDEN",
    );
    const results = await Promise.all(
      Array.from({ length: 4 }, () => create(charity)),
    );
    assert.equal(results.filter((result) => result.success).length, 1);
    assert.equal(
      results.filter((result) => result.error?.code === "CONFLICT").length,
      3,
    );
    const created = results.find((result) => result.success).data.item;
    assert.equal(created.data.action_id, action);
    assert.equal(created.data.title, "New campaign");
    assert.equal(created.authorId, charityMapped.cmsUserId);
    assert.equal(created.status, "draft");
    assert.equal(created.slug, action);
    assert.ok(results.find((result) => result.success).data._rev);
    await sql`UPDATE ec_campaign_pages SET deleted_at=CURRENT_TIMESTAMP WHERE id=${created.id}`.execute(
      database,
    );
    assert.equal((await create(charity)).error.code, "CONFLICT");
    const systemCreated = await create(
      system,
      { data: { title: "System campaign", action_id: other } },
      { id: other },
      mapped.cmsUserId,
    );
    assert.equal(systemCreated.success, true);
    assert.equal(systemCreated.data.item.authorId, mapped.cmsUserId);
    const failedAction = "20000000-0000-4000-8000-000000000053";
    await sql`CREATE FUNCTION public.leonaid_test_create_failure() RETURNS trigger
      LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''synthetic_late_create_failure''; END;'`.execute(
      database,
    );
    await sql`CREATE TRIGGER leonaid_test_create_failure AFTER INSERT ON public.ec_campaign_pages
      FOR EACH ROW EXECUTE FUNCTION public.leonaid_test_create_failure()`.execute(
      database,
    );
    try {
      await assert.rejects(
        create(
          system,
          { data: { title: "Must roll back", action_id: failedAction } },
          { id: failedAction },
          mapped.cmsUserId,
        ),
        /campaign_create_failed/,
      );
      const rows =
        await sql`SELECT id FROM public.ec_campaign_pages WHERE action_id=${failedAction}`.execute(
          database,
        );
      assert.equal(rows.rows.length, 0);
    } finally {
      await sql`DROP TRIGGER leonaid_test_create_failure ON public.ec_campaign_pages`.execute(
        database,
      );
      await sql`DROP FUNCTION public.leonaid_test_create_failure()`.execute(
        database,
      );
    }
    assert.equal(
      (
        await create(
          system,
          { data: { title: "After recovery", action_id: failedAction } },
          { id: failedAction },
          mapped.cmsUserId,
        )
      ).success,
      true,
    );
    console.log(
      "campaign-create: OK: real PostgreSQL/EmDash draft creation, actor mapping, scope/metadata denial, one concurrent winner, trash binding reservation and late-write rollback/recovery; HTTP remains closed",
    );
  } finally {
    await pool.end();
  }
}
