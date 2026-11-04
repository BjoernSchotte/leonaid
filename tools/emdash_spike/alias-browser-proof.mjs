import assert from "node:assert/strict";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { guardCsp } from "./csp-guard.mjs";
import { browserLogin } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const action = "20000000-0000-4000-8000-000000000001";
const other = "20000000-0000-4000-8000-000000000003";
const admin = (id) => `/admin/actions/${id}`;
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = guardCsp(await engine.launch({ headless: true }));
  try {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: name === "webkit" ? 390 : 1440, height: 900 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    await page.goto(
      `${origin}/login?returnTo=${encodeURIComponent(admin(action))}`,
    );
    await browserLogin(
      context,
      page,
      admin(action),
      false,
      "klara.kern@leonaid.invalid",
    );
    await page.getByRole("tab", { name: /Aliase/ }).click();
    const section = page.getByRole("region", {
      name: "Adressen und Weiterleitungen",
    });
    await expect(
      section.getByText("Dauerhafte Adresse", { exact: true }),
    ).toBeVisible();
    const aliasDialog = () =>
      page.getByRole("dialog", { name: /Alias hinzufügen|bearbeiten$/ });
    const submit = async (dialog, method, button, status = 200) => {
      const result = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname.includes("/redirect-aliases") &&
          r.request().method() === method,
      );
      await dialog.getByRole("button", { name: button, exact: true }).click();
      assert.equal((await result).status(), status);
    };
    for (const suffix of ["one", "two"]) {
      await section.getByTestId("alias-add").click();
      const dialog = aliasDialog();
      await dialog.getByTestId("alias-input").fill(`browser-${name}-${suffix}`);
      await submit(dialog, "POST", "Speichern");
      await expect(dialog).toBeHidden();
      await expect(section.locator(".campaign-alias-row")).toHaveCount(
        suffix === "one" ? 1 : 2,
      );
    }
    const row = section.locator(".campaign-alias-row").filter({
      has: page.getByRole("link", {
        name: `/browser-${name}-one`,
        exact: true,
      }),
    });
    const edit = async (target) => {
      await target.getByRole("button", { name: /bearbeiten$/ }).click();
      return aliasDialog();
    };
    let form = await edit(row);
    await expect(
      form.getByTestId("alias-target").locator("option"),
    ).toHaveCount(1);
    await form.getByTestId("alias-enabled").selectOption("disabled");
    await submit(form, "PUT", "Speichern");
    await expect(form).toBeHidden();
    await expect(row.getByRole("status").first()).toHaveText("Deaktiviert");
    const inactive = await context.request.get(`${origin}/browser-${name}-one`);
    assert.equal(inactive.headers()["x-leonaid-public-state"], "inactive");
    form = await edit(row);
    await form.getByTestId("alias-input").fill("krapfentaxi");
    await submit(form, "PUT", "Speichern", 409);
    await expect(
      form.getByText("Ihre Eingaben bleiben erhalten.", { exact: false }),
    ).toBeVisible();
    await expect(form.getByTestId("alias-input")).toHaveValue("krapfentaxi");
    await form.getByTestId("alias-input").fill(`browser-${name}-one`);
    await form.getByTestId("alias-enabled").selectOption("enabled");
    await submit(form, "PUT", "Speichern");
    await expect(form).toBeHidden();
    const redirect = await context.request.get(
      `${origin}/browser-${name}-one`,
      { maxRedirects: 0 },
    );
    assert.equal(redirect.status(), 302);
    assert.equal(redirect.headers().location, "/campaigns/krapfentaxi-2026/");
    await page.screenshot({
      path: `/visual-proof/aliases-${name}.png`,
      fullPage: true,
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
    );
    await row.getByRole("button", { name: /entfernen$/ }).click();
    await submit(
      page.getByRole("alertdialog"),
      "DELETE",
      "Entfernen bestätigen",
    );
    await expect(section.locator(".campaign-alias-row")).toHaveCount(1);
    await context.close();

    // System Admin sees all eligible targets and moves the remaining address
    // using the actual selection and save controls, not a fixture HTTP write.
    const system = await browser.newContext({ ignoreHTTPSErrors: true });
    const systemPage = await system.newPage();
    systemPage.setDefaultTimeout(20000);
    await systemPage.goto(
      `${origin}/login?returnTo=${encodeURIComponent(admin(action))}`,
    );
    await browserLogin(system, systemPage, admin(action));
    await systemPage.getByRole("tab", { name: /Aliase/ }).click();
    const systemSection = systemPage.getByRole("region", {
      name: "Adressen und Weiterleitungen",
    });
    const remaining = systemSection
      .locator(".campaign-alias-row")
      .filter({ hasText: `browser-${name}-two` });
    await remaining.getByRole("button", { name: /bearbeiten$/ }).click();
    const move = systemPage.getByRole("dialog", { name: /bearbeiten$/ });
    await move.getByTestId("alias-target").selectOption(other);
    const moved = systemPage.waitForResponse(
      (r) =>
        new URL(r.url()).pathname.includes("/redirect-aliases/") &&
        r.request().method() === "PUT",
    );
    await move
      .getByRole("button", { name: "Alias umstellen", exact: true })
      .click();
    assert.equal((await moved).status(), 200);
    await expect(systemSection.locator(".campaign-alias-row")).toHaveCount(0);
    await systemPage.goto(origin + admin(other));
    await systemPage.getByRole("tab", { name: /Aliase/ }).click();
    const movedRow = systemPage
      .locator(".campaign-alias-row")
      .filter({ hasText: `browser-${name}-two` });
    await expect(movedRow).toBeVisible();
    await movedRow.getByRole("button", { name: /entfernen$/ }).click();
    const removed = systemPage.waitForResponse(
      (r) =>
        new URL(r.url()).pathname.includes("/redirect-aliases/") &&
        r.request().method() === "DELETE",
    );
    await systemPage
      .getByRole("alertdialog")
      .getByRole("button", { name: "Entfernen bestätigen", exact: true })
      .click();
    assert.equal((await removed).status(), 200);
    await expect(movedRow).toHaveCount(0);
    await system.close();
    console.log(
      `alias-browser ${name}: actual Charity/System SMTP login, two aliases, disable/enable, collision with preserved inputs, scoped target selection, move/remove, redirect and responsive layout passed`,
    );
  } finally {
    await browser.close();
  }
}
