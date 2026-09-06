import assert from "node:assert/strict";
import { expect } from "@playwright/test";

const origin = "https://proxy:8443";
const mail = "http://mailpit:8025/mail/api/v1";
const email = "system-admin@leonaid.invalid";

// Read actual SMTP deliveries from this proof project's Mailpit. Never print
// challenge material or inject cookies, network responses, or form state.
export async function browserLogin(context, page, returnTo, fresh = false) {
  if (!fresh) assert.equal((await context.cookies()).length, 0);
  const before = await context.request.get(`${mail}/messages`);
  assert.equal(before.status(), 200);
  const seen = new Set((await before.json()).messages.map((item) => item.ID));
  if (!fresh) await page.locator("#login-email").fill(email);
  await page.locator('[data-testid="request-login"]').click();
  await expect(page.locator("#complete-login-form")).toBeVisible();
  let code;
  await expect
    .poll(
      async () => {
        const response = await context.request.get(`${mail}/messages`);
        if (response.status() !== 200) return false;
        for (const item of (await response.json()).messages) {
          if (seen.has(item.ID) || !item.To.some((to) => to.Address === email))
            continue;
          const detail = await context.request.get(
            `${mail}/message/${item.ID}`,
          );
          if (detail.status() !== 200) continue;
          const match = (await detail.json()).Text?.match(
            /\bCode ([0-9]{6})\b/,
          );
          if (match) {
            code = match[1];
            return true;
          }
        }
        return false;
      },
      {
        timeout: 30000,
        intervals: [100, 200, 400],
        message: "actual SMTP login delivery",
      },
    )
    .toBe(true);
  await page.locator("#login-code").fill(code);
  await page.locator('[data-testid="complete-login"]').click();
  await page.waitForURL(origin + returnTo);
  const session = (await context.cookies()).find(
    (item) => item.name === "__Host-leonaid_session",
  );
  assert.ok(session);
  assert.equal(session.secure, true);
  assert.equal(session.httpOnly, true);
  assert.equal(session.path, "/");
  assert.equal(session.sameSite, "Lax");
  assert.equal(
    (await context.request.get(origin + "/api/v1/identity/me")).status(),
    200,
  );
}

export async function browserFreshLogin(context, page, editorPath, apiRoot) {
  const profile = await context.request.get(origin + "/_emdash/api/auth/me");
  assert.equal(profile.status(), 200);
  const identity = (await profile.json()).data;
  const previous = (await context.cookies()).find(
    (item) => item.name === "__Host-leonaid_session",
  );
  assert.ok(previous);
  await expect
    .poll(
      async () =>
        (
          await context.request.get(origin + "/api/v1/auth/fresh/status")
        ).status(),
      {
        timeout: 15000,
        intervals: [200, 400],
        message: "real Core freshness expiry",
      },
    )
    .toBe(401);
  // Ordinary editing remains authenticated; stale freshness is not logout.
  assert.equal((await context.request.get(origin + apiRoot)).status(), 200);
  await page.goto(
    origin + "/fresh-login?returnTo=" + encodeURIComponent(editorPath),
  );
  await page
    .getByRole("heading", { name: "Anmeldung bestätigen", exact: true })
    .waitFor();
  await browserLogin(context, page, editorPath, true);
  assert.equal(
    (await context.request.get(origin + "/api/v1/auth/fresh/status")).status(),
    200,
  );
  const current = (await context.cookies()).find(
    (item) => item.name === "__Host-leonaid_session",
  );
  assert.ok(
    current && current.value !== previous.value,
    "Core rotates the session on fresh login",
  );
  const after = await context.request.get(origin + "/_emdash/api/auth/me");
  assert.equal(after.status(), 200);
  assert.deepEqual((await after.json()).data, identity);
  assert.equal((await context.request.get(origin + apiRoot)).status(), 200);
}

export async function coreLogout(context, page, editorRoot, apiRoot) {
  const response = await context.request.post(origin + "/api/v1/auth/logout", {
    headers: { Origin: origin },
  });
  assert.ok(response.ok());
  assert.equal(
    (await context.request.get(origin + "/api/v1/identity/me")).status(),
    401,
  );
  assert.equal((await context.request.get(origin + apiRoot)).status(), 401);
  await page.goto(origin + editorRoot);
  await page.waitForURL("**/login?returnTo=**");
  assert.equal(new URL(page.url()).searchParams.get("returnTo"), editorRoot);
  assert.equal(
    (await context.cookies()).some(
      (item) => item.name === "__Host-leonaid_session",
    ),
    false,
  );
}
