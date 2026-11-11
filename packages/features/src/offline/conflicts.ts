/*
 * What the acquirer reads when Core refused a queued capture
 * (specs/pwa-offline-queue §10), in "Du". Stage 4 adds the choices.
 */
import type { DeliveryStateEntry, QueueEntry, TourOrderEntry } from "./queue";

/** Core's answer to a driver's mark or order, in the driver's words (§9). */
export const TOUR_CONFLICT_TITLE = {
  changed: "Vom Planer geändert",
  closed: "Fenster geschlossen",
} as const;

function tourConflictText(entry: DeliveryStateEntry | TourOrderEntry): string {
  const code = entry.lastError?.code ?? "";
  const stop = entry.kind === "delivery-state";
  switch (code) {
    case "delivery_state_conflict":
    case "tour_revision_conflict":
    case "tour_order_stale":
      return stop
        ? `${TOUR_CONFLICT_TITLE.changed}. ${entry.party.displayName} wurde inzwischen geändert; deine Eintragung wurde nicht übernommen. „Meine Tour“ zeigt den aktuellen Stand.`
        : `${TOUR_CONFLICT_TITLE.changed}. Die Tour wurde inzwischen geändert; deine Reihenfolge wurde nicht übernommen. Es gilt die Reihenfolge der Planung.`;
    case "delivery_window_closed":
      return `${TOUR_CONFLICT_TITLE.closed}. Die Aktionsleitung hat das Lieferfenster abgeschlossen; deine ${stop ? "Eintragung" : "Reihenfolge"} wurde nicht übernommen. Wende dich an die Aktionsleitung.`;
    case "delivery_not_assigned":
      return `${entry.party.displayName} ist dir nicht mehr zugewiesen. Die Eintragung wurde nicht übernommen.`;
    case "delivery_order_not_deliverable":
      return "Diese Bestellung wird nicht (mehr) ausgeliefert.";
    case "sponsor_not_assigned":
      // 404: no delivery planning (or no tours) in this action any more.
      return "Für diese Aktion gibt es keine Tour mehr. Der Eintrag kann nicht gesendet werden.";
    default:
      return (
        entry.lastError?.message || "LeonAid konnte den Eintrag nicht senden."
      );
  }
}

function money(amountMinor: number, currency = "EUR") {
  return new Intl.NumberFormat("de-DE", { currency, style: "currency" }).format(
    amountMinor / 100,
  );
}

function shortDate(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "Europe/Berlin",
  }).format(new Date(value));
}

interface PriceDetails {
  readonly lines?: ReadonlyArray<{
    readonly quotedUnitPriceMinor?: number;
    readonly unitPriceMinor?: number;
  }>;
  readonly totalMinor?: number;
  readonly currency?: string;
}

const statusLabel = {
  committed: "Zugesagt",
  contacted: "Kontaktiert",
  declined: "Abgesagt",
} as const;

export function conflictText(entry: QueueEntry, actionName: string): string {
  const sponsor = entry.party.displayName;
  if (entry.state === "expired") {
    return "Der Eintrag ist älter als 14 Tage und wird nicht mehr gesendet. In zwei Tagen löscht LeonAid ihn von diesem Gerät.";
  }
  if (entry.state === "blocked") {
    return `Du kannst für ${actionName || "diese Aktion"} keine Einträge mehr senden. Der Eintrag bleibt auf diesem Gerät, bis du ihn verwirfst oder die Berechtigung zurück ist und du ihn erneut versuchst.`;
  }
  const code = entry.lastError?.code ?? "";
  if (entry.state === "failed") {
    if (entry.kind === "delivery-state" || entry.kind === "tour-order") {
      return "Der Eintrag konnte mehrmals nicht gesendet werden. Versuche es erneut oder verwirf ihn.";
    }
    return code === "idempotency_conflict"
      ? `Dieser Eintrag passt nicht zu dem, was LeonAid unter seinem Schlüssel schon gespeichert hat. Er wird nicht erneut gesendet. Supportcode: ${entry.idempotencyKey}`
      : "Der Eintrag konnte mehrmals nicht gesendet werden. Versuche es erneut oder verwirf ihn.";
  }
  if (entry.kind === "delivery-state" || entry.kind === "tour-order") {
    return tourConflictText(entry);
  }
  switch (code) {
    case "follow_up_not_applied": {
      const current = entry.conflictAssignment;
      const theirs = [
        current?.nextAction,
        current?.dueAt ? shortDate(current.dueAt) : null,
      ]
        .filter(Boolean)
        .join(", ");
      return `Dein Kontakt mit ${sponsor} ist gespeichert. Die Wiedervorlage wurde nicht übernommen, weil inzwischen jemand anderes etwas eingetragen hat${theirs ? `: ${theirs}` : ""}.`;
    }
    case "status_not_applied": {
      const status =
        entry.kind === "activity"
          ? statusLabel[
              entry.request.outcome === "committed"
                ? "committed"
                : entry.request.outcome === "declined"
                  ? "declined"
                  : "contacted"
            ]
          : "";
      return `Dein Kontakt mit ${sponsor} ist gespeichert. Der Status „${status}“ wurde nicht übernommen, weil inzwischen jemand anderes etwas eingetragen hat.`;
    }
    case "commitment_owner_required":
    case "commitment_source_forbidden":
      return `Diese Bestellung für ${sponsor} darfst du so nicht mehr senden.`;
    case "assignment_revision_conflict":
      return `${sponsor} wurde inzwischen geändert. Der Eintrag wurde nicht gespeichert.`;
    case "contact_suppressed":
      return `${sponsor} möchte auf diesem Weg nicht kontaktiert werden. Der Kontakt wurde nicht gespeichert.`;
    case "sponsor_not_assigned":
      return `${sponsor} ist dir nicht mehr zugeordnet. Der Eintrag kann nicht gesendet werden.`;
    case "delivery_window_full":
      return "Das gewählte Lieferfenster ist inzwischen ausgebucht.";
    case "delivery_window_unavailable":
      return "Das gewählte Lieferfenster gibt es nicht mehr.";
    case "commitment_price_changed": {
      const details = (entry.lastError?.details ?? {}) as PriceDetails;
      const lines = details.lines ?? [];
      // Several lines: the new total says it all (#132 L7).
      if (lines.length > 1 && details.totalMinor !== undefined) {
        return `Die Preise haben sich geändert. Die Bestellung kostet jetzt ${money(details.totalMinor, details.currency)}.`;
      }
      const line = lines[0];
      if (
        line?.unitPriceMinor !== undefined &&
        details.totalMinor !== undefined
      ) {
        return `Der Preis ist jetzt ${money(line.unitPriceMinor, details.currency)} statt ${money(line.quotedUnitPriceMinor ?? entry.base.unitPriceMinor ?? 0, details.currency)}. Die Bestellung kostet ${money(details.totalMinor, details.currency)}.`;
      }
      return "Der Preis hat sich geändert.";
    }
    case "offering_not_available":
      return "Das Angebot ist nicht mehr bestellbar.";
    case "commitment_ordering_disabled":
    case "commitment_action_closed":
      return `Für ${actionName || "diese Aktion"} nimmt der Club keine Bestellungen mehr an.`;
    case "delivery_required":
    case "delivery_address_required":
    case "delivery_window_required":
      return "Für diese Aktion braucht eine Bestellung jetzt eine Lieferadresse und ein Lieferfenster.";
    case "commitment_donation_not_offered":
      return `${actionName || "Diese Aktion"} bietet keine Zusatzspende mehr an. Verwirf den Eintrag und erfasse die Bestellung ohne Zusatzspende neu.`;
    case "commitment_donation_amount_invalid":
      return "Die Zusatzspende muss zwischen 1,00 € und 10.000,00 € liegen. Verwirf den Eintrag und erfasse die Bestellung neu.";
    case "commitment_donation_recipient_required":
      return "Eine Bestellung mit Zusatzspende braucht einen vollständigen Rechnungsempfänger, denn er ist der Spender. Verwirf den Eintrag und erfasse die Bestellung mit Rechnungsanschrift neu.";
    case "captured_at_out_of_range":
      return "Die Uhrzeit deines Geräts stimmt nicht. Prüfe Datum und Uhrzeit.";
    default:
      return (
        entry.lastError?.message || "LeonAid konnte den Eintrag nicht senden."
      );
  }
}
