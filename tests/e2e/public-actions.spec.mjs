import { analyzeAccessibility, WCAG_TAGS } from "./axe.mjs";
import { expect, test } from "./csp-guard.mjs";

const baseUrl = process.env.LEONAID_E2E_BASE_URL;
const artifactDirectory = process.env.LEONAID_E2E_ARTIFACT_DIR;

if (!baseUrl || !artifactDirectory) {
  throw new Error(
    "LEONAID_E2E_BASE_URL and LEONAID_E2E_ARTIFACT_DIR are required",
  );
}

test.use({ ignoreHTTPSErrors: true });

// Every public page loads this script for the header's app links.
const headerScript = 'script[src*="/_astro/PublicAppLinks."]';
const pageScripts = `script:not(${headerScript})`;

async function expectNoHorizontalScroll(page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

async function expectTouchTargets(page) {
  const undersized = await page.evaluate(() =>
    [...document.querySelectorAll("a, button")]
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return (
          style.visibility !== "hidden" &&
          style.display !== "none" &&
          rect.width > 0 &&
          rect.height > 0 &&
          (rect.width < 44 || rect.height < 44)
        );
      })
      .map((element) => ({
        height: Math.round(element.getBoundingClientRect().height),
        label:
          element.getAttribute("aria-label") ?? element.textContent?.trim(),
        width: Math.round(element.getBoundingClientRect().width),
      })),
  );
  expect(undersized).toEqual([]);
}

test("active, inactive and archived public pages stay functionally identical", async ({
  browserName,
  page,
}) => {
  const response = await page.goto(`${baseUrl}/krapfentaxi`);
  expect(response?.status()).toBe(200);
  expect(response?.headers()["x-leonaid-public-state"]).toBe("published");
  await expect(page).toHaveTitle("Krapfentaxi 2027 · LeonAid");
  await expect(page.getByTestId("public-action-name")).toHaveText(
    "Krapfentaxi 2027",
  );
  await expect(page.getByTestId("public-offerings")).toContainText(
    "Krapfenbox",
  );
  await expect(page.getByTestId("public-offerings")).toContainText("24 Stück");
  await expect(page.getByTestId("public-offerings")).toContainText("36,00");
  await expect(
    page.getByRole("heading", { name: "Wem die Aktion hilft" }),
  ).toBeVisible();
  await expect(page.getByText("Zukunftswerk Beispielstadt")).toBeVisible();
  // A live action takes contact requests only with the consent checkbox.
  const inquiry = page.locator("leonaid-inbox-form");
  await expect(inquiry).toBeVisible();
  await expect(
    inquiry.getByRole("checkbox", { name: /Ich willige ein/ }),
  ).toHaveAttribute("required", "");
  await expect(
    page.getByRole("heading", {
      name: "Transparent, bevor Daten erhoben werden.",
    }),
  ).toBeVisible();
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    `${baseUrl}/archive/krapfentaxi-2027`,
  );
  await expect(page.locator('meta[property="og:image"]')).toHaveAttribute(
    "content",
    new RegExp(`/_astro/hero\\.[^/]+\\.webp$`),
  );
  await expect(page.locator("body")).toHaveClass("taxi-site");
  await expect(page.locator(".taxi-hero__logo")).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Aktionsnavigation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: /Unsere Krapfenbäckerei/ }),
  ).toBeVisible();
  const unloadedImages = await page
    .locator("img")
    .evaluateAll((images) =>
      images
        .filter(
          (image) =>
            image.loading !== "lazy" &&
            (!image.complete || image.naturalWidth === 0),
        )
        .map((image) => image.src),
    );
  expect(unloadedImages).toEqual([]);
  await expect(page.locator('img[src*="lions-krapfentaxi.de"]')).toHaveCount(0);
  // Besides the header's app links (headerScript), the inquiry form is the
  // only enhanced element of this page.
  await expect(page.locator(headerScript)).toHaveCount(1);
  await expect(page.locator(pageScripts)).toHaveCount(1);
  await expect(page.locator(pageScripts)).toHaveAttribute(
    "src",
    /\/_astro\/PublicInbox\./,
  );
  await expect(page.locator("[data-order-form]")).toHaveCount(0);
  await expectNoHorizontalScroll(page);
  await expectTouchTargets(page);

  await page.keyboard.press("Tab");
  await expect(page.getByText("Zum Inhalt springen")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main-content$/);

  await page.screenshot({
    path: `${artifactDirectory}/public-active-${browserName}-390.png`,
    fullPage: true,
  });

  const archiveResponse = await page.goto(
    `${baseUrl}/archive/krapfentaxi-2027`,
  );
  expect(archiveResponse?.status()).toBe(200);
  expect(archiveResponse?.headers()["x-leonaid-public-state"]).toBe("archive");
  await expect(
    page.getByRole("heading", { name: "Diese Aktion ist abgeschlossen." }),
  ).toBeVisible();
  await expect(page.getByTestId("public-offerings")).toContainText(
    "Krapfenbox",
  );
  await expect(page.locator("form")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Jetzt bestellen" })).toHaveCount(
    0,
  );
  await expect(page.locator("body")).toHaveClass("taxi-site");
  await expect(page.locator(pageScripts)).toHaveCount(0);
  await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
    "href",
    `${baseUrl}/archive/krapfentaxi-2027`,
  );

  const inactiveResponse = await page.goto(`${baseUrl}/winterpause`);
  expect(inactiveResponse?.status()).toBe(200);
  expect(inactiveResponse?.headers()["x-leonaid-public-state"]).toBe(
    "inactive",
  );
  await expect(
    page.getByRole("heading", { name: "Derzeit keine aktive Aktion" }),
  ).toBeVisible();
  await expect(page.getByText("Krapfentaxi 2027")).toHaveCount(0);
  await expect(page.locator("form")).toHaveCount(0);
  await expect(page.locator(".taxi-hero")).toHaveCount(0);
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
    "content",
    "noindex,follow",
  );

  if (browserName === "chromium") {
    await page.screenshot({
      path: `${artifactDirectory}/public-inactive-chromium-390.png`,
      fullPage: true,
    });
  }
});

test("public action page stays readable from 320 to 1440 pixels", async ({
  browserName,
  page,
}) => {
  test.skip(
    browserName !== "chromium",
    "This run archives the visual edge widths.",
  );

  await page.setViewportSize({ width: 320, height: 760 });
  await page.goto(`${baseUrl}/krapfentaxi`);
  await expectNoHorizontalScroll(page);
  await expectTouchTargets(page);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`${baseUrl}/krapfentaxi`);
  await expectNoHorizontalScroll(page);
  await page.screenshot({
    path: `${artifactDirectory}/public-active-chromium-1440.png`,
    fullPage: true,
  });

  await page.goto(`${baseUrl}/archive/krapfentaxi-2027`);
  await page.screenshot({
    path: `${artifactDirectory}/public-archive-chromium-1440.png`,
    fullPage: true,
  });
});

test("the home page campaign list fits phone and desktop", async ({ page }) => {
  await page.goto(`${baseUrl}/`);
  const list = page.getByTestId("public-campaign-list");
  const link = list.locator('a[href="/krapfentaxi"]');
  for (const [width, height] of [
    [390, 844],
    [1440, 900],
  ]) {
    await page.setViewportSize({ width, height });
    await expectNoHorizontalScroll(page);
    const box = await link.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
  const accessibility = await analyzeAccessibility(page, {
    include: '[data-testid="public-campaign-list"]',
  });
  expect(accessibility.violations).toEqual([]);
  await link.click();
  await expect(page).toHaveURL(/\/krapfentaxi$/);
});

// Server-rendered links and the active campaigns: HTML answers, no browser
// (E-026). The legal pages' layout and a11y stay in the browser below.
test("public pages link the active campaigns, Impressum and Datenschutz", async ({
  request,
}) => {
  const html = async (path) => {
    const response = await request.get(`${baseUrl}${path}`);
    expect(response.status(), path).toBe(200);
    return response.text();
  };
  // The markup from a marker on: the links that follow it.
  const after = (text, marker, path) => {
    const index = text.indexOf(marker);
    expect(index, `${path}: ${marker}`).toBeGreaterThan(-1);
    return text.slice(index);
  };
  const legalLinks = (text, path) => {
    for (const [href, label] of [
      ["/impressum", "Impressum"],
      ["/datenschutz", "Datenschutz"],
    ]) {
      expect(text, path).toMatch(
        new RegExp(`<a [^>]*href="${href}"[^>]*>\\s*${label}\\s*<`),
      );
    }
  };

  // The current Krapfentaxi edition links its alias page with the order
  // form; the archived 2025 edition is not listed.
  const home = await html("/");
  const campaigns = after(home, 'data-testid="public-campaign-list"', "/");
  const list = campaigns.slice(0, campaigns.indexOf("</section>"));
  expect(list).toContain("Aktuelle Aktionen");
  const hrefs = [...list.matchAll(/<a [^>]*href="([^"]+)"/g)].map(
    (match) => match[1],
  );
  expect(hrefs.filter((path) => path === "/krapfentaxi")).toHaveLength(1);
  expect(hrefs.some((path) => path.includes("krapfentaxi-2025"))).toBe(false);

  // Action page: provider and address, Impressum and the privacy page; the
  // per-action notice stays on the page and links the full policy.
  const action = await html("/krapfentaxi");
  const footer = after(action, "data-footer-legal", "/krapfentaxi");
  expect(footer).toMatch(
    /<span [^>]*data-footer-provider[^>]*>\s*Lions Hilfswerk LeonAid Golden e\.V\. · Clubweg 1 · 86150 Augsburg\s*</,
  );
  legalLinks(footer, "/krapfentaxi");
  expect(action.match(/id="datenschutz"/g)).toHaveLength(1);
  expect(action).toMatch(
    /<a [^>]*(data-privacy-full-link[^>]*href="\/datenschutz"|href="\/datenschutz"[^>]*data-privacy-full-link)/,
  );

  // Pages without an action and the legal pages themselves keep both links
  // (a live survey: surveys-completion-message.spec.mjs); sign-in,
  // invitation and e-mail change pages link both as well.
  for (const [path, marker] of [
    ["/", "data-footer-legal"],
    ["/impressum", "data-footer-legal"],
    ["/datenschutz", "data-footer-legal"],
    ["/login", "data-auth-legal"],
    ["/invite", "data-auth-legal"],
    ["/email-change", "data-auth-legal"],
  ]) {
    legalLinks(after(await html(path), marker, path), path);
  }
});

test("the Impressum and the privacy page render the legal configuration", async ({
  browserName,
  page,
}) => {
  test.skip(browserName !== "chromium", "Content check; parity is above.");
  const provider = "Lions Hilfswerk LeonAid Golden e.V.";
  const address = "Clubweg 1 · 86150 Augsburg";

  // The Impressum comes from the active legal configuration.
  for (const [width, height] of [
    [390, 844],
    [1440, 900],
  ]) {
    await page.setViewportSize({ width, height });
    const response = await page.goto(`${baseUrl}/impressum`);
    expect(response?.status()).toBe(200);
    await expect(
      page.getByRole("heading", { level: 1, name: "Impressum" }),
    ).toBeVisible();
    await expect(page.locator("[data-imprint-name]")).toHaveText(provider);
    await expect(page.locator("[data-imprint-address]")).toHaveText(address);
    await expect(
      page.getByRole("link", { name: "finanzen@leonaid.invalid" }),
    ).toHaveAttribute("href", "mailto:finanzen@leonaid.invalid");
    // § 5 DDG: representatives, second channel and register entry.
    await expect(page.locator("[data-imprint-representatives]")).toHaveText(
      "Vorstand: Paula Golden (Präsidentin), Simone System (Schatzmeisterin)",
    );
    await expect(page.locator("[data-imprint-phone]")).toHaveText(
      "+49 30 23125 044",
    );
    await expect(page.locator("[data-imprint-register]")).toHaveText(
      "Vereinsregister: Amtsgericht Augsburg, VR 0044",
    );
    await expect(page.locator("[data-imprint-content-responsible]")).toHaveText(
      "Paula Golden, Clubweg 1, 86150 Augsburg",
    );
    // No VAT ID in the golden data: the row is left out.
    await expect(page.locator("[data-imprint-vat-id]")).toHaveCount(0);
    // Only contact data is public: no tax number, no bank account.
    await expect(page.locator("main")).not.toContainText("103/999/99999");
    await expect(page.locator("body")).not.toContainText("DE89");
    await expectNoHorizontalScroll(page);
    await expectTouchTargets(page);
    const accessibility = await analyzeAccessibility(page, { tags: WCAG_TAGS });
    expect(
      accessibility.violations
        .filter((violation) =>
          ["serious", "critical"].includes(violation.impact),
        )
        .map((violation) => violation.id),
    ).toEqual([]);
    await page.screenshot({
      path: `${artifactDirectory}/public-impressum-${width}.png`,
      fullPage: true,
    });

    // The privacy page renders the active legal configuration's texts.
    const privacy = await page.goto(`${baseUrl}/datenschutz`);
    expect(privacy?.status()).toBe(200);
    await expect(
      page.getByRole("heading", { level: 1, name: "Datenschutzerklärung" }),
    ).toBeVisible();
    await expect(page.locator("[data-privacy-controller-name]")).toHaveText(
      `${provider} · ${address}`,
    );
    await expect(page.locator("[data-privacy-contact]")).toHaveAttribute(
      "href",
      "mailto:datenschutz@leonaid.invalid",
    );
    await expect(
      page.getByRole("heading", { level: 2, name: "Ihre Rechte" }),
    ).toBeVisible();
    await expect(page.locator("[data-privacy-orders]")).toContainText(
      "Krapfentaxi-Bestellung",
    );
    await expect(
      page.locator("#mitglieder").getByRole("heading", {
        level: 3,
        name: "Speicherung auf deinem Gerät",
      }),
    ).toBeVisible();
    await expect(page.locator("body")).not.toContainText("DATENSCHUTZ-GOLDEN");
    await expect(page.locator("body")).not.toContainText("DE89");
    await expectNoHorizontalScroll(page);
    await expectTouchTargets(page);
    const privacyAccessibility = await analyzeAccessibility(page, {
      tags: WCAG_TAGS,
    });
    expect(
      privacyAccessibility.violations
        .filter((violation) =>
          ["serious", "critical"].includes(violation.impact),
        )
        .map((violation) => violation.id),
    ).toEqual([]);
    await page.screenshot({
      path: `${artifactDirectory}/public-datenschutz-${width}.png`,
      fullPage: true,
    });
  }
});

// Sessions seeded by tools/public_actions/contract.py: Finn may use the
// admin app only, Anna the acquisition PWA only.
const appSessions = {
  admin: process.env.FINN_SESSION,
  acquirer: process.env.ANNA_SESSION,
};

async function openWithIdentity(page, path) {
  // The header asks the API after load; wait for that answer.
  const identity = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/identity/me"),
  );
  await page.goto(`${baseUrl}${path}`);
  return (await identity).status();
}

const appLinks = (page) =>
  page.getByRole("navigation", { name: "Ihre Bereiche" }).getByRole("link");

test("the public header links signed-in visitors to their apps", async ({
  browser,
  browserName,
  page,
}) => {
  expect(appSessions.admin && appSessions.acquirer).toBeTruthy();

  // Signed out: the header stays as it is, without app links.
  expect(await openWithIdentity(page, "/krapfentaxi")).toBe(401);
  await expect(
    page.getByRole("navigation", { name: "Ihre Bereiche" }),
  ).toBeHidden();
  await expect(page.locator("[data-app-link]")).toHaveCount(0);

  for (const [persona, expected] of [
    ["admin", [["Zur Verwaltung", "/admin/"]]],
    ["acquirer", [["Zur Akquise-App", "/app/"]]],
  ]) {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    await context.addCookies([
      {
        name: "__Host-leonaid_session",
        value: appSessions[persona],
        url: baseUrl,
        httpOnly: true,
        secure: true,
        sameSite: "Lax",
      },
    ]);
    const signedIn = await context.newPage();
    for (const path of ["/krapfentaxi", "/"]) {
      for (const [width, height] of [
        [390, 844],
        [1440, 900],
      ]) {
        await signedIn.setViewportSize({ width, height });
        expect(await openWithIdentity(signedIn, path)).toBe(200);
        const links = appLinks(signedIn);
        await expect(links).toHaveCount(expected.length);
        for (const [index, [label, href]] of expected.entries()) {
          await expect(links.nth(index)).toHaveText(label);
          await expect(links.nth(index)).toHaveAttribute("href", href);
          await expect(links.nth(index)).toBeVisible();
          const box = await links.nth(index).boundingBox();
          expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(44);
        }
        await expectNoHorizontalScroll(signedIn);
      }
      if (browserName === "chromium") {
        // Keyboard: Tab reaches the link after the header's own links, and
        // the link shows its focus.
        await signedIn.locator(".site-header__home").focus();
        let focused = false;
        for (let step = 0; step < 8 && !focused; step += 1) {
          await signedIn.keyboard.press("Tab");
          focused = await signedIn.evaluate(() =>
            document.activeElement?.hasAttribute("data-app-link"),
          );
        }
        expect(focused).toBe(true);
        const outline = await signedIn.evaluate(() => {
          const style = getComputedStyle(document.activeElement);
          return { style: style.outlineStyle, width: style.outlineWidth };
        });
        expect(outline.style).not.toBe("none");
        expect(Number.parseFloat(outline.width)).toBeGreaterThanOrEqual(2);
        await signedIn.screenshot({
          path: `${artifactDirectory}/public-header-${persona}${path === "/" ? "-home" : ""}-1440.png`,
        });
      }
    }
    await context.close();
  }
});
