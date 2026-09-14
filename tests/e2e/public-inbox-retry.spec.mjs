import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

const endpoint = "**/api/v1/public/inbox-cases";
test("lost committed response followed by real rate limit retains identical command", async ({
  page,
}, testInfo) => {
  await page.goto(process.env.LEONAID_E2E_BASE_URL);
  const form = page.locator("leonaid-inbox-form");
  await form.getByLabel("Vorname", { exact: true }).fill("Replay");
  await form.getByLabel("Nachname", { exact: true }).fill("Browsernachweis");
  await form
    .getByLabel("E-Mail-Adresse", { exact: true })
    .fill(`${randomUUID()}@example.org`);
  await form
    .getByLabel("Betreff", { exact: true })
    .fill("Verlorene Bestätigung und Rate Limit");
  await form
    .getByLabel("Deine Nachricht", { exact: true })
    .fill("Synthetische Prüfung eines bereits gespeicherten Eingangs.");
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
