import { expect, test } from "./csp-guard.mjs";
import { readFileSync } from "node:fs";

// Transport faults on the individual-response list. Every request reaches
// the real API except the two acknowledgements this spec drops.
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!baseURL || !proof) throw new Error("Survey fixture access is required");
const fixture = JSON.parse(
  readFileSync(`${proof}/raw-response-access.json`, "utf8"),
);

test("a lost response read and a lost selection acknowledgement recover from the server", async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1280, height: 900 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.readerToken,
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  await page.goto(
    `${baseURL}/admin/surveys/${fixture.surveyId}/responses?responseSelection=${fixture.snapshotId}`,
  );
  await expect(page.locator(".svr-applied")).toContainText("51 Teilnahmen");

  // Abort one response read: the pane reports it; a retry loads the stored answer.
  await page.route(
    "**/response-selections/*/responses/*",
    (route) => route.abort("failed"),
    { times: 1 },
  );
  await page.getByRole("button", { name: "Freitexte", exact: true }).click();
  const free = page.getByRole("dialog", { name: "Freitextantworten" });
  await free
    .getByRole("listitem")
    .filter({ hasText: "Saved partial feedback" })
    .getByRole("button")
    .click();
  const pane = page.getByRole("complementary", { name: /^Details: Antwort / });
  await expect(pane.getByRole("alert")).toContainText(
    "Die Anfrage konnte nicht bestätigt werden.",
  );
  await expect(pane).not.toContainText("Saved partial feedback");
  await pane.getByRole("button", { name: "Erneut laden", exact: true }).click();
  await expect(pane).toContainText("Saved partial feedback");
  await expect(pane).not.toContainText("Updated partial feedback");

  // Drop the acknowledgement of a committed selection; the retry repeats the
  // identical request and gets the stored selection.
  let originalBody;
  let stored;
  await page.route(
    `**/surveys/${fixture.surveyId}/response-selections`,
    async (route) => {
      originalBody = route.request().postDataJSON();
      const response = await route.fetch();
      expect(response.status()).toBe(200);
      stored = await response.json();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await page
    .getByRole("button", { name: "Antwortstand wählen", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Antwortstand wählen" });
  await dialog.getByLabel("In Bearbeitung", { exact: true }).check();
  await dialog
    .getByRole("button", { name: "Antworten auswählen", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Die Anfrage konnte nicht bestätigt werden.",
  );
  const repeat = page.waitForRequest(
    (r) =>
      r.url().endsWith(`/surveys/${fixture.surveyId}/response-selections`) &&
      r.method() === "POST",
  );
  await dialog
    .getByRole("button", { name: "Auswahl erneut anfordern" })
    .click();
  expect((await repeat).postDataJSON()).toEqual(originalBody);
  await expect(dialog).toHaveCount(0);
  await expect(page.locator(".svr-applied")).toContainText("52 Teilnahmen");
  expect(new URL(page.url()).searchParams.get("responseSelection")).toBe(
    stored.id,
  );
  await context.close();
});
