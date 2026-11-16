// The order deadline of a public action: the latest end of the offerings'
// order periods (E-068). Null while any offering is open-ended, since the
// form then keeps taking orders.

export interface DeadlineOffering {
  readonly availableUntil?: string | null;
}

export function orderDeadline(
  offerings: readonly DeadlineOffering[],
): string | null {
  if (!offerings.length) return null;
  let latest: number | null = null;
  for (const offering of offerings) {
    if (!offering.availableUntil) return null;
    const instant = Date.parse(offering.availableUntil);
    if (Number.isNaN(instant)) return null;
    latest = latest === null ? instant : Math.max(latest, instant);
  }
  return latest === null ? null : new Date(latest).toISOString();
}

/** In the action's delivery time zone; the installation's without one. */
export function deadlineLabel(iso: string, timeZone = "Europe/Berlin"): string {
  const format = new Intl.DateTimeFormat("de-DE", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  });
  return `${format.format(new Date(iso))} Uhr`;
}

/** "noch 78 Tage", "noch 5 Stunden", "noch 12 Minuten"; null when past. */
export function remainingLabel(iso: string, now: number): string | null {
  const left = Date.parse(iso) - now;
  if (!(left > 0)) return null;
  const minutes = Math.ceil(left / 60_000);
  if (minutes < 120)
    return minutes === 1 ? "noch 1 Minute" : `noch ${minutes} Minuten`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `noch ${hours} Stunden`;
  return `noch ${Math.floor(hours / 24)} Tage`;
}

export interface FactWindow {
  readonly deliveryOn: string;
  readonly startsAt: string;
  readonly endsAt: string;
}

const dayFormat = new Intl.DateTimeFormat("de-DE", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

const clock = (value: string) => {
  const [hours = "0", minutes = "00"] = value.split(":");
  return minutes === "00"
    ? String(Number(hours))
    : `${Number(hours)}:${minutes}`;
};

/**
 * The delivery days of the open windows, each with its earliest start and
 * latest end in the action's local time ("Mittwoch, 3. Februar 2027,
 * 7–13 Uhr"). Empty without windows.
 */
export function deliveryDays(windows: readonly FactWindow[]): string[] {
  const days = new Map<string, { start: string; end: string }>();
  for (const window of windows) {
    const day = days.get(window.deliveryOn);
    days.set(window.deliveryOn, {
      start: !day || window.startsAt < day.start ? window.startsAt : day.start,
      end: !day || window.endsAt > day.end ? window.endsAt : day.end,
    });
  }
  return [...days.entries()]
    .sort(([first], [second]) => first.localeCompare(second))
    .map(
      ([day, { start, end }]) =>
        `${dayFormat.format(new Date(`${day}T00:00:00Z`))}, ${clock(start)}–${clock(end)} Uhr`,
    );
}
