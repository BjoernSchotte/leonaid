import { localIsoDate, shortDate, TIME_ZONE } from "../shared/dates";
import type { QueryClient } from "@tanstack/react-query";
import type {
  Case,
  CurrentIdentityResponse,
  LeonAidApiClient,
} from "@leonaid/api-client";
import type { StatusShape } from "@leonaid/ui";

/** "Sie" in the back office, "du" in the PWA. */
export type Address = "Sie" | "du";

export const CASE_STATUSES = ["new", "in_progress", "closed"] as const;

export const caseStatusLabels: Readonly<Record<Case["status"], string>> = {
  new: "Neu",
  in_progress: "In Bearbeitung",
  closed: "Abgeschlossen",
};

export const CONTACT_STATES = [
  "pending",
  "linked",
  "needs_review",
  "failed",
] as const;

/** Full wording (pane) and the short row chip, as in the prototype. */
export const contactStateLabels: Readonly<
  Record<
    Case["contactStatus"],
    {
      readonly full: string;
      readonly short: string;
      readonly shape: StatusShape;
    }
  >
> = {
  pending: {
    full: "Kontaktzuordnung ausstehend",
    short: "Zuordnung ausstehend",
    shape: "draft",
  },
  linked: {
    full: "Kontakt zugeordnet",
    short: "Kontakt zugeordnet",
    shape: "done",
  },
  needs_review: {
    full: "Kontaktzuordnung benötigt Klärung",
    short: "Klärung nötig",
    shape: "review",
  },
  failed: {
    full: "Kontaktzuordnung fehlgeschlagen",
    short: "Zuordnung fehlgeschlagen",
    shape: "alert",
  },
};

/** Option value of the assignee and action properties for "nobody / none". */
export const NONE = "none";

/** The prototype's minimum for a closing note; the server needs one character. */
export const MIN_CLOSURE_NOTE = 10;

/** Server limits of `GET /inbox-cases`: 100 per page, offset at most 5000. */
const PAGE_SIZE = 100;
const MAX_OFFSET = 5000;

export interface CasePage {
  readonly items: readonly Case[];
  /** The server stops paging at offset 5000; older cases are not loaded. */
  readonly truncated: boolean;
}

/** Every case the account may read, newest first. */
export async function loadAllCases(
  client: LeonAidApiClient,
  signal?: AbortSignal,
): Promise<CasePage> {
  const byId = new Map<string, Case>();
  let offset = 0;
  for (;;) {
    const page = await client.listInboxCases(
      { offset, limit: PAGE_SIZE },
      { signal },
    );
    for (const item of page.items) byId.set(item.id, item);
    if (page.nextOffset == null) {
      return {
        items: [...byId.values()],
        truncated:
          page.items.length === PAGE_SIZE && offset + PAGE_SIZE > MAX_OFFSET,
      };
    }
    offset = page.nextOffset;
  }
}

/**
 * Mirrors the server's management rule (system admin, or charity admin of
 * the case's action). Only decides which controls are offered; every write
 * is authorized again by the server.
 */
export function managesCase(
  identity: CurrentIdentityResponse,
  item: Pick<Case, "actionId">,
): boolean {
  if (identity.globalRoles.includes("system_admin")) return true;
  if (item.actionId === null) return false;
  return identity.actionMemberships.some(
    (membership) =>
      membership.actionId === item.actionId &&
      membership.role === "charity_admin",
  );
}

/** Key of the action a case belongs to; `none` for general inquiries. */
export const actionKey = (item: Pick<Case, "actionId">) =>
  item.actionId ?? NONE;

const clock = new Intl.DateTimeFormat("de-DE", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: TIME_ZONE,
});

/**
 * "28.10." in the row, as in the prototype; older years get the year.
 * Days are the club's (Berlin) days, as on the other screens.
 */
export function shortDay(iso: string, now = new Date()): string {
  return shortDate(iso, localIsoDate(now));
}

/** "28.10. 09:14 Uhr" in the pane; older years get the year. */
export function receivedLabel(iso: string, now = new Date()): string {
  return `${shortDay(iso, now)} ${clock.format(new Date(iso))} Uhr`;
}

export function fullName(item: Pick<Case, "givenName" | "familyName">) {
  return `${item.givenName} ${item.familyName}`.trim();
}

/**
 * Turns the old case path `<base>/<id>` into the list URL with the pane open,
 * before the list reads the URL. Other query parameters are kept.
 */
export function migrateCasePath(basePath: string, caseId: string) {
  const params = new URLSearchParams(window.location.search);
  if (!params.has("view")) params.set("view", "all");
  params.set("open", caseId);
  window.history.replaceState(
    window.history.state,
    "",
    `${basePath}?${params.toString()}${window.location.hash}`,
  );
}

/** The `open` parameter the page was entered with (deep link or search hit). */
export function requestedCaseId(): string | null {
  return new URLSearchParams(window.location.search).get("open");
}

/** Query key of the full case list (every page). */
export const CASES_KEY = ["inbox-cases"] as const;

/**
 * Puts server answers into the list and the single-case cache at once, so
 * the row and the pane show them without loading every page again.
 */
export function acceptCases(cache: QueryClient, cases: readonly Case[]) {
  if (cases.length === 0) return;
  const byId = new Map(cases.map((item) => [item.id, item]));
  cache.setQueryData<CasePage>(CASES_KEY, (page) =>
    page
      ? {
          ...page,
          items: page.items.map((item) => byId.get(item.id) ?? item),
        }
      : page,
  );
  for (const item of cases) {
    cache.setQueryData(["inbox-case", item.id], item);
    void cache.invalidateQueries({ queryKey: ["inbox-permissions", item.id] });
  }
  // No refetch of every page here: the rows are already patched. Failures
  // refetch (useCaseUpdates), and the list refreshes on window focus.
}

/**
 * The public reference is a UUID the submitter receives in full. Rows, the
 * closing dialog and toasts show its first eight characters; the pane and
 * the search use the whole value.
 */
export const shortReference = (reference: string) =>
  reference.slice(0, 8).toUpperCase();
