import { ApiError } from "@leonaid/api-client";

/*
 * A typed value survives the fresh sign-in: /fresh-login reloads the page,
 * so the value waits in this tab's sessionStorage under its own key. It
 * belongs to the account that typed it and lives at most 15 minutes (the
 * fresh sign-in window). The form takes it back once; a value of another
 * account or an expired one is dropped. The invitation dialog keeps its
 * richer draft in invite-draft.ts.
 */
const PREFIX = "leonaid.fresh-login-draft:";
export const FRESH_LOGIN_DRAFT_TTL_MS = 15 * 60 * 1000;

interface StoredValue {
  readonly userId: string;
  readonly savedAt: number;
  readonly value: string;
}

/** The server asks for a fresh sign-in; actionErrorMessage will redirect. */
export function needsFreshLogin(error: unknown): boolean {
  return (
    error instanceof ApiError && error.detail.code === "fresh_login_required"
  );
}

export function saveFreshLoginDraft(
  key: string,
  userId: string,
  value: string,
  now: number = Date.now(),
): void {
  const stored: StoredValue = { userId, savedAt: now, value };
  try {
    window.sessionStorage.setItem(PREFIX + key, JSON.stringify(stored));
  } catch {
    // Storage blocked: the person types the value again.
  }
}

/** The value of this account under `key`, if younger than 15 minutes. Removes it. */
export function takeFreshLoginDraft(
  key: string,
  userId: string,
  now: number = Date.now(),
): string | null {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(PREFIX + key);
    window.sessionStorage.removeItem(PREFIX + key);
  } catch {
    return null;
  }
  if (!raw) return null;
  let stored: Partial<StoredValue>;
  try {
    stored = JSON.parse(raw) as Partial<StoredValue>;
  } catch {
    return null;
  }
  const age = typeof stored.savedAt === "number" ? now - stored.savedAt : NaN;
  if (
    stored.userId !== userId ||
    typeof stored.value !== "string" ||
    !(age >= 0 && age <= FRESH_LOGIN_DRAFT_TTL_MS)
  ) {
    return null;
  }
  return stored.value;
}
