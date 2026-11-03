// Shared native EmDash 1.x editor interactions for the browser proofs. Each
// helper clicks only the real admin controls; no request is fabricated.

const publishName = /^Publish (now|changes)$/;

// EmDash 1.x asks for confirmation before it publishes. The toolbar button
// opens the dialog; the dialog's own button sends the publish request.
export async function confirmPublish(page) {
  await page.getByRole("button", { name: publishName }).first().click();
  const dialog = page.getByRole("dialog", {
    name: /^Publish (now|changes)\?$/,
  });
  await dialog.getByRole("button", { name: publishName }).click();
}

// The native unpublish control of a live entry ("Unpublish <label>").
export function unpublishButton(page) {
  return page.getByRole("button", { name: /^Unpublish / }).first();
}
