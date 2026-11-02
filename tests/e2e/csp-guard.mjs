// Fails every browser test whose pages raise a Content-Security-Policy
// violation. Specs import `test` and `expect` from here instead of
// "@playwright/test", so all suites that load LeonAid through Caddy prove the
// real headers do not block any script, style, frame or connection.
//
// Every browser context, whether created by Playwright's `context` fixture or
// by a spec through `browser.newContext()`/`browser.newPage()`, gets an init
// script that forwards `securitypolicyviolation` events from every frame.
import { expect, test as base } from "@playwright/test";

const BINDING = "__leonaidReportCspViolation";
const guarded = new WeakSet();
const violations = [];
// Browser console reports of the same violations; they often name the
// blocked resource more precisely than the event and explain failures.
const consoleReports = [];

async function guard(context) {
  if (guarded.has(context)) return context;
  guarded.add(context);
  context.on("console", (message) => {
    if (/content.security.policy/i.test(message.text())) {
      consoleReports.push(message.text());
    }
  });
  await context.exposeBinding(BINDING, ({ frame }, violation) => {
    violations.push({ ...violation, frame: frame.url() });
  });
  await context.addInitScript((binding) => {
    // Before every WebKit screenshot, Playwright briefly inserts
    // <style>body {}</style> to sync animations; the policy rightly blocks it.
    // Such harness styles are counted here and their violations skipped.
    let harnessStyles = 0;
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeName === "STYLE" && node.textContent === "body {}") {
            harnessStyles += 1;
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
    document.addEventListener("securitypolicyviolation", (event) => {
      // Browsers render non-HTML responses (JSON, plain text) in a generated
      // viewer document whose own inline styles the policy blocks.
      if (!/html|xml/.test(document.contentType)) return;
      if (
        event.effectiveDirective === "style-src-elem" &&
        harnessStyles > 0 &&
        !(event.target instanceof Element && event.target.isConnected)
      ) {
        harnessStyles -= 1;
        return;
      }
      window[binding]?.({
        directive: event.effectiveDirective,
        blocked: event.blockedURI,
        source: event.sourceFile,
        line: event.lineNumber,
        sample: event.sample,
        disposition: event.disposition,
        // The element that carried the blocked inline code, if any.
        element:
          event.target instanceof Element
            ? event.target.outerHTML.slice(0, 160)
            : "",
        document: event.documentURI,
      });
    });
  }, BINDING);
  return context;
}

function takeViolations() {
  const found = violations.splice(0, violations.length);
  const reports = consoleReports.splice(0, consoleReports.length);
  if (found.length > 0 && reports.length > 0) {
    found.push({ console: reports });
  }
  return found;
}

function describe(found) {
  return found
    .map(({ console: reports, ...violation }) =>
      reports
        ? `browser console:\n  ${reports.join("\n  ")}`
        : describeOne(violation),
    )
    .join("\n");
}

function describeOne({
  directive,
  blocked,
  document,
  source,
  line,
  sample,
  element,
}) {
  return (
    `${directive} blocked ${blocked || "inline"} on ${document}` +
    (source ? ` (${source}:${line})` : "") +
    (sample ? ` sample=${JSON.stringify(sample)}` : "") +
    (element ? ` element=${element}` : "")
  );
}

export const test = base.extend({
  browser: [
    async ({ browser }, use) => {
      const newContext = browser.newContext.bind(browser);
      browser.newContext = async (options) => guard(await newContext(options));
      await use(browser);
      // Violations raised in beforeAll/afterAll hooks surface here.
      const found = takeViolations();
      if (found.length > 0) {
        throw new Error(
          `Content-Security-Policy violations:\n${describe(found)}`,
        );
      }
    },
    { scope: "worker" },
  ],
  context: async ({ context }, use) => {
    await use(await guard(context));
  },
  cspViolations: [
    async ({}, use) => {
      takeViolations();
      await use(undefined);
      const found = takeViolations();
      expect(
        found,
        `Content-Security-Policy violations:\n${describe(found)}`,
      ).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

/**
 * Screenshots a locator with the sticky app top bar taken out of the flow.
 * Playwright's `screenshot({ style })` injects an inline <style>, which the
 * strict CSP blocks (so it never applied); the CSSOM is not subject to CSP.
 */
export async function screenshotWithStaticTopbar(locator, options) {
  const topbars = locator.page().locator(".ui-topbar");
  await topbars.evaluateAll((elements) => {
    for (const element of elements) {
      element.style.setProperty("position", "static", "important");
    }
  });
  try {
    await locator.screenshot(options);
  } finally {
    await topbars.evaluateAll((elements) => {
      for (const element of elements) element.style.removeProperty("position");
    });
  }
}
