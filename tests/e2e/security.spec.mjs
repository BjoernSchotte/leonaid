import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error("POC-110 Browserumgebung ist unvollständig");
}

test("Login-Rate-Limit erklärt den sicheren nächsten Schritt", async ({
  page,
}) => {
  await page.goto(`${baseUrl}/login`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Bei LeonAid anmelden",
  );

  const statuses = await page.evaluate(async () => {
    const values = [];
    for (let index = 0; index < 5; index += 1) {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "poc110-browser@leonaid.invalid" }),
      });
      values.push(response.status);
    }
    return values;
  });
  expect(statuses).toEqual([202, 202, 202, 202, 202]);

  await page.locator("#login-email").fill("poc110-browser@leonaid.invalid");
  await page.getByTestId("request-login").click();
  await expect(page.getByRole("alert")).toContainText("Zu viele Versuche");
  await expect(page.getByRole("alert")).toContainText(/warte/i);
  await page.screenshot({
    path: `${artifactDirectory}/security-rate-limit.png`,
    fullPage: true,
  });
});
