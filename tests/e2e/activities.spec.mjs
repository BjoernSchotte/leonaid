import { expect, test } from "./csp-guard.mjs";

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

test("acquirer records a contact and finds it after reload", async ({
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
    await page.goto(`${baseUrl}/app/activities?view=contacts`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Anna Akquise",
    );
    // Prototype FollowUps: grouped by when they are due.
    await expect(
      page.getByRole("heading", { level: 1, name: "Wiedervorlagen" }),
    ).toBeVisible();
    const overdue = page.getByTestId("follow-ups-overdue");
    const soon = page.getByTestId("follow-ups-soon");
    await expect(overdue.getByTestId("sponsor-row")).toHaveCount(1);
    await expect(overdue).toContainText("Musterwerk GmbH");
    await expect(soon.getByTestId("sponsor-row")).toHaveCount(1);
    await expect(soon).toContainText("Doppelkontakt AG");
    await expect(soon).toContainText("Heute");

    // The contact is recorded on the sponsor, in the contact sheet.
    await overdue.getByTestId("sponsor-row").click();
    await expect(
      page.getByRole("heading", { level: 1, name: "Musterwerk GmbH" }),
    ).toBeVisible();
    await page.keyboard.press("k");
    const sheet = page.getByRole("dialog", {
      name: "Kontakt mit Musterwerk GmbH",
    });
    await expect(sheet).toBeVisible();
    await sheet.getByRole("button", { name: "Persönlich" }).click();
    await sheet.getByText("Erreicht", { exact: true }).click();
    await sheet.getByLabel("Wiedervorlage am").fill(berlinTomorrow());
    await sheet.getByLabel("Nächster Schritt").fill("Lieferadresse bestätigen");
    await sheet.getByLabel("Notiz").fill("Lieferadresse gemeinsam geprüft.");

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().endsWith("/acquisition/activities") &&
        response.request().method() === "POST",
    );
    await sheet.getByTestId("activity-submit").click();
    const response = await responsePromise;
    expect(response.status()).toBe(201);
    const recorded = await response.json();
    expect(recorded.activity.channel).toBe("in_person");
    expect(recorded.activity.outcome).toBe("reached");

    await expect(sheet).toBeHidden();
    const newest = page.locator('[data-testid="activity-entry"]').first();
    await expect(newest).toContainText("Erreicht");
    await expect(newest).toContainText("Lieferadresse gemeinsam geprüft.");
    await expect(page.getByTestId("detail-follow-up")).toContainText(
      "Lieferadresse bestätigen",
    );
    await page.screenshot({
      path: `${artifactDirectory}/activity-recorded-mobile.png`,
      fullPage: true,
    });

    await page.reload();
    const persisted = page.locator(
      `[data-activity-id="${recorded.activity.id}"]`,
    );
    await expect(persisted).toContainText("Lieferadresse gemeinsam geprüft.");
    await expect(page.getByTestId("detail-follow-up")).toContainText(
      "Lieferadresse bestätigen",
    );
    await page.goto(`${baseUrl}/app/activities?view=contacts`);
    await expect(page.getByTestId("follow-ups-overdue")).toHaveCount(0);
    await expect(
      page.getByTestId("follow-ups-soon").getByTestId("sponsor-row"),
    ).toHaveCount(2);
    await page.screenshot({
      path: `${artifactDirectory}/activity-persisted-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
