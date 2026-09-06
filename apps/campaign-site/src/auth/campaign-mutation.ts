import { sql } from "kysely";
import {
  getRequestContext,
  runWithContext,
  type EmDashRequestContext,
} from "emdash/request-context";

type Updater = App.Locals["emdash"]["handleContentUpdate"];
type Result = Awaited<ReturnType<Updater>>;

class RejectedMutation extends Error {
  constructor(readonly result: Result) {
    super("campaign_mutation_rejected");
  }
}

function deferredTracker(): NonNullable<EmDashRequestContext["deferredTasks"]> {
  const pending = new Set<Promise<unknown>>();
  let finish!: () => void;
  const settled = new Promise<void>((resolve) => {
    finish = resolve;
  });
  return {
    settled,
    track<T>(promise: Promise<T>) {
      pending.add(promise);
      void promise.then(
        () => pending.delete(promise),
        () => pending.delete(promise),
      );
      return promise;
    },
    settle() {
      void (async () => {
        while (pending.size) await Promise.allSettled([...pending]);
        finish();
      })();
    },
  };
}

// Called only after the current Core actor and immutable binding are authorized.
// Public EmDash request-context API keeps its original updater on this same
// transaction; checking the actual runtime getter makes adapter drift fail closed.
export async function updateCampaignAtomically(
  emdash: App.Locals["emdash"],
  updater: Updater,
  collection: string,
  id: string,
  body: Parameters<Updater>[2],
  actor: { coreUserId: string; cmsUserId: string },
): Promise<Result> {
  return mutateCampaignAtomically(emdash, collection, id, actor, () =>
    updater(collection, id, body),
  );
}

export async function mutateCampaignAtomically(
  emdash: App.Locals["emdash"],
  collection: string,
  id: string,
  actor: { coreUserId: string; cmsUserId: string },
  mutate: () => Promise<Result>,
  effect: "new-draft" | "discard-draft" | "publish" = "new-draft",
): Promise<Result> {
  if (collection !== "campaign_pages" || !/^[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) {
    throw new Error("campaign_mutation_target_invalid");
  }
  const database = emdash.db;
  try {
    return await database.transaction().execute(async (transaction) => {
      await sql`SET LOCAL lock_timeout = '2s'`.execute(transaction);
      await sql`SET LOCAL statement_timeout = '3s'`.execute(transaction);
      const mapping =
        await sql`SELECT cms_user_id FROM public.leonaid_external_identity
        WHERE core_user_id=${actor.coreUserId} AND cms_user_id=${actor.cmsUserId}`.execute(
          transaction,
        );
      if (mapping.rows.length !== 1)
        throw new Error("campaign_actor_mapping_mismatch");
      const entry = await sql<{
        draft_revision_id: string | null;
        live_revision_id: string | null;
      }>`SELECT draft_revision_id, live_revision_id FROM public.ec_campaign_pages
        WHERE id=${id} AND deleted_at IS NULL FOR UPDATE`.execute(transaction);
      if (!entry.rows.length)
        throw new RejectedMutation({
          success: false,
          error: { code: "NOT_FOUND", message: "Content not found" },
        });
      for (const revisionId of new Set([
        entry.rows[0].draft_revision_id,
        entry.rows[0].live_revision_id,
      ])) {
        if (revisionId === null) continue;
        const linked = await sql`SELECT id FROM public.revisions
          WHERE id=${revisionId} AND collection='campaign_pages' AND entry_id=${id}
          FOR SHARE`.execute(transaction);
        if (linked.rows.length !== 1)
          throw new Error("campaign_revision_pointer_invalid");
      }
      const tasks = deferredTracker();
      return runWithContext(
        {
          ...getRequestContext(),
          editMode: false,
          db: transaction,
          deferredTasks: tasks,
        },
        async () => {
          if (emdash.db !== transaction)
            throw new Error("campaign_transaction_context_mismatch");
          try {
            // The updater checks _rev AFTER the row lock and uses this transaction
            // for revision insertion, pointer updates and schema validation.
            const result = await mutate();
            if (!result.success) throw new RejectedMutation(result);
            if (effect === "publish") {
              const published =
                await sql`SELECT id FROM public.ec_campaign_pages
                WHERE id=${id} AND status='published' AND draft_revision_id IS NULL
                AND live_revision_id IS NOT NULL AND deleted_at IS NULL`.execute(
                  transaction,
                );
              if (published.rows.length !== 1)
                throw new Error("campaign_publish_failed");
              return result;
            }
            if (effect === "discard-draft") {
              const cleared = await sql`SELECT id FROM public.ec_campaign_pages
                WHERE id=${id} AND draft_revision_id IS NULL AND deleted_at IS NULL`.execute(
                transaction,
              );
              if (cleared.rows.length !== 1)
                throw new Error("campaign_draft_discard_failed");
              return result;
            }
            // Attribute only the newly staged revision. Passing authorId to the
            // upstream updater would also change the content's author metadata.
            const attributed = await sql`UPDATE public.revisions AS revision
              SET author_id=${actor.cmsUserId}
              FROM public.ec_campaign_pages AS content
              WHERE content.id=${id} AND content.draft_revision_id=revision.id
                AND revision.collection='campaign_pages' AND revision.entry_id=content.id
                AND revision.id IS DISTINCT FROM ${entry.rows[0].draft_revision_id}
              RETURNING revision.id`.execute(transaction);
            if (attributed.rows.length !== 1)
              throw new Error("campaign_revision_attribution_failed");
            return result;
          } finally {
            // Upstream after() work must not retain a completed transaction.
            tasks.settle();
            await tasks.settled;
          }
        },
      );
    });
  } catch (error) {
    if (error instanceof RejectedMutation) return error.result;
    throw error; // The HTTP boundary returns a sanitized unavailable response.
  }
}
