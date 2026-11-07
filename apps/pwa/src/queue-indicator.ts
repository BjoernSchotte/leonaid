/*
 * The queue indicator and banner copy of specs/pwa-offline-queue §12.1 and
 * §12.2, derived from the queue's snapshot.
 */
import type { QueueSnapshot } from "@leonaid/features/offline";

export interface QueueIndicator {
  readonly count: number;
  readonly state: "empty" | "waiting" | "sending" | "decision" | "failed";
  readonly label: string;
  /** Entries still waiting to be sent (banner "N warten auf Versand"). */
  readonly waiting: number;
}

function entries(count: number) {
  return count === 1 ? "1 Eintrag" : `${count} Einträge`;
}

export function queueIndicator(snapshot: QueueSnapshot): QueueIndicator {
  const sendable = snapshot.entries.filter(
    (entry) => entry.kind !== "sponsor-draft",
  );
  const count = (states: readonly string[]) =>
    sendable.filter((entry) => states.includes(entry.state)).length;
  const waiting = count(["queued", "sending"]);
  const failed = count(["failed"]);
  // A sponsor draft needs the acquirer's check (§10.4), whatever its state.
  const decision =
    count(["conflict", "blocked", "expired"]) +
    snapshot.entries.length -
    sendable.length;
  if (failed) {
    return {
      count: failed,
      label: `${entries(failed)} konnte${failed === 1 ? "" : "n"} nicht gesendet werden`,
      state: "failed",
      waiting,
    };
  }
  if (decision) {
    return {
      count: decision,
      label: `${entries(decision)} ${decision === 1 ? "braucht" : "brauchen"} deine Entscheidung`,
      state: "decision",
      waiting,
    };
  }
  if (waiting && snapshot.sending) {
    return {
      count: waiting,
      label: "Einträge werden gesendet",
      state: "sending",
      waiting,
    };
  }
  if (waiting) {
    return {
      count: waiting,
      label: `${entries(waiting)} ${waiting === 1 ? "wartet" : "warten"} auf Versand`,
      state: "waiting",
      waiting,
    };
  }
  return { count: 0, label: "", state: "empty", waiting: 0 };
}

export const QUEUE_OFFLINE_TEXT =
  "Du bist offline. Neue Kontakte, Wiedervorlagen und Bestellungen speichert LeonAid auf diesem Gerät und sendet sie, sobald du wieder online bist.";
