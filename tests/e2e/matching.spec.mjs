import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und ANNA_SESSION sind erforderlich",
  );
}

test("Akquisiteurin prüft Neuanlage, Mehrdeutigkeit, Abbruch und Mehrfachzuordnung", async ({
  browser,
}) => {
  test.setTimeout(90_000);
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    ignoreHTTPSErrors: true,
  });
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
  const page = await context.newPage();
  const resolveBodies = [];
  page.on("request", (request) => {
    if (
      request.url().endsWith("/acquisition/sponsor-match/resolve") &&
      request.method() === "POST"
    ) {
      resolveBodies.push(request.postDataJSON());
    }
  });
  try {
    await page.goto(`${baseUrl}/app/sponsors`);
    await expect(page.locator('[data-testid="display-name"]')).toHaveText(
      "Anna Akquise",
    );
    await page.getByRole("tab", { name: "Sponsor erfassen" }).click();
    await expect(
      page.getByRole("heading", { name: "Sponsor erfassen" }),
    ).toBeVisible();
    await expect(page.locator("#sponsor-company-help")).toContainText(
      "CRM-Prüfung",
    );
    await expect(page.getByTestId("sponsor-company")).toHaveAttribute(
      "aria-describedby",
      "sponsor-company-help",
    );

    await page.getByRole("button", { name: "Privatperson" }).click();
    await page.locator("#sponsor-given-name").fill("MAX");
    await page.locator("#sponsor-family-name").fill("mustermann");
    await page.getByTestId("sponsor-preview").click();
    await expect(
      page.getByRole("heading", { name: "Mehrere mögliche Treffer" }),
    ).toBeVisible();
    await expect(page.locator(".candidate")).toHaveCount(2);
    await expect(page.getByTestId("sponsor-resolve")).toBeDisabled();
    await page.screenshot({
      path: `${artifactDirectory}/matching-ambiguous-mobile.png`,
      fullPage: true,
    });
    await page.getByTestId("sponsor-cancel").click();
    await expect(
      page.getByText("Noch keine CRM-Prüfung", { exact: true }),
    ).toBeVisible();
    await expect(page.locator("#sponsor-given-name")).toBeEnabled();
    expect(resolveBodies).toHaveLength(0);

    await page.getByRole("button", { name: "Firma", exact: true }).click();

    await page
      .locator('[data-testid="sponsor-company"]')
      .fill("Baeckerei  Sonnenseite K.G.");
    await page.locator("#sponsor-postal-code").fill("99999");
    await page.locator("#sponsor-city").fill("Nicht überschreiben");
    await page.locator('[data-testid="sponsor-preview"]').click();

    await expect(
      page.getByRole("heading", { name: "Ein eindeutiger Treffer" }),
    ).toBeVisible();
    await expect(page.locator(".candidate")).toContainText(
      "Bäckerei Sonnenseite KG",
    );
    await expect(page.locator(".candidate")).toContainText("10243");
    await expect(page.locator(".assignment-warning")).toContainText(
      "Bernd Binder",
    );
    const confirmation = page.locator('[data-testid="sponsor-resolve"]');
    await expect(confirmation).toHaveText("Trotzdem ebenfalls zuordnen");
    await expect(page.locator('[data-testid="sponsor-success"]')).toHaveCount(
      0,
    );

    await page.screenshot({
      path: `${artifactDirectory}/matching-warning-mobile.png`,
      fullPage: true,
    });

    const resolutionResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/acquisition/sponsor-match/resolve") &&
        response.request().method() === "POST",
    );
    await confirmation.click();
    const resolved = await resolutionResponse;
    expect(resolved.status()).toBe(201);
    const payload = await resolved.json();
    expect(payload).toMatchObject({
      outcome: "reused",
      assignmentCreated: true,
      displayName: "Bäckerei Sonnenseite KG",
    });

    await expect(page.locator('[data-testid="sponsor-success"]')).toContainText(
      "Zuordnung gespeichert",
    );
    await expect(
      page.locator('[data-testid="shared-assignees"]'),
    ).toContainText("Anna Akquise");
    await expect(
      page.locator('[data-testid="shared-assignees"]'),
    ).toContainText("Bernd Binder");
    await expect(page.locator("#sponsor-status")).toContainText(
      "ist jetzt dir zugeordnet",
    );
    await page.screenshot({
      path: `${artifactDirectory}/matching-success-mobile.png`,
      fullPage: true,
    });

    await page
      .getByRole("button", { name: "Weiteren Sponsor erfassen" })
      .click();
    await page
      .getByTestId("sponsor-company")
      .fill("POC063 Hafenlicht Logistik GmbH");
    await page.locator("#sponsor-given-name").fill("Helena");
    await page.locator("#sponsor-family-name").fill("Hafenlicht");
    await page
      .locator("#sponsor-email")
      .fill("helena.hafenlicht@leonaid.invalid");
    await page.locator("#sponsor-street").fill("Kaiweg 63");
    await page.locator("#sponsor-postal-code").fill("20457");
    await page.locator("#sponsor-city").fill("Hamburg");
    await page.getByTestId("sponsor-preview").click();
    await expect(
      page.getByRole("heading", {
        name: "Kein gleichnamiger Sponsor gefunden",
      }),
    ).toBeVisible();
    await page.screenshot({
      path: `${artifactDirectory}/matching-no-match-mobile.png`,
      fullPage: true,
    });

    const creationResponses = [];
    const collectCreationResponse = async (response) => {
      if (
        response.url().endsWith("/acquisition/sponsor-match/resolve") &&
        response.request().method() === "POST" &&
        response.status() === 201
      ) {
        creationResponses.push(await response.json());
      }
    };
    page.on("response", collectCreationResponse);
    await page.getByTestId("sponsor-resolve").dblclick();
    await expect
      .poll(() => creationResponses.length, {
        message: "Beide Antworten des echten Doppelklick-Retry abwarten",
      })
      .toBe(2);
    page.off("response", collectCreationResponse);
    expect(
      new Set(creationResponses.map((payload) => payload.replayed)),
    ).toEqual(new Set([false, true]));
    const createdPayload = creationResponses.find(
      (payload) => payload.replayed === false,
    );
    expect(createdPayload).toBeDefined();
    expect(createdPayload).toMatchObject({
      assignmentCreated: true,
      displayName: "POC063 Hafenlicht Logistik GmbH",
      outcome: "created",
      replayed: false,
    });
    expect(createdPayload.contactTwentyId).toMatch(/^[0-9a-f-]{36}$/);
    await expect(page.getByTestId("sponsor-success")).toContainText(
      "wurde neu im CRM angelegt",
    );
    await page.waitForTimeout(300);
    expect(resolveBodies.length).toBeGreaterThanOrEqual(2);
    const creationBodies = resolveBodies.slice(1);
    expect(new Set(creationBodies.map((body) => body.commandId)).size).toBe(1);
    await page.screenshot({
      path: `${artifactDirectory}/matching-created-mobile.png`,
      fullPage: true,
    });
  } finally {
    await context.close();
  }
});
