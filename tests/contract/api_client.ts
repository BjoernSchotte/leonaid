import {
  ApiError,
  LeonAidApiClient,
  type PlatformInformationResponse,
} from "../../packages/api-client/src";

const requestId = "poc023:contract:golden-v1";
const client = new LeonAidApiClient("http://api:8000");

const platform: PlatformInformationResponse =
  await client.getPlatformInformation({
    headers: { "X-Request-ID": requestId },
  });
if (
  platform.service !== "leonaid-api" ||
  platform.release !== "0.0.0" ||
  platform.apiVersion !== "v1"
) {
  throw new Error(`Unerwartete Plattformantwort: ${JSON.stringify(platform)}`);
}

const live = await client.getHealthLive();
if (live.status !== "live") {
  throw new Error(`API is not live: ${JSON.stringify(live)}`);
}

const ready = await client.getHealthReady();
if (
  ready.status !== "ready" ||
  ready.checks.postgres?.status !== "ready" ||
  ready.checks.twenty?.status !== "ready" ||
  ready.checks.rustfs?.status !== "ready"
) {
  throw new Error(`API is not ready: ${JSON.stringify(ready)}`);
}

try {
  await client.request<never>(
    "/api/v1/does-not-exist",
    { method: "GET" },
    { headers: { "X-Request-ID": requestId } },
  );
  throw new Error("Error response was treated as success.");
} catch (error: unknown) {
  if (!(error instanceof ApiError)) {
    throw error;
  }
  if (
    error.status !== 404 ||
    error.detail.code !== "endpoint_not_found" ||
    error.detail.requestId !== requestId ||
    !error.detail.message.includes("existiert nicht")
  ) {
    throw new Error(`Error response is not typed: ${JSON.stringify(error)}`);
  }
}

// A non-JSON success body (here the real Prometheus endpoint) must surface as
// a typed ApiError instead of a JSON SyntaxError without status.
try {
  await client.request<never>("/metrics", { method: "GET" });
  throw new Error("Non-JSON response was treated as success.");
} catch (error: unknown) {
  if (!(error instanceof ApiError)) {
    throw error;
  }
  if (
    error.status !== 200 ||
    error.detail.code !== "unexpected_response_type" ||
    !error.detail.message.includes("text/plain")
  ) {
    throw new Error(`Non-JSON response is not typed: ${JSON.stringify(error)}`);
  }
}

// Query parameters travel through the generated client: the bounded core
// search rejects a too-short query before it checks the session.
try {
  await client.searchCore(
    { q: "a", limit: 8 },
    { headers: { "X-Request-ID": requestId } },
  );
  throw new Error("Invalid search query was treated as success.");
} catch (error: unknown) {
  if (!(error instanceof ApiError)) {
    throw error;
  }
  if (error.status !== 422 || error.detail.code !== "request_invalid") {
    throw new Error(`Search validation is not typed: ${JSON.stringify(error)}`);
  }
}

try {
  await client.searchCore({ q: "Krapfen" });
  throw new Error("Search without a session was treated as success.");
} catch (error: unknown) {
  if (!(error instanceof ApiError)) {
    throw error;
  }
  if (error.status !== 401) {
    throw new Error(
      `Search did not require a session: ${JSON.stringify(error)}`,
    );
  }
}

console.log(
  "poc023-contract: OK: generierter Client, Golden-Antwort und typisierter Fehler",
);
