import { expect, test } from "@playwright/test";
import { writeFile } from "node:fs/promises";
import path from "node:path";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

test("POC-013 liest denselben Golden-Sponsor sichtbar in der PWA", async ({
  context,
  page,
}) => {
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: annaSession,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("display-name")).toHaveText("Anna Akquise");
  await expect(
    page.getByRole("heading", { name: "Meine Sponsoren" }),
  ).toBeVisible();

  const goldenSponsor = page
    .getByTestId("sponsor-row")
    .filter({ hasText: "Musterwerk GmbH" });
  await expect(goldenSponsor).toHaveCount(1);
  await expect(goldenSponsor).toHaveAttribute(
    "data-party-id",
    "40000000-0000-4000-8000-000000000001",
  );

  await page.screenshot({
    path: path.join(artifactDirectory, "testkit-ui.png"),
    fullPage: true,
  });
  await writeFile(
    path.join(artifactDirectory, "ui-proof.json"),
    `${JSON.stringify(
      {
        displayName: "Musterwerk GmbH",
        partyId: await goldenSponsor.getAttribute("data-party-id"),
        persona: "Akquisiteurin Anna Akquise",
        url: page.url(),
      },
      null,
      2,
    )}\n`,
  );
});
