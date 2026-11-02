// Makes a browser proof fail when any page raises a Content-Security-Policy
// violation. Wrap the launched browser:
//
//   const browser = guardCsp(await engine.launch({ headless: true }));
//
// Every context the proof creates forwards `securitypolicyviolation` events
// from every frame. browser.close() prints them and sets a failing exit code;
// it does not throw, so an earlier proof error stays the reported cause.
const BINDING = "__leonaidReportCspViolation";

export function guardCsp(browser) {
  const violations = [];
  const newContext = browser.newContext.bind(browser);
  browser.newContext = async (options) => {
    const context = await newContext(options);
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
          document: event.documentURI,
        });
      });
    }, BINDING);
    return context;
  };
  const close = browser.close.bind(browser);
  browser.close = async (options) => {
    await close(options);
    if (violations.length === 0) return;
    process.exitCode = 1;
    for (const { directive, blocked, document, source, line, sample } of violations) {
      console.error(
        `csp-guard: ${browser.browserType().name()}: ${directive} blocked ` +
          `${blocked || "inline"} on ${document}` +
          (source ? ` (${source}:${line})` : "") +
          (sample ? ` sample=${JSON.stringify(sample)}` : ""),
      );
    }
    violations.length = 0;
  };
  return browser;
}
