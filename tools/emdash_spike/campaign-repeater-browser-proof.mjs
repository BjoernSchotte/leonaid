import assert from "node:assert/strict";
import { expect } from "@playwright/test";

export async function proveCampaignRepeaters({ page, json, apiPath }) {
  for (const [field, label, additions] of [
    [
      "faq",
      "Question",
      { question: "When can I help?", answer: "Contact our volunteers." },
    ],
    [
      "partners",
      "Name",
      {
        name: "Another local partner",
        description: "Community support.",
        website: "https://example.org/partner",
        logo: null,
      },
    ],
  ]) {
    const before = (await json(apiPath)).item.data;
    assert.equal(before[field].length, 1);
    const widget = page
      .locator(`label[for="field-${field}"]`)
      .locator("..")
      .locator("..");
    const accepted = (matches) =>
      page.waitForResponse((response) => {
        if (
          new URL(response.url()).pathname !== apiPath ||
          response.request().method() !== "PUT"
        )
          return false;
        return matches(response.request().postDataJSON().data?.[field]);
      });
    const saved = async (response) => {
      assert.equal((await response).status(), 200);
      await expect(
        page.getByRole("button", { name: "Saved", exact: true }),
      ).toBeVisible();
    };
    const added = accepted(
      (items) =>
        items?.length === 2 &&
        Object.entries(additions).every(
          ([key, value]) => items[1][key] === value,
        ),
    );
    await widget.getByRole("button", { name: "Add Item", exact: true }).click();
    await expect(widget.getByLabel(label, { exact: true })).toHaveCount(2);
    for (const [name, value] of Object.entries(additions)) {
      if (name === "logo") continue;
      await widget
        .getByLabel(name[0].toUpperCase() + name.slice(1), { exact: true })
        .last()
        .fill(value);
    }
    await saved(added);
    const newTitle = additions[field === "faq" ? "question" : "name"];
    const originalTitle =
      before[field][0][field === "faq" ? "question" : "name"];
    // Collapse through the visible native controls, then reach the second drag
    // handle via actual Tab navigation and reorder with Space/ArrowUp/Space.
    await widget
      .getByRole("button", { name: originalTitle, exact: true })
      .click();
    await widget.getByRole("button", { name: newTitle, exact: true }).click();
    await expect(
      widget.getByRole("button", { name: newTitle, exact: true }),
    ).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("Shift+Tab");
    await expect(
      widget.getByRole("button", { name: `Reorder ${newTitle}`, exact: true }),
    ).toBeFocused();
    const dragHandle = widget.getByRole("button", {
      name: `Reorder ${newTitle}`,
      exact: true,
    });
    const originalHandle = widget.getByRole("button", {
      name: `Reorder ${originalTitle}`,
      exact: true,
    });
    await page.keyboard.press("Space");
    await expect(dragHandle).toHaveAttribute("aria-pressed", "true");
    await page.keyboard.press("ArrowUp");
    await expect
      .poll(async () => {
        const moved = await dragHandle.boundingBox();
        const original = await originalHandle.boundingBox();
        return moved !== null && original !== null && moved.y < original.y;
      })
      .toBe(true);
    const reordered = accepted(
      (items) =>
        items?.length === 2 &&
        items[0][field === "faq" ? "question" : "name"] === newTitle,
    );
    await page.keyboard.press("Space");
    await saved(reordered);
    assert.deepEqual((await json(apiPath)).item.data[field], [
      additions,
      ...before[field],
    ]);
    await page.reload();
    await expect(widget.getByLabel(label, { exact: true }).first()).toHaveValue(
      newTitle,
    );
    await expect(widget.getByLabel(label, { exact: true }).last()).toHaveValue(
      originalTitle,
    );
    const removed = accepted(
      (items) =>
        items?.length === 1 &&
        items[0][field === "faq" ? "question" : "name"] === originalTitle,
    );
    await widget
      .getByRole("button", { name: "Remove item 1", exact: true })
      .click();
    await saved(removed);
    await page.reload();
    await expect(widget.getByLabel(label, { exact: true })).toHaveValue(
      originalTitle,
    );
    // This also protects the original partner logo, story and other fields
    // against index-key reuse, stale repeater state and cross-field writes.
    assert.deepEqual((await json(apiPath)).item.data, before);
    console.log(
      `campaign-repeater-browser: ${field}: native add, keyboard reorder, save/reload and removal passed; complete original data preserved`,
    );
  }
}
