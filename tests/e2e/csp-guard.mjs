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

async function guard(context) {
  if (guarded.has(context)) return context;
  guarded.add(context);
  await context.exposeBinding(BINDING, ({ frame }, violation) => {
    violations.push({ ...violation, frame: frame.url() });
  });
  await context.addInitScript((binding) => {
    document.addEventListener("securitypolicyviolation", (event) => {
      window[binding]?.({
        directive: event.effectiveDirective,
        blocked: event.blockedURI,
        source: event.sourceFile,
        line: event.lineNumber,
        sample: event.sample,
        disposition: event.disposition,
        document: event.documentURI,
      });
    });
  }, BINDING);
  return context;
}

function takeViolations() {
  return violations.splice(0, violations.length);
}

function describe(found) {
  return found
    .map(
      ({ directive, blocked, document, source, line, sample }) =>
        `${directive} blocked ${blocked || "inline"} on ${document}` +
        (source ? ` (${source}:${line})` : "") +
        (sample ? ` sample=${JSON.stringify(sample)}` : ""),
    )
    .join("\n");
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
        throw new Error(`Content-Security-Policy violations:\n${describe(found)}`);
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
      expect(found, `Content-Security-Policy violations:\n${describe(found)}`).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };
