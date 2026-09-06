import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { request } from "node:https";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const ca = await readFile("/proof/root.crt");
const mode = process.argv[2];
async function call(
  path,
  {
    token = tokens.system,
    method = "GET",
    origin = "https://proxy:8443",
    extra = {},
  } = {},
) {
  const body =
    method === "POST"
      ? JSON.stringify({
          title: "LeonAid synthetic proof",
          tagline: "",
          includeContent: false,
        })
      : undefined;
  return new Promise((resolve, reject) => {
    const req = request(
      new URL(path, "https://proxy:8443"),
      {
        ca,
        servername: "proxy",
        method,
        headers: {
          ...(token ? { Cookie: `__Host-leonaid_session=${token}` } : {}),
          Origin: origin,
          "X-EmDash-Request": "1",
          ...(body
            ? {
                "Content-Type": "application/json",
                "Content-Length": Buffer.byteLength(body),
              }
            : {}),
          ...extra,
        },
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            body: Buffer.concat(chunks).toString(),
          }),
        );
      },
    );
    req.setTimeout(6000, () =>
      req.destroy(new Error("Bootstrap HTTP deadline")),
    );
    req.on("error", reject);
    req.end(body);
  });
}
async function expect(path, status, options) {
  const response = await call(path, options);
  assert.equal(response.status, status, `${path}: unexpected status`);
  assert.equal(response.headers["cache-control"], "no-store");
  assert.equal(response.headers["set-cookie"], undefined);
  return response;
}
if (mode === "--armed") {
  const wrongHost = await call("/_emdash/api/setup/status", {
    extra: { Host: "attacker.invalid" },
  });
  assert.ok(wrongHost.status >= 400, "Wrong Host must not reach setup");
  const http = await fetch("http://proxy:8080/_emdash/admin/setup", {
    redirect: "manual",
  });
  assert.equal(http.status, 308);
  assert.match(
    http.headers.get("location"),
    /^https:\/\/localhost:\d+\/_emdash\/admin\/setup$/,
  );
  await expect("/_emdash/api/setup/status", 401, { token: null });
  await expect("/_emdash/api/setup/status", 403, { token: tokens.charity });
  await expect("/_emdash/api/setup/status", 403, {
    origin: "https://attacker.invalid",
  });
  // Caddy must replace client-supplied forwarding values, not trust them.
  await expect("/_emdash/api/setup/status", 200, {
    extra: {
      "X-Forwarded-Host": "attacker.invalid",
      "X-Forwarded-Proto": "http",
      Forwarded: "host=attacker.invalid;proto=http",
    },
  });
  await expect("/_emdash/admin/setup", 200);
  await expect("/_emdash/api/setup", 403, {
    method: "POST",
    origin: "https://attacker.invalid",
  });
  await expect("/_emdash/api/setup", 200, { method: "POST" });
  await expect("/_emdash/api/setup", 503, { method: "POST" });
} else {
  for (const path of ["/_emdash/admin/setup", "/_emdash/api/setup/status"]) {
    await expect(path, 503);
    await expect(path, 503, { token: null });
  }
  await expect("/_emdash/api/setup", 503, { method: "POST" });
}
console.log(
  "emdash-bootstrap-runtime: OK: " +
    mode +
    "; actual TLS verified against project CA; protected setup and no independent session",
);
