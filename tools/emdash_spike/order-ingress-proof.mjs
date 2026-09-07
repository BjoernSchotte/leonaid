import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

const ca = await readFile("/proof/root.crt");
const pilot = process.argv.includes("--pilot");
// Pass the raw path to Node: URL construction would normalize away attack cases.
function call(path, method, secure, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = (secure ? httpsRequest : httpRequest)(
      {
        hostname: "proxy",
        port: secure ? (pilot ? 443 : 8443) : pilot ? 80 : 8080,
        ca,
        servername: pilot ? "localhost" : "proxy",
        path,
        method,
        headers: {
          ...headers,
          ...(pilot ? { Host: "localhost" } : {}),
        },
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () =>
          resolve({
            status: res.statusCode,
            headers: res.headers,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(5000, () =>
      req.destroy(new Error("order ingress deadline")),
    );
    req.on("error", reject);
    req.end();
  });
}
const canonical = "/api/v1/public/actions/krapfentaxi/orders";
const paths = [
  canonical,
  `${canonical}/`,
  `${canonical}//`,
  `${canonical}?ignored=1`,
  canonical.replace("api", "%61pi"),
  canonical.replace("orders", "%6frders"),
  canonical.replace("krapfentaxi", "%6brapfentaxi"),
  canonical.replace("/orders", "%2forders"),
  canonical.replace("/orders", "%2Forders"),
  canonical.replace("/v1/", "//v1//"),
  canonical.replace("/v1/", "/health/../v1/"),
  canonical.replace("/orders", "/unused/../orders"),
  canonical.replace("/orders", "/unused/%2e%2e/orders"),
];
let count = 0;
for (const secure of [false, true]) {
  for (const method of [
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
  ]) {
    for (const path of paths) {
      const response = await call(path, method, secure, {
        "X-Forwarded-For": "127.0.0.1",
        "X-Forwarded-Host": "api:8000",
        "X-Forwarded-Proto": "https",
        Forwarded: "for=127.0.0.1;host=api:8000;proto=https",
        "X-EmDash-Request": "1",
        Origin: "https://proxy:8443",
      });
      assert.equal(response.status, 404, `${method} ${path} secure=${secure}`);
      assert.equal(response.body, method === "HEAD" ? "" : "Not Found");
      assert.equal(response.headers["cache-control"], "no-store");
      assert.equal(response.headers.location, undefined);
      assert.equal(response.headers["set-cookie"], undefined);
      count++;
    }
  }
}
if (pilot) {
  assert.equal((await call("/_health", "GET", false)).status, 200);
  assert.equal((await call("/_health", "GET", true)).status, 200);
  for (const method of ["GET", "POST"]) {
    const redirect = await call("/api/v1/platform", method, false);
    assert.equal(redirect.status, 308);
    assert.equal(
      redirect.headers.location,
      "https://localhost/api/v1/platform",
    );
  }
  // No backend is started: distinguish an upstream attempt from the fixed deny.
  assert.equal((await call("/api/v1/platform", "GET", true)).status, 502);
} else if (!process.argv.includes("--core-stopped")) {
  assert.equal((await call("/api/v1/platform", "GET", true)).status, 200);
  const internal = await fetch(`http://api:8000${canonical}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
    signal: AbortSignal.timeout(5000),
    redirect: "manual",
  });
  assert.equal(
    internal.status,
    422,
    "internal Core schema validation remains reachable",
  );
}
console.log(
  `order-ingress: ${count} raw HTTP/HTTPS method/path/forged-header requests denied without redirect or cookie; pilot=${pilot}; coreStopped=${process.argv.includes("--core-stopped")}`,
);
