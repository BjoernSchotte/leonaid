import type { CreateInvitationRequest } from "@leonaid/api-client";

/*
 * The invitation draft survives the fresh sign-in: /fresh-login reloads the
 * page, so it waits in this tab's sessionStorage. It belongs to the account
 * that typed it and lives at most 15 minutes (the fresh sign-in window). The
 * dialog takes it back once; a draft of another account or an expired one is
 * dropped.
 */
export const INVITE_DRAFT_KEY = "leonaid.member-invite-draft";
export const INVITE_DRAFT_TTL_MS = 15 * 60 * 1000;

export interface InviteDraft {
  readonly email: string;
  readonly displayName: string;
  readonly actionId: string;
  readonly role: CreateInvitationRequest["role"] | "";
}

interface StoredDraft extends InviteDraft {
  readonly userId: string;
  readonly savedAt: number;
}

export function saveInviteDraft(
  userId: string,
  draft: InviteDraft,
  now: number = Date.now(),
): void {
  const stored: StoredDraft = { ...draft, userId, savedAt: now };
  try {
    window.sessionStorage.setItem(INVITE_DRAFT_KEY, JSON.stringify(stored));
  } catch {
    // Storage blocked: the person types the invitation again.
  }
}

const text = (value: unknown) => (typeof value === "string" ? value : "");

/** The draft of this account, if it is younger than 15 minutes. Removes it. */
export function takeInviteDraft(
  userId: string,
  now: number = Date.now(),
): InviteDraft | null {
  let raw: string | null;
  try {
    raw = window.sessionStorage.getItem(INVITE_DRAFT_KEY);
    window.sessionStorage.removeItem(INVITE_DRAFT_KEY);
  } catch {
    return null;
  }
  if (!raw) return null;
  let value: Partial<StoredDraft>;
  try {
    value = JSON.parse(raw) as Partial<StoredDraft>;
  } catch {
    return null;
  }
  const age = typeof value.savedAt === "number" ? now - value.savedAt : NaN;
  if (value.userId !== userId || !(age >= 0 && age <= INVITE_DRAFT_TTL_MS)) {
    return null;
  }
  return {
    email: text(value.email),
    displayName: text(value.displayName),
    actionId: text(value.actionId),
    role: text(value.role) as InviteDraft["role"],
  };
}
