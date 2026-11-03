import { test, expect } from "./csp-guard.mjs";
import { randomUUID } from "node:crypto";

const endpoint = "**/api/v1/public/inbox-cases";
async function fillRequest(form, subject) {
  await form.getByLabel("Vorname", { exact: true }).fill("Replay");
  await form.getByLabel("Nachname", { exact: true }).fill("Browsernachweis");
  await form
    .getByLabel("E-Mail-Adresse", { exact: true })
    .fill(`${randomUUID()}@example.org`);
  await form.getByLabel("Betreff", { exact: true }).fill(subject);
  await form
    .getByLabel("Deine Nachricht", { exact: true })
    .fill("Synthetische Prüfung eines bereits gespeicherten Eingangs.");
}

// One test: the real rate limit counts every request of this browser address.
test("consent is mandatory; a lost committed response and the real rate limit keep the identical command", async ({
  page,
}, testInfo) => {
  await page.goto(process.env.LEONAID_E2E_BASE_URL);
  const form = page.locator("leonaid-inbox-form");
  await expect(
    page.getByRole("heading", { name: "Hinweise zur Datenverarbeitung" }),
  ).toBeVisible();
  for (const topic of ["Zweck:", "Speicherung:", "Löschung:"]) {
    await expect(page.locator(".inbox-privacy")).toContainText(topic);
  }
  const consent = form.getByRole("checkbox", { name: /Ich willige ein/ });

  // Without consent the browser does not send anything.
  await fillRequest(form, "Ohne Einwilligung");
  let sent = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/v1/public/inbox-cases")) sent += 1;
  });
  await form.getByRole("button").click();
  expect(await consent.evaluate((input) => input.validity.valueMissing)).toBe(
    true,
  );
  expect(sent).toBe(0);

  // With consent the case is accepted and the receipt names its reference.
  await consent.check();
  const accepted = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/public/inbox-cases") &&
      response.status() === 201,
  );
  await form.getByRole("button").click();
  const receipt = await (await accepted).json();
  expect((await accepted).request().postDataJSON()).toMatchObject({
    privacyConsent: true,
    privacyNoticeVersion: "inbox-privacy-2026-11",
  });
  await expect(form.getByRole("status")).toContainText(receipt.reference);

  await page.goto(process.env.LEONAID_E2E_BASE_URL);
  await fillRequest(form, "Verlorene Bestätigung und Rate Limit");
  await form.getByRole("checkbox", { name: /Ich willige ein/ }).check();
  let original;
  let reference;
  await page.route(
    endpoint,
    async (route) => {
      original = route.request().postDataJSON();
      const committed = await route.fetch();
      expect(committed.status()).toBe(201);
      reference = (await committed.json()).reference;
      // Real server commit; simulate only losing its response in transit.
      await route.abort("connectionreset");
    },
    { times: 1 },
  );
  await form.getByRole("button").click();
  await expect(form.getByRole("status")).toContainText("noch unklar");
  expect(reference).toBeTruthy();
  const saturated = await page.evaluate(async () => {
    for (let i = 0; i < 6; i++) {
      const response = await fetch("/api/v1/public/inbox-cases", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (response.status === 429) return true;
      if (response.status !== 422)
        throw new Error(`Unexpected rejection ${response.status}`);
    }
    return false;
  });
  expect(saturated).toBe(true);
  const request = page.waitForRequest(
    (request) =>
      request.url().endsWith("/api/v1/public/inbox-cases") &&
      request.method() === "POST",
  );
  const response = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/public/inbox-cases") &&
      response.status() === 429,
  );
  await form
    .getByRole("button", { name: "Erneut senden", exact: true })
    .click();
  expect((await request).postDataJSON()).toEqual(original);
  await response;
  await expect(form.getByRole("status")).toContainText("noch unklar");
  await expect(form.getByLabel("Vorname", { exact: true })).toBeDisabled();
  await expect(form.getByLabel("Betreff", { exact: true })).toHaveValue(
    original.subject,
  );
  await expect(
    form.getByRole("button", { name: "Erneut senden", exact: true }),
  ).toBeEnabled();
  await page.screenshot({
    path: testInfo.outputPath("inbox-uncertain-rate-limit.png"),
    fullPage: false,
  });
  await testInfo.attach("committed-reference", {
    body: JSON.stringify({ reference }),
    contentType: "application/json",
  });
});
