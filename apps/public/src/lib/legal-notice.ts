import {
  LeonAidApiClient,
  type PublicLegalProviderResponse,
} from "@leonaid/api-client";

/**
 * The installation's Impressum provider (active legal configuration), read
 * server side for the footer of every public page and for /impressum.
 * One club per installation, so a short in-process cache spares Core a
 * request per page view (only a known provider is cached). A failed read
 * keeps the last known value.
 */
const freshMilliseconds = 60_000;
const retryMilliseconds = 10_000;
const timeoutMilliseconds = 2_000;

let cached: {
  provider: PublicLegalProviderResponse | null;
  until: number;
} | null = null;

export type LegalNoticeResult =
  | {
      readonly state: "ready";
      readonly provider: PublicLegalProviderResponse | null;
    }
  | { readonly state: "unavailable" };

export async function readLegalNotice(
  now: number = Date.now(),
): Promise<LegalNoticeResult> {
  if (cached && cached.until > now) {
    return { state: "ready", provider: cached.provider };
  }
  try {
    const baseUrl = process.env.CORE_API_URL?.trim() || "http://api:8000";
    const notice = await new LeonAidApiClient(baseUrl).getPublicLegalNotice({
      headers: { "X-Request-ID": `public-legal:${crypto.randomUUID()}` },
      signal: AbortSignal.timeout(timeoutMilliseconds),
    });
    // No active configuration yet is a setup state: read again next time,
    // so an activation shows up at once.
    cached = notice.provider
      ? { provider: notice.provider, until: now + freshMilliseconds }
      : null;
    return { state: "ready", provider: notice.provider };
  } catch {
    if (cached) {
      cached = { ...cached, until: now + retryMilliseconds };
      return { state: "ready", provider: cached.provider };
    }
    return { state: "unavailable" };
  }
}

const countryNames: Readonly<Record<string, string>> = {
  DE: "Deutschland",
  AT: "Österreich",
  CH: "Schweiz",
};

/** "Hauptstraße 1 · 86150 Augsburg" (plus the country outside Germany). */
export function providerAddress(provider: PublicLegalProviderResponse) {
  const country =
    provider.countryCode === "DE"
      ? ""
      : ` · ${countryNames[provider.countryCode] ?? provider.countryCode}`;
  return `${provider.streetLine1} · ${provider.postalCode} ${provider.city}${country}`;
}
