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
      // Before every WebKit screenshot, Playwright briefly inserts
      // <style>body {}</style> to sync animations; the policy rightly blocks
      // it. Such harness styles are counted here and their violations skipped.
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
  };
  const close = browser.close.bind(browser);
  browser.close = async (options) => {
    await close(options);
    if (violations.length === 0) return;
    process.exitCode = 1;
    for (const {
      directive,
      blocked,
      document,
      source,
      line,
      sample,
      element,
    } of violations) {
      console.error(
        `csp-guard: ${browser.browserType().name()}: ${directive} blocked ` +
          `${blocked || "inline"} on ${document}` +
          (source ? ` (${source}:${line})` : "") +
          (sample ? ` sample=${JSON.stringify(sample)}` : "") +
          (element ? ` element=${element}` : ""),
      );
    }
    violations.length = 0;
  };
  return browser;
}
