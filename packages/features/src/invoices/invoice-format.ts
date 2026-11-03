/** Formatting and parsing helpers of the invoice screens (German, Berlin time). */

const TIME_ZONE = "Europe/Berlin";

export function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
}

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

export function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"] as const;
  let value = bytes / 1024;
  let unit: (typeof units)[number] = units[0];
  for (const candidate of units.slice(1)) {
    if (value < 1024) break;
    value /= 1024;
    unit = candidate;
  }
  return `${new Intl.NumberFormat("de-DE", {
    maximumFractionDigits: value < 10 ? 1 : 0,
  }).format(value)} ${unit}`;
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

/**
 * Parses an amount typed in German ("1.234,50", "144,00 €") or with a
 * decimal point ("359.99") into minor units. Null when it is not an amount.
 */
export function parseAmountMinor(value: string): number | null {
  const compact = value.replace(/[\s €]/g, "");
  if (!compact) return null;
  let normalised: string;
  if (compact.includes(",")) {
    // German: dots group thousands, the comma is the decimal mark.
    if (!/^\d{1,3}(\.\d{3})*(,\d{1,2})?$|^\d+(,\d{1,2})?$/.test(compact)) {
      return null;
    }
    normalised = compact.replace(/\./g, "").replace(",", ".");
  } else if (/^\d+\.\d{1,2}$/.test(compact)) {
    normalised = compact;
  } else if (/^\d{1,3}(\.\d{3})+$|^\d+$/.test(compact)) {
    normalised = compact.replace(/\./g, "");
  } else {
    return null;
  }
  const minor = Math.round(Number(normalised) * 100);
  return Number.isSafeInteger(minor) ? minor : null;
}

/** An IBAN in groups of four. */
export function formatIban(iban: string) {
  return iban.match(/.{1,4}/g)?.join(" ") ?? iban;
}
