/*
 * The CRM check of a sponsor draft (specs/pwa-offline-queue §10.4, review
 * #132 N1). Core replays a resolve only for the same command id and the
 * exact same body; a new preview after a committed resolve finds the new
 * sponsor and builds a different body (idempotency_conflict). So the draft
 * keeps the body it sent before sending and Core's answer once it has it:
 * a check after a lost answer, a closed tab or a missing revision replays
 * that body or uses that answer, and the sponsor is created once.
 */
import {
  ApiError,
  type LeonAidApiClient,
  type ResolveSponsorMatchRequest,
  type SponsorResolutionResponse,
} from "@leonaid/api-client";

import type { QueueController } from "./controller";
import type { SponsorDraftEntry } from "./queue";

export type DraftCheck =
  /** Core resolved the draft (now or before). */
  | {
      readonly state: "resolved";
      readonly resolution: SponsorResolutionResponse;
    }
  /** Nothing of an earlier check is kept at Core: a normal check follows. */
  | { readonly state: "check"; readonly commandId: string }
  /** The earlier check may still be under way or unanswered: try again. */
  | { readonly state: "unknown"; readonly error: unknown };

/**
 * Whether Core certainly kept nothing under the request: a refusal, not a
 * lost answer, a session or rights problem, an overload or a check that
 * Core is still finishing. idempotency_conflict counts as kept nothing for
 * this body: the key then holds another body, and the next check's preview
 * finds what that one created.
 */
export function resolveKeptNothing(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.detail.code === "idempotency_incomplete") return false;
  return (
    error.status >= 400 &&
    error.status < 500 &&
    ![401, 403, 408, 429].includes(error.status)
  );
}

/** Sends a draft's resolve: the body is kept first, Core's answer after. */
export async function resolveDraftSponsor(
  client: LeonAidApiClient,
  queue: QueueController,
  actionId: string,
  draftId: string,
  request: ResolveSponsorMatchRequest,
): Promise<SponsorResolutionResponse> {
  await queue.updateDraft(draftId, { resolveRequest: request });
  let resolution: SponsorResolutionResponse;
  try {
    resolution = await client.resolveSponsorMatch(actionId, request);
  } catch (error) {
    // Refused: the next check starts fresh under a new command id.
    if (resolveKeptNothing(error)) {
      await queue.updateDraft(draftId, {
        commandId: crypto.randomUUID(),
        resolveRequest: null,
      });
    }
    throw error;
  }
  await queue.updateDraft(draftId, { resolution });
  return resolution;
}

/** What an earlier check of this draft left, before a new one starts. */
export async function resumeDraftCheck(
  client: LeonAidApiClient,
  queue: QueueController,
  actionId: string,
  draft: SponsorDraftEntry,
): Promise<DraftCheck> {
  if (draft.resolution) {
    return { resolution: draft.resolution, state: "resolved" };
  }
  if (!draft.resolveRequest) {
    return { commandId: draft.commandId, state: "check" };
  }
  try {
    // The exact body again: Core replays its answer, or runs it now.
    const resolution = await client.resolveSponsorMatch(
      actionId,
      draft.resolveRequest,
    );
    await queue.updateDraft(draft.entryId, { resolution });
    return { resolution, state: "resolved" };
  } catch (error) {
    if (!resolveKeptNothing(error)) return { error, state: "unknown" };
    const commandId = crypto.randomUUID();
    await queue.updateDraft(draft.entryId, { commandId, resolveRequest: null });
    return { commandId, state: "check" };
  }
}
