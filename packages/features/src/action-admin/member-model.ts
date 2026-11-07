/** Rows, labels and URL helpers of the member list (Mitglieder). */
import type {
  LeonAidApiClient,
  MemberDirectoryActionResponse,
  MemberDirectoryMemberResponse,
} from "@leonaid/api-client";
import type { StatusShape } from "@leonaid/ui";

import { CREATE_PARAMETER } from "../command-palette/create-request";
import { adminHref } from "@leonaid/ui/base-paths";

export type MemberRow = MemberDirectoryMemberResponse;
export type MemberStatus = MemberRow["status"];
export type GlobalRole = MemberRow["globalRoles"][number];
export type ActionRole =
  MemberDirectoryActionResponse["availableRoles"][number];

/** `?create=` kind of the invitation dialog (palette "Mitglied einladen"). */
export const INVITE_KIND = "member-invitation";

export const MEMBER_STATUSES: readonly MemberStatus[] = [
  "active",
  "invited",
  "suspended",
  "archived",
];

export const memberStatusLabels: Readonly<Record<MemberStatus, string>> = {
  active: "Aktiv",
  invited: "Eingeladen",
  suspended: "Gesperrt",
  archived: "Archiviert",
};

/** Prototype shapes: aktiv done, eingeladen open, gesperrt struck through. */
export const memberStatusShapes: Readonly<Record<MemberStatus, StatusShape>> = {
  active: "done",
  invited: "open",
  suspended: "cancelled",
  archived: "draft",
};

export const GLOBAL_ROLES: readonly GlobalRole[] = [
  "system_admin",
  "finance_manager",
  "finance_reader",
];

export const globalRoleLabels: Readonly<Record<GlobalRole, string>> = {
  system_admin: "System-Admin",
  finance_reader: "Finanzen lesen",
  finance_manager: "Finanzen verwalten",
};

export const globalRoleDescriptions: Readonly<Record<GlobalRole, string>> = {
  system_admin: "Verwaltet Benutzer, Betrieb und globale Einstellungen.",
  finance_reader: "Sieht Rechnungen und Finanzstatus in allen Aktionen.",
  finance_manager: "Darf Zahlungen und Stornierungen clubweit bearbeiten.",
};

export const ACTION_ROLES: readonly ActionRole[] = [
  "charity_admin",
  "acquirer",
  "driver",
  "finance_reader",
];

export const actionRoleLabels: Readonly<Record<ActionRole, string>> = {
  charity_admin: "Charity-Admin",
  acquirer: "Akquisiteur",
  finance_reader: "Finanzen lesen",
  driver: "Ausfahrer",
};

/*
 * Role filter values. "Finanzen lesen" exists club-wide and per action, so
 * the two scopes get their own values.
 */
export type RoleFilterValue = `global:${GlobalRole}` | `action:${ActionRole}`;

export function roleFilterValues(row: MemberRow): RoleFilterValue[] {
  return [
    ...row.globalRoles.map((role) => `global:${role}` as const),
    ...new Set(
      row.actionMemberships.map(
        (membership) => `action:${membership.role}` as const,
      ),
    ),
  ];
}

export const roleFilterOptions: ReadonlyArray<{
  readonly value: RoleFilterValue;
  readonly label: string;
}> = [
  ...GLOBAL_ROLES.map((role) => ({
    value: `global:${role}` as const,
    label:
      role === "finance_reader"
        ? "Finanzen lesen (clubweit)"
        : globalRoleLabels[role],
  })),
  ...ACTION_ROLES.map((role) => ({
    value: `action:${role}` as const,
    label: actionRoleLabels[role],
  })),
];

/** Filter value for members without a role in any visible action. */
export const NO_ACTION = "none";

export function actionFilterValues(row: MemberRow): string[] {
  const ids = [
    ...new Set(row.actionMemberships.map((membership) => membership.actionId)),
  ];
  return ids.length ? ids : [NO_ACTION];
}

/** Every action the rows or the directory name, sorted by name. */
export function knownActions(
  actions: readonly MemberDirectoryActionResponse[],
  rows: readonly MemberRow[],
): { readonly actionId: string; readonly actionName: string }[] {
  const byId = new Map<string, string>();
  for (const action of actions) byId.set(action.actionId, action.actionName);
  for (const row of rows) {
    for (const membership of row.actionMemberships) {
      if (!byId.has(membership.actionId)) {
        byId.set(membership.actionId, membership.actionName);
      }
    }
  }
  return [...byId.entries()]
    .map(([actionId, actionName]) => ({ actionId, actionName }))
    .sort((a, b) => a.actionName.localeCompare(b.actionName, "de"));
}

/** "Klara Kern" sorts under K(ern): family name first, as in the prototype. */
export function familyNameKey(displayName: string): string {
  const words = displayName.trim().split(/\s+/);
  return `${words.at(-1) ?? ""} ${words.slice(0, -1).join(" ")}`;
}

export interface MemberDirectory {
  readonly actions: readonly MemberDirectoryActionResponse[];
  readonly items: readonly MemberRow[];
  readonly partial: boolean;
  /** The server has more members than one page walk loads. */
  readonly truncated: boolean;
}

/** The server's page maximum. */
export const PAGE_SIZE = 100;
/** Upper bound of the page walk (5 000 members). */
export const MAX_PAGES = 50;

/**
 * Loads every member the account may see, page by page. The list filters,
 * groups and searches client-side, so it needs all of them. The server
 * decides which members and roles are in the response.
 */
export async function loadMemberDirectory(
  client: LeonAidApiClient,
  signal?: AbortSignal,
): Promise<MemberDirectory> {
  const byId = new Map<string, MemberRow>();
  let cursor: string | undefined;
  let actions: readonly MemberDirectoryActionResponse[] = [];
  let partial = false;
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const response = await client.listMembers(
      { cursor, limit: PAGE_SIZE },
      signal ? { signal } : {},
    );
    if (page === 0) {
      actions = response.actions;
      partial = response.partial;
    }
    // A member that moves between pages while they load is kept once.
    for (const item of response.items) byId.set(item.userId, item);
    if (!response.nextCursor) {
      return { actions, items: [...byId.values()], partial, truncated: false };
    }
    cursor = response.nextCursor;
  }
  return { actions, items: [...byId.values()], partial, truncated: true };
}

/**
 * Old links: `?view=invite` opened the invitation tab. It now opens the
 * invitation dialog through `?create=`, before the list reads `?view=`.
 */
export function migrateLegacyInviteParam(): void {
  const url = new URL(window.location.href);
  if (url.searchParams.get("view") !== "invite") return;
  url.searchParams.delete("view");
  url.searchParams.set(CREATE_PARAMETER, INVITE_KIND);
  window.history.replaceState(window.history.state, "", url);
}

export function membersPath(section: "list" | "invitations"): string {
  return section === "list"
    ? adminHref("members")
    : adminHref("members/invitations");
}

/** A plausible address; the server decides. The forms show `INVALID_EMAIL`. */
export const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
export const INVALID_EMAIL =
  "Bitte eine gültige E-Mail-Adresse eingeben, z. B. name@beispiel.de.";
