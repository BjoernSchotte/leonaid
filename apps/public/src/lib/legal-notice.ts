import {
  LeonAidApiClient,
  type PublicLegalProviderResponse,
} from "@leonaid/api-client";

/**
 * The installation's Impressum provider (active legal configuration), read
 * server side for the footer of every public page and for /impressum.
 * One club per installation, so every result is cached per process and one
 * request is shared by concurrent renders:
 * - a provider for 60 s;
 * - "none active yet" for 10 s, so an activation shows up soon;
 * - a failed read for 10 s: renders do not each wait for the timeout. A
 *   failure after a known provider keeps serving that provider.
 */
const providerMilliseconds = 60_000;
const noneMilliseconds = 10_000;
const failureMilliseconds = 10_000;
const timeoutMilliseconds = 2_000;

export type LegalNoticeResult =
  | {
      readonly state: "ready";
      readonly provider: PublicLegalProviderResponse | null;
    }
  | { readonly state: "unavailable" };

type LoadProvider = () => Promise<PublicLegalProviderResponse | null>;

export function createLegalNoticeReader(
  load: LoadProvider,
  clock: () => number = Date.now,
) {
  let cached: { result: LegalNoticeResult; until: number } | null = null;
  let lastProvider: PublicLegalProviderResponse | null = null;
  let pending: Promise<LegalNoticeResult> | null = null;

  async function refresh(): Promise<LegalNoticeResult> {
    let result: LegalNoticeResult;
    let ttl: number;
    try {
      const provider = await load();
      lastProvider = provider;
      result = { state: "ready", provider };
      ttl = provider ? providerMilliseconds : noneMilliseconds;
    } catch {
      result = lastProvider
        ? { state: "ready", provider: lastProvider }
        : { state: "unavailable" };
      ttl = failureMilliseconds;
    }
    cached = { result, until: clock() + ttl };
    return result;
  }

  return function readLegalNotice(): Promise<LegalNoticeResult> {
    if (cached && cached.until > clock()) return Promise.resolve(cached.result);
    pending ??= refresh().finally(() => {
      pending = null;
    });
    return pending;
  };
}

async function loadFromCore(): Promise<PublicLegalProviderResponse | null> {
  const baseUrl = process.env.CORE_API_URL?.trim() || "http://api:8000";
  const notice = await new LeonAidApiClient(baseUrl).getPublicLegalNotice({
    headers: { "X-Request-ID": `public-legal:${crypto.randomUUID()}` },
    signal: AbortSignal.timeout(timeoutMilliseconds),
  });
  return notice.provider;
}

export const readLegalNotice = createLegalNoticeReader(loadFromCore);

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
