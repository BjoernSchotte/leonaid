import { analyzeAccessibility, WCAG_TAGS } from "./axe.mjs";
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
  const results = await analyzeAccessibility(page, { tags: WCAG_TAGS });
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
    page.getByRole("heading", { level: 1, name: "Sponsoren" }),
  ).toBeVisible();

  // Prototype SponsorList: search, status chips, scope segment, rows.
  const rows = page.locator('[data-testid="sponsor-row"]');
  await expect(rows).toHaveCount(2);
  await expect(rows.filter({ hasText: "Musterwerk GmbH" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Doppelkontakt AG" })).toHaveCount(1);
  await expect(page.getByText("Bäckerei Sonnenseite KG")).toHaveCount(0);
  await expect(page.getByText("Sophie Sponsor")).toHaveCount(0);
  await expect(page.locator('[data-testid="co-assignees"]')).toContainText(
    "mit Bernd Binder",
  );
  const scope = page.getByRole("group", { name: "Zuständigkeit" });
  await expect(
    scope.getByRole("button", { name: "Meine (2)" }),
  ).toHaveAttribute("aria-pressed", "true");
  await scope.getByRole("button", { name: "Gemeinsam betreut (1)" }).click();
  await expect(rows).toHaveCount(1);
  await scope.getByRole("button", { name: "Meine (2)" }).click();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);

  const allChip = page.getByTestId("sponsor-status-all");
  for (const locator of [
    allChip,
    scope.getByRole("button", { name: "Meine (2)" }),
    rows.first(),
  ]) {
    const box = await locator.boundingBox();
    expect(box).not.toBeNull();
    expect(box.height).toBeGreaterThanOrEqual(44);
  }

  await allChip.focus();
  const focusStyle = await allChip.evaluate((element) => {
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
      page.getByRole("heading", { level: 1, name: "Sponsoren" }),
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

  // Prototype SponsorDetail: call, mail and contact tiles, order button.
  await rows.filter({ hasText: "Musterwerk GmbH" }).click();
  await expect(page).toHaveURL(/\/app\/sponsors\?.*assignment=/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Musterwerk GmbH" }),
  ).toBeVisible();
  const call = page.getByRole("link", { name: "Anrufen" });
  await expect(call).toHaveAttribute("href", "tel:+493012345678");
  await expect(page.getByRole("link", { name: "E-Mail" })).toHaveAttribute(
    "href",
    "mailto:mara.muster@musterwerk.leonaid.invalid",
  );
  await expect(page.getByTestId("co-assignees")).toContainText(
    "Gemeinsam mit Bernd Binder",
  );
  for (const locator of [
    call,
    page.getByTestId("contact-open"),
    page.getByTestId("order-open"),
  ]) {
    const box = await locator.boundingBox();
    expect(box).not.toBeNull();
    expect(box.height).toBeGreaterThanOrEqual(44);
  }
  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-detail-${testInfo.project.name}.png`,
    fullPage: true,
  });
  // Esc returns to the list (prototype hotkey).
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { level: 1, name: "Sponsoren" }),
  ).toBeVisible();

  await page.goto(`${baseUrl}/app/`);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: /^Guten (Morgen|Tag|Abend), Anna\.$/,
    }),
  ).toBeVisible();
  // One campaign: the app bar names it, no picker (prototype).
  await expect(page.getByTestId("acquirer-action")).toHaveCount(0);
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
    .locator(
      ".pwa-main .pwa-segment button:visible, .pwa-main .pwa-row:visible",
    )
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
  // Every control of the sheet (outside the column) is a 44 px target,
  // measured after the sheet's rise animation.
  await sheet.evaluate((element) =>
    Promise.all(element.getAnimations().map((animation) => animation.finished)),
  );
  const sheetTargets = await sheet
    .locator("a:visible, button:visible, summary:visible")
    .evaluateAll((elements) =>
      elements.map((element) => {
        const box = element.getBoundingClientRect();
        return {
          height: box.height,
          text: (element.textContent ?? "").trim().slice(0, 40),
          width: box.width,
        };
      }),
    );
  expect(sheetTargets.length).toBeGreaterThan(5);
  for (const target of sheetTargets) {
    expect(target.height, target.text).toBeGreaterThanOrEqual(44);
    expect(target.width, target.text).toBeGreaterThanOrEqual(44);
  }
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

  // Shortcut help, also outside the column: phone targets up to 800 px.
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Tastenkürzel" });
  await expect(help).toBeVisible();
  await expect(help).toContainText("App: Wiedervorlagen");
  const helpTarget = viewport.width <= 800 ? 44 : 28;
  const helpClose = help.getByRole("button", { name: "Schließen" });
  // Measured after the dialog's rise animation has ended.
  await expect
    .poll(async () => {
      const box = await helpClose.boundingBox();
      return Math.min(box.width, box.height);
    })
    .toBeGreaterThanOrEqual(helpTarget);
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();

  // "Neu" opens the sponsor capture, as in the prototype.
  await tabs.getByRole("link", { name: "Neu", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/sponsors\?view=new$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Neuer Sponsor" }),
  ).toBeVisible();
  await expect(
    tabs.getByRole("link", { name: "Neu", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  const company = page.getByLabel("Firmenname");
  await company.fill("Ungespeichert GmbH");

  // A tab asks once, in the app (iOS shows no beforeunload dialog).
  const nativeDialogs = [];
  page.on("dialog", (dialog) => {
    nativeDialogs.push(dialog.type());
    void dialog.dismiss();
  });
  const startTab = tabs.getByRole("link", { name: "Start" });
  await startTab.click();
  const question = page.getByRole("alertdialog", { name: "Seite wechseln?" });
  await expect(question).toContainText(
    "Du hast Eingaben, die noch nicht gespeichert sind.",
  );
  await question.getByRole("button", { name: "Abbrechen" }).click();
  await expect(question).toBeHidden();
  await expect(page).toHaveURL(/\/app\/sponsors\?view=new$/);
  await expect(company).toHaveValue("Ungespeichert GmbH");
  await startTab.click();
  await question
    .getByRole("button", { name: "Verwerfen und wechseln" })
    .click();
  await expect(page).toHaveURL(/\/app\/(\?.*)?$/);
  expect(nativeDialogs).toEqual([]);

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
    page.getByRole("heading", { level: 1, name: "Wiedervorlagen" }),
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
  await expect(
    page.getByRole("heading", { name: "Noch kein Sponsor zugeordnet" }),
  ).toBeVisible();
  await assertNoSeriousAxeFindings(page);
  await page.screenshot({
    path: `${artifactDirectory}/pwa-empty-chromium-390.png`,
    fullPage: true,
  });
});
