import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL and LEONAID_E2E_ARTIFACT_DIR are required",
  );
}

test.use({
  ignoreHTTPSErrors: true,
  launchOptions: { args: ["--ignore-certificate-errors"] },
  viewport: { width: 390, height: 844 },
});

test("WCAG- und Web-Vitals-Budgets werden im definierten mobilen Profil eingehalten", async ({
  context,
  page,
}) => {
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    connectionType: "cellular4g",
    downloadThroughput: (10 * 1024 * 1024) / 8,
    latency: 40,
    offline: false,
    uploadThroughput: (5 * 1024 * 1024) / 8,
  });
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await page.addInitScript(() => {
    window.__leonaidVitals = { cls: 0, inp: 0, lcp: 0 };
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__leonaidVitals.lcp = Math.max(
          window.__leonaidVitals.lcp,
          entry.startTime,
        );
      }
    }).observe({ buffered: true, type: "largest-contentful-paint" });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) {
          window.__leonaidVitals.cls += entry.value;
        }
      }
    }).observe({ buffered: true, type: "layout-shift" });
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__leonaidVitals.inp = Math.max(
          window.__leonaidVitals.inp,
          entry.duration,
        );
      }
    }).observe({ buffered: true, durationThreshold: 16, type: "event" });
  });

  await page.goto(`${baseUrl}/krapfentaxi`, { waitUntil: "networkidle" });
  await page.getByRole("link", { name: "Angebote ansehen" }).click();
  await expect(page).toHaveURL(/#angebote$/);
  await page.waitForTimeout(250);

  const vitals = await page.evaluate(() => window.__leonaidVitals);
  const inpObserved = vitals.inp > 0;
  const performanceReport = {
    budgets: {
      cls: 0.1,
      inpMilliseconds: 200,
      lcpMilliseconds: 2500,
    },
    measured: {
      cls: Number(vitals.cls.toFixed(4)),
      inpMilliseconds: inpObserved ? Math.round(vitals.inp) : 16,
      lcpMilliseconds: Math.round(vitals.lcp),
    },
    measurementNotes: {
      inp: inpObserved
        ? "Event Timing hat die echte Link-Interaktion beobachtet."
        : "Kein Eingabe-Event erreichte die 16-ms-Beobachtungsschwelle; ausgewiesen ist diese Obergrenze.",
    },
    profile: {
      browser: "Chromium 138 via Playwright 1.54.1",
      cpuThrottlingRate: 4,
      network: {
        downloadMbps: 10,
        latencyMilliseconds: 40,
        uploadMbps: 5,
      },
      route: "/krapfentaxi",
      viewport: "390x844",
    },
  };
  await writeFile(
    `${artifactDirectory}/performance-report.json`,
    `${JSON.stringify(performanceReport, null, 2)}\n`,
  );
  expect(performanceReport.measured.lcpMilliseconds).toBeGreaterThan(0);
  expect(performanceReport.measured.lcpMilliseconds).toBeLessThanOrEqual(
    performanceReport.budgets.lcpMilliseconds,
  );
  expect(performanceReport.measured.inpMilliseconds).toBeLessThanOrEqual(
    performanceReport.budgets.inpMilliseconds,
  );
  expect(performanceReport.measured.cls).toBeLessThanOrEqual(
    performanceReport.budgets.cls,
  );

  const axeResults = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const seriousFindings = axeResults.violations.filter(({ impact }) =>
    ["critical", "serious"].includes(impact),
  );
  const accessibilityReport = {
    checkedUrl: `${baseUrl}/krapfentaxi`,
    criticalOrSeriousFindings: seriousFindings.map(
      ({ description, help, impact, id, nodes }) => ({
        description,
        help,
        id,
        impact,
        nodeCount: nodes.length,
      }),
    ),
    standard: "WCAG 2.2 AA",
    totalViolations: axeResults.violations.length,
  };
  await writeFile(
    `${artifactDirectory}/accessibility-report.json`,
    `${JSON.stringify(accessibilityReport, null, 2)}\n`,
  );
  expect(seriousFindings).toEqual([]);
});
