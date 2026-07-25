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
  throw new Error(`API ist nicht live: ${JSON.stringify(live)}`);
}

const ready = await client.getHealthReady();
if (
  ready.status !== "ready" ||
  ready.checks.postgres?.status !== "ready" ||
  ready.checks.twenty?.status !== "ready" ||
  ready.checks.rustfs?.status !== "ready"
) {
  throw new Error(`API ist nicht bereit: ${JSON.stringify(ready)}`);
}

try {
  await client.request<never>(
    "/api/v1/does-not-exist",
    { method: "GET" },
    { headers: { "X-Request-ID": requestId } },
  );
  throw new Error("Fehlerantwort wurde als Erfolg behandelt.");
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
    throw new Error(
      `Fehlerantwort ist nicht typisiert: ${JSON.stringify(error)}`,
    );
  }
}

console.log(
  "poc023-contract: OK: generierter Client, Golden-Antwort und typisierter Fehler",
);
