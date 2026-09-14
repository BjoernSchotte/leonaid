import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const baseURL = process.env.LEONAID_DOCS_BASE_URL;
const artifactDirectory = process.env.LEONAID_DOCS_ARTIFACT_DIR;
const expectedRevision = process.env.LEONAID_DOCS_EXPECTED_REVISION;
if (!baseURL || !artifactDirectory) {
  throw new Error(
    "LEONAID_DOCS_BASE_URL and LEONAID_DOCS_ARTIFACT_DIR are required",
  );
}
const siteRoot = new URL(baseURL.endsWith("/") ? baseURL : `${baseURL}/`);
const siteUrl = (relative = "") =>
  new URL(relative.replace(/^\/+/, ""), siteRoot).href;

const observations = [];

async function waitUntilReady(request) {
  await expect
    .poll(
      async () => {
        try {
          return (await request.get(siteUrl("build-manifest.json"))).status();
        } catch {
          return 0;
        }
      },
      { timeout: 30_000 },
    )
    .toBe(200);
}

async function scan(page, label) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const serious = result.violations.filter((finding) =>
    ["critical", "serious"].includes(finding.impact),
  );
  observations.push({
    label,
    passedRules: result.passes.length,
    incompleteRules: result.incomplete.map((finding) => finding.id),
    violations: result.violations,
  });
  expect(
    serious,
    `${label}: critical or serious accessibility findings`,
  ).toEqual([]);
}

async function search(page, query) {
  return page.evaluate(
    async ({ script, term }) => {
      const pagefind = await import(script);
      await pagefind.init();
      const result = await pagefind.search(term);
      return Promise.all(
        result.results.slice(0, 10).map(async (entry) => {
          const data = await entry.data();
          return { title: data.meta.title, url: data.url };
        }),
      );
    },
    { script: new URL("pagefind/pagefind.js", siteRoot).pathname, term: query },
  );
}

test.beforeAll(async ({ request }) => {
  await mkdir(artifactDirectory, { recursive: true });
  await waitUntilReady(request);
});

test.afterAll(async () => {
  await writeFile(
    path.join(artifactDirectory, "accessibility.json"),
    `${JSON.stringify(observations, null, 2)}\n`,
  );
});

test("serves the exact manifested bilingual artifact", async ({
  page,
  request,
}) => {
  const response = await request.get(siteUrl("build-manifest.json"));
  expect(response.status()).toBe(200);
  const manifest = await response.json();
  expect(manifest.schemaVersion).toBe(1);
  expect(manifest.sourceSha).toMatch(/^([0-9a-f]{40}|development)$/);
  if (expectedRevision) expect(manifest.sourceSha).toBe(expectedRevision);
  expect(manifest.documentation).toMatchObject({
    defaultLocale: "de",
    locales: ["de", "en"],
    publishedPages: 62,
    languagePairs: 31,
  });
  expect(manifest.api.sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(manifest.hosting.publicUrl).toBe(
    `${manifest.hosting.siteUrl.replace(/\/$/, "")}${manifest.hosting.basePath}/`,
  );
  expect(new URL(manifest.hosting.siteUrl).protocol).toBe("https:");
  expect(new URL(manifest.hosting.publicUrl).pathname).toBe(siteRoot.pathname);

  await page.goto(siteUrl());
  await expect(page).toHaveURL(siteUrl("de/"));
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Hilfe, die zur Aufgabe passt.",
    }),
  ).toBeVisible();
  await expect(
    page.locator('meta[name="leonaid-docs-revision"]'),
  ).toHaveAttribute("content", manifest.sourceSha);
});

test("keeps navigation, language switch and search localized", async ({
  page,
}) => {
  await page.goto(siteUrl("de/ops/tutorials/local-demo/"));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Lokale Demo installieren",
  );
  await expect(
    page.getByRole("link", { name: "LeonAid betreiben" }).first(),
  ).toBeVisible();
  const germanResults = await search(page, "Lieferfenster");
  const germanPath = new URL("de/", siteRoot).pathname;
  expect(
    germanResults.some((entry) =>
      new URL(entry.url, siteRoot).pathname.startsWith(germanPath),
    ),
  ).toBe(true);

  const language = page.getByLabel("Sprache wählen").first();
  await language.selectOption({ label: "English" });
  await expect(page).toHaveURL(siteUrl("en/ops/tutorials/local-demo/"));
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Install a local demo",
  );
  await expect(
    page.getByText("Developing LeonAid", { exact: true }).first(),
  ).toBeVisible();

  const englishResults = await search(page, "delivery window");
  const englishPath = new URL("en/", siteRoot).pathname;
  expect(
    englishResults.some((entry) =>
      new URL(entry.url, siteRoot).pathname.startsWith(englishPath),
    ),
  ).toBe(true);
});

test("is accessible by keyboard at desktop and 200 percent zoom", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  try {
    await page.goto(siteUrl("en/dev/reference/api/"));
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Skip to content" }),
    ).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#_top$/);
    await expect(page.locator("#_top")).toBeVisible();
    await scan(page, "desktop API reference");
    await page.screenshot({
      path: path.join(artifactDirectory, "desktop-api-reference.png"),
      fullPage: false,
    });

    await page.evaluate(() => {
      document.documentElement.style.zoom = "200%";
    });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
    await scan(page, "desktop API reference at 200 percent zoom");
    await page.screenshot({
      path: path.join(artifactDirectory, "desktop-api-reference-zoom-200.png"),
      fullPage: false,
    });
  } finally {
    await context.close();
  }
});

test("keeps the 375 pixel mobile entry usable", async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 375, height: 812 },
  });
  const page = await context.newPage();
  try {
    await page.goto(siteUrl("de/"));
    await expect(
      page.getByRole("link", { name: "LeonAid verwenden" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "LeonAid betreiben" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Entwicklung" })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    ).toBe(true);
    await scan(page, "375 pixel German entry");
    await page.screenshot({
      path: path.join(artifactDirectory, "mobile-german-entry.png"),
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
