/** Berlin-time date helpers shared by the back-office screens (prototype shortDate/relativeDay). */

/** The club's time zone: one club per installation, in Germany. */
export const TIME_ZONE = "Europe/Berlin";

export function formatDate(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeZone: TIME_ZONE,
  }).format(new Date(value));
}

export function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: TIME_ZONE,
  }).format(new Date(value));
}

/** Today in Berlin as an ISO day (YYYY-MM-DD). */
export function localIsoDate(now: Date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    day: "2-digit",
    month: "2-digit",
    timeZone: TIME_ZONE,
    year: "numeric",
  }).format(now);
}

/** The Berlin ISO day of a timestamp, or the day itself for an ISO day. */
export function isoDay(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
    ? value
    : localIsoDate(new Date(value));
}

/** "03.11." in the current year, "03.11.2025" otherwise (prototype shortDate). */
export function shortDate(value: string, today: string = localIsoDate()) {
  const [year, month, day] = isoDay(value).split("-");
  return year === today.slice(0, 4)
    ? `${day}.${month}.`
    : `${day}.${month}.${year}`;
}

/** "Heute", "Morgen", "vor 3 Tagen", or the short date (prototype relativeDay). */
export function relativeDay(value: string, today: string = localIsoDate()) {
  const diff = Math.round(
    (Date.parse(isoDay(value)) - Date.parse(today)) / 86_400_000,
  );
  if (diff === 0) return "Heute";
  if (diff === 1) return "Morgen";
  if (diff === -1) return "Gestern";
  if (diff > 1 && diff < 7) return `in ${diff} Tagen`;
  if (diff < -1 && diff > -7) return `vor ${-diff} Tagen`;
  return shortDate(value, today);
}
