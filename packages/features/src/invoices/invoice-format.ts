/** Formatting and parsing helpers of the invoice screens (German, Berlin time). */

export {
  formatDate,
  formatDateTime,
  isoDay,
  localIsoDate,
  relativeDay,
  shortDate,
} from "../shared/dates";

export function formatMoney(amountMinor: number, currency: string) {
  return new Intl.NumberFormat("de-DE", {
    currency,
    style: "currency",
  }).format(amountMinor / 100);
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

/** "360,00": an amount in the German format the amount fields accept. */
export function amountInput(minor: number) {
  return new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

/** An IBAN in groups of four. */
export function formatIban(iban: string) {
  return iban.match(/.{1,4}/g)?.join(" ") ?? iban;
}
