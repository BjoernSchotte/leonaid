// Command palette (Leitsystem Task 3.3) against the real stack with the
// golden fixture: Klara is charity admin of Krapfentaxi 2026 (invoices
// KT26-…), Felix only of Krapfentaxi Nord 2026, Simone is system admin
// without memberships. With LEONAID_PALETTE_DISABLED_MODULES set, the API
// runs with LEONAID_DISABLED_MODULES and only the switched-off test runs.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const klaraSession = process.env.KLARA_SESSION;
const felixSession = process.env.FELIX_SESSION;
const simoneSession = process.env.SIMONE_SESSION;
const disabledModules = (process.env.LEONAID_PALETTE_DISABLED_MODULES ?? "")
  .split(",")
  .filter(Boolean);
const actionId = "20000000-0000-4000-8000-000000000001";

if (!baseUrl || !klaraSession || !felixSession || !simoneSession) {
  throw new Error("Command palette browser environment is incomplete");
}

test.setTimeout(90_000);

async function signedIn(
  browser,
  session,
  viewport = { width: 1440, height: 900 },
) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport,
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
  await context.addInitScript(() => {
    window.localStorage.setItem("leonaid.theme", "light");
    // Every <style> element added after load, except Playwright's own
    // screenshot helper ("body {}").
    window.__addedStyles = 0;
    new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node.nodeName === "STYLE" && node.textContent !== "body {}") {
            window.__addedStyles += 1;
          }
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
  return context;
}

// The loading screen also has an h1; the mounted palette means the shell
// and its hotkeys are live.
async function shellReady(page) {
  await expect(page.locator("dialog.palette")).toBeAttached();
  await expect(page.locator("main h1, #main-content h1").first()).toBeVisible();
}

const palette = (page) => page.getByRole("dialog", { name: "Befehlspalette" });
const paletteInput = (page) => palette(page).getByRole("combobox");

async function openPalette(page) {
  await page.keyboard.press("Control+k");
  await expect(palette(page)).toBeVisible();
  await expect(paletteInput(page)).toBeFocused();
}

const navLabel = (group, label) =>
  group.locator(".palette-label", { hasText: new RegExp(`^${label}$`) });

function searchResponse(page, query) {
  return page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/search?") &&
      new URL(response.url()).searchParams.get("q") === query,
  );
}

test.describe("enabled modules", () => {
  test.skip(disabledModules.length > 0, "runs against the default API");

  test("opens with Strg+K and /, searches, closes with focus return and adds no <style>", async ({
    browser,
  }) => {
    const context = await signedIn(browser, klaraSession);
    const page = await context.newPage();
    try {
      await page.goto(`${baseUrl}/admin/?action=${actionId}`);
      await shellReady(page);
      await page.keyboard.press("Tab");
      const skipLink = page.getByRole("link", { name: "Zum Inhalt springen" });
      await expect(skipLink).toBeFocused();

      await openPalette(page);
      const goTo = palette(page).getByRole("group", { name: "Gehe zu" });
      await expect(navLabel(goTo, "Aufgaben")).toBeVisible();
      await expect(navLabel(goTo, "Rechnungen")).toBeVisible();

      const response = searchResponse(page, "KT26");
      await paletteInput(page).fill("KT26");
      const body = await (await response).json();
      expect(body.results.some((hit) => hit.type === "invoice")).toBe(true);
      const invoices = palette(page).getByRole("group", { name: "Rechnungen" });
      await expect(
        invoices.getByRole("option", { name: /KT26-0001/ }),
      ).toBeVisible();
      const axe = await new AxeBuilder({ page })
        .include("dialog.palette")
        .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
        .analyze();
      expect(
        axe.violations.filter(({ impact }) =>
          ["serious", "critical"].includes(impact),
        ),
      ).toEqual([]);

      await page.keyboard.press("Escape");
      await expect(palette(page)).toBeHidden();
      await expect(skipLink).toBeFocused();

      // "/" opens it outside fields and lists; inside the field it types.
      await page.locator("body").click({ position: { x: 5, y: 400 } });
      await page.keyboard.press("/");
      await expect(palette(page)).toBeVisible();
      await expect(paletteInput(page)).toHaveValue("");
      await page.keyboard.press("/");
      await expect(paletteInput(page)).toHaveValue("/");
      // Strg+K toggles it closed from inside the field.
      await page.keyboard.press("Control+k");
      await expect(palette(page)).toBeHidden();

      expect(await page.evaluate(() => window.__addedStyles)).toBe(0);
      // CSSOM writes (the theme's color-scheme on <html>) are allowed; the
      // palette itself carries no style attribute.
      expect(
        await page
          .locator("dialog.palette[style], dialog.palette [style]")
          .count(),
      ).toBe(0);
    } finally {
      await context.close();
    }
  });

  test("typing aborts the request in flight", async ({ browser }) => {
    const context = await signedIn(browser, klaraSession);
    const page = await context.newPage();
    try {
      await page.route("**/api/v1/search?*", async (route) => {
        const query = new URL(route.request().url()).searchParams.get("q");
        if (query === "Kr") await new Promise((done) => setTimeout(done, 3000));
        try {
          await route.continue();
        } catch {
          // The page aborted the request while it was held.
        }
      });
      await page.goto(`${baseUrl}/admin/?action=${actionId}`);
      await shellReady(page);
      await openPalette(page);
      const sent = page.waitForRequest(
        (request) =>
          request.url().includes("/api/v1/search?") &&
          new URL(request.url()).searchParams.get("q") === "Kr",
      );
      await paletteInput(page).fill("Kr");
      const first = await sent;
      await expect(palette(page).getByRole("status")).toHaveText(
        "Wird gesucht …",
      );
      const aborted = page.waitForEvent(
        "requestfailed",
        (request) => request === first,
      );
      const latest = searchResponse(page, "Kra");
      await paletteInput(page).press("a");
      expect((await aborted).failure()?.errorText).toMatch(/abort/i);
      await latest;
      await expect(
        palette(page)
          .getByRole("group", { name: "Charity-Aktionen" })
          .getByRole("option", { name: /Krapfentaxi 2026/ }),
      ).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test("Anlegen opens the create form; the page offers it in place", async ({
    browser,
  }) => {
    const context = await signedIn(browser, klaraSession);
    const page = await context.newPage();
    try {
      await page.goto(`${baseUrl}/admin/?action=${actionId}`);
      await shellReady(page);
      await openPalette(page);
      const creates = palette(page).getByRole("group", { name: "Anlegen" });
      for (const label of [
        "Aktion anlegen",
        "Aufgabe anlegen",
        "Material hochladen",
        "Wissensseite anlegen",
        "Mitglied einladen",
      ]) {
        await expect(
          creates.getByRole("option", { name: label }),
        ).toBeVisible();
      }
      await creates.getByRole("option", { name: "Aufgabe anlegen" }).click();
      await expect(page).toHaveURL(/\/admin\/tasks/);
      const title = page
        .getByRole("form", { name: "Aufgabe schnell erfassen" })
        .getByLabel("Titel", { exact: true });
      await expect(title).toBeFocused();
      // The request is used once; a reload does not reopen it.
      expect(new URL(page.url()).searchParams.has("create")).toBe(false);

      // On the tasks page the same create is a page command.
      await page.locator("body").click({ position: { x: 5, y: 400 } });
      await openPalette(page);
      const onPage = palette(page).getByRole("group", {
        name: "Auf dieser Seite · Aufgaben",
      });
      await expect(
        onPage.getByRole("option", { name: "Aufgabe anlegen" }),
      ).toBeVisible();
      await expect(
        palette(page)
          .getByRole("group", { name: "Anlegen" })
          .getByRole("option", {
            name: "Aufgabe anlegen",
          }),
      ).toHaveCount(0);
      await onPage.getByRole("option", { name: "Aufgabe anlegen" }).click();
      await expect(palette(page)).toBeHidden();
      await expect(title).toBeFocused();

      await openPalette(page);
      await palette(page)
        .getByRole("group", { name: "Anlegen" })
        .getByRole("option", { name: "Mitglied einladen" })
        .click();
      // The members page opens its invitation dialog and drops ?create=.
      await expect(
        page.getByRole("dialog", { name: "Mitglied einladen" }),
      ).toBeVisible();
      await expect(page).toHaveURL(/\/admin\/members$/);
    } finally {
      await context.close();
    }
  });

  test("opens on top of an open modal; Esc closes only the palette", async ({
    browser,
  }) => {
    const context = await signedIn(browser, klaraSession);
    const page = await context.newPage();
    try {
      await page.goto(`${baseUrl}/admin/?action=${actionId}`);
      await shellReady(page);
      await page.keyboard.press("?");
      const help = page.getByRole("dialog", { name: "Tastenkürzel" });
      await expect(help).toBeVisible();
      const close = help.getByRole("button", { name: "Schließen" });
      await close.focus();
      await openPalette(page);
      // The palette is the topmost modal: the help behind it is inert.
      expect(
        await page.evaluate(() => {
          const point = document
            .querySelector("dialog.palette")
            .getBoundingClientRect();
          const hit = document.elementFromPoint(point.x + 40, point.y + 28);
          return Boolean(hit?.closest("dialog.palette"));
        }),
      ).toBe(true);
      await page.keyboard.press("Escape");
      await expect(palette(page)).toBeHidden();
      await expect(help).toBeVisible();
      await expect(close).toBeFocused();
      await page.keyboard.press("Escape");
      await expect(help).toBeHidden();
    } finally {
      await context.close();
    }
  });

  test("a charity admin of another action sees no invoice hit", async ({
    browser,
  }) => {
    const context = await signedIn(browser, felixSession, {
      width: 390,
      height: 844,
    });
    const page = await context.newPage();
    try {
      await page.goto(`${baseUrl}/admin/`);
      await shellReady(page);
      await openPalette(page);
      const response = searchResponse(page, "KT26");
      await paletteInput(page).fill("KT26");
      const body = await (await response).json();
      expect(body.results.filter((hit) => hit.type === "invoice")).toEqual([]);
      await expect(palette(page).locator(".palette-empty")).toContainText(
        "Keine Treffer für „KT26“",
      );
      await expect(
        palette(page).locator("[data-hit-type='invoice']"),
      ).toHaveCount(0);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow).toBeLessThanOrEqual(1);
    } finally {
      await context.close();
    }
  });

  test("a system admin lands on the action of an invoice and order hit", async ({
    browser,
  }) => {
    const context = await signedIn(browser, simoneSession);
    const page = await context.newPage();
    try {
      await page.goto(`${baseUrl}/admin/actions`);
      await shellReady(page);
      await openPalette(page);
      const invoiceSearch = searchResponse(page, "KT26-0001");
      await paletteInput(page).fill("KT26-0001");
      await invoiceSearch;
      await palette(page)
        .getByRole("group", { name: "Rechnungen" })
        .getByRole("option", { name: /KT26-0001/ })
        .click();
      await expect(page).toHaveURL(
        new RegExp(`/admin/invoices\\?action=${actionId}`),
      );
      await expect(page).toHaveURL(/[?&]view=all(&|$)/);
      await expect(page).toHaveURL(/[?&]open=[0-9a-f-]{36}/);
      // The unlisted action stays the selected one and the hit opens.
      await expect(
        page.locator(
          '[data-testid="invoice-action"] option:checked, [data-testid="invoice-action-name"]',
        ),
      ).toHaveText("Krapfentaxi 2026");
      await expect(page.getByTestId("invoice-detail")).toContainText(
        "KT26-0001",
      );

      await openPalette(page);
      const orderSearch = searchResponse(page, "Musterwerk");
      await paletteInput(page).fill("Musterwerk");
      const orders = (await (await orderSearch).json()).results.filter(
        (hit) => hit.type === "order",
      );
      expect(orders.length).toBeGreaterThan(0);
      await palette(page)
        .getByRole("group", { name: "Bestellungen" })
        .getByRole("option")
        .first()
        .click();
      await expect(page).toHaveURL(
        new RegExp(`/admin/orders\\?action=${actionId}`),
      );
      await expect(page.getByTestId("commitment-admin-action")).toHaveValue(
        actionId,
      );
      await expect(
        page.getByTestId("commitment-admin-action").locator("option:checked"),
      ).toHaveText("Krapfentaxi 2026");
    } finally {
      await context.close();
    }
  });
});

test.describe("switched-off modules", () => {
  test.skip(
    disabledModules.length === 0,
    "needs the API with LEONAID_DISABLED_MODULES",
  );

  test("a switched-off module contributes no navigation and no search", async ({
    browser,
  }) => {
    // Knowledge and inbox require tasks, so the server only accepts tasks off
    // together with both (bootstrap/api.py).
    expect(disabledModules).toEqual(["tasks", "inbox", "knowledge"]);
    const context = await signedIn(browser, klaraSession);
    const page = await context.newPage();
    const moduleRequests = [];
    page.on("request", (request) => {
      const path = new URL(request.url()).pathname;
      if (/^\/api\/v1\/(tasks|task-lists|inbox|knowledge)/.test(path)) {
        moduleRequests.push(path);
      }
    });
    try {
      const identity = page.waitForResponse((response) =>
        response.url().endsWith("/api/v1/identity/me"),
      );
      await page.goto(`${baseUrl}/admin/?action=${actionId}`);
      const keys = (await (await identity).json()).navigation.map(
        (item) => item.key,
      );
      expect(keys).not.toContain("tasks");
      expect(keys).not.toContain("inbox");
      expect(keys).not.toContain("knowledge");
      expect(keys).toContain("materials");

      await openPalette(page);
      const goTo = palette(page).getByRole("group", { name: "Gehe zu" });
      await expect(navLabel(goTo, "Material")).toBeVisible();
      await expect(navLabel(goTo, "Wissen")).toHaveCount(0);
      await expect(navLabel(goTo, "Aufgaben")).toHaveCount(0);
      await expect(navLabel(goTo, "Eingang")).toHaveCount(0);
      const creates = palette(page).getByRole("group", { name: "Anlegen" });
      await expect(
        creates.getByRole("option", { name: "Material hochladen" }),
      ).toBeVisible();
      await expect(
        creates.getByRole("option", { name: /Aufgabe anlegen/ }),
      ).toHaveCount(0);
      await expect(
        creates.getByRole("option", { name: /Wissensseite/ }),
      ).toHaveCount(0);

      const response = searchResponse(page, "Aufgabe");
      await paletteInput(page).fill("Aufgabe");
      await response;
      await expect(palette(page).getByRole("status")).toBeHidden();
      await expect(
        palette(page).locator(
          "[data-hit-type='task'], [data-hit-type='inbox-case'], [data-hit-type='knowledge-page']",
        ),
      ).toHaveCount(0);
      await expect(palette(page).locator(".palette-footer")).not.toContainText(
        /Aufgaben|Eingänge|Wissen/,
      );
      expect(moduleRequests).toEqual([]);
    } finally {
      await context.close();
    }
  });
});
