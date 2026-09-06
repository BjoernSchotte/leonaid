import { test, expect } from "@playwright/test";
import { writeFileSync, readFileSync } from "node:fs";
const baseURL = "http://localhost:8080";
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;
if (!proof) throw new Error("Artifact directory required");

test("packed consumer saves a multipage response in its own host", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1100, height: 850 },
  });
  const page = await context.newPage();
  await page.goto(baseURL);
  const control = page.getByRole("button", { name: "Change host theme" });
  await expect(control).toHaveCSS("background-color", "rgb(23, 61, 56)");
  await page.getByRole("button", { name: "Start feedback" }).click();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(
    page.getByText("Please answer this question.", { exact: true }),
  ).toBeVisible();
  await page.locator("[data-name=name] input").fill("Independent respondent");
  await expect(
    page.getByText("Saved by the independent host", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page
    .locator("[data-name=feedback] textarea")
    .fill("More community events");
  await expect(
    page.getByText("Saved by the independent host", { exact: true }),
  ).toBeVisible();
  await control.click();
  await expect(control).toHaveCSS("background-color", "rgb(23, 61, 56)");
  await expect(page.locator(".sd-theme-root").first()).toHaveCSS(
    "--sjs2-color-project-brand-600",
    "#85451b",
  );
  const state = await page.evaluate(async () => ({
    participation: await (await fetch("/api/participation")).json(),
    diagnostics: await (await fetch("/api/diagnostics")).json(),
  }));
  expect(state.participation.value.response.answers).toEqual({
    name: "Independent respondent",
    feedback: "More community events",
  });
  expect(state.diagnostics.value.participations).toBe(1);
  await context.storageState({ path: `${proof}/consumer-browser.json` });
  writeFileSync(`${proof}/consumer-before.json`, JSON.stringify(state));
  await page.screenshot({
    path: `${proof}/consumer-before.png`,
    fullPage: true,
  });
  await context.close();
});

test("packed consumer restores after backend restart without an extra save", async ({
  browser,
}) => {
  const before = JSON.parse(
    readFileSync(`${proof}/consumer-before.json`, "utf8"),
  );
  const context = await browser.newContext({
    storageState: `${proof}/consumer-browser.json`,
    viewport: { width: 390, height: 844 },
  });
  const page = await context.newPage();
  const writes = [];
  page.on("request", (request) => {
    if (["POST", "PUT", "PATCH"].includes(request.method()))
      writes.push(request.method());
  });
  await page.goto(baseURL);
  await expect(page.locator("[data-name=feedback] textarea")).toHaveValue(
    "More community events",
  );
  const restored = await page.evaluate(async () => ({
    participation: await (await fetch("/api/participation")).json(),
    diagnostics: await (await fetch("/api/diagnostics")).json(),
  }));
  expect(restored).toEqual(before);
  expect(writes).toEqual([]);
  await page.getByRole("button", { name: "Complete", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your feedback is safe" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Your feedback is safe" }),
  ).toBeVisible();
  const final = await page.evaluate(async () =>
    (await fetch("/api/participation")).json(),
  );
  expect(final.value.id).toBe(before.participation.value.id);
  expect(final.value.response.status).toBe("completed");
  expect(final.value.response.answers).toEqual(
    before.participation.value.response.answers,
  );
  await page.screenshot({
    path: `${proof}/consumer-completed.png`,
    fullPage: true,
  });
  await context.close();
});
