import { ApiError, type InvoiceResponse } from "@leonaid/api-client";

import { deliveryDetailsMissing } from "./delivery-completion";
import type { OrderRow } from "./order-format";

/*
 * Bulk invoice release ("Rechnungen freigeben") for checked orders. The
 * client only pre-sorts the selection; the server checks every order again
 * on issue, exactly as in the single review.
 */

export type ReleaseSkipReason = "status" | "recipient" | "delivery";

export const releaseSkipLabels: Readonly<Record<ReleaseSkipReason, string>> = {
  status: "nicht prüfbereit",
  recipient: "Rechnungsadresse fehlt",
  delivery: "Lieferangaben fehlen",
};

export interface ReleaseSelection {
  readonly eligible: readonly OrderRow[];
  readonly skipped: readonly {
    readonly row: OrderRow;
    readonly reason: ReleaseSkipReason;
  }[];
}

/**
 * Splits checked rows into those the single review would let through and
 * the rest, with the reason. Same rules as the "Rechnung verbindlich
 * freigeben" button: review-ready, an invoice recipient, and delivery
 * details while delivery planning is on.
 */
export function releaseSelection(
  rows: readonly OrderRow[],
  deliveryEnabled: boolean,
): ReleaseSelection {
  const eligible: OrderRow[] = [];
  const skipped: { row: OrderRow; reason: ReleaseSkipReason }[] = [];
  for (const row of rows) {
    const { commitment } = row;
    if (commitment.status !== "review_ready")
      skipped.push({ row, reason: "status" });
    else if (!commitment.invoiceRecipient)
      skipped.push({ row, reason: "recipient" });
    else if (deliveryDetailsMissing(commitment, deliveryEnabled))
      skipped.push({ row, reason: "delivery" });
    else eligible.push(row);
  }
  return { eligible, skipped };
}

export type ReleaseOutcome =
  | { readonly kind: "issued"; readonly invoice: InvoiceResponse }
  /** The server refused this order; the others go on. */
  | { readonly kind: "failed"; readonly message: string }
  /** No answer: it may be issued. A retry replays the same key safely. */
  | { readonly kind: "unconfirmed"; readonly message: string }
  /** Not attempted because the run stopped earlier. */
  | { readonly kind: "not-run" };

/** Why a run stopped before the end. */
export type ReleaseStop =
  | { readonly kind: "fresh-login" }
  | { readonly kind: "forbidden"; readonly message: string }
  | { readonly kind: "network" };

export interface ReleaseRun {
  readonly outcomes: ReadonlyMap<string, ReleaseOutcome>;
  readonly stop: ReleaseStop | null;
}

const LOST_ANSWER =
  "Keine Antwort vom Server. Die Rechnung ist vielleicht schon ausgestellt; erneutes Senden erzeugt keine zweite.";

function refusalMessage(cause: ApiError) {
  const message =
    cause.detail.code === "idempotency_conflict"
      ? "Für diese Bestellung wurde schon eine Freigabe mit anderen Angaben (etwa einem anderen Leistungsdatum) gesendet. Die Rechnung ist vielleicht schon ausgestellt; prüfen Sie die Bestellung."
      : cause.detail.message;
  return cause.detail.requestId
    ? `${message} (Support-Code ${cause.detail.requestId})`
    : message;
}

/**
 * Issues one order after the other. Per-order refusals (validation,
 * conflicts) are collected and the run goes on. It stops on authorization
 * errors (fresh sign-in, missing rights) and when the answer is lost (no
 * connection, gateway errors), and marks the rest "not-run".
 */
export async function runRelease(
  ids: readonly string[],
  issue: (commitmentId: string) => Promise<InvoiceResponse>,
  onProgress: (
    done: number,
    outcomes: ReadonlyMap<string, ReleaseOutcome>,
  ) => void = () => {},
): Promise<ReleaseRun> {
  const outcomes = new Map<string, ReleaseOutcome>();
  let stop: ReleaseStop | null = null;
  for (const [index, id] of ids.entries()) {
    if (stop) {
      outcomes.set(id, { kind: "not-run" });
      continue;
    }
    try {
      outcomes.set(id, { kind: "issued", invoice: await issue(id) });
    } catch (cause) {
      // The answer may be lost although the server committed: no response,
      // a timeout or rate limit on the way (408, 429), a gateway error (5xx)
      // or a page that is not the API's JSON.
      if (
        !(cause instanceof ApiError) ||
        cause.status === 408 ||
        cause.status === 429 ||
        cause.status >= 500 ||
        cause.detail.code === "unexpected_response_type"
      ) {
        stop = { kind: "network" };
        outcomes.set(id, { kind: "unconfirmed", message: LOST_ANSWER });
      } else if (cause.detail.code === "fresh_login_required") {
        stop = { kind: "fresh-login" };
        outcomes.set(id, { kind: "not-run" });
      } else if (cause.status === 401 || cause.status === 403) {
        stop = { kind: "forbidden", message: cause.detail.message };
        outcomes.set(id, { kind: "failed", message: cause.detail.message });
      } else {
        outcomes.set(id, { kind: "failed", message: refusalMessage(cause) });
      }
    }
    onProgress(index + 1, outcomes);
  }
  return { outcomes, stop };
}

/* ---------- resume after the fresh sign-in ---------- */

const PENDING_PREFIX = "leonaid.bulk-release.";
const PENDING_MAX_AGE_MS = 30 * 60 * 1000;

/** An invoice issued before the run stopped for the fresh sign-in. */
export interface IssuedBefore {
  readonly id: string;
  readonly number: string;
  readonly buyer: string;
}

export interface PendingRelease {
  readonly ids: readonly string[];
  readonly serviceOn: string;
  readonly issued: readonly IssuedBefore[];
  readonly savedAt: number;
}

/** Remembers the selection and date across the fresh sign-in redirect. */
export function savePendingRelease(
  actionId: string,
  pending: Omit<PendingRelease, "savedAt">,
) {
  try {
    window.sessionStorage.setItem(
      `${PENDING_PREFIX}${actionId}`,
      JSON.stringify({ ...pending, savedAt: Date.now() }),
    );
  } catch {
    // Without storage the person selects again after the sign-in.
  }
}

/** Reads and forgets a recent pending release for this action. */
export function takePendingRelease(actionId: string): PendingRelease | null {
  try {
    const key = `${PENDING_PREFIX}${actionId}`;
    const raw = window.sessionStorage.getItem(key);
    window.sessionStorage.removeItem(key);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PendingRelease>;
    if (
      !Array.isArray(value.ids) ||
      !value.ids.every((id) => typeof id === "string") ||
      typeof value.serviceOn !== "string" ||
      typeof value.savedAt !== "number" ||
      (value.issued !== undefined && !Array.isArray(value.issued)) ||
      Date.now() - value.savedAt > PENDING_MAX_AGE_MS
    )
      return null;
    return {
      ids: value.ids,
      serviceOn: value.serviceOn,
      issued: (value.issued ?? []).filter(
        (item): item is IssuedBefore =>
          typeof item?.id === "string" &&
          typeof item.number === "string" &&
          typeof item.buyer === "string",
      ),
      savedAt: value.savedAt,
    };
  } catch {
    return null;
  }
}
