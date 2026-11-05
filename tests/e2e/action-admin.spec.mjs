import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const session = process.env.KLARA_SESSION;

if (!baseUrl || !artifactDirectory || !session) {
  throw new Error(
    "LEONAID_E2E_BASE_URL, LEONAID_E2E_ARTIFACT_DIR und KLARA_SESSION sind erforderlich",
  );
}

test.setTimeout(90_000);

async function confirmTransition(page, trigger, confirm) {
  await page.getByTestId(trigger).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.locator(".modal-description")).toHaveText(/.{20,}/);
  await dialog.getByRole("button", { name: confirm }).click();
}

test("charity admin takes a golden action accessibly through the full lifecycle", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: session,
      url: baseUrl,
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    const response = await page.goto(`${baseUrl}/admin/actions/new`);
    try {
      await expect(
        page.getByRole("heading", { name: "Neue Aktion anlegen" }),
      ).toBeVisible({ timeout: 10_000 });
    } catch {
      const identityDiagnostic = await page.evaluate(async () => {
        try {
          const identity = await fetch("/api/v1/identity/me", {
            credentials: "include",
            headers: { Accept: "application/json" },
          });
          return {
            body: (await identity.text()).slice(0, 500),
            status: identity.status,
          };
        } catch (error) {
          return { error: String(error) };
        }
      });
      throw new Error(
        `React entry point missing: HTTP ${response?.status()}; URL ${page.url()}; ` +
          `browser errors ${JSON.stringify(pageErrors)}; ` +
          `identity ${JSON.stringify(identityDiagnostic)}; ` +
          `page ${JSON.stringify((await page.locator("body").innerText()).slice(0, 800))}`,
      );
    }
    await expect(page.getByTestId("desktop-sidebar")).toBeVisible();
    await expect(page.getByTestId("mobile-menu")).toBeHidden();
    await expect(page.locator("#action-name-help")).toContainText(
      "öffentliche Titel",
    );
    await expect(page.locator("#action-carrier-help")).toContainText(
      "Organisation",
    );
    await expect(page.locator("#archive-slug-help")).toContainText(
      "ohne Leerzeichen",
    );
    await expect(page.getByTestId("action-name")).toHaveAttribute(
      "aria-describedby",
      "action-name-help",
    );
    await page.screenshot({
      path: `${artifactDirectory}/action-create-guidance.png`,
      fullPage: true,
    });

    await page.getByTestId("theme-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute(
      "data-theme-preference",
      "dark",
    );
    // The pre-paint script sets the preference before React registers the
    // hotkey; press again only while the switch has not happened yet.
    await expect(page.getByTestId("desktop-sidebar")).toBeVisible();
    await expect(async () => {
      if (
        (await page.locator("html").getAttribute("data-theme-preference")) !==
        "light"
      )
        await page.keyboard.press("Shift+T");
      await expect(page.locator("html")).toHaveAttribute(
        "data-theme-preference",
        "light",
        { timeout: 1000 },
      );
    }).toPass({ timeout: 15000 });

    await page.getByTestId("action-name").fill("Krapfentaxi Golden UI 2028");
    await page
      .getByTestId("action-carrier")
      .fill("Lions Hilfswerk Beispielstadt");
    await page.getByTestId("action-slug").fill("krapfentaxi-golden-ui-2028");
    await page
      .getByTestId("action-purpose")
      .fill("Krapfen bestellen und zwei lokale Bildungsorte fördern.");
    await page.getByTestId("action-start").fill("2028-09-01");
    await page.getByTestId("action-end").fill("2028-11-15");
    for (const capability of [
      "acquisition",
      "offerings",
      "ordering",
      "invoicing",
    ]) {
      await page.locator(`input[value="${capability}"]`).check();
    }
    await page.getByTestId("action-goal").fill("1500");
    await page.getByTestId("action-unit").fill("Boxen");
    await page.getByTestId("action-actual").fill("0");
    await page
      .getByTestId("beneficiary-name-0")
      .fill("Bildungshafen Beispielstadt");
    await page
      .getByTestId("beneficiary-description-0")
      .fill("Finanziert Lernmaterial für Kinder.");
    await page.getByTestId("action-submit").click();

    const createdStatus = page.locator("#action-status");
    await expect(createdStatus).toHaveAttribute("data-state", "success");
    const actionId = await createdStatus.getAttribute("data-action-id");
    expect(actionId).toMatch(/^[0-9a-f-]{36}$/);
    await expect(
      page.getByRole("heading", { name: "Lieferung planen" }),
    ).toHaveCount(0);
    await page.getByRole("link", { name: "Aktion jetzt verwalten" }).click();

    await expect(page.getByTestId("management-title")).toHaveText(
      "Krapfentaxi Golden UI 2028",
    );
    await expect(page.getByTestId("management-status")).toHaveText("Entwurf");
    await expect(page.getByTestId("current-action")).toHaveText(
      "Krapfentaxi Golden UI 2028",
    );
    const tab = (name) => page.getByRole("tab", { name: new RegExp(name) });
    await expect(tab("Überblick")).toHaveAttribute("aria-selected", "true");
    // No delivery capability: no Lieferfenster tab.
    await expect(tab("Lieferfenster")).toHaveCount(0);
    await expect(page.getByTestId("action-next-step")).toContainText(
      "Nächster Schritt:",
    );
    await expect(
      page.locator('a[data-nav-key="invoices"]').first(),
    ).toHaveAttribute(
      "href",
      // Campaign-scoped rail links carry the campaign on screen.
      `/admin/invoices?action=${actionId}`,
    );
    await page.getByTestId("action-edit").click();
    await expect(page).toHaveURL(/#overview\/edit$/);
    await expect(page.locator("#manage-name-hint")).toContainText(
      "öffentliche Titel",
    );
    await expect(page.locator("#manage-carrier-hint")).toContainText(
      "Organisation",
    );
    await expect(page.locator("#manage-archive-slug-hint")).toContainText(
      "nicht geändert",
    );
    await expect(page.getByTestId("manage-name")).toHaveAttribute(
      "aria-describedby",
      "manage-name-hint",
    );
    await expect(page.getByTestId("manage-archive-slug")).toHaveAttribute(
      "aria-describedby",
      "manage-archive-slug-hint",
    );

    await page.getByTestId("manage-name").fill("Krapfentaxi Golden 2028");
    await page.getByTestId("manage-name").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByTestId("manage-carrier")).toBeFocused();
    await page.getByTestId("save-details").click();
    await expect(
      page.getByText("Grunddaten und Zeitraum wurden gespeichert."),
    ).toBeVisible();

    await page.getByTestId("manage-actual").fill("25");
    await page.getByTestId("save-goal").click();
    await expect(
      page.getByText("Aktionsziel und Fortschritt wurden gespeichert."),
    ).toBeVisible();

    await page.evaluate(() => {
      document.documentElement.style.scrollBehavior = "auto";
      window.scrollTo(0, 0);
    });
    await page.screenshot({
      path: `${artifactDirectory}/action-admin-desktop.png`,
      fullPage: false,
    });
    const desktopAccessibility = await analyzeAccessibility(page);
    expect(
      desktopAccessibility.violations.filter(
        (violation) => violation.impact === "critical",
      ),
    ).toEqual([]);

    await page
      .getByTestId("manage-beneficiary-name-0")
      .fill("Bildungshafen und Lerninsel Beispielstadt");
    await page.getByTestId("save-beneficiaries").click();
    await expect(
      page.getByText("Die Begünstigten wurden gespeichert."),
    ).toBeVisible();

    await page.locator('#capabilities input[value="invoicing"]').uncheck();
    await page.getByTestId("save-capabilities").click();
    await expect(
      page.getByText("Die Funktionen der Aktion wurden gespeichert."),
    ).toBeVisible();

    await page
      .getByTestId("administrator-10000000-0000-4000-8000-000000000007")
      .check();
    await page.getByTestId("save-administrators").click();
    await expect(
      page.getByText("Die verantwortlichen Admins wurden gespeichert."),
    ).toBeVisible();
    await page.getByTestId("action-edit-done").click();
    await expect(page.getByTestId("manage-name")).toHaveCount(0);

    // Tabs: arrow keys move between them; the number keys pick one.
    await tab("Überblick").focus();
    await page.keyboard.press("ArrowRight");
    await expect(tab("Aliase")).toBeFocused();
    await expect(tab("Aliase")).toHaveAttribute("aria-selected", "true");
    await expect(page).toHaveURL(/#aliases$/);
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("3");
    await expect(tab("Vorlagen")).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("template-snapshot")).toBeVisible();
    await page.keyboard.press("4");
    await expect(tab("Angebote")).toHaveAttribute("aria-selected", "true");
    // An action without a template has no offerings yet.
    await expect(
      page.getByRole("heading", { name: "Keine Angebote" }),
    ).toBeVisible();
    await page.keyboard.press("2");
    await page.getByTestId("publication-start").fill("2028-08-01T08:00");
    await page.getByTestId("publication-end").fill("2028-11-15T23:00");
    await page.getByTestId("publication-alias").fill("krapfentaxi-golden-ui");
    await page.getByTestId("save-publication").click();
    await expect(
      page.getByText(
        "Die Einstellungen der öffentlichen Seite wurden gespeichert.",
      ),
    ).toBeVisible();

    await page.evaluate(() => {
      document.documentElement.style.scrollBehavior = "auto";
      window.scrollTo(0, 0);
    });
    await page.screenshot({
      path: `${artifactDirectory}/action-admin-public.png`,
      fullPage: false,
    });
    await page.getByTestId("theme-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.screenshot({
      path: `${artifactDirectory}/action-admin-dark.png`,
      fullPage: false,
    });
    await page.getByTestId("theme-toggle").click();

    await page.keyboard.press("1");
    await expect(tab("Überblick")).toHaveAttribute("aria-selected", "true");
    await confirmTransition(page, "transition-scheduled", "Aktion einplanen");
    await expect(page.getByTestId("management-status")).toHaveText("Geplant");
    await expect(page.getByTestId("transition-active")).toBeVisible();

    await confirmTransition(page, "transition-active", "Aktion aktivieren");
    await expect(page.getByTestId("management-status")).toHaveText("Aktiv");
    await expect(page.getByTestId("transition-completed")).toBeVisible();

    await confirmTransition(page, "transition-completed", "Aktion abschließen");
    await expect(page.getByTestId("management-status")).toHaveText(
      "Abgeschlossen",
    );
    await expect(page.getByTestId("transition-archived")).toBeVisible();

    await confirmTransition(
      page,
      "transition-archived",
      "Unwiderruflich archivieren",
    );
    await expect(page.getByTestId("management-status")).toHaveText(
      "Archiviert",
    );
    await expect(page.getByTestId("action-edit")).toHaveCount(0);
    await expect(page.getByTestId("action-read-only")).toContainText(
      "vollständig nachvollziehbar",
    );

    const persisted = await page.evaluate(async (id) => {
      const response = await fetch(`/api/v1/actions/${id}/management`, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      return { body: await response.json(), status: response.status };
    }, actionId);
    expect(persisted.status).toBe(200);
    expect(persisted.body.action).toMatchObject({
      name: "Krapfentaxi Golden 2028",
      status: "archived",
      capabilities: ["acquisition", "offerings", "ordering"],
    });
    expect(persisted.body.publicAlias).toBeNull();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => {
      document.documentElement.style.scrollBehavior = "auto";
      window.scrollTo(0, 0);
    });
    await expect(page.getByTestId("desktop-sidebar")).toBeHidden();
    await page.getByTestId("mobile-menu").focus();
    await page.keyboard.press("Enter");
    const drawer = page.getByRole("dialog", { name: "Alle Bereiche" });
    await expect(drawer).toBeVisible();
    await expect(drawer.locator('[data-nav-key="actions"]')).toBeVisible();
    await drawer.screenshot({
      path: `${artifactDirectory}/action-admin-mobile.png`,
    });
    const mobileAccessibility = await analyzeAccessibility(page);
    expect(
      mobileAccessibility.violations.filter(
        (violation) => violation.impact === "critical",
      ),
    ).toEqual([]);

    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.goto(`${baseUrl}/admin/actions/${actionId}`);
    await expect(page.getByTestId("management-title")).toBeVisible();
    // Esc goes back to the action list (prototype).
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Escape");
    await page.waitForURL(`${baseUrl}/admin/actions`);
    // The action list (prototype CampaignList): the archived action is not
    // under "Laufend und geplant" but under "Archiv".
    await expect(
      page.getByRole("heading", { name: "Aktionen", level: 1 }),
    ).toBeVisible();
    const actionRow = page.locator(
      `a.row-link[href="/admin/actions/${actionId}"]`,
    );
    await expect(actionRow).toHaveCount(0);
    await page.getByRole("button", { name: "Archiv", exact: true }).click();
    await expect(actionRow).toBeVisible();
    await expect(actionRow).toContainText("Krapfentaxi Golden 2028");
    await expect(page.getByTestId("topbar-zone")).toHaveText("Aktionen");
    await page.screenshot({
      path: `${artifactDirectory}/action-overview-desktop.png`,
      fullPage: false,
    });
  } finally {
    await context.close();
  }
});
