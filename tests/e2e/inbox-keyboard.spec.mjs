import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { expect, test } from "./csp-guard.mjs";

// Runs in the inbox stack (tools/inbox/test.sh): three "Tastaturprobe" cases
// for the first fixture account, a system administrator.
const baseURL = process.env.LEONAID_E2E_BASE_URL;
const fixture = JSON.parse(
  readFileSync(process.env.LEONAID_MODULE_FIXTURE, "utf8"),
);

async function expectNoSeriousAccessibilityViolations(page, label) {
  const accessibility = await new AxeBuilder({ page }).analyze();
  expect(
    accessibility.violations
      .filter(
        (violation) =>
          violation.impact === "critical" || violation.impact === "serious",
      )
      .map((violation) => `${label}: ${violation.id}`),
  ).toEqual([]);
}

test("inbox list: j/k, Enter, Esc, x and closing with a note by keyboard", async ({
  browser,
}) => {
  expect(fixture.keyboardCases).toHaveLength(3);
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([
    {
      name: "__Host-leonaid_session",
      value: fixture.sessions[0],
      url: baseURL,
      secure: true,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseURL}/admin/inbox`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Eingang" }),
    ).toBeVisible();
    // The default view "Offen" is grouped by status.
    const views = page.getByRole("navigation", {
      name: "Gespeicherte Ansichten",
    });
    await expect(
      views.getByRole("button", { name: "Offen", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    const rows = page.locator(".listview .row-link");

    // "/" focuses the search; ArrowDown goes to the first hit.
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("/");
    await expect(page.getByRole("searchbox")).toBeFocused();
    await page.keyboard.type("Tastaturprobe");
    await expect(rows).toHaveCount(3);
    await expect(page).toHaveURL(/[?&]q=Tastaturprobe/);
    await page.keyboard.press("ArrowDown");
    await expect(rows.first()).toBeFocused();

    // j/k move; Enter opens the pane; j in the pane shows the next case.
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await page.keyboard.press("k");
    await expect(rows.nth(1)).toBeFocused();
    await page.keyboard.press("Enter");
    const pane = page.getByRole("complementary", {
      name: /^Details: Tastaturprobe/,
    });
    await expect(pane).toBeVisible();
    await expect(page).toHaveURL(/[?&]open=[0-9a-f-]{36}/);
    await expect(pane.getByTestId("inbox-case-detail")).toBeVisible();
    await expect(pane.getByText("Nächster Schritt:")).toBeVisible();
    await expect(
      pane.getByRole("group", { name: "Eigenschaften" }),
    ).toContainText("Zuständigkeit");
    await expectNoSeriousAccessibilityViolations(page, "Anfrage im Detail");
    const firstTitle = await pane.locator(".pane-title").textContent();
    await page.keyboard.press("j");
    await expect(rows.nth(2)).toBeFocused();
    await expect(pane.locator(".pane-title")).not.toHaveText(firstTitle ?? "");

    // Esc closes the pane and returns focus to the row.
    await page.keyboard.press("Escape");
    await expect(pane).toHaveCount(0);
    await expect(rows.nth(2)).toBeFocused();
    await expect(page).not.toHaveURL(/[?&]open=/);

    // x checks two rows; S on the selection asks for the closing note.
    await page.keyboard.press("x");
    await page.keyboard.press("k");
    await page.keyboard.press("x");
    const bulk = page.getByRole("region", { name: "Auswahl" });
    await expect(bulk).toContainText("2 ausgewählt");
    await page.keyboard.press("s");
    await page.getByRole("option", { name: /Abgeschlossen/ }).click();
    const dialog = page.getByRole("dialog", { name: "2 Anfragen abschließen" });
    await expect(dialog).toBeVisible();
    await expect(dialog.getByLabel(/Abschlussnotiz/)).toBeFocused();
    // List keys are inert while typing in the dialog.
    await page.keyboard.type("jk");
    await expect(dialog.getByLabel(/Abschlussnotiz/)).toHaveValue("jk");
    await expectNoSeriousAccessibilityViolations(page, "Abschlussdialog");

    // Esc backs out: nothing changes, no toast, the selection stays.
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(page.getByText(/Status bei 2 Einträgen/)).toHaveCount(0);
    await expect(bulk).toContainText("2 ausgewählt");
    await expect(rows).toHaveCount(3);

    // Again, with a note: both cases close and leave the "Offen" view.
    await page.keyboard.press("s");
    await page.getByRole("option", { name: /Abgeschlossen/ }).click();
    await expect(dialog).toBeVisible();
    await dialog
      .getByLabel(/Abschlussnotiz/)
      .fill("Rückruf erledigt, Zeiten genannt.");
    await dialog
      .getByRole("button", { name: "Abschließen", exact: true })
      .click();
    await expect(dialog).toHaveCount(0);
    await expect(
      page.getByText("Status bei 2 Einträgen: Abgeschlossen"),
    ).toBeVisible();
    await expect(rows).toHaveCount(1);
    await expect(bulk).toHaveCount(0);

    // f filters by contact state; the URL keeps the filter.
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("f");
    const filterMenu = page.getByRole("dialog", { name: "Filter wählen" });
    await expect(filterMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.type("Kontakt");
    await page.keyboard.press("Enter");
    const contactMenu = page.getByRole("dialog", { name: "Filter Kontakt" });
    await contactMenu
      .getByRole("option", { name: /Zuordnung ausstehend/ })
      .click();
    await page.keyboard.press("Escape");
    await expect(contactMenu).toHaveCount(0);
    await expect(page).toHaveURL(/f\.contact=pending/);

    // "Alle" shows the closed cases again, with their status chip.
    // A view switch resets the search, so search again.
    await views.getByRole("button", { name: "Alle", exact: true }).click();
    await page.getByRole("searchbox").fill("Tastaturprobe");
    await expect(rows).toHaveCount(3);
    await expect(
      page.locator(".listview .row").filter({ hasText: "Abgeschlossen" }),
    ).toHaveCount(2);
    await expectNoSeriousAccessibilityViolations(page, "Eingang");
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
