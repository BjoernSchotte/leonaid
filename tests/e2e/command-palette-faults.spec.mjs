// Command palette fault test, split from command-palette.spec.mjs so the
// reviewed network fault (one held search request) lives in its own file.
// Runs in the same stack and run as command-palette.spec.mjs
// (tools/ux_acceptance/test.sh), with the golden fixture: Klara is charity
// admin of Krapfentaxi 2026.
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const klaraSession = process.env.KLARA_SESSION;
const disabledModules = (process.env.LEONAID_PALETTE_DISABLED_MODULES ?? "")
  .split(",")
  .filter(Boolean);
const actionId = "20000000-0000-4000-8000-000000000001";

if (!baseUrl || !klaraSession) {
  throw new Error("Command palette browser environment is incomplete");
}

test.setTimeout(90_000);

async function signedIn(browser, session) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1440, height: 900 },
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

function searchResponse(page, query) {
  return page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/search?") &&
      new URL(response.url()).searchParams.get("q") === query,
  );
}

test.describe("enabled modules", () => {
  test.skip(disabledModules.length > 0, "runs against the default API");

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
});
