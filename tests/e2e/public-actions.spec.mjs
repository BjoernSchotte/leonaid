import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL and LEONAID_E2E_ARTIFACT_DIR are required",
  );
}

test.use({ ignoreHTTPSErrors: true });

async function expectNoHorizontalScroll(page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

async function expectTouchTargets(page) {
  const undersized = await page.evaluate(() =>
    [...document.querySelectorAll("a, button")]
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
          style.visibility !== "hidden" &&
          style.display !== "none" &&
          rect.width > 0 &&
          rect.height > 0 &&
          (rect.width < 44 || rect.height < 44)
        );
      })
      .map((element) => ({
        height: Math.round(element.getBoundingClientRect().height),
        label:
          element.getAttribute("aria-label") ?? element.textContent?.trim(),
        width: Math.round(element.getBoundingClientRect().width),
      })),
  );
  expect(undersized).toEqual([]);
}

test("aktive, inaktive und archivierte Public-Seite bleiben in jeder Browser-Engine fachlich gleich", async ({
  browserName,
  page,
}) => {
  const response = await page.goto(`${baseUrl}/krapfentaxi`);
  expect(response?.status()).toBe(200);
  expect(response?.headers()["x-leonaid-public-state"]).toBe("published");
  await expect(page).toHaveTitle("Krapfentaxi 2027 · LeonAid");
  await expect(page.getByTestId("public-action-name")).toHaveText(
    "Krapfentaxi 2027",
  );
  await expect(page.getByTestId("public-offerings")).toContainText(
    "Krapfenbox",
  );
  await expect(page.getByTestId("public-offerings")).toContainText("24 Stück");
  await expect(page.getByTestId("public-offerings")).toContainText("36,00");
  await expect(
    page.getByRole("heading", { name: "Wem die Aktion hilft" }),
  ).toBeVisible();
  await expect(page.getByText("Zukunftswerk Beispielstadt")).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name: "Transparent, bevor Daten erhoben werden.",
    }),
  ).toBeVisible();
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    `${baseUrl}/archive/krapfentaxi-2027`,
  );
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
    "content",
    `${baseUrl}/community-routes.png`,
  );
  await expect(page.locator("script")).toHaveCount(0);
  await expectNoHorizontalScroll(page);
  await expectTouchTargets(page);

  await page.keyboard.press("Tab");
  await expect(page.getByText("Zum Inhalt springen")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main-content$/);

  await page.screenshot({
    path: `${artifactDirectory}/public-active-${browserName}-390.png`,
    fullPage: true,
  });

  const archiveResponse = await page.goto(
    `${baseUrl}/archive/krapfentaxi-2027`,
  );
  expect(archiveResponse?.status()).toBe(200);
  expect(archiveResponse?.headers()["x-leonaid-public-state"]).toBe("archive");
  await expect(
    page.getByRole("heading", { name: "Diese Aktion ist abgeschlossen." }),
  ).toBeVisible();
  await expect(page.getByTestId("public-offerings")).toContainText(
    "Krapfenbox",
  );
  await expect(page.locator("form")).toHaveCount(0);
  await expect(page.locator("script")).toHaveCount(0);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    `${baseUrl}/archive/krapfentaxi-2027`,
  );

  const inactiveResponse = await page.goto(`${baseUrl}/winterpause`);
  expect(inactiveResponse?.status()).toBe(200);
  expect(inactiveResponse?.headers()["x-leonaid-public-state"]).toBe(
    "inactive",
  );
  await expect(
    page.getByRole("heading", { name: "Derzeit keine aktive Aktion" }),
  ).toBeVisible();
  await expect(page.getByText("Krapfentaxi 2027")).toHaveCount(0);
  await expect(page.locator("form")).toHaveCount(0);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
    "content",
    "noindex,follow",
  );

  if (browserName === "chromium") {
    await page.screenshot({
      path: `${artifactDirectory}/public-inactive-chromium-390.png`,
      fullPage: true,
    });
  }
});

test("öffentliche Aktionsseite bleibt von 320 bis 1440 Pixeln lesbar", async ({
  browserName,
  page,
}) => {
  test.skip(
    browserName !== "chromium",
    "Die Browser-Parität ist oben bewiesen; dieser Lauf archiviert die visuellen Randbreiten.",
  );

  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto(`${baseUrl}/krapfentaxi`);
  await expectNoHorizontalScroll(page);
  await expectTouchTargets(page);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${baseUrl}/krapfentaxi`);
  await expectNoHorizontalScroll(page);
  await page.screenshot({
    path: `${artifactDirectory}/public-active-chromium-1440.png`,
    fullPage: true,
  });

  await page.goto(`${baseUrl}/archive/krapfentaxi-2027`);
  await page.screenshot({
    path: `${artifactDirectory}/public-archive-chromium-1440.png`,
    fullPage: true,
  });
});
