import { analyzeAccessibility } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

// The Lieferfenster tab of the action detail (Leitsystem Task 6.1) against
// the real stack: a fresh Krapfentaxi draft from the template (delivery
// capability), windows added through the modal, a real concurrent save
// (409, input kept), retiring a window, the "ausgebucht" switch and the
// phone width. Runs in the
// action-admin stack (tools/action_admin/test.sh) as Klara.
const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;
const session = process.env.KLARA_SESSION;

if (!baseUrl || !artifactDirectory || !session) {
  throw new Error("Delivery windows browser environment is incomplete");
}

test.setTimeout(120_000);

async function expectNoSeriousAccessibilityViolations(page, label) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter(
          (animation) => animation.effect?.getTiming().iterations !== Infinity,
        )
        .map((animation) => animation.finished),
    ),
  );
  const accessibility = await analyzeAccessibility(page);
  expect(
    accessibility.violations
      .filter((violation) =>
        ["critical", "serious"].includes(violation.impact ?? ""),
      )
      .map((violation) => `${label}: ${violation.id}`),
  ).toEqual([]);
}

test("Lieferfenster: add in the modal, keep input on a conflict, retire", async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
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
    const suffix = Date.now();
    const created = await context.request.post(
      `${baseUrl}/api/v1/actions/from-template`,
      {
        headers: { Origin: baseUrl },
        data: {
          templateKey: "krapfentaxi",
          name: "Krapfentaxi Lieferfenster 2037",
          carrierName: "Synthetischer Testclub",
          purpose: "Synthetische Abnahme der Lieferfenster",
          archiveSlug: `lieferfenster-${suffix}`,
          startsOn: "2037-12-01",
          endsOn: "2037-12-31",
          beneficiaries: [
            {
              organizationName: "Testorganisation",
              publicDescription: "Synthetische Begünstigte",
            },
          ],
          goal: { goalValue: "100", unit: "Boxen", actualValue: "0" },
        },
      },
    );
    expect(created.status()).toBe(201);
    const actionId = (await created.json()).action.id;
    const configPath = `${baseUrl}/api/v1/actions/${actionId}/delivery-configuration`;

    await page.goto(`${baseUrl}/admin/actions/${actionId}#delivery`);
    const tab = page.getByRole("tab", { name: /Lieferfenster/ });
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("delivery-next-step")).toContainText(
      "Erstes Lieferfenster anlegen",
    );

    const addWindow = async (day, from, to) => {
      await page
        .getByRole("button", { name: "Lieferfenster hinzufügen", exact: true })
        .first()
        .click();
      const dialog = page.getByRole("dialog", {
        name: "Lieferfenster hinzufügen",
      });
      await expect(dialog).toBeVisible();
      await dialog.getByTestId("delivery-window-day").fill(day);
      await dialog.getByTestId("delivery-window-from").fill(from);
      await dialog.getByTestId("delivery-window-to").fill(to);
      return dialog;
    };

    // The modal checks the period and the times before it saves.
    let dialog = await addWindow("2038-01-04", "10:00", "09:00");
    await dialog.getByTestId("delivery-window-save").click();
    await expect(
      dialog.getByText("Der Tag muss im Zeitraum der Aktion liegen."),
    ).toBeVisible();
    await expect(
      dialog.getByText("Das Ende muss nach dem Beginn liegen."),
    ).toBeVisible();
    await dialog.getByTestId("delivery-window-day").fill("2037-12-04");
    await dialog.getByTestId("delivery-window-to").fill("12:00");
    await dialog.getByTestId("delivery-window-save").click();
    await expect(dialog).toBeHidden();
    await expect(page.locator(".toast").last()).toContainText("angelegt");

    dialog = await addWindow("2037-12-05", "08:00", "10:00");
    await dialog.getByTestId("delivery-window-save").click();
    await expect(dialog).toBeHidden();
    const rows = page.getByTestId("delivery-windows").locator("tbody tr");
    await expect(rows).toHaveCount(2);
    await expect(tab).toContainText("2");
    let saved = await (await context.request.get(configPath)).json();
    expect(saved.windows).toHaveLength(2);
    await expectNoSeriousAccessibilityViolations(page, "Lieferfenster");

    // A real concurrent save from another session: 409, the modal keeps
    // its input, the second try saves on the current revision.
    dialog = await addWindow("2037-12-06", "14:00", "16:00");
    const parallel = await context.request.put(configPath, {
      headers: { Origin: baseUrl },
      data: {
        expectedRevision: saved.revision,
        enabled: saved.enabled,
        timezone: saved.timezone,
        windows: [
          ...saved.windows,
          { deliveryOn: "2037-12-07", startsAt: "08:00", endsAt: "10:00" },
        ],
      },
    });
    expect(parallel.status()).toBe(200);
    await dialog.getByTestId("delivery-window-save").click();
    await expect(dialog.getByText(/inzwischen geändert/)).toBeVisible();
    await expect(dialog.getByTestId("delivery-window-day")).toHaveValue(
      "2037-12-06",
    );
    await expect(dialog.getByTestId("delivery-window-from")).toHaveValue(
      "14:00",
    );
    await dialog.getByTestId("delivery-window-save").click();
    await expect(dialog).toBeHidden();
    await expect(rows).toHaveCount(4);
    saved = await (await context.request.get(configPath)).json();
    expect(saved.windows).toHaveLength(4);

    // Activation is the next step once windows exist (template: off).
    if (!saved.enabled) {
      await page.getByTestId("delivery-enable").click();
      await page
        .getByRole("alertdialog")
        .getByRole("button", { name: "Lieferplanung aktivieren" })
        .click();
      await expect(page.getByTestId("delivery-next-step")).toHaveCount(0);
      saved = await (await context.request.get(configPath)).json();
      expect(saved.enabled).toBe(true);
    }

    // Retiring asks first and keeps the row, struck through.
    await page
      .getByRole("button", { name: /05\.12\. · 08:00–10:00 Uhr stilllegen$/ })
      .click();
    const confirm = page.getByRole("alertdialog");
    await expect(confirm).toContainText("Bestehende Bestellungen");
    await confirm.getByRole("button", { name: "Fenster stilllegen" }).click();
    const retired = rows.filter({ hasText: "05.12. · 08:00–10:00" });
    await expect(retired).toHaveAttribute("data-retired", "true");
    await expect(retired).toContainText("Stillgelegt");
    saved = await (await context.request.get(configPath)).json();
    expect(saved.windows.filter((window) => window.retired)).toHaveLength(1);
    await expect(tab).toContainText("3");

    // "Ausgebucht" saves at once, outside the form, and keeps the revision.
    const before = saved.revision;
    const full = page.getByRole("switch", {
      name: /04\.12\. · 10:00–12:00 Uhr ausgebucht$/,
    });
    // The switch follows the saved state, so click and wait for it.
    await full.click();
    await expect(full).toBeChecked();
    await expect(page.locator(".toast").last()).toContainText(
      "als ausgebucht markiert",
    );
    const fullRow = rows.filter({ hasText: "04.12. · 10:00–12:00" });
    await expect(fullRow).toContainText("Ausgebucht");
    saved = await (await context.request.get(configPath)).json();
    expect(saved.revision).toBe(before);
    expect(
      saved.windows.find((window) => window.startsAt.startsWith("10:00"))
        .fullyBooked,
    ).toBe(true);
    await expectNoSeriousAccessibilityViolations(page, "Ausgebucht");
    await full.click();
    await expect(full).not.toBeChecked();
    await expect(page.locator(".toast").last()).toContainText("wieder buchbar");
    await expect(fullRow).toContainText("Buchbar");

    // Retiring a full window clears "Ausgebucht".
    const second = page.getByRole("switch", {
      name: /06\.12\. · 14:00–16:00 Uhr ausgebucht$/,
    });
    await second.click();
    await expect(second).toBeChecked();
    await expect(
      rows.filter({ hasText: "06.12. · 14:00–16:00" }),
    ).toContainText("Ausgebucht");
    await page
      .getByRole("button", { name: /06\.12\. · 14:00–16:00 Uhr stilllegen$/ })
      .click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Fenster stilllegen" })
      .click();
    const retiredFull = rows.filter({ hasText: "06.12. · 14:00–16:00" });
    await expect(retiredFull).toHaveAttribute("data-retired", "true");
    await expect(retiredFull.getByRole("switch")).toHaveCount(0);
    saved = await (await context.request.get(configPath)).json();
    const cleared = saved.windows.find(
      (window) => window.deliveryOn === "2037-12-06",
    );
    expect([cleared.retired, cleared.fullyBooked]).toEqual([true, false]);
    await expect(tab).toContainText("2");

    // Phone width: the page does not scroll sideways.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("delivery-windows")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${artifactDirectory}/delivery-windows-mobile.png`,
      fullPage: true,
    });
    expect(pageErrors).toEqual([]);
  } finally {
    await context.close();
  }
});
