import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

function berlinTomorrow() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Berlin",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(new Date())
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
  const tomorrow = new Date(
    Date.UTC(parts.year, parts.month - 1, parts.day + 1),
  );
  return tomorrow.toISOString().slice(0, 10);
}

test("Akquisiteurin dokumentiert Kontakt und findet ihn nach Reload", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: annaSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  try {
    await page.goto(`${baseUrl}/app/activities`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Anna Akquise",
    );
    await expect(
      page.getByRole("heading", { name: "Aktivitäten & Wiedervorlagen" }),
    ).toBeVisible();
    await expect(page.locator('[data-testid="overdue-count"]')).toHaveText("1");
    await expect(page.locator('[data-testid="today-count"]')).toHaveText("1");
    const reminderCards = page.locator("[data-select-assignment]");
    await expect(reminderCards.nth(0)).toContainText("Musterwerk GmbH");
    await expect(reminderCards.nth(0)).toContainText("Überfällig");
    await expect(reminderCards.nth(1)).toContainText("Doppelkontakt AG");
    await expect(reminderCards.nth(1)).toContainText("Heute");

    const musterwerkValue = await page
      .locator('[data-testid="activity-party"] option')
      .filter({ hasText: "Musterwerk GmbH" })
      .getAttribute("value");
    expect(musterwerkValue).toBeTruthy();
    await page
      .locator('[data-testid="activity-party"]')
      .selectOption(musterwerkValue);
    await page.locator("#activity-channel").selectOption("in_person");
    await page.locator("#activity-outcome").selectOption("reached");
    await page
      .locator("#activity-note")
      .fill("Lieferadresse gemeinsam geprüft.");
    await page
      .locator("#activity-next-action")
      .fill("Lieferadresse bestätigen");
    await page.locator("#activity-due-on").fill(berlinTomorrow());

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/acquisition/activities") &&
        response.request().method() === "POST",
    );
    await page.locator('[data-testid="activity-submit"]').click();
    const response = await responsePromise;
    expect(response.status()).toBe(201);
    const recorded = await response.json();

    await expect(page.locator("#activity-status")).toContainText(
      "Aktivität für Musterwerk GmbH wurde gespeichert",
    );
    const newest = page.locator('[data-testid="activity-entry"]').first();
    await expect(newest).toContainText("Musterwerk GmbH");
    await expect(newest).toContainText("Lieferadresse gemeinsam geprüft.");
    await expect(newest).toContainText("Lieferadresse bestätigen");
    await page.screenshot({
      path: `${artifactDirectory}/activity-recorded-mobile.png`,
      fullPage: true,
    });

    await page.reload();
    const persisted = page.locator(
      `[data-activity-id="${recorded.activity.id}"]`,
    );
    await expect(persisted).toContainText("Lieferadresse gemeinsam geprüft.");
    await expect(persisted).toContainText("Lieferadresse bestätigen");
    await expect(page.locator('[data-testid="overdue-count"]')).toHaveText("0");
    await expect(page.locator('[data-testid="today-count"]')).toHaveText("1");
    await page.screenshot({
      path: `${artifactDirectory}/activity-persisted-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
