import assert from "node:assert/strict";
import { setTimeout as delay } from "node:timers/promises";
import { krapfentaxiImportContext } from "./krapfentaxi-import-context.mjs";
import { importKrapfentaxi } from "./krapfentaxi-import.mjs";

// Local Golden-data operator only. Authenticate normally through Core and the
// project's real Mailpit delivery; keep the short-lived session in memory.
// No database session insertion, browser cookie export or independent CMS login.
assert.equal(process.env.LEONAID_ENV, "local");
const mode = process.argv[2];
assert.ok(["dry-run", "apply"].includes(mode));
assert.equal(process.argv.length, 3);
const origin = "https://proxy:8443";
const email = "system-admin@leonaid.invalid";
async function request(path, body, cookie) {
  return fetch(origin + path, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Origin: origin,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(cookie ? { Cookie: cookie } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    redirect: "error",
    signal: AbortSignal.timeout(10000),
  });
}
let context;
let cookie;
try {
  const before = await request("/mail/api/v1/messages");
  assert.equal(before.status, 200);
  const seen = new Set((await before.json()).messages.map((item) => item.ID));
  const sent = await request("/api/v1/auth/login", { email });
  assert.equal(sent.status, 202);
  let code;
  const deadline = Date.now() + 30000;
  while (!code && Date.now() < deadline) {
    const messages = await request("/mail/api/v1/messages");
    assert.equal(messages.status, 200);
    for (const item of (await messages.json()).messages) {
      if (seen.has(item.ID) || !item.To.some((to) => to.Address === email))
        continue;
      const detail = await request(`/mail/api/v1/message/${item.ID}`);
      assert.equal(detail.status, 200);
      code = (await detail.json()).Text?.match(/\bCode ([0-9]{6})\b/)?.[1];
      if (code) break;
    }
    if (!code) await delay(500);
  }
  assert.ok(code);
  const login = await request("/api/v1/auth/login/complete", { email, code });
  assert.equal(login.status, 200);
  cookie = login.headers
    .getSetCookie()
    .find((value) => value.startsWith("__Host-leonaid_session="))
    ?.split(";")[0];
  assert.ok(cookie);
  context = krapfentaxiImportContext(
    cookie.slice(cookie.indexOf("=") + 1),
    "krapfentaxi-2026",
  );
  const result = await importKrapfentaxi({ ...context, mode });
  console.log(JSON.stringify(result));
} catch {
  console.error(
    "local-krapfentaxi-import: failed; no automatic publication or overwrite",
  );
  process.exitCode = 1;
} finally {
  await context?.database.destroy();
  if (cookie) {
    const logout = await request("/api/v1/auth/logout", {}, cookie);
    assert.ok(logout.ok);
  }
}
