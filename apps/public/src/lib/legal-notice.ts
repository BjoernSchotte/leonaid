import {
  LeonAidApiClient,
  type PublicLegalProviderResponse,
  type PublicPrivacyPolicyContentResponse,
} from "@leonaid/api-client";

/**
 * The installation's legal pages (active legal configuration), read server
 * side: the Impressum provider for the footer of every public page and for
 * /impressum, the privacy policy for /datenschutz. One club per
 * installation (multi-domain decision D4: one content for all hosts), so
 * every result is cached per process and one request is shared by
 * concurrent renders:
 * - a value for 60 s;
 * - "none active yet" for 10 s, so an activation shows up soon;
 * - a failed read for 10 s: renders do not each wait for the timeout. A
 *   failure after a known value keeps serving that value.
 */
const valueMilliseconds = 60_000;
const noneMilliseconds = 10_000;
const failureMilliseconds = 10_000;
const timeoutMilliseconds = 2_000;

export type ActiveLegalResult<T> =
  | { readonly state: "ready"; readonly value: T | null }
  | { readonly state: "unavailable" };

export function createActiveLegalReader<T>(
  load: () => Promise<T | null>,
  clock: () => number = Date.now,
) {
  let cached: { result: ActiveLegalResult<T>; until: number } | null = null;
  let lastValue: T | null = null;
  let pending: Promise<ActiveLegalResult<T>> | null = null;

  async function refresh(): Promise<ActiveLegalResult<T>> {
    let result: ActiveLegalResult<T>;
    let ttl: number;
    try {
      const value = await load();
      lastValue = value;
      result = { state: "ready", value };
      ttl = value ? valueMilliseconds : noneMilliseconds;
    } catch {
      result = lastValue
        ? { state: "ready", value: lastValue }
        : { state: "unavailable" };
      ttl = failureMilliseconds;
    }
    cached = { result, until: clock() + ttl };
    return result;
  }

  return function read(): Promise<ActiveLegalResult<T>> {
    if (cached && cached.until > clock()) return Promise.resolve(cached.result);
    pending ??= refresh().finally(() => {
      pending = null;
    });
    return pending;
  };
}

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
  const read = createActiveLegalReader(load, clock);
  return async function readLegalNotice(): Promise<LegalNoticeResult> {
    const result = await read();
    return result.state === "ready"
      ? { state: "ready", provider: result.value }
      : result;
  };
}

function coreClient() {
  const baseUrl = process.env.CORE_API_URL?.trim() || "http://api:8000";
  return new LeonAidApiClient(baseUrl);
}

async function loadFromCore(): Promise<PublicLegalProviderResponse | null> {
  const notice = await coreClient().getPublicLegalNotice({
    headers: { "X-Request-ID": `public-legal:${crypto.randomUUID()}` },
    signal: AbortSignal.timeout(timeoutMilliseconds),
  });
  return notice.provider;
}

export const readLegalNotice = createLegalNoticeReader(loadFromCore);

export type PrivacyPolicyResult =
  ActiveLegalResult<PublicPrivacyPolicyContentResponse>;

export const readPrivacyPolicy = createActiveLegalReader(async () => {
  const policy = await coreClient().getPublicPrivacyPolicy({
    headers: { "X-Request-ID": `public-privacy:${crypto.randomUUID()}` },
    signal: AbortSignal.timeout(timeoutMilliseconds),
  });
  return policy.policy;
});

/** Route names of the legal pages; stable on every host (multi-domain §7.5). */
export const IMPRINT_PATH = "/impressum";
export const PRIVACY_PATH = "/datenschutz";

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

/** "Amtsgericht Augsburg, VR 1234", or null without a register entry. */
export function providerRegister(provider: PublicLegalProviderResponse) {
  return provider.registerCourt && provider.registerNumber
    ? `${provider.registerCourt}, ${provider.registerNumber}`
    : null;
}

/** tel: target: digits and a leading +, separators removed. */
export function telephoneHref(phone: string) {
  return `tel:${phone.replace(/[^\d+]/g, "")}`;
}
