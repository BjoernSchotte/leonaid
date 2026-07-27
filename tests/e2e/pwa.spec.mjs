import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const annaSession = process.env.ANNA_SESSION;
const gesaSession = process.env.GESA_SESSION;

if (!baseUrl || !artifactDirectory || !annaSession || !gesaSession) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR, ANNA_SESSION und GESA_SESSION sind erforderlich",
  );
}

async function authenticate(context, token) {
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: token,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
}

async function assertNoSeriousAxeFindings(page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
    .analyze();
  const severe = results.violations.filter(({ impact }) =>
    ["critical", "serious"].includes(impact),
  );
  expect(
    severe,
    severe
      .map(
        (violation) =>
          `${violation.id}: ${violation.description} (${violation.nodes.length})`,
      )
      .join("\n"),
  ).toEqual([]);
}

test("POC-062 Sponsorliste erfüllt Sicht-, Responsive- und A11y-Budgets", async ({
  context,
  page,
}, testInfo) => {
  await authenticate(context, annaSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.locator('[data-testid="display-name"]')).toHaveText(
    "Anna Akquise",
  );
  await expect(
    page.getByRole("heading", { name: "Meine Sponsoren" }),
  ).toBeVisible();

  const rows = page.locator('[data-testid="sponsor-row"]');
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: "Musterwerk GmbH" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Doppelkontakt AG" })).toHaveCount(1);
  await expect(page.getByText("Bäckerei Sonnenseite KG")).toHaveCount(0);
  await expect(page.getByText("Sophie Sponsor")).toHaveCount(0);
  await expect(page.locator('[data-testid="co-assignees"]')).toContainText(
    "Gemeinsam mit Bernd Binder",
  );

  await expect(
    page.getByRole("link", { name: "Musterwerk GmbH anrufen" }),
  ).toHaveAttribute("href", "tel:+493012345678");
  await expect(
    page.getByRole("link", { name: "E-Mail an Musterwerk GmbH schreiben" }),
  ).toHaveAttribute("href", "mailto:mara.muster@musterwerk.leonaid.invalid");

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);

  for (const locator of [
    page.getByRole("tab", { name: "Übersicht" }),
    page.getByRole("tab", { name: "Sponsor erfassen" }),
    page.getByRole("link", { name: "Musterwerk GmbH anrufen" }),
  ]) {
    const box = await locator.boundingBox();
    expect(box).not.toBeNull();
    expect(box.height).toBeGreaterThanOrEqual(44);
  }

  const sponsorTab = page.getByRole("tab", { name: "Sponsor erfassen" });
  await sponsorTab.focus();
  const focusStyle = await sponsorTab.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
    };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(Number.parseFloat(focusStyle.outlineWidth)).toBeGreaterThanOrEqual(2);

  if (testInfo.project.name === "chromium-390") {
    await page.evaluate(() => {
      document.documentElement.style.fontSize = "32px";
    });
    await expect(
      page.getByRole("heading", { name: "Meine Sponsoren" }),
    ).toBeVisible();
    const scaledLayout = await page.evaluate(() => ({
      offenders: [...document.querySelectorAll("body *")]
        .map((element) => {
          const box = element.getBoundingClientRect();
          return {
            className:
              typeof element.className === "string" ? element.className : "",
            right: Math.round(box.right),
            tag: element.tagName,
            text: (element.textContent ?? "").trim().slice(0, 80),
          };
        })
        .filter((item) => item.right > window.innerWidth + 1)
        .slice(0, 12),
      overflow: document.documentElement.scrollWidth - window.innerWidth,
    }));
    expect(
      scaledLayout.overflow,
      JSON.stringify(scaledLayout.offenders, null, 2),
    ).toBeLessThanOrEqual(1);
  }

  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-list-${testInfo.project.name}.png`,
    fullPage: true,
  });

  await page.goto(`${baseUrl}/app/`);
  await expect(
    page.getByRole("heading", { level: 1, name: "Guten Tag, Anna." }),
  ).toBeVisible();
  const actionSelector = page.getByRole("combobox", {
    name: "Charity-Aktion",
  });
  await expect(actionSelector).toContainText("Krapfentaxi 2026");
  await expect(actionSelector.locator("option")).toHaveCount(1);
});

test("POC-062 zeigt einen echten leeren Arbeitsvorrat", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-390",
    "Der reale Leerzustand wird einmal im mobilen Leitbrowser belegt.",
  );
  await authenticate(context, gesaSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.locator('[data-testid="display-name"]')).toHaveText(
    "Gesa Gesperrt",
  );
  await expect(page.locator('[data-testid="sponsor-empty"]')).toContainText(
    "Noch kein Sponsor zugeordnet",
  );
  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-empty-chromium-390.png`,
    fullPage: true,
  });
});
