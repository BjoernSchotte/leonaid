import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
const base = process.env.LEONAID_E2E_BASE_URL;
const proof = process.env.LEONAID_E2E_ARTIFACT_DIR;

test("publisher-only reviews, rejects a stale draft and retries an unacknowledged publication", async ({
  browser,
}) => {
  const fixture = JSON.parse(
    readFileSync(`${proof}/publisher-private.json`, "utf8"),
  );
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.publisher,
      url: base,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  try {
    const page = await context.newPage();
    let publicWrites = 0;
    page.on("request", (request) => {
      if (
        request.url().includes("/api/v1/public/surveys/") &&
        ["POST", "PUT"].includes(request.method())
      )
        publicWrites++;
    });
    await page.goto(`${base}/admin/surveys/${fixture.survey}`);
    const review = page.getByRole("region", {
      name: "Veröffentlichung prüfen",
      exact: true,
    });
    await expect(review).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Fragebogen bearbeiten" }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Teilantworten nach Inaktivität", { exact: true }),
    ).toHaveCount(0);
    await page
      .getByRole("button", { name: "Aktuellen Entwurf prüfen", exact: true })
      .click();
    await review
      .locator('[data-name="answer"] input[type="text"]')
      .fill("Preview never persisted");
    await review
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(
      review.locator('[data-name="answer"] input[type="text"]'),
    ).toHaveCount(0);
    expect(publicWrites).toBe(0);
    const stale = await context.request.put(
      `${base}/api/v1/surveys/${fixture.survey}/draft`,
      {
        data: {
          operationId: "unauthorized-edit",
          expectedRevision: 1,
          definition: { pages: [] },
        },
      },
    );
    expect(stale.status()).toBe(404);
    const designer = await browser.newContext({ ignoreHTTPSErrors: true });
    await designer.addCookies([
      {
        name: "__Host-leonaid_session",
        value: fixture.designer,
        url: base,
        secure: true,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);
    try {
      const changed = await designer.request.put(
        `${base}/api/v1/surveys/${fixture.survey}/draft`,
        {
          data: {
            operationId: "concurrent-edit",
            expectedRevision: 1,
            definition: {
              pages: [
                {
                  name: "one",
                  elements: [
                    {
                      type: "text",
                      name: "answer",
                      title: "Reviewed revision two",
                    },
                  ],
                },
              ],
            },
          },
        },
      );
      expect(changed.status()).toBe(200);
      const forbidden = await designer.request.get(
        `${base}/api/v1/surveys/${fixture.survey}/publication`,
      );
      expect(forbidden.status()).toBe(404);
    } finally {
      await designer.close();
    }
    await review
      .getByRole("button", { name: "Veröffentlichen", exact: true })
      .click();
    await expect(review.getByRole("alert")).toContainText("Entwurf");
    await expect(page.locator("[data-survey-status]")).toHaveAttribute(
      "data-survey-status",
      "draft",
    );
    await review
      .getByRole("button", { name: "Aktuellen Entwurf prüfen", exact: true })
      .click();
    await expect(
      review.getByText("Reviewed revision two", { exact: true }),
    ).toBeVisible();
    await review.screenshot({ path: `${proof}/publisher-review-mobile.png` });
    const attempts = [];
    await page.route(
      `**/api/v1/surveys/${fixture.survey}/publish`,
      async (route) => {
        attempts.push(route.request().postDataJSON());
        const response = await route.fetch();
        expect(response.status()).toBe(200);
        if (attempts.length === 1) await route.abort("failed");
        else await route.fulfill({ response });
      },
    );
    await review
      .getByRole("button", { name: "Veröffentlichen", exact: true })
      .click();
    await expect(review.getByRole("alert")).toBeVisible();
    await expect(
      review.getByRole("button", {
        name: "Aktuellen Entwurf prüfen",
        exact: true,
      }),
    ).toBeDisabled();
    await review
      .getByRole("button", {
        name: "Veröffentlichung erneut prüfen",
        exact: true,
      })
      .click();
    await expect(review.getByRole("status")).toContainText(
      "wurde veröffentlicht",
    );
    await expect(page.locator("[data-survey-status]")).toHaveAttribute(
      "data-survey-status",
      "active",
    );
    expect(attempts).toHaveLength(2);
    expect(attempts[0]).toEqual(attempts[1]);
    expect(attempts[0].expectedRevision).toBe(2);
    expect(publicWrites).toBe(0);
    await page.reload();
    await expect(
      page.getByRole("button", { name: "Teilnahme beenden", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Fragebogen bearbeiten" }),
    ).toHaveCount(0);
    writeFileSync(
      `${proof}/publisher-browser.json`,
      JSON.stringify({
        survey: fixture.survey,
        exactRetry: true,
        staleReviewRejected: true,
        previewPublicWrites: publicWrites,
      }),
    );
  } finally {
    await context.close();
  }
});
