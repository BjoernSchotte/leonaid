/*
 * Words and shapes of the capture queue (specs/pwa-offline-queue §12.3):
 * a state is always text plus shape, never colour alone.
 */
import type { StatusShape } from "@leonaid/ui";

import type { QueueEntry, QueueState } from "./queue";

export const queueStateLabel: Readonly<Record<QueueState, string>> = {
  queued: "Wartet auf Verbindung",
  sending: "Wird gesendet …",
  conflict: "Braucht deine Entscheidung",
  failed: "Konnte nicht gesendet werden",
  expired: "Abgelaufen",
  blocked: "Nicht mehr möglich",
};

export const queueStateShape: Readonly<Record<QueueState, StatusShape>> = {
  queued: "draft",
  sending: "progress",
  conflict: "alert",
  failed: "cancelled",
  expired: "cancelled",
  blocked: "cancelled",
};

export function entryTitle(entry: QueueEntry): string {
  switch (entry.kind) {
    case "activity":
      return `Kontakt mit ${entry.party.displayName}`;
    case "commitment":
      return `Bestellung für ${entry.party.displayName}`;
    case "commitment-completion":
      return `Bestellung für ${entry.party.displayName} vervollständigen`;
    case "sponsor-draft":
      return `Neuer Sponsor ${entry.party.displayName}`;
  }
}
