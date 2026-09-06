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
): Promise<Result> {
  if (collection !== "campaign_pages" || !/^[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) {
    throw new Error("campaign_mutation_target_invalid");
  }
  const database = emdash.db;
  try {
    return await database.transaction().execute(async (transaction) => {
      await sql`SET LOCAL lock_timeout = '2s'`.execute(transaction);
      await sql`SET LOCAL statement_timeout = '3s'`.execute(transaction);
      const entry = await sql`SELECT id FROM public.ec_campaign_pages
        WHERE id=${id} AND deleted_at IS NULL FOR UPDATE`.execute(transaction);
      if (!entry.rows.length)
        throw new RejectedMutation({
          success: false,
          error: { code: "NOT_FOUND", message: "Content not found" },
        });
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
            const result = await updater(collection, id, body);
            if (!result.success) throw new RejectedMutation(result);
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
