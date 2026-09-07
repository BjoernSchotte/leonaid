import pg from "pg";
import { Kysely, PostgresDialect } from "kysely";
import {
  readCoreIdentity,
  requireCoreCampaign,
} from "../../apps/campaign-site/src/auth/core-identity.ts";
import { readPublicCoreCampaign } from "../../apps/campaign-site/src/public/core-campaign.ts";
import { campaignStorage } from "../../apps/campaign-site/src/auth/campaign-media-io.mjs";

// Run with pinned Bun in the operator container; reuse the application's typed
// Core transport/validation rather than creating another authentication stack.
export function krapfentaxiImportContext(session, slug) {
  if (
    !/^[A-Za-z0-9_-]{32,256}$/.test(session) ||
    !/^krapfentaxi(?:-[a-z0-9]+)*$/.test(slug) ||
    slug.length > 160 ||
    process.env.PGHOST !== "core-postgres" ||
    process.env.PGDATABASE !== "emdash" ||
    process.env.PGUSER !== "emdash" ||
    !process.env.PGPASSWORD
  )
    throw new Error("krapfentaxi_import_configuration");
  const database = new Kysely({
    dialect: new PostgresDialect({
      pool: new pg.Pool({
        host: "core-postgres",
        database: "emdash",
        user: "emdash",
        password: process.env.PGPASSWORD,
        max: 4,
        connectionTimeoutMillis: 3000,
        statement_timeout: 5000,
        query_timeout: 8000,
      }),
    }),
  });
  const request = new Request("http://operator.invalid", {
    headers: { Cookie: `__Host-leonaid_session=${session}` },
  });
  const resolveTarget = async () => {
    const profile = await readCoreIdentity(request);
    const route = await readPublicCoreCampaign(slug);
    if (!route.action) throw new Error("krapfentaxi_import_target_unavailable");
    await requireCoreCampaign(request, route.action.id);
    const mapping = await database
      .selectFrom("leonaid_external_identity")
      .innerJoin("users", "users.id", "leonaid_external_identity.cms_user_id")
      .select("cms_user_id")
      .where("core_user_id", "=", profile.userId)
      .where("users.disabled", "=", 0)
      .where("users.role", "=", profile.role)
      .executeTakeFirst();
    if (!mapping) throw new Error("krapfentaxi_import_cms_login_required");
    return { action: route.action, profile, authorId: mapping.cms_user_id };
  };
  return { database, resolveTarget, storage: campaignStorage() };
}
