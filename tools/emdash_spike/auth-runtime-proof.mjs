import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
async function identity(token, expected) {
  const response = await fetch(
    "http://campaign-site:3000/_emdash/api/auth/me",
    {
      headers: token
        ? { Cookie: `__Host-leonaid_session=${token}; emdash_session=ignored` }
        : {},
      redirect: "manual",
      signal: AbortSignal.timeout(6000),
    },
  );
  assert.equal(response.status, expected);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("set-cookie"), null);
  return response.json();
}
await identity(null, 401);
const bearer = await fetch("http://campaign-site:3000/_emdash/api/auth/me", {
  headers: {
    Cookie: `__Host-leonaid_session=${tokens.system}`,
    Authorization: "Bearer ec_pat_disabled",
  },
});
assert.equal(bearer.status, 403);
assert.equal(bearer.headers.get("cache-control"), "no-store");
assert.equal(bearer.headers.get("set-cookie"), null);
if (!process.argv.includes("--unavailable"))
  await identity(tokens.charity, 403);
if (process.argv.includes("--revoked")) {
  await identity(tokens.system, 401);
} else if (process.argv.includes("--unavailable")) {
  // No valid cached/local CMS identity survives losing Core.
  await identity(tokens.system, 503);
} else {
  const result = await identity(tokens.system, 200);
  assert.equal(result.data.role, 50);
  assert.match(result.data.id, /^[0-9A-HJKMNP-TV-Z]{26}$/);
  if (process.argv.includes("--renamed")) {
    assert.equal(result.data.id, await readFile("/proof/cms-id", "utf8"));
    assert.equal(result.data.email, "renamed-system@leonaid.invalid");
  } else {
    await writeFile("/proof/cms-id", result.data.id);
    assert.equal((await identity(tokens.system, 200)).data.id, result.data.id);
  }
}
for (const path of [
  "/_emdash/admin/",
  "/_emdash/api/setup",
  "/_emdash/api/auth/passkey/options",
]) {
  const response = await fetch(`http://campaign-site:3000${path}`, {
    headers: { Cookie: `__Host-leonaid_session=${tokens.system}` },
  });
  assert.equal(response.status, 503);
}
console.log(
  "emdash-auth-runtime: OK: real production middleware, stable mapped ID, no local session, closed setup and revocation/outage denial",
);
