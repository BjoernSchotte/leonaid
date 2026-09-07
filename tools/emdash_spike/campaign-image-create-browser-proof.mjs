import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { chromium, firefox, webkit, expect } from "@playwright/test";
import { browserLogin, coreLogout } from "./browser-login.mjs";

const origin = "https://proxy:8443";
const root = "/_emdash/api/content/campaign_pages";
const editor = "/_emdash/admin/content/campaign_pages";
const state = JSON.parse(
  await readFile("/proof/media-http-state.json", "utf8"),
);
for (const [index, [name, engine]] of Object.entries({
  chromium,
  firefox,
  webkit,
}).entries()) {
  const browser = await engine.launch({ headless: true });
  try {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      locale: "en-US",
      viewport: { width: 1440, height: 1000 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(15000);
    const action = `20000000-0000-4000-8000-${String(43 + index).padStart(12, "0")}`;
    const handoff = `/_emdash/admin/campaigns/${action}`;
    const newPath = `${editor}/new?campaign=${action}`;
    await page.goto(origin + handoff);
    await page.getByRole("heading", { name: "Bei LeonAid anmelden" }).waitFor();
    await browserLogin(
      context,
      page,
      newPath,
      false,
      "klara.kern@leonaid.invalid",
    );
    await page.waitForURL(
      (url) =>
        url.pathname === `${editor}/new` &&
        url.searchParams.get("campaign") === action,
    );
    const json = async (path) => {
      const response = await context.request.get(origin + path);
      assert.equal(response.status(), 200);
      return (await response.json()).data;
    };
    const before = await json(root);
    assert.ok(before.items.every((item) => item.data.action_id !== action));
    await expect(page.locator("#field-action_id")).toHaveValue(action);
    const title = `Native ${name} image campaign`;
    await page.locator("#field-title").fill(title);
    await page
      .locator("#field-hero_title")
      .fill("A new campaign with an image");
    const story = page.locator('#field-body [contenteditable="true"]');
    await story.click();
    await story.pressSequentially("## Helping together");
    await story.press("Enter");
    await story.pressSequentially("Our volunteers support local projects. ");
    await story.press("Control+b");
    await story.pressSequentially("Every contribution matters.");
    await story.press("Control+b");
    const repeater = (field) =>
      page.locator(`label[for="field-${field}"]`).locator("..").locator("..");
    await repeater("faq")
      .getByRole("button", { name: "Add First Item", exact: true })
      .click();
    await page.getByLabel("Question", { exact: true }).fill("Who can help?");
    await page
      .getByLabel("Answer", { exact: true })
      .fill("Everyone in our community.");
    await repeater("partners")
      .getByRole("button", { name: "Add First Item", exact: true })
      .click();
    await page.getByLabel("Name", { exact: true }).fill("Community partner");
    await page
      .getByLabel("Description", { exact: true })
      .fill("Supporting our volunteers.");
    await page
      .getByLabel("Website", { exact: true })
      .fill("https://example.org/charity");
    await page.getByRole("combobox", { name: "Theme", exact: true }).click();
    await page
      .getByRole("option", { name: "krapfentaxi", exact: true })
      .click();
    await page
      .locator("#field-seo_description")
      .fill("Our local charity campaign.");
    const mediaList = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return (
        url.pathname === "/_emdash/api/media" &&
        url.searchParams.get("campaign") === action
      );
    });
    await page
      .locator("#field-hero_image")
      .getByRole("button", { name: "Select image", exact: true })
      .click();
    const listed = await mediaList;
    assert.equal(listed.status(), 200);
    assert.deepEqual((await listed.json()).data.items, []);
    const dialog = page.getByRole("dialog");
    const fixture = await context.request.get(
      `${origin}/_emdash/api/media/file/${state.ready.storageKey}`,
    );
    assert.equal(fixture.status(), 200);
    const confirmed = page.waitForResponse(
      (response) =>
        /\/_emdash\/api\/media\/[0-9A-Z]+\/confirm$/.test(
          new URL(response.url()).pathname,
        ) && response.request().method() === "POST",
    );
    const filename = `new-${name}-campaign.png`;
    await dialog.getByLabel("Upload file", { exact: true }).setInputFiles({
      name: filename,
      mimeType: "image/png",
      buffer: await fixture.body(),
    });
    const confirmation = await confirmed;
    assert.equal(confirmation.status(), 200);
    const uploaded = (await confirmation.json()).data.item;
    assert.ok(uploaded.storageKey.startsWith(`campaigns/${action}/`));
    // Confirmation precedes the native picker query refresh and selection UI.
    // Wait for that user-visible state before clicking a moving footer button.
    await expect(
      dialog.getByRole("button", {
        name: `${filename} (selected)`,
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      dialog.getByText(`Selected: ${filename}`, { exact: true }),
    ).toBeVisible();
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page
      .locator("#field-social_image")
      .getByRole("button", { name: "Select image", exact: true })
      .click();
    await dialog.getByRole("button", { name: filename, exact: true }).click();
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await page
      .getByText("Partner logo", { exact: true })
      .locator("..")
      .getByRole("button", { name: "Select image", exact: true })
      .click();
    await dialog.getByRole("button", { name: filename, exact: true }).click();
    await dialog.getByRole("button", { name: "Insert", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    // Uploading for a Core action must not silently create its CMS record.
    assert.deepEqual(await json(root), before);
    const createdResponse = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === root &&
        response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Save", exact: true }).click();
    const created = await createdResponse;
    assert.equal(created.status(), 201);
    const item = (await created.json()).data.item;
    assert.equal(item.data.action_id, action);
    assert.equal(item.data.title, title);
    assert.equal(item.data.hero_image.id, uploaded.id);
    assert.equal(item.data.social_image.id, uploaded.id);
    const assertEditorial = (data) => {
      assert.equal(data.body[0].style, "h2");
      assert.equal(
        data.body[0].children.map((span) => span.text).join(""),
        "Helping together",
      );
      assert.ok(
        data.body
          .flatMap((block) => block.children)
          .some(
            (span) =>
              span.text === "Every contribution matters." &&
              span.marks.includes("strong"),
          ),
      );
      assert.deepEqual(data.faq, [
        { question: "Who can help?", answer: "Everyone in our community." },
      ]);
      assert.equal(data.partners[0].name, "Community partner");
      assert.equal(data.partners[0].description, "Supporting our volunteers.");
      assert.equal(data.partners[0].website, "https://example.org/charity");
      assert.equal(data.partners[0].logo.id, uploaded.id);
      assert.equal(data.theme, "krapfentaxi");
      assert.equal(data.seo_description, "Our local charity campaign.");
    };
    assertEditorial(item.data);
    assert.equal(item.status, "draft");
    assert.equal(item.liveRevisionId, null);
    assert.equal(item.authorId, (await json("/_emdash/api/auth/me")).id);
    await page.waitForURL((url) => url.pathname === `${editor}/${item.id}`);
    await page.reload();
    await expect(page.locator("#field-title")).toHaveValue(title);
    await expect(story.locator("h2")).toHaveText("Helping together");
    await expect(story.locator("strong")).toHaveText(
      "Every contribution matters.",
    );
    await expect(page.getByLabel("Question", { exact: true })).toHaveValue(
      "Who can help?",
    );
    await expect(page.getByLabel("Name", { exact: true })).toHaveValue(
      "Community partner",
    );
    await expect(
      page.getByRole("combobox", { name: "Theme", exact: true }),
    ).toContainText("krapfentaxi");
    const updated = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === `${root}/${item.id}` &&
        response.request().method() === "PUT",
    );
    // Use the native document-end shortcut, not a coordinate click on an empty
    // paragraph. Wait for actual DOM selection, including editor focus frames;
    // no injected selection or editor-state mutation substitutes for keyboard UX.
    await story.click();
    await expect(story).toBeFocused();
    await story.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.keyboard.press("Control+End");
    await expect
      .poll(() =>
        story.evaluate((element) => {
          const selection = window.getSelection();
          const last = element.lastElementChild;
          return (
            !!last &&
            last.tagName === "P" &&
            last.textContent === "" &&
            !!selection?.anchorNode &&
            last.contains(selection.anchorNode) &&
            selection.isCollapsed
          );
        }),
      )
      .toBe(true);
    await page.keyboard.type("Thank you for helping.");
    await expect(story.locator("p").last()).toHaveText(
      "Thank you for helping.",
    );
    await expect(story.locator("h2")).toHaveText("Helping together");
    const updateResponse = await updated;
    assert.equal(updateResponse.status(), 200);
    assertEditorial(updateResponse.request().postDataJSON().data);
    await expect(
      page.getByRole("button", { name: "Saved", exact: true }),
    ).toBeVisible();
    await page.reload();
    await expect(story.locator("p").last()).toHaveText(
      "Thank you for helping.",
    );
    const edited = (await json(`${root}/${item.id}`)).item.data;
    assertEditorial(edited);
    assert.equal(
      edited.body
        .at(-1)
        .children.map((span) => span.text)
        .join(""),
      "Thank you for helping.",
    );
    for (const field of ["hero_image", "social_image"]) {
      await expect
        .poll(() =>
          page
            .locator(`#field-${field} img`)
            .evaluate((img) => img.complete && img.naturalWidth > 0),
        )
        .toBe(true);
      assert.equal(
        (await json(`${root}/${item.id}`)).item.data[field].id,
        uploaded.id,
      );
    }
    const after = await json(root);
    assert.equal(after.total, before.total + 1);
    assert.equal(
      after.items.filter((entry) => entry.data.action_id === action).length,
      1,
    );
    const resolved = await context.request.get(origin + handoff, {
      maxRedirects: 0,
    });
    assert.equal(resolved.status(), 303);
    assert.equal(resolved.headers().location, `${editor}/${item.id}`);
    await coreLogout(context, page, handoff, root);
    assert.equal(
      (
        await context.request.get(
          `${origin}/_emdash/api/media/file/${encodeURIComponent(uploaded.storageKey)}`,
        )
      ).status(),
      401,
    );
    await context.close();
    console.log(
      `campaign-image-create-browser: ${name}: actual SMTP Core login and action handoff; native formatted story, FAQ, partner/logo, theme and SEO; empty scoped picker and hero/social upload before explicit draft creation; subsequent native story edit and reload retain editorial fields/private previews; logout denied media`,
    );
  } finally {
    await browser.close();
  }
}
