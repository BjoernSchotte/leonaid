import { getRequestContext, runWithContext } from "emdash/request-context";
import { createCampaignContent } from "./campaign-create.mjs";
import { deferredTracker } from "./campaign-mutation";
import {
  readCoreIdentity,
  requireCoreCampaign,
  requireCurrentCampaignActor,
  CoreIdentityError,
} from "./core-identity";

type Creator = App.Locals["emdash"]["handleContentCreate"];

// The caller captures the original request-local runtime method before wrapping
// it. Do not call the lower-level creator from the production HTTP integration.
export async function createCampaignWithRuntime(
  request: Request,
  emdash: App.Locals["emdash"],
  creator: Creator,
  cmsUserId: string,
  body: { data: Record<string, unknown> },
) {
  const profile = await readCoreIdentity(request);
  if (![40, 50].includes(profile.role)) throw new CoreIdentityError(403);
  const actionId = body.data?.action_id;
  if (typeof actionId !== "string") throw new CoreIdentityError(403);
  if (
    profile.role === 40 &&
    !profile.actionMemberships.some(
      (membership) =>
        membership.role === "charity_admin" && membership.actionId === actionId,
    )
  )
    throw new CoreIdentityError(403);
  const action = await requireCoreCampaign(request, actionId);
  return createCampaignContent(
    emdash.db,
    profile,
    action,
    cmsUserId,
    body,
    async (transaction, collection, normalized) => {
      const tasks = deferredTracker();
      return runWithContext(
        {
          ...getRequestContext(),
          editMode: false,
          db: transaction,
          deferredTasks: tasks,
        },
        async () => {
          if (emdash.db !== transaction) throw new CoreIdentityError(503);
          try {
            // Recheck current Core access after the serialization lock, immediately
            // before the original creator performs schema validation and writes.
            await requireCurrentCampaignActor(
              request,
              {
                coreUserId: profile.userId,
                coreRole: profile.role,
              },
              actionId,
            );
            return await creator(collection, normalized);
          } finally {
            tasks.settle();
            await tasks.settled;
          }
        },
      );
    },
  );
}
