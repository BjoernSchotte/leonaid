import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import {
  injectCoreRoutes,
  injectBuiltinAuthRoutes,
  injectMcpRoute,
} from "../../node_modules/emdash/src/astro/integration/routes.ts";

type Route = {
  pattern: string;
  entrypoint: string;
  registration: "core" | "builtin-disabled" | "mcp-disabled";
};
const routes: Route[] = [];
injectCoreRoutes((route) => routes.push({ ...route, registration: "core" }));
injectBuiltinAuthRoutes((route) =>
  routes.push({ ...route, registration: "builtin-disabled" }),
);
injectMcpRoute((route) =>
  routes.push({ ...route, registration: "mcp-disabled" }),
);
assert.equal(new Set(routes.map((route) => route.pattern)).size, routes.length);
const httpMethods = new Set([
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "HEAD",
  "OPTIONS",
  "ALL",
]);
const inventory = [];
for (const route of routes.sort((a, b) =>
  a.pattern.localeCompare(b.pattern, "en"),
)) {
  const source = await readFile(route.entrypoint, "utf8");
  const methods = route.entrypoint.endsWith(".astro")
    ? ["GET"]
    : [
        ...new Set(
          [...source.matchAll(/export\s*\{([^}]+)\}/g)].flatMap((match) =>
            match[1]
              .split(",")
              .map(
                (name) =>
                  name
                    .trim()
                    .split(/\s+as\s+/)
                    .at(-1)!,
              )
              .filter((name) => httpMethods.has(name)),
          ),
        ),
      ].sort();
  assert.ok(methods.length, `Unclassified HTTP exports: ${route.pattern}`);
  const module = route.entrypoint.split("/node_modules/emdash/")[1];
  assert.ok(module);
  inventory.push({
    pattern: route.pattern,
    methods,
    registration: route.registration,
    module,
    sha256: createHash("sha256").update(source).digest("hex"),
  });
}
const result = {
  emdash: "0.36.0",
  upstreamCommit: "603062902369d9695608e85c2d034d4f66f7a1f1",
  routes: inventory,
};
if (process.argv.includes("--table")) {
  console.log(
    "| Route | Methods | Registration | Current rule | Required campaign lookup |\n| --- | --- | --- | --- | --- |",
  );
  for (const route of inventory) {
    const p = route.pattern;
    const current =
      p === "/_emdash/admin/[...path]"
        ? "Root/one-shot setup only"
        : [
              "/_emdash/api/manifest",
              "/_emdash/api/dashboard",
              "/_emdash/api/auth/me",
            ].includes(p)
          ? "Core System Admin GET only"
          : ["/_emdash/api/setup", "/_emdash/api/setup/status"].includes(p)
            ? "Designated one-shot setup only"
            : !p.startsWith("/_emdash/")
              ? "Not routed to CMS"
              : "Denied for all actors";
    const lookup = p.includes("/content/")
      ? "Current/proposed content action_id; list/count filters"
      : p.includes("/revisions/")
        ? "Revision to owning content action_id"
        : p.includes("/media")
          ? "Media-to-campaign binding (not global ownership)"
          : p.includes("/search") || p.includes("/preview")
            ? "Every result/target to owning action_id"
            : "Global/identity surface; no campaign authority implied";
    console.log(
      `| \`${p}\` | ${route.methods.join(", ")} | ${route.registration} | ${current} | ${lookup} |`,
    );
  }
} else if (process.argv.includes("--emit")) {
  console.log(JSON.stringify(result, null, 2));
} else {
  const checkedIn = JSON.parse(
    await readFile(
      "specs/emdash-campaign-microsite-spike/route-inventory.json",
      "utf8",
    ),
  );
  const verify = (expected: typeof result) =>
    assert.deepEqual(
      result,
      expected,
      "EmDash route/export/source drift requires authorization re-review",
    );
  verify(checkedIn);
  // Data-contract mutation tests; no server or adapter is substituted.
  const missing = structuredClone(result);
  missing.routes.pop();
  const changedMethod = structuredClone(result);
  changedMethod.routes[0].methods = ["UNREVIEWED"];
  const changedSource = structuredClone(result);
  changedSource.routes[0].sha256 = "unreviewed";
  for (const changed of [missing, changedMethod, changedSource]) {
    assert.throws(() => verify(changed), /authorization re-review/);
  }
  console.log(
    `emdash-authorization-inventory: OK: ${inventory.length} pinned routes, methods and source hashes match`,
  );
}
