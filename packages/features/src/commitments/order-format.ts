import type {
  CommitmentRecordResponse,
  CommitmentResponse,
  DeliveryConfigurationResponse,
} from "@leonaid/api-client";

import { deliveryDetailsMissing } from "./delivery-completion";

/* Formatting shared by the orders list, its pane and the bulk release. */

export type OrderStatus = CommitmentResponse["status"];
export type OrderRow = CommitmentRecordResponse;

export const statusLabels: Readonly<Record<OrderStatus, string>> = {
  cancelled: "Storniert",
  confirmed: "Bestätigt",
  draft: "Entwurf",
  invoiced: "Fakturiert",
  review_ready: "Prüfbereit",
};

export const sourceLabels = {
  acquisition: "Akquise",
  admin: "Verwaltung",
  public_form: "Öffentliches Formular",
} as const;

export const NO_WINDOW = "none";
export const NO_CAPTURER = "none";

export const euro = (amountMinor: number, currency: string) =>
  new Intl.NumberFormat("de-DE", { currency, style: "currency" }).format(
    amountMinor / 100,
  );

export const berlinDate = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeZone: "Europe/Berlin",
});
export const berlinDateTime = new Intl.DateTimeFormat("de-DE", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Europe/Berlin",
});
export const shortDay = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  timeZone: "Europe/Berlin",
});

export function lineLabel(commitment: CommitmentResponse) {
  return commitment.lines
    .map((line) => `${line.quantity} × ${line.description}`)
    .join(", ");
}

/** Draft or review-ready orders that still lack invoice or delivery data. */
export function detailsMissing(
  commitment: CommitmentResponse,
  deliveryOn: boolean,
) {
  const editable =
    commitment.status === "draft" || commitment.status === "review_ready";
  return (
    editable &&
    (!commitment.invoiceRecipient ||
      deliveryDetailsMissing(commitment, deliveryOn))
  );
}

/** "08" for a full hour, "08:30" otherwise (prototype: "07–09 Uhr"). */
export function clock(value: string) {
  const time = value.slice(0, 5);
  return time.endsWith(":00") ? time.slice(0, 2) : time;
}

export function weekdayDay(isoDay: string) {
  const date = new Date(`${isoDay}T12:00:00Z`);
  const weekday = new Intl.DateTimeFormat("de-DE", {
    weekday: "short",
    timeZone: "UTC",
  })
    .format(date)
    .replace(".", "");
  return `${weekday} ${isoDay.slice(8, 10)}.${isoDay.slice(5, 7)}.`;
}

export function configuredWindowLabel(
  window: DeliveryConfigurationResponse["windows"][number],
) {
  return `${weekdayDay(window.deliveryOn)} · ${clock(window.startsAt)}–${clock(window.endsAt)} Uhr`;
}

/** Label from an order's stored window snapshot (the window may be gone). */
export function snapshotWindowLabel(snapshot: Record<string, string>) {
  const zone = snapshot.timezone ?? "Europe/Berlin";
  const start = new Date(snapshot.startsAt ?? "");
  const end = new Date(snapshot.endsAt ?? "");
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()))
    return "Lieferfenster";
  const part = (date: Date, options: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat("de-DE", { ...options, timeZone: zone }).format(
      date,
    );
  const day = part(start, { year: "numeric", month: "2-digit", day: "2-digit" })
    .split(".")
    .reverse()
    .join("-");
  const time = (date: Date) =>
    clock(part(date, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }));
  return `${weekdayDay(day)} · ${time(start)}–${time(end)} Uhr`;
}
