import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  coreSessionCookie,
  readCoreIdentity,
} from "../../apps/campaign-site/src/auth/core-identity.ts";

const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
for (const key of [
  "CORE_DATABASE_URL",
  "CORE_POSTGRES_PASSWORD",
  "RUSTFS_SECRET_KEY",
  "CMS_POSTGRES_PASSWORD",
]) {
  assert.ok(
    process.env[key] === undefined,
    "probe must not load database/operator credentials",
  );
}
const request = (token, extras = {}) =>
  new Request("https://leonaid.invalid/_emdash/admin/", {
    headers: { Cookie: `__Host-leonaid_session=${token}`, ...extras },
  });
const denied = (status) => (error) =>
  error.status === status &&
  ["identity_denied", "identity_unavailable"].includes(error.message);
if (process.argv.includes("--unavailable")) {
  const started = Date.now();
  await assert.rejects(readCoreIdentity(request(tokens.system)), denied(503));
  assert.ok(Date.now() - started < 4000);
} else if (process.argv.includes("--revoked")) {
  await assert.rejects(readCoreIdentity(request(tokens.system)), denied(401));
  await assert.rejects(readCoreIdentity(request(tokens.charity)), denied(403));
} else {
  const system = await readCoreIdentity(
    request(tokens.system, {
      Cookie: `unrelated=do-not-forward; __Host-leonaid_session=${tokens.system}; emdash_session=ignored`,
      "X-User-Id": "forged",
      "X-Forwarded-Email": "forged@leonaid.invalid",
    }),
  );
  assert.equal(system.userId, "10000000-0000-4000-8000-000000000001");
  assert.equal(system.role, 50);
  const charity = await readCoreIdentity(request(tokens.charity));
  assert.equal(charity.role, 40);
  await assert.rejects(readCoreIdentity(request(tokens.finance)), denied(403));
  await assert.rejects(readCoreIdentity(request("a".repeat(64))), denied(401));
  await assert.rejects(
    readCoreIdentity(
      new Request("https://leonaid.invalid", {
        headers: {
          "X-User-Id": system.userId,
          "X-Role": "system_admin",
          Cookie: "emdash_session=local-only",
        },
      }),
    ),
    denied(401),
  );
  for (const cookie of [
    `__Host-leonaid_session=${tokens.system}; __Host-leonaid_session=${tokens.system}`,
    "__Host-leonaid_session=%2Fescaped",
    "__Host-leonaid_session=short",
  ]) {
    assert.throws(
      () => coreSessionCookie(request(tokens.system, { Cookie: cookie })),
      denied(401),
    );
  }
  assert.ok(
    coreSessionCookie(
      request(tokens.system, {
        Cookie: `unrelated=ignored; __Host-leonaid_session=${tokens.system}`,
      }),
    ) === `__Host-leonaid_session=${tokens.system}`,
  );
}
console.log(
  "emdash-core-auth: OK: real Core HTTP, exact session cookie, runtime profile validation, role denial and bounded revocation/outage checks",
);
