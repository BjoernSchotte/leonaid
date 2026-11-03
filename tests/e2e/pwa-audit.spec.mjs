import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

test.use({
  ignoreHTTPSErrors: true,
  launchOptions: {
    args: ["--ignore-certificate-errors"],
  },
  viewport: { width: 390, height: 844 },
});

test("POC-062 manifest, installation, update and offline notice are real", async ({
  browserName,
  context,
  page,
}) => {
  test.setTimeout(60_000);
  test.skip(
    browserName !== "chromium",
    "Installability is checked through Chromium CDP.",
  );
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
  await page.goto(`${baseUrl}/app/`);

  const manifestResponse = await page.request.get(
    `${baseUrl}/app/manifest.webmanifest`,
  );
  expect(manifestResponse.status()).toBe(200);
  const manifest = await manifestResponse.json();
  expect(manifest).toMatchObject({
    display: "standalone",
    name: "LeonAid Akquise",
    scope: "/app/",
    start_url: "/app/",
  });
  expect(manifest.icons).toEqual(
    expect.arrayContaining([
      expect.objectContaining({ sizes: "192x192" }),
      expect.objectContaining({ sizes: "512x512" }),
    ]),
  );
  for (const icon of manifest.icons) {
    const iconResponse = await page.request.get(`${baseUrl}${icon.src}`);
    expect(iconResponse.status()).toBe(200);
    expect(iconResponse.headers()["content-type"]).toContain("image/svg+xml");
    const iconSource = await iconResponse.text();
    expect(iconSource.length).toBeGreaterThan(250);
    expect(iconSource).toContain("<svg");
    expect(iconSource).toContain("viewBox");
  }

  const session = await context.newCDPSession(page);
  await session.send("Page.enable");
  await expect
    .poll(async () => (await session.send("Page.getAppManifest")).url)
    .toBe(`${baseUrl}/app/manifest.webmanifest`);
  const appManifest = await session.send("Page.getAppManifest");
  expect(appManifest.url).toBe(`${baseUrl}/app/manifest.webmanifest`);
  expect(appManifest.errors).toEqual([]);
  const installability = await session.send("Page.getInstallabilityErrors");
  expect(installability.installabilityErrors).toEqual([]);

  await expect
    .poll(
      async () => {
        try {
          return await page.evaluate(async () =>
            (await navigator.serviceWorker.getRegistrations()).map(
              (registration) => registration.scope,
            ),
          );
        } catch (error) {
          if (
            error instanceof Error &&
            error.message.includes("Execution context was destroyed")
          ) {
            await page.waitForLoadState("domcontentloaded");
            return [];
          }
          throw error;
        }
      },
      { timeout: 20_000 },
    )
    .toContain(`${baseUrl}/app/`);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload();
  await expect
    .poll(() =>
      page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
    )
    .toBe(true);
  await expect(page.locator("main h1")).toContainText("Guten Tag, Anna.");

  const serviceWorkerResponse = await page.request.get(`${baseUrl}/app/sw.js`);
  const serviceWorkerSource = await serviceWorkerResponse.text();
  expect(serviceWorkerSource).not.toContain('addEventListener("sync"');
  expect(serviceWorkerSource).not.toContain("backgroundSync");

  await page.evaluate(() => {
    window.dispatchEvent(new Event("leonaid:update-available"));
  });
  await expect(page.locator('[data-testid="pwa-update"]')).toContainText(
    "Eine neue Version ist bereit",
  );
  await page.screenshot({
    path: `${artifactDirectory}/pwa-update-chromium.png`,
    fullPage: true,
  });

  await context.setOffline(true);
  await expect(page.locator('[data-testid="offline-banner"]')).toContainText(
    "LeonAid speichert keine Änderungen im Hintergrund",
  );
  // The shell keeps the open page, its tabs and the gold network state.
  await expect(page.getByRole("img", { name: "Offline" })).toBeVisible();
  await expect(page.locator("main h1")).toContainText("Guten Tag, Anna.");
  await expect(
    page.getByRole("navigation", { name: "App-Navigation" }),
  ).toBeVisible();
  const offlineNavigation = await page.goto(
    `${baseUrl}/app/nicht-im-cache-${Date.now()}`,
  );
  expect(offlineNavigation?.status()).toBe(200);
  await expect(page).toHaveTitle("LeonAid ist offline");
  await expect(
    page.getByRole("heading", { name: "Gerade keine Verbindung" }),
  ).toBeVisible();
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter(({ impact }) =>
      ["critical", "serious"].includes(impact),
    ),
  ).toEqual([]);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-offline-chromium.png`,
    fullPage: true,
  });
});

test("Leitsystem shell keeps an open capture visible while offline", async ({
  context,
  page,
}) => {
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
  await page.goto(`${baseUrl}/app/sponsors`);
  await page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" })
    .getByRole("link", { name: "Bestellung" })
    .click();
  await expect(page.getByTestId("commitment-party")).toContainText(
    "Musterwerk GmbH",
  );
  // Orders have no tab of their own ("Neu" creates a sponsor).
  await expect(
    page
      .getByRole("navigation", { name: "App-Navigation" })
      .locator('[aria-current="page"]'),
  ).toHaveCount(0);
  const street = page.getByTestId("commitment-street");
  await street.fill("Offlineweg 7");
  await page.getByTestId("commitment-quantity").fill("3");

  await context.setOffline(true);
  const banner = page.getByTestId("offline-banner");
  await expect(banner).toBeVisible();
  await expect(banner.locator("..")).toHaveAttribute("role", "status");
  await expect(banner).toContainText("Du bist offline.");
  // What the acquirer already entered stays on screen and editable.
  await expect(street).toHaveValue("Offlineweg 7");
  await expect(street).toBeEditable();
  await expect(page.getByTestId("commitment-quantity")).toHaveValue("3");
  await expect(page.getByTestId("commitment-party")).toContainText(
    "Musterwerk GmbH",
  );
  // The gold glyph stays in the sticky bar; the banner sits under the bar.
  await expect(page.getByRole("img", { name: "Offline" })).toBeInViewport();
  await page.evaluate(() => window.scrollTo(0, 0));
  const bannerBox = await banner.boundingBox();
  const barBox = await page.locator(".pwa-bar").boundingBox();
  expect(bannerBox.y).toBeGreaterThanOrEqual(barBox.y + barBox.height - 1);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
  const results = await new AxeBuilder({ page }).analyze();
  expect(
    results.violations.filter(({ impact }) =>
      ["critical", "serious"].includes(impact),
    ),
  ).toEqual([]);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-offline-capture-chromium-390.png`,
    fullPage: true,
  });

  // Saving offline fails in Du wording and keeps every entry.
  await page.getByTestId("commitment-save-draft").click();
  await expect(page.locator("main")).toContainText(
    "Die Bestellung konnte nicht gespeichert werden. Prüfe deine Verbindung; deine Eingaben bleiben erhalten.",
  );
  await expect(street).toHaveValue("Offlineweg 7");
  await expect(page.getByTestId("commitment-quantity")).toHaveValue("3");
  await expect(page.getByTestId("commitment-party")).toContainText(
    "Musterwerk GmbH",
  );

  await context.setOffline(false);
  await expect(banner).toHaveCount(0);
  await expect(page.getByRole("img", { name: "Online" })).toBeVisible();
  await expect(street).toHaveValue("Offlineweg 7");
});
