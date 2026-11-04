// Helpers for the member list (ListView rows, the pane or sheet, dialogs).
import { expect } from "@playwright/test";

/** Every visible member row link. */
export function memberRows(page) {
  return page.locator(".listview .row-link");
}

/** The row link of one member, by display name. */
export function memberRow(page, name) {
  return page.locator(".listview .row-link").filter({
    has: page.locator(".row-primary", { hasText: name }),
  });
}

/** The pane (desktop) or sheet (phone) body of the open member. */
export function memberPane(page) {
  return page.getByTestId("member-detail");
}

/** Types into the list search box. */
export async function searchMembers(page, text) {
  await page.getByPlaceholder("Mitglieder durchsuchen").fill(text);
}

/** Searches for one member, opens the row and returns the pane. */
export async function openMember(page, name) {
  await searchMembers(page, name);
  await expect(memberRow(page, name)).toHaveCount(1);
  await memberRow(page, name).click();
  const pane = memberPane(page);
  await expect(pane).toBeVisible();
  await expect(
    page.getByRole("heading", { level: 2, name, exact: true }),
  ).toBeVisible();
  return pane;
}

/** The newest toast with this text (earlier ones may still be shown). */
export function toast(page, text) {
  return page.locator(".toast").filter({ hasText: text }).last();
}

/** Opens the invitation dialog from the list header and returns it. */
export async function openInviteDialog(page) {
  await page
    .getByRole("button", { name: /^Mitglied einladen/ })
    .first()
    .click();
  const dialog = page.getByRole("dialog", { name: "Mitglied einladen" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByTestId("invite-action")).toBeEnabled();
  return dialog;
}

/**
 * Grants (enabled) or revokes a role in the pane, confirms it and waits for
 * the success toast. `actionId` is omitted for club-wide roles.
 */
export async function changeRole(page, { actionId, role, enabled, label }) {
  const pane = memberPane(page);
  if (enabled) {
    if (actionId) {
      await pane.getByTestId("member-role-add-action").selectOption(actionId);
      await pane.getByTestId("member-role-add-role").selectOption(role);
      await pane.getByTestId("member-role-add-submit").click();
    } else {
      await pane.getByTestId("member-global-role-add").selectOption(role);
      await pane.getByTestId("member-global-role-add-submit").click();
    }
  } else {
    await pane
      .getByTestId(
        actionId
          ? `member-revoke-action-${actionId}-${role}`
          : `member-revoke-global-${role}`,
      )
      .click();
  }
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();
  await dialog
    .getByRole("button", {
      name: enabled ? "Rolle zuweisen" : "Rolle entziehen",
    })
    .click();
  await expect(dialog).toBeHidden();
  await expect(
    page
      .locator(".toast")
      .filter({ hasText: label })
      .filter({ hasText: enabled ? "zugewiesen" : "entzogen" })
      .last(),
  ).toBeVisible();
  await expect(
    pane.getByTestId(
      actionId
        ? `member-revoke-action-${actionId}-${role}`
        : `member-revoke-global-${role}`,
    ),
  ).toHaveCount(enabled ? 1 : 0);
}
