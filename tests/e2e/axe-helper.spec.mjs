// The shared axe scan itself: runs on a plain page and fails fast where
// axe-core cannot finish (JavaScript disabled) instead of hanging.
import { analyzeAccessibility, WCAG_TAGS } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const PAGE = `<!doctype html><html lang="de"><head><title>Probe</title></head>
<body><main><h1>Probe</h1><p>Text</p></main></body></html>`;

test("analyzeAccessibility scans a page with scripts enabled", async ({
  browser,
}) => {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.setContent(PAGE);
    const results = await analyzeAccessibility(page, { tags: WCAG_TAGS });
    expect(results.violations).toEqual([]);
    expect(results.passes.length).toBeGreaterThan(0);
  } finally {
    await context.close();
  }
});

test("analyzeAccessibility fails fast with JavaScript disabled", async ({
  browser,
}) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.setContent(PAGE);
    const started = Date.now();
    await expect(analyzeAccessibility(page)).rejects.toThrow(
      /page scripts did not run within 2 s/,
    );
    expect(Date.now() - started).toBeLessThan(10_000);
  } finally {
    await context.close();
  }
});
