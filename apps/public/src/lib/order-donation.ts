// Optional extra donation of a public order. Shared by the server action
// (authoritative) and the browser enhancement (live feedback).
export const DONATION_MIN_MINOR = 100;
export const DONATION_MAX_MINOR = 1_000_000;

export const DONATION_INVALID_MESSAGE =
  "Bitte geben Sie einen Betrag zwischen 1,00 € und 10.000,00 € ein oder lassen Sie das Feld leer.";

export const DONATION_SUCCESS_NOTE =
  "Ihre Spendenzusage erhalten Sie in einer eigenen E-Mail.";

/** Native check for browsers without script; the range is checked on submit. */
export const DONATION_INPUT_PATTERN =
  "\\s*(\\d{1,3}(\\.\\d{3})+|\\d+)([.,]\\d{1,2})?\\s*€?\\s*";

export type DonationAmount =
  | { readonly kind: "empty" }
  | { readonly kind: "invalid" }
  | { readonly kind: "amount"; readonly minor: number };

const grouped = /^\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?$/;
const plain = /^\d+(?:[.,]\d{1,2})?$/;

/**
 * Reads a euro amount as typed: "5", "5,5", "5,50", "5.50", "1.000",
 * "10.000,00", with or without "€". Empty means no donation.
 */
export function parseDonationAmount(
  raw: string | null | undefined,
): DonationAmount {
  const text = (raw ?? "").trim().replace(/\s*€$/, "");
  if (!text) return { kind: "empty" };
  let normalised: string;
  if (grouped.test(text))
    normalised = text.replaceAll(".", "").replace(",", ".");
  else if (plain.test(text)) normalised = text.replace(",", ".");
  else return { kind: "invalid" };
  const [euros, cents = ""] = normalised.split(".");
  if (euros.length > 7) return { kind: "invalid" };
  const minor = Number(euros) * 100 + Number(cents.padEnd(2, "0"));
  return minor >= DONATION_MIN_MINOR && minor <= DONATION_MAX_MINOR
    ? { kind: "amount", minor }
    : { kind: "invalid" };
}
