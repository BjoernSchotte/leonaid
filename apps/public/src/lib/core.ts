import {
  ApiError,
  LeonAidApiClient,
  type CreatePublicOrderRequest,
  type PublicActionRouteResponse,
  type PublicCampaignListItemResponse,
  type PublicOrderResultResponse,
} from "@leonaid/api-client";

const routeTimeoutMilliseconds = 5_000;
const mutationTimeoutMilliseconds = 12_000;

function client(): LeonAidApiClient {
  const baseUrl = process.env.CORE_API_URL?.trim() || "http://api:8000";
  return new LeonAidApiClient(baseUrl);
}

export async function resolvePublicAction(
  routeKind: "alias" | "archive",
  routeValue: string,
): Promise<PublicActionRouteResponse> {
  const options = {
    headers: { "X-Request-ID": `public:${crypto.randomUUID()}` },
    signal: AbortSignal.timeout(routeTimeoutMilliseconds),
  };
  return routeKind === "alias"
    ? client().resolvePublicActionAlias(routeValue, options)
    : client().resolvePublicActionArchive(routeValue, options);
}

/**
 * Active campaigns for the home page (specs/multi-domain §6.5). The home page
 * stays usable without them: an unreachable Core yields an empty list.
 */
export async function listActiveCampaigns(): Promise<
  readonly PublicCampaignListItemResponse[]
> {
  try {
    const result = await client().listPublicCampaigns(
      { availability: "active" },
      {
        headers: { "X-Request-ID": `public:${crypto.randomUUID()}` },
        signal: AbortSignal.timeout(routeTimeoutMilliseconds),
      },
    );
    return result.items;
  } catch {
    console.warn("public_campaign_list_unavailable");
    return [];
  }
}

export async function submitPublicOrder(
  publicAlias: string,
  body: CreatePublicOrderRequest,
  requestHeaders: {
    forwardedFor?: string;
    userAgent?: string;
  } = {},
): Promise<PublicOrderResultResponse> {
  const orderKey = process.env.LEONAID_ORDER_SUBMISSION_KEY ?? "";
  const coreUrl = process.env.CORE_API_URL?.trim() || "http://api:8000";
  if (!/^[0-9a-f]{64}$/.test(orderKey) || coreUrl !== "http://api:8000") {
    throw new Error("Order transport is unavailable");
  }
  const headers: Record<string, string> = {
    "X-Request-ID": `public-order:${crypto.randomUUID()}`,
    "X-LeonAid-Order-Key": orderKey,
  };
  if (requestHeaders.forwardedFor) {
    headers["X-Forwarded-For"] = requestHeaders.forwardedFor;
  }
  if (requestHeaders.userAgent) {
    headers["User-Agent"] = requestHeaders.userAgent;
  }
  return client().createPublicOrder(publicAlias, body, {
    headers,
    signal: AbortSignal.timeout(mutationTimeoutMilliseconds),
  });
}

export function isMissingPublicAction(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status === 404 &&
    error.detail.code === "public_action_not_found"
  );
}
