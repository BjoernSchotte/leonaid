import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import http from "node:http";
import { setTimeout as delay } from "node:timers/promises";

// Run inside the production image with --network none and no published ports.
// A real Astro server handles every request; no mocked request/auth/DB objects.
// The configured origin is synthetic; nothing resolves or listens there.
const siteOrigin = new URL("https://cms.leonaid.invalid");
const server = spawn(process.execPath, ["./dist/server/entry.mjs"], {
  stdio: "ignore",
  env: {
    ...process.env,
    HOST: "127.0.0.1",
    PORT: "3000",
    EMDASH_SITE_URL: siteOrigin.origin,
  },
});

// node:http keeps an explicit Host header, as Caddy sends it; fetch cannot.
function request(path, { method = "GET", headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const outgoing = http.request(
      {
        host: "127.0.0.1",
        port: 3000,
        path,
        method,
        headers,
        timeout: 1000,
      },
      (response) => {
        let text = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => (text += chunk));
        response.on("end", () =>
          resolve({
            status: response.statusCode,
            headers: response.headers,
            text,
          }),
        );
      },
    );
    outgoing.on("timeout", () =>
      outgoing.destroy(new Error(`${method} ${path} timed out`)),
    );
    outgoing.on("error", reject);
    outgoing.end(body);
  });
}

try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null)
      throw new Error("CMS process exited before liveness");
    try {
      const response = await request("/health/live");
      if (response.status === 200) {
        assert.equal(response.text, "ok");
        ready = true;
        break;
      }
    } catch {
      // Startup only. A persistent failure fails the bounded readiness assertion.
    }
    await delay(100);
  }
  assert.ok(ready, "liveness must work without a database or network");
  let denied = 0;
  const expectDenied = async (label, response, status, text) => {
    assert.equal(response.status, status, `${label} must remain closed`);
    assert.equal(response.headers["cache-control"], "no-store", label);
    assert.equal(response.text, text, label);
    denied += 1;
  };
  for (const path of [
    "/_emdash/admin/",
    "/_emdash/admin/setup",
    "/_emdash/api/setup",
    "/_emdash/api/setup/complete",
    "/_emdash/api/auth/login",
    "/_emdash/api/plugins",
    "/_emdash/mcp",
    "/health/ready",
  ]) {
    for (const method of ["GET", "POST"]) {
      await expectDenied(
        `${method} ${path}`,
        await request(path, { method }),
        503,
        path === "/health/ready" ? "unavailable" : "CMS access is not enabled",
      );
    }
  }
  // Public campaign pages have their own admission order (EMS-050/085): the
  // trusted Caddy origin first, then completed bootstrap. Prove both gates.
  const trusted = {
    Host: siteOrigin.host,
    "X-Forwarded-Host": siteOrigin.host,
    "X-Forwarded-Proto": "https",
  };
  const campaign = "/campaigns/test/";
  const unavailable = "Aktionsseite vorübergehend nicht erreichbar";
  await expectDenied(
    `GET ${campaign} without the trusted origin`,
    await request(campaign),
    403,
    "Invalid CMS origin",
  );
  await expectDenied(
    `GET ${campaign} before bootstrap`,
    await request(campaign, { headers: trusted }),
    503,
    unavailable,
  );
  const plainPost = await request(campaign, {
    method: "POST",
    headers: trusted,
  });
  await expectDenied(`POST ${campaign}`, plainPost, 405, "Method not allowed");
  assert.equal(plainPost.headers.allow, "GET, HEAD");
  const order = new URLSearchParams({ synthetic: "closed-runtime" }).toString();
  await expectDenied(
    `native order POST ${campaign} before bootstrap`,
    await request(`${campaign}?_action=createPublicOrder`, {
      method: "POST",
      headers: {
        ...trusted,
        Origin: siteOrigin.origin,
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": String(Buffer.byteLength(order)),
      },
      body: order,
    }),
    503,
    unavailable,
  );
  assert.equal(denied, 20);
  console.log(
    `emdash-closed-runtime: OK: production Node server, liveness, ${denied} default-deny requests, no network or database`,
  );
} finally {
  server.kill("SIGTERM");
}
