import { ContentRepository } from "emdash";
import { sql } from "kysely";
import { requireCampaignBindings } from "../auth/campaign-bindings.mjs";
import { validCampaignEditorial } from "../auth/campaign-editorial.mjs";
import { requireCampaignMediaReferences } from "../auth/campaign-media-references.mjs";

export class PublishedCampaignUnavailable extends Error {
  constructor() {
    super("published_campaign_unavailable");
  }
}

// Server-only CMS reader. The caller must FIRST resolve current public Core
// availability and pass its action ID. This function does not authorize public
// visibility on its own, accept a CMS slug, or load preview/draft revisions.
export async function readPublishedCampaign(database, actionId) {
  if (
    typeof actionId !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(
      actionId,
    )
  )
    throw new PublishedCampaignUnavailable();
  try {
    return await database.transaction().execute(async (transaction) => {
      await sql`SET LOCAL lock_timeout = '1s'`.execute(transaction);
      await sql`SET LOCAL statement_timeout = '2s'`.execute(transaction);
      await requireCampaignBindings(transaction);
      const row = await transaction
        .selectFrom("ec_campaign_pages")
        .select("id")
        .where("action_id", "=", actionId)
        .where("status", "=", "published")
        .where("deleted_at", "is", null)
        .forShare()
        .executeTakeFirst();
      if (!row) return null;
      // Pinned repository reads live table columns only. Do not replace with
      // locals.emdash.handleContentGet: the runtime hydrates private drafts.
      // Keep the row locked through hydration/validation and media binding.
      const item = await new ContentRepository(transaction).findById(
        "campaign_pages",
        row.id,
      );
      if (
        !item ||
        item.status !== "published" ||
        item.data.action_id !== actionId ||
        !validCampaignEditorial(item.data)
      )
        throw new PublishedCampaignUnavailable();
      const rows = await requireCampaignMediaReferences(
        transaction,
        actionId,
        item.data,
      );
      // No author, revision IDs, draft metadata or EmDash slug in the result.
      // `media` carries each referenced file's content hash and size for
      // versioned image URLs (published-media.mjs).
      const media = Object.fromEntries(
        rows.map((row) => [
          row.id,
          { contentHash: row.content_hash, width: row.width },
        ]),
      );
      return { entryId: item.id, data: item.data, media };
    });
  } catch {
    // Never expose driver errors, draft contents or operational diagnostics.
    throw new PublishedCampaignUnavailable();
  }
}
