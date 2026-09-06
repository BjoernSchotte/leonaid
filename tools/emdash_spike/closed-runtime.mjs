import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";

// Run inside the production image with --network none and no published ports.
// A real Astro server handles every request; no mocked request/auth/DB objects.
const server = spawn(process.execPath, ["./dist/server/entry.mjs"], {
  stdio: "ignore",
  env: { ...process.env, HOST: "127.0.0.1", PORT: "3000" },
});
try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null)
      throw new Error("CMS process exited before liveness");
    try {
      const response = await fetch("http://127.0.0.1:3000/health/live", {
        signal: AbortSignal.timeout(500),
      });
      if (response.status === 200) {
        assert.equal(await response.text(), "ok");
        ready = true;
        break;
      }
    } catch {
      // Startup only. A persistent failure fails the bounded readiness assertion.
    }
    await delay(100);
  }
  assert.ok(ready, "liveness must work without a database or network");
  for (const path of [
    "/_emdash/admin/",
    "/_emdash/admin/setup",
    "/_emdash/api/setup",
    "/_emdash/api/setup/complete",
    "/_emdash/api/auth/login",
    "/_emdash/api/plugins",
    "/_emdash/mcp",
    "/campaigns/test/",
    "/health/ready",
  ]) {
    for (const method of ["GET", "POST"]) {
      const response = await fetch(`http://127.0.0.1:3000${path}`, {
        method,
        redirect: "manual",
        signal: AbortSignal.timeout(1000),
      });
      assert.equal(
        response.status,
        503,
        `${method} ${path} must remain closed`,
      );
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(
        await response.text(),
        path === "/health/ready" ? "unavailable" : "CMS access is not enabled",
      );
    }
  }
  console.log(
    "emdash-closed-runtime: OK: production Node server, liveness, 18 default-deny requests, no network or database",
  );
} finally {
  server.kill("SIGTERM");
}
