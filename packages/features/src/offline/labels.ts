/*
 * Words and shapes of the capture queue (specs/pwa-offline-queue §12.3):
 * a state is always text plus shape, never colour alone.
 */
import type { StatusShape } from "@leonaid/ui";

import { deliveryTarget, type QueueEntry, type QueueState } from "./queue";

const targetWord = {
  delivered: "zugestellt",
  missed: "nicht angetroffen",
  open: "wieder offen",
} as const;

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
    case "delivery-state":
      return `Zustellung ${entry.party.displayName}: ${targetWord[deliveryTarget(entry.request)]}`;
    case "tour-order":
      return `Tour-Reihenfolge ${entry.party.displayName}`;
  }
}

/** The state in words; a capture waiting for its sponsor draft says so. */
export function entryStateLabel(entry: QueueEntry): string {
  if (entry.kind === "sponsor-draft" && entry.state === "queued") {
    return "Wartet auf deine Prüfung";
  }
  if (entry.dependsOn && entry.state === "queued") {
    return "Wartet auf den Entwurf";
  }
  return queueStateLabel[entry.state];
}
