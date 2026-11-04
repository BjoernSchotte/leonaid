import { test, expect } from "./csp-guard.mjs";
import { writeFileSync, readFileSync } from "node:fs";
const baseURL = "http://localhost:8080";
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!proof) throw new Error("Artifact directory required");

// Runs in its own Playwright call after "packed consumer saves a multipage
// response" (tools/surveys/package.sh), in the same container before the
// restart: it exports the participation that test saved, and the restart
// test reads consumer-export.json.
test("packed consumer retries a lost export acknowledgement", async ({
  browser,
}) => {
  const context = await browser.newContext({
    storageState: `${proof}/consumer-browser.json`,
    viewport: { width: 1100, height: 850 },
  });
  const page = await context.newPage();
  await page.goto(baseURL);
  await expect(page.locator("[data-name=feedback] textarea")).toHaveValue(
    "More community events",
  );
  await page
    .getByRole("link", { name: "Download saved feedback", exact: true })
    .click();
  const panel = page.getByRole("region", {
    name: "Download your saved feedback",
    exact: true,
  });
  const exportRequests = [];
  let dropped = false;
  await page.route("**/api/exports", async (route) => {
    exportRequests.push(route.request().postDataJSON());
    if (!dropped) {
      dropped = true;
      expect((await route.fetch()).ok()).toBe(true);
      await route.abort("failed");
    } else await route.continue();
  });
  await panel
    .getByRole("button", { name: "Prepare my file", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText(
    "Connection interrupted",
  );
  const created = page.waitForResponse(
    (r) => r.url().endsWith("/api/exports") && r.status() === 200,
  );
  await panel
    .getByRole("button", { name: "Confirm the same request", exact: true })
    .click();
  const job = (await (await created).json()).value;
  await expect(
    panel.getByText("Your file is ready", { exact: true }),
  ).toBeVisible();
  expect(exportRequests).toHaveLength(2);
  expect(exportRequests[0]).toEqual(exportRequests[1]);
  const event = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Save my CSV", exact: true }).click();
  const download = await event;
  expect(await download.failure()).toBeNull();
  expect(download.suggestedFilename()).toBe("my-feedback.csv");
  const content = readFileSync(await download.path(), "utf8");
  expect(content).toContain('"Independent respondent","More community events"');
  expect(content).toContain(job.snapshotId);
  writeFileSync(
    `${proof}/consumer-export.json`,
    JSON.stringify({ job, content }),
  );
  await page.screenshot({
    path: `${proof}/consumer-exports.png`,
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    panel.getByRole("button", { name: "Save my CSV", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: `${proof}/consumer-exports-mobile.png`,
    fullPage: true,
  });
  await context.close();
});
