/*
 * Carries out an acquirer's choice of §10 against the queue (and, for
 * "Meine Wiedervorlage übernehmen", against Core as a normal online
 * update on the current revision, §11.4).
 */
import {
  ApiError,
  type AcquisitionAssignmentResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";

import type { QueueController } from "./controller";
import type { QueueEntry } from "./queue";
import { outcomeStatus } from "./sync";
import {
  acceptPrice,
  asDraft,
  asVisit,
  bookAnyway,
  type Resolution,
} from "./resolutions";

export class ResolutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ResolutionError";
  }
}

/** 09:00 of the follow-up day in the device's zone, as Core's `dueAt`. */
export function followUpDueAt(dueOn: string): string {
  const [year, month, day] = dueOn.split("-").map(Number);
  const local = new Date(year!, month! - 1, day!, 9, 0, 0, 0);
  const offset = -local.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const hours = String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0");
  const minutes = String(Math.abs(offset) % 60).padStart(2, "0");
  return `${dueOn}T09:00:00${sign}${hours}:${minutes}`;
}

/**
 * "Meine Wiedervorlage übernehmen" / "Meinen Stand übernehmen": a normal
 * online update on Core's current revision (§11.4). If the assignment
 * moved again meanwhile, the decision shows Core's newest state.
 */
export async function keepMine(
  client: LeonAidApiClient,
  queue: QueueController,
  entry: QueueEntry,
): Promise<AcquisitionAssignmentResponse> {
  if (entry.kind !== "activity" || !entry.conflictAssignment) {
    throw new ResolutionError("Dieser Stand kann nicht übernommen werden.");
  }
  const current = entry.conflictAssignment;
  if (current.status === "handed_over") {
    throw new ResolutionError("Der Sponsor wurde übergeben.");
  }
  const { dueOn, nextAction, outcome } = entry.request;
  try {
    const updated = await client.updateAcquisitionAssignment(
      entry.actionId,
      entry.assignmentId,
      {
        dueAt: dueOn ? followUpDueAt(dueOn) : current.dueAt,
        nextAction: nextAction ?? current.nextAction,
        priority: current.priority,
        revision: current.revision,
        status: outcomeStatus(outcome),
      },
    );
    await queue.discard(entry.entryId);
    return updated;
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.detail.code === "assignment_revision_conflict"
    ) {
      const board = await client
        .getAcquisitionActivityBoard(entry.actionId, { limit: 100 })
        .catch(() => null);
      const item = board?.workItems.find(
        (work) => work.assignmentId === entry.assignmentId,
      );
      if (item) {
        await queue.annotate(entry.entryId, {
          conflictAssignment: {
            dueAt: item.dueAt,
            nextAction: item.nextAction,
            priority: item.priority,
            revision: item.revision,
            status: item.status,
          },
        });
      }
    }
    throw error;
  }
}

/**
 * The choices that only change the entry. Returns false when the choice
 * needs more input (a window, an address) or Core's help.
 */
export async function applySimpleResolution(
  queue: QueueController,
  entry: QueueEntry,
  resolution: Resolution,
): Promise<boolean> {
  switch (resolution) {
    case "discard":
    case "discard-follow-up":
    case "discard-status":
      await queue.discard(entry.entryId);
      return true;
    case "as-visit":
      if (entry.kind !== "activity") return false;
      await queue.replace(entry.entryId, () => asVisit(entry), {
        newKey: true,
      });
      return true;
    case "book-anyway":
      if (entry.kind !== "commitment") return false;
      // allowFullWindow is not part of Core's hash: the key stays.
      await queue.replace(entry.entryId, () => bookAnyway(entry), {
        newKey: false,
      });
      return true;
    case "as-draft":
      if (entry.kind !== "commitment") return false;
      await queue.replace(entry.entryId, () => asDraft(entry), {
        newKey: true,
      });
      return true;
    case "accept-price": {
      if (entry.kind !== "commitment") return false;
      const changed = acceptPrice(entry);
      if (!changed) return false;
      await queue.replace(entry.entryId, () => changed, { newKey: true });
      return true;
    }
    default:
      return false;
  }
}
