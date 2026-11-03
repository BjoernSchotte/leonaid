import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";
import { memberRows } from "./member-list.mjs";

// Runs in the identity stack (tools/identity/test.sh): eight golden members
// for Simone System (system admin). Read-only apart from opening dialogs.
const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const systemSession = process.env.SYSTEM_SESSION;

if (!baseUrl || !artifactDirectory || !systemSession) {
  throw new Error("Member keyboard browser environment is incomplete");
}

function sessionCookie(value) {
  return {
    name: "__Host-leonaid_session",
    value,
    url: baseUrl,
    httpOnly: true,
    secure: true,
    sameSite: "Lax",
  };
}

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

test("member list: j/k, Enter, Esc, x, filter and invite by keyboard", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    ignoreHTTPSErrors: true,
  });
  await context.addCookies([sessionCookie(systemSession)]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/admin/members`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Mitglieder" }),
    ).toBeVisible();
    const rows = memberRows(page);
    await expect(rows).toHaveCount(8);
    // Status and roles are read-only in the list: no letter key, no chip
    // menu. Role changes stay in the pane behind the fresh sign-in.
    await expect(page.locator(".list-hint")).not.toContainText("Status");
    await expect(page.locator(".list-hint")).not.toContainText("Rolle");
    await expect(page.locator("[data-chip]")).toHaveCount(0);
    await page.locator("body").click({ position: { x: 5, y: 5 } });

    // j/k move the focus, Enter opens the pane, Esc closes it again.
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await page.keyboard.press("k");
    await expect(rows.first()).toBeFocused();
    await page.keyboard.press("Enter");
    const pane = page.getByRole("complementary", { name: /^Details: / });
    await expect(pane).toBeVisible();
    await expect(pane.getByTestId("member-detail")).toBeVisible();
    await expect(page).toHaveURL(/[?&]open=[0-9a-f-]{36}/);
    await expect(pane.locator(".pane-props")).toHaveCount(0);
    await expect(pane.getByTestId("member-role-admin")).toBeVisible();
    await expectNoSeriousAccessibilityViolations(page, "Mitglied im Detail");

    // j in the open pane shows the next member.
    const firstTitle = await pane.locator(".pane-title").textContent();
    await page.keyboard.press("j");
    await expect(rows.nth(1)).toBeFocused();
    await expect(pane.locator(".pane-title")).not.toHaveText(firstTitle ?? "");
    await page.keyboard.press("Escape");
    await expect(pane).toHaveCount(0);
    await expect(rows.nth(1)).toBeFocused();
    await expect(page).not.toHaveURL(/[?&]open=/);

    // x checks rows; the bulk bar offers no role or status edit; Esc clears.
    await page.keyboard.press("x");
    await page.keyboard.press("k");
    await page.keyboard.press("x");
    const bulk = page.getByRole("region", { name: "Auswahl" });
    await expect(bulk).toContainText("2 ausgewählt");
    await expect(bulk.getByRole("button", { name: /Status|Rolle/ })).toHaveCount(
      0,
    );
    await page.keyboard.press("Escape");
    await expect(bulk).toHaveCount(0);

    // f filters by status; the URL keeps it.
    await page.keyboard.press("f");
    const filterMenu = page.getByRole("dialog", { name: "Filter wählen" });
    await expect(filterMenu.getByRole("combobox")).toBeFocused();
    await page.keyboard.type("Stat");
    await page.keyboard.press("Enter");
    const statusMenu = page.getByRole("dialog", { name: "Filter Status" });
    await expect(statusMenu.getByRole("combobox")).toBeFocused();
    await statusMenu.getByRole("option", { name: /Gesperrt/ }).click();
    await page.keyboard.press("Escape");
    await expect(statusMenu).toHaveCount(0);
    await expect(page).toHaveURL(/f\.status=suspended/);
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText("Gesa Gesperrt");
    await page.screenshot({
      path: `${artifactDirectory}/members-keyboard-filter.png`,
      fullPage: false,
    });

    // c opens the invitation dialog; Esc closes it and the list keeps focus.
    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("c");
    const invite = page.getByRole("dialog", { name: "Mitglied einladen" });
    await expect(invite).toBeVisible();
    await expect(invite.getByLabel("E-Mail-Adresse")).toBeFocused();
    await expectNoSeriousAccessibilityViolations(page, "Mitglied einladen");
    await page.keyboard.press("Escape");
    await expect(invite).toBeHidden();

    // The palette leads to the invitations ledger.
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Befehlspalette" });
    await expect(palette).toBeVisible();
    await page.keyboard.type("Einladungen ansehen");
    await page.keyboard.press("Enter");
    await page.waitForURL(`${baseUrl}/admin/members/invitations`);
    await expect(
      page.getByRole("heading", { level: 1, name: "Einladungen" }),
    ).toBeVisible();
    await expect(
      page
        .getByRole("navigation", { name: "Mitgliederbereiche" })
        .getByRole("link", { name: "Einladungen", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expectNoSeriousAccessibilityViolations(page, "Einladungen");
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
