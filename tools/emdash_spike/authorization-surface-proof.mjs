import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";

const inventory = JSON.parse(
  await readFile(
    "/workspace/specs/emdash-campaign-microsite-spike/route-inventory.json",
    "utf8",
  ),
);
const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const openedReads = new Set([
  "/_emdash/api/auth/me",
  "/_emdash/api/manifest",
  "/_emdash/api/dashboard",
]);
const methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"];
let assertions = 0;
for (const route of inventory.routes.filter((route) =>
  route.pattern.startsWith("/_emdash/"),
)) {
  const path = route.pattern.replace(/\[(?:\.\.\.)?[^\]]+\]/g, "scope-probe");
  for (const method of new Set([
    ...route.methods.flatMap((method) =>
      method === "ALL" ? methods : [method],
    ),
    "HEAD",
    "OPTIONS",
  ])) {
    for (const actor of ["system", "charity", "anonymous"]) {
      const response = await new Promise((resolve, reject) => {
        const req = request(
          new URL(path, "https://proxy:8443"),
          {
            ca,
            servername: "proxy",
            method,
            headers: {
              ...(actor === "anonymous"
                ? {}
                : { Cookie: `__Host-leonaid_session=${tokens[actor]}` }),
              Origin: "https://proxy:8443",
              "X-EmDash-Request": "1",
              ...(!["GET", "HEAD"].includes(method)
                ? { "Content-Type": "application/json", "Content-Length": "2" }
                : {}),
            },
          },
          (response) => {
            response.resume();
            response.on("end", () =>
              resolve({
                status: response.statusCode,
                headers: response.headers,
              }),
            );
          },
        );
        req.setTimeout(6000, () =>
          req.destroy(new Error("Authorization surface deadline")),
        );
        req.on("error", reject);
        req.end(!["GET", "HEAD"].includes(method) ? "{}" : undefined);
      });
      const expected =
        (openedReads.has(path) && method === "GET") ||
        (path === "/_emdash/api/auth/me" && method === "POST")
          ? actor === "system"
            ? method === "POST"
              ? 400
              : 200
            : actor === "charity"
              ? path === "/_emdash/api/dashboard"
                ? 403
                : method === "POST"
                  ? 400
                  : 200
              : 401
          : 503;
      assert.equal(response.status, expected, `${actor} ${method} ${path}`);
      assert.equal(
        response.headers["cache-control"],
        "no-store",
        `${method} ${path}`,
      );
      assert.equal(response.headers["set-cookie"], undefined);
      assertions += 1;
    }
  }
}
console.log(
  `emdash-authorization-surface: OK: ${assertions} real TLS requests; every registered HTTP operation plus HEAD/OPTIONS follows the current closed policy for three actors`,
);
