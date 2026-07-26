import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

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

test("POC-062 Manifest, Installation, Update und Offline-Hinweis sind echt", async ({
  browserName,
  context,
  page,
}) => {
  test.setTimeout(60_000);
  test.skip(
    browserName !== "chromium",
    "Installability wird über Chromium-CDP geprüft.",
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
      () =>
        page.evaluate(async () =>
          (await navigator.serviceWorker.getRegistrations()).map(
            (registration) => registration.scope,
          ),
        ),
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
