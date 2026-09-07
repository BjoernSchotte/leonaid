import assert from "node:assert/strict";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const action = "20000000-0000-4000-8000-000000000001";
const other = "20000000-0000-4000-8000-000000000003";
const admin = (id) => `/admin/actions/${id}`;
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
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
    await page.getByRole("tab", { name: /Öffentliche Seite/ }).click();
    const section = page.getByRole("region", {
      name: "Adressen und Weiterleitungen",
    });
    await expect(
      section.getByText("Dauerhafte Kampagnenadresse:", { exact: false }),
    ).toBeVisible();
    const submit = async (form, method, button, status = 200) => {
      const result = page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname.includes("/redirect-aliases") &&
          r.request().method() === method,
      );
      await form.getByRole("button", { name: button, exact: true }).click();
      assert.equal((await result).status(), status);
    };
    const create = section
      .locator("form")
      .filter({ has: page.getByLabel("Neue Kurzadresse", { exact: false }) });
    for (const suffix of ["one", "two"]) {
      await create
        .getByLabel("Neue Kurzadresse", { exact: false })
        .fill(`browser-${name}-${suffix}`);
      await submit(create, "POST", "Adresse hinzufügen");
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
    const form = row.locator("form");
    await expect(form.getByLabel("Zielkampagne").locator("option")).toHaveCount(
      1,
    );
    await form
      .getByLabel("Weiterleitung", { exact: false })
      .selectOption("disabled");
    await submit(form, "PUT", "Änderungen speichern");
    await expect(row.getByRole("status").first()).toHaveText("Deaktiviert");
    const inactive = await context.request.get(`${origin}/browser-${name}-one`);
    assert.equal(inactive.headers()["x-leonaid-public-state"], "inactive");
    await form
      .getByLabel("Kurzadresse bearbeiten", { exact: false })
      .fill("krapfentaxi");
    await submit(form, "PUT", "Änderungen speichern", 409);
    await expect(
      form.getByText("Deine Eingaben bleiben erhalten.", { exact: false }),
    ).toBeVisible();
    await expect(
      form.getByLabel("Kurzadresse bearbeiten", { exact: false }),
    ).toHaveValue("krapfentaxi");
    await form
      .getByLabel("Kurzadresse bearbeiten", { exact: false })
      .fill(`browser-${name}-one`);
    await form
      .getByLabel("Weiterleitung", { exact: false })
      .selectOption("enabled");
    await submit(form, "PUT", "Änderungen speichern");
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
    await form
      .getByRole("button", { name: "Adresse entfernen", exact: true })
      .click();
    await submit(form, "DELETE", "Entfernen bestätigen");
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
    await systemPage.getByRole("tab", { name: /Öffentliche Seite/ }).click();
    const systemSection = systemPage.getByRole("region", {
      name: "Adressen und Weiterleitungen",
    });
    const remaining = systemSection
      .locator(".campaign-alias-row")
      .filter({ hasText: `browser-${name}-two` });
    await remaining.getByLabel("Zielkampagne").selectOption(other);
    const moved = systemPage.waitForResponse(
      (r) =>
        new URL(r.url()).pathname.includes("/redirect-aliases/") &&
        r.request().method() === "PUT",
    );
    await remaining
      .getByRole("button", { name: "Änderungen speichern", exact: true })
      .click();
    assert.equal((await moved).status(), 200);
    await expect(systemSection.locator(".campaign-alias-row")).toHaveCount(0);
    await systemPage.goto(origin + admin(other));
    await systemPage.getByRole("tab", { name: /Öffentliche Seite/ }).click();
    const movedRow = systemPage
      .locator(".campaign-alias-row")
      .filter({ hasText: `browser-${name}-two` });
    await expect(movedRow).toBeVisible();
    await movedRow
      .getByRole("button", { name: "Adresse entfernen", exact: true })
      .click();
    const removed = systemPage.waitForResponse(
      (r) =>
        new URL(r.url()).pathname.includes("/redirect-aliases/") &&
        r.request().method() === "DELETE",
    );
    await movedRow
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
