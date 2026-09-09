import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";

const origin = "https://proxy:8443";
const path = "/campaigns/krapfentaxi-2026/";
const root = "/_emdash/api/content/campaign_pages";
const tokens = JSON.parse(await readFile("/proof/sessions.json", "utf8"));
const media = JSON.parse(await readFile("/proof/public-media.json", "utf8"));
for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({ ignoreHTTPSErrors: true });
    const admin = async (url, method = "GET", data) => {
      const response = await context.request.fetch(origin + url, {
        method,
        data,
        headers: {
          Cookie: `__Host-leonaid_session=${tokens.system}`,
          Origin: origin,
          "X-EmDash-Request": "1",
        },
      });
      assert.equal(response.status(), 200);
      assert.equal(response.headers()["cache-control"], "no-store");
      return (await response.json()).data;
    };
    const entry = (await admin(root)).items.find(
      (item) => item.data.action_id === "20000000-0000-4000-8000-000000000001",
    );
    const editor = `${root}/${entry.id}`;
    const original = (await admin(editor)).item.data;
    const save = async (data) =>
      admin(editor, "PUT", {
        _rev: (await admin(editor))._rev,
        data,
      });
    const marker = `Editorial story ${name}`;
    await save({
      ...original,
      theme: "krapfentaxi",
      hero_title: "Editable introduction",
      story_eyebrow: "CMS section label",
      story_title: marker,
      partners: [
        {
          name: "CMS partner heading",
          eyebrow: "CMS partner label",
          description: "CMS partner description",
          website: "https://example.org/",
          link_label: "CMS partner link",
          logo: original.brand_logo,
        },
      ],
    });
    const before = await context.request.get(origin + path);
    assert.ok(!(await before.text()).includes(marker));
    await admin(`${editor}/publish`, "POST");
    const coreResponse = await context.request.get(
      origin + "/api/v1/public/actions/campaign/krapfentaxi-2026",
    );
    assert.equal(coreResponse.status(), 200);
    const core = await coreResponse.json();
    assert.equal(core.canonicalPath, path);
    for (const javaScriptEnabled of [false, true]) {
      const anonymous = await browser.newContext({
        ignoreHTTPSErrors: true,
        javaScriptEnabled,
        viewport: { width: javaScriptEnabled ? 1280 : 390, height: 900 },
      });
      const page = await anonymous.newPage();
      const response = await page.goto(origin + path);
      assert.equal(response.status(), 200);
      assert.equal(response.headers()["cache-control"], "no-store");
      await expect(page.locator("body")).toHaveClass("taxi-site");
      await expect(page.locator("h1")).toHaveText(core.action.name);
      await expect(
        page.getByRole("heading", { name: marker, exact: true }),
      ).toBeVisible();
      await expect(page.locator(".taxi-story__lead")).toHaveText(
        core.action.purpose,
      );
      await expect(
        page.getByRole("link", { name: "CMS partner link" }),
      ).toHaveAttribute("href", "https://example.org/");
      for (const selector of [
        ".site-header__home img",
        ".taxi-hero__logo",
        ".taxi-bakery__logo img",
      ]) {
        const img = page.locator(selector);
        await img.scrollIntoViewIfNeeded();
        await expect(img).toHaveAttribute("src", media.url);
        await expect
          .poll(() =>
            img.evaluate((image) => image.complete && image.naturalWidth > 0),
          )
          .toBe(true);
      }
      await expect(page.locator("[data-order-form]")).toHaveCount(1);
      await expect(page.locator("#datenschutz")).toContainText(
        core.action.orderForm.privacyNoticeText,
      );
      await expect(
        page.locator("[data-testid=public-canonical-path]"),
      ).toHaveText(path);
      for (const offering of core.action.offerings)
        await expect(
          page.locator("[data-testid=public-offerings]"),
        ).toContainText(offering.name);
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
      assert.equal((await anonymous.cookies()).length, 0);
      await page.evaluate(() => {
        document.activeElement?.blur();
        window.scrollTo({ top: 0, behavior: "instant" });
      });
      await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
      if (name === "chromium")
        await page.screenshot({
          path: `/visual-proof/taxi-${javaScriptEnabled ? "desktop" : "mobile"}.png`,
          fullPage: true,
        });
      // The same shared Core sections still serve the old demo unchanged.
      const legacy = await page.goto(origin + "/krapfentaxi");
      assert.equal(legacy.status(), 200);
      await expect(page.locator("h1")).toHaveText(core.action.name);
      await expect(page.locator(".taxi-hero__tagline")).toHaveText(
        "Eine kleine Geste für dein Team. Eine große Hilfe vor Ort.",
      );
      await expect(page.locator("[data-order-form]")).toHaveCount(1);
      assert.ok(!(await page.content()).includes(marker));
      await anonymous.close();
    }
    await save({
      ...(await admin(editor)).item.data,
      story_title: `PRIVATE_${marker}`,
    });
    assert.ok(
      !(await (await context.request.get(origin + path)).text()).includes(
        `PRIVATE_${marker}`,
      ),
    );
    await save(original);
    await admin(`${editor}/publish`, "POST");
    await context.close();
    console.log(
      `krapfentaxi-renderer: ${name}: CMS theme/text/media publish without rebuild, private drafts, Core facts and shared order/privacy sections, anonymous mobile/desktop JS/no-JS passed`,
    );
  } finally {
    await browser.close();
  }
}
