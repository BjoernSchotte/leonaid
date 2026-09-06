import { sql } from "kysely";
import { handleContentCreate } from "emdash";
import { requireCampaignBindings } from "./campaign-bindings.mjs";
import { validCampaignEditorial } from "./campaign-editorial.mjs";
import {
  requireCampaignMediaReferences,
  requireCampaignResultMediaReferences,
} from "./campaign-media-references.mjs";

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const reject = (code) => ({
  success: false,
  error: { code, message: "Campaign creation denied" },
});

// Database primitive only: profile and resolvedAction must come from current
// Core reads. This does not admit HTTP or enable Charity access. It exercises
// the lower-level creator only; the eventual HTTP integration must retain the
// original runtime creator, including its hooks and schema validation.
/**
 * @param {(...args: Parameters<typeof handleContentCreate>) => Promise<{success: boolean, data?: unknown, error?: {code: string, message: string}}>} [create]
 */
export async function createCampaignContent(
  database,
  profile,
  resolvedAction,
  cmsUserId,
  body,
  create = handleContentCreate,
) {
  const data = body?.data;
  if (
    !body ||
    typeof body !== "object" ||
    Array.isArray(body) ||
    Object.keys(body).some((key) => key !== "data") ||
    !validCampaignEditorial(data) ||
    typeof data.action_id !== "string" ||
    !uuid.test(data.action_id) ||
    resolvedAction?.id !== data.action_id
  )
    return reject("FORBIDDEN");
  const permitted =
    profile.globalRoles.includes("system_admin") ||
    profile.actionMemberships.some(
      (item) =>
        item.role === "charity_admin" && item.actionId === data.action_id,
    );
  if (!permitted) return reject("FORBIDDEN");
  return database.transaction().execute(async (transaction) => {
    await sql`SET LOCAL lock_timeout = '2s'`.execute(transaction);
    await sql`SET LOCAL statement_timeout = '3s'`.execute(transaction);
    await requireCampaignBindings(transaction);
    const mapping =
      await sql`SELECT cms_user_id FROM public.leonaid_external_identity
      WHERE core_user_id=${profile.userId} AND cms_user_id=${cmsUserId}`.execute(
        transaction,
      );
    if (mapping.rows.length !== 1) return reject("FORBIDDEN");
    // Serialize this create path per immutable Core action. Existing/trash rows
    // reserve the binding too; do not silently create a second microsite.
    await sql`SELECT pg_advisory_xact_lock(hashtextextended(${data.action_id}, 724381903))`.execute(
      transaction,
    );
    const existing = await sql`SELECT id FROM public.ec_campaign_pages
      WHERE action_id=${data.action_id} LIMIT 1`.execute(transaction);
    if (existing.rows.length) return reject("CONFLICT");
    await requireCampaignMediaReferences(transaction, data.action_id, data);
    const result = await create(transaction, "campaign_pages", {
      data: { ...data, title: data.title.trim() },
      slug: data.action_id,
      status: "draft",
      authorId: cmsUserId,
    });
    // Upstream may return an error after partial work: abort the transaction,
    // never commit a failed result. The HTTP layer must sanitize exceptions.
    if (!result.success) throw new Error("campaign_create_failed");
    await requireCampaignResultMediaReferences(
      transaction,
      data.action_id,
      result,
    );
    return result;
  });
}
