import type { APIRoute } from "astro";
import { sql } from "kysely";
import {
  CoreIdentityError,
  readCoreIdentity,
  requireCoreCampaign,
} from "./core-identity";
import { requireCampaignBindings } from "./campaign-bindings.mjs";

// Stable Core-facing entry point. Public campaign slugs never select CMS rows.
// This GET performs no content mutation; creation still requires native Save.
export const GET: APIRoute = async ({ request, params, locals }) => {
  const headers = { "Cache-Control": "no-store" };
  try {
    const profile = await readCoreIdentity(request);
    if (profile.role !== 50 || locals.user?.role !== 50)
      throw new CoreIdentityError(403);
    const actionId = params.actionId;
    if (!actionId) throw new CoreIdentityError(403);
    await requireCoreCampaign(request, actionId);
    const database = locals.emdash?.db;
    if (!database) throw new CoreIdentityError(503);
    const rows = await database.transaction().execute(async (transaction) => {
      await sql`SET LOCAL lock_timeout = '2s'`.execute(transaction);
      await sql`SET LOCAL statement_timeout = '3s'`.execute(transaction);
      await requireCampaignBindings(transaction);
      return (
        await sql<{ id: string; deleted_at: unknown }>`
          SELECT id, deleted_at FROM public.ec_campaign_pages
          WHERE action_id=${actionId} LIMIT 2 FOR SHARE`.execute(transaction)
      ).rows;
    });
    // A trashed row still reserves the binding. Historical duplicates must be
    // reconciled explicitly, never hidden by picking whichever row comes first.
    if (rows.length > 1 || (rows.length === 1 && rows[0].deleted_at !== null))
      return Response.json(
        { error: { code: "CAMPAIGN_BINDING_CONFLICT" } },
        { status: 409, headers },
      );
    if (rows.length && !/^[0-9A-HJKMNP-TV-Z]{26}$/.test(rows[0].id))
      throw new CoreIdentityError(503);
    const destination = rows.length
      ? `/_emdash/admin/content/campaign_pages/${rows[0].id}`
      : `/_emdash/admin/content/campaign_pages/new?campaign=${actionId}`;
    return new Response(null, {
      status: 303,
      headers: { ...headers, Location: destination },
    });
  } catch (error) {
    return Response.json(
      { error: { code: "CAMPAIGN_HANDOFF_DENIED" } },
      {
        status: error instanceof CoreIdentityError ? error.status : 503,
        headers,
      },
    );
  }
};
