import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;
const berndSession = process.env.BERND_SESSION;
const klaraSession = process.env.KLARA_SESSION;

if (
  !baseUrl ||
  !artifactDirectory ||
  !annaSession ||
  !berndSession ||
  !klaraSession
) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und alle Persona-Sitzungen sind erforderlich",
  );
}

async function pageFor(browser, session, viewport) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: session,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  return { context, page: await context.newPage() };
}

async function expectNoSeriousA11yIssues(page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter(({ impact }) =>
      ["critical", "serious"].includes(impact),
    ),
  ).toEqual([]);
}

test("Anna sieht exklusive und gemeinsame öffentliche Bestellungen", async ({
  browser,
}) => {
  const { context, page } = await pageFor(browser, annaSession, {
    width: 390,
    height: 844,
  });
  try {
    await page.goto(`${baseUrl}/app/activities`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Anna Akquise",
    );
    await expect(
      page.getByRole("heading", { name: "Neues & Aktivitäten" }),
    ).toBeVisible();
    await expect(
      page.locator('[data-testid="activity-feed-unread-count"] strong'),
    ).toHaveText("2");
    const entries = page.locator('[data-testid="activity-feed-entry"]');
    await expect(entries).toHaveCount(2);
    await expect(entries).toContainText([
      /Doppelkontakt AG/,
      /Musterwerk GmbH/,
    ]);
    await expect(entries.filter({ hasText: "Doppelkontakt AG" })).toContainText(
      "2 Boxen · 48 Stück",
    );
    await expect(entries.filter({ hasText: "Musterwerk GmbH" })).toContainText(
      "1 Box · 24 Stück",
    );
    await expect(
      page.locator('[data-testid="activity-feed-next-action"]'),
    ).toHaveCount(2);

    await page.screenshot({
      path: `${artifactDirectory}/activity-feed-anna-mobile.png`,
      fullPage: true,
    });
    await expectNoSeriousA11yIssues(page);

    const musterwerk = entries.filter({ hasText: "Musterwerk GmbH" });
    const markResponse = page.waitForResponse(
      (response) =>
        response.url().includes("/api/v1/activity-feed/") &&
        response.request().method() === "PATCH",
    );
    await musterwerk
      .locator('[data-testid="activity-feed-read-toggle"]')
      .click();
    expect((await markResponse).status()).toBe(200);
    await expect(
      page.locator('[data-testid="activity-feed-unread-count"] strong'),
    ).toHaveText("1");

    await page.getByRole("tab", { name: /Ungelesen/ }).click();
    await expect(entries).toHaveCount(1);
    await expect(entries).toContainText("Doppelkontakt AG");
    await expect(entries).not.toContainText("Musterwerk GmbH");

    await page.getByRole("tab", { name: "Kontakt dokumentieren" }).click();
    await expect(
      page.getByRole("heading", { name: "Aktivitäten & Wiedervorlagen" }),
    ).toBeVisible();
  } finally {
    await context.close();
  }
});

test("Bernd sieht den gemeinsam betreuten Sponsor mit eigener Folgeaktion", async ({
  browser,
}) => {
  const { context, page } = await pageFor(browser, berndSession, {
    width: 390,
    height: 844,
  });
  try {
    await page.goto(`${baseUrl}/app/activities`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Bernd Binder",
    );
    const entries = page.locator('[data-testid="activity-feed-entry"]');
    await expect(entries).toHaveCount(1);
    await expect(entries).toContainText("Doppelkontakt AG");
    const nextAction = entries.locator(
      '[data-testid="activity-feed-next-action"]',
    );
    await expect(nextAction).toHaveText(/Kontakt und Bestellung abstimmen/);
    await expect(nextAction).toHaveAttribute(
      "href",
      /view=contacts&assignment=60000000-0000-4000-8000-000000000004/,
    );
  } finally {
    await context.close();
  }
});

test("Klara bearbeitet die unzugeordnete Bestellung im Admin-Arbeitsvorrat", async ({
  browser,
}) => {
  const { context, page } = await pageFor(browser, klaraSession, {
    width: 1440,
    height: 1000,
  });
  try {
    await page.goto(`${baseUrl}/admin/activities`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Klara Kern",
    );
    await expect(
      page.getByRole("heading", { name: "Neues & Aktivitäten" }),
    ).toBeVisible();
    const entries = page.locator('[data-testid="activity-feed-entry"]');
    await expect(entries).toHaveCount(1);
    await expect(entries).toContainText("Freie Firma e.K.");
    await expect(entries).toContainText("3 Boxen · 72 Stück");
    const nextAction = entries.locator(
      '[data-testid="activity-feed-next-action"]',
    );
    await expect(nextAction).toHaveText(/Bestellung prüfen und zuordnen/);
    await expect(nextAction).toHaveAttribute("href", /\/admin\/orders\?/);
    await expectNoSeriousA11yIssues(page);
    await page.screenshot({
      path: `${artifactDirectory}/activity-feed-admin-desktop.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
