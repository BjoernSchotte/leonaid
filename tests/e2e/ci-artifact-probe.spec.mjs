import { expect, test } from "./csp-guard.mjs";
import path from "node:path";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL und LEONAID_E2E_ARTIFACT_DIR sind erforderlich",
  );
}

test("POC-003 deliberately produces safe failure artifacts", async ({
  page,
}) => {
  await page.goto(`${baseUrl}/krapfentaxi`);
  await expect(
    page.getByRole("heading", { name: "Krapfentaxi 2026" }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(artifactDirectory, "artifact-probe.png"),
    fullPage: true,
  });

  expect(
    "absichtlicher-ci-artefakt-probe-fehler",
    "Dieser Probe-Branch muss rot werden und seine Artefakte trotzdem hochladen.",
  ).toBe("grün");
});
