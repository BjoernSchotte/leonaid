import { chromium } from "@playwright/test";
import { writeFileSync } from "node:fs";
const browser = await chromium.launch();
const page = await browser.newPage();
const results = [];
try {
  for (const [name, html, method] of [
    ["absent", "<p>PRIVATE_CANARY</p>", "press"],
    ["hidden", '<button id="PRIVATE_CANARY" style="display:none">private</button>', "click"],
    ["disabled", '<button id="PRIVATE_CANARY" disabled>private</button>', "click"],
    ["intercepted", '<button id="PRIVATE_CANARY">private</button><div style="position:fixed;inset:0;z-index:99"></div>', "click"],
    ["outside", '<button id="PRIVATE_CANARY" style="position:fixed;left:-1000px;top:10px">private</button>', "click"],
  ]) {
    await page.setContent(html);
    try {
      const target = page.locator("#PRIVATE_CANARY");
      if (method === "press") await target.press("Space", { timeout: 10000 });
      else await target.click({ timeout: 10000 });
      throw new Error("Fixture unexpectedly succeeded");
    } catch (error) {
      if (error.name !== "TimeoutError") throw error;
      results.push({ name, raw: error.stack });
    }
  }
  writeFileSync("/proof/browser-errors.json", JSON.stringify(results), { mode: 0o600 });
} finally { await browser.close(); }
