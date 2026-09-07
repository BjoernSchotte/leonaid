import assert from "node:assert/strict";
import { test } from "bun:test";
import type { PublicActionRouteResponse } from "@leonaid/api-client";
import { campaignRedirect } from "../../apps/public/src/lib/campaign-redirect";

// Pure transport contract, not evidence of Core authorization or live routing.
const route = {
  routeKind: "alias",
  routeValue: "taxi",
  routePath: "/taxi",
  canonicalPath: "/campaigns/krapfentaxi-2026/",
  redirectPath: "/campaigns/krapfentaxi-2026/",
  availability: "published",
  submissionsAllowed: false,
  action: { archiveSlug: "krapfentaxi-2026" },
} as PublicActionRouteResponse;

for (const method of ["GET", "HEAD"]) {
  test(`${method}: temporary canonical redirect without state or caching`, async () => {
    const response = campaignRedirect(route, method)!;
    assert.equal(response.status, 302);
    assert.equal(response.headers.get("location"), route.canonicalPath);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("set-cookie"), null);
    assert.equal(await response.text(), "");
  });
}

for (const method of ["POST", "PUT", "PATCH", "DELETE", "OPTIONS"]) {
  test(`${method}: never redirect a mutation`, () => {
    const response = campaignRedirect(route, method)!;
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), "GET, HEAD");
    assert.equal(response.headers.get("location"), null);
    assert.equal(response.headers.get("cache-control"), "no-store");
  });
}

test("existing primary and archive routes remain untouched", () => {
  for (const redirectPath of [null, undefined]) {
    for (const method of ["GET", "HEAD", "POST"]) {
      assert.equal(campaignRedirect({ ...route, redirectPath }, method), null);
    }
  }
});

const invalid: Partial<PublicActionRouteResponse>[] = [
  { routeKind: "archive" },
  { availability: "inactive" },
  { availability: "archive" },
  { submissionsAllowed: true },
  { action: null },
  { canonicalPath: "/another-alias" },
  ...[
    "https://evil.invalid/",
    "//evil.invalid/",
    "/another-alias",
    "/campaigns/krapfentaxi-2026/?token=secret",
    "/campaigns/krapfentaxi-2026/#fragment",
  ].map((redirectPath) => ({ redirectPath })),
  ...["../admin", "taxi%2fadmin", "taxi\n", "", "taxi/other"].map(
    (archiveSlug) => ({
      action: { ...route.action!, archiveSlug },
      redirectPath: `/campaigns/${archiveSlug}/`,
      canonicalPath: `/campaigns/${archiveSlug}/`,
    }),
  ),
];

for (const [index, patch] of invalid.entries()) {
  test(`invalid Core redirect contract ${index}: fail closed`, () => {
    const response = campaignRedirect({ ...route, ...patch }, "GET")!;
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("location"), null);
    assert.equal(response.headers.get("cache-control"), "no-store");
  });
}
