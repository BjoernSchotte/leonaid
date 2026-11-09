import type {
  DeliveryBoardWindowResponse,
  DeliveryDropResponse,
} from "@leonaid/api-client";

/*
 * Formatting shared by the delivery board, the tour planner and "Meine
 * Tour". Times are shown in the action's zone.
 */

/** How often the managers' board and tour planner reload (drivers tick in the PWA). */
export const BOARD_POLL_MS = 20_000;

export const weekday = (iso: string, zone: string) =>
  new Intl.DateTimeFormat("de-DE", { weekday: "short", timeZone: zone })
    .format(new Date(iso))
    .replace(".", "");

/** "07" on the full hour, else "07:30". */
export const clock = (iso: string, zone: string) => {
  const value = clockMinutes(iso, zone);
  return value.endsWith(":00") ? value.slice(0, 2) : value;
};

/** "08:12". */
export const clockMinutes = (iso: string, zone: string) =>
  new Intl.DateTimeFormat("de-DE", {
    hour: "2-digit",
    hourCycle: "h23",
    minute: "2-digit",
    timeZone: zone,
  }).format(new Date(iso));

export const dayMonth = (iso: string, zone: string) =>
  new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    timeZone: zone,
  }).format(new Date(iso));

/** "07–09" (window times in the action's zone). */
export function deliveryTimeRange(
  window: Pick<DeliveryBoardWindowResponse, "startsAt" | "endsAt">,
  zone: string,
) {
  return `${clock(window.startsAt, zone)}–${clock(window.endsAt, zone)}`;
}

/** "Mittwoch, 11. November" for an ISO day. */
export function longDay(day: string) {
  return new Intl.DateTimeFormat("de-DE", {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
    weekday: "long",
  }).format(new Date(`${day}T12:00:00Z`));
}

/** "Lieferweg 2, 86150 Augsburg", or null without an address. */
export function dropAddress(drop: DeliveryDropResponse) {
  const address = drop.address;
  if (!address) return null;
  return `${address.streetLine1}, ${address.postalCode} ${address.city}`;
}
