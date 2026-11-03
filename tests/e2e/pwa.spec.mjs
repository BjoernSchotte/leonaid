import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";

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

test("POC-062 sponsor list meets visual, responsive and a11y budgets", async ({
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

test("Leitsystem mobile shell: tabs, 44 px targets and the Mehr sheet", async ({
  context,
  page,
}, testInfo) => {
  await authenticate(context, annaSession);
  await page.goto(`${baseUrl}/app/sponsors`);
  await expect(page.getByTestId("display-name")).toHaveText("Anna Akquise");
  await expect(page.getByTestId("current-action")).toHaveText(
    "Krapfentaxi 2026",
  );

  const tabs = page.getByRole("navigation", { name: "App-Navigation" });
  const links = tabs.getByRole("link");
  await expect(links).toHaveText([
    "Start",
    "Sponsoren",
    "Neu",
    "Wiedervorlagen",
    "Neues",
  ]);
  await expect(tabs.getByRole("link", { name: "Sponsoren" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  const viewport = page.viewportSize();
  const column = await page.locator(".pwa").boundingBox();
  expect(column.width).toBeLessThanOrEqual(480);
  // Centred on the stage on wide screens.
  expect(
    Math.abs(column.x - (viewport.width - column.width) / 2),
  ).toBeLessThanOrEqual(1);
  const tabBar = await tabs.boundingBox();
  expect(tabBar.y + tabBar.height).toBeLessThanOrEqual(viewport.height + 1);
  for (let index = 0; index < 5; index += 1) {
    const box = await links.nth(index).boundingBox();
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
    expect(box.x).toBeGreaterThanOrEqual(column.x - 1);
    expect(box.x + box.width).toBeLessThanOrEqual(column.x + column.width + 1);
  }
  // Shared pages get their phone layout in the column at every width.
  const pageControls = await page
    .locator(".pwa-main .btn:visible, .pwa-main a[href^='tel:']:visible")
    .evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return {
          height: box.height,
          left: box.left,
          right: box.right,
          text: (element.textContent ?? "").trim().slice(0, 40),
        };
      }),
    );
  expect(pageControls.length).toBeGreaterThan(0);
  for (const control of pageControls) {
    expect(control.left, control.text).toBeGreaterThanOrEqual(column.x - 1);
    expect(control.right, control.text).toBeLessThanOrEqual(
      column.x + column.width + 1,
    );
    expect(control.height, control.text).toBeGreaterThanOrEqual(44);
  }
  const menuButton = page.getByRole("button", { name: "Mehr" });
  const menuBox = await menuButton.boundingBox();
  expect(menuBox.width).toBeGreaterThanOrEqual(44);
  expect(menuBox.height).toBeGreaterThanOrEqual(44);
  await expect(page.getByRole("img", { name: "Online" })).toBeVisible();
  await expect(page.getByTestId("offline-banner")).toHaveCount(0);

  await menuButton.click();
  const sheet = page.getByRole("dialog", { name: "Mehr" });
  await expect(sheet).toBeVisible();
  await expect(sheet.getByTestId("logout")).toBeVisible();
  const logoutBox = await sheet.getByTestId("logout").boundingBox();
  expect(logoutBox.height).toBeGreaterThanOrEqual(44);
  await sheet.getByRole("button", { name: "Dunkel" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-sheet-${testInfo.project.name}.png`,
  });
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(menuButton).toBeFocused();
  await page.keyboard.press("Shift+T");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  // Tab shortcuts 1–5 follow the tab order.
  await page.locator("main h1").click();
  await page.keyboard.press("5");
  await expect(page).toHaveURL(/\/app\/activities$/);
  await expect(tabs.getByRole("link", { name: "Neues" })).toHaveAttribute(
    "aria-current",
    "page",
  );
  await tabs.getByRole("link", { name: "Wiedervorlagen" }).click();
  await expect(page).toHaveURL(/\/app\/activities\?view=contacts$/);
  await expect(
    page.getByRole("heading", { name: "Aktivitäten & Wiedervorlagen" }),
  ).toBeVisible();
  await expect(
    tabs.getByRole("link", { name: "Wiedervorlagen" }),
  ).toHaveAttribute("aria-current", "page");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});

test("POC-062 shows a real empty work queue", async ({
  context,
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "chromium-390",
    "The real empty state is proven once in the lead mobile browser.",
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
