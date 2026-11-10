import { StatusMessage } from "@leonaid/ui";

interface BuyerMailNoticeProps {
  /** The buyer's address in the order (from the sponsor's CRM record). */
  readonly email: string | null | undefined;
  /** The action's switches, from the capture context. */
  readonly internalOrderMails?: boolean | undefined;
  readonly deliveryDayMail?: boolean | undefined;
  /** "du" in the acquisition app (default), "Sie" in the web admin. */
  readonly address?: "du" | "Sie";
}

/** "die Bestellbestätigung, am Liefertag … und eine Stornierung" */
export function buyerMailList(
  internalOrderMails: boolean,
  deliveryDayMail: boolean,
): string {
  const mails = [
    ...(internalOrderMails ? ["die Bestellbestätigung"] : []),
    ...(deliveryDayMail
      ? ["am Liefertag der Hinweis auf das Lieferfenster"]
      : []),
    ...(internalOrderMails ? ["eine Stornierung"] : []),
  ];
  return mails.length > 1
    ? `${mails.slice(0, -1).join(", ")} und ${mails.at(-1)}`
    : (mails[0] ?? "");
}

/**
 * Tells the member where the buyer's mails for this order go, before the
 * order is saved. The address is the sponsor's from the CRM, not one the
 * buyer named for this order, so the member checks it with the buyer.
 * Nothing is shown while the action sends no mails for recorded orders.
 */
export function BuyerMailNotice({
  address: form = "du",
  deliveryDayMail = false,
  email,
  internalOrderMails = false,
}: BuyerMailNoticeProps) {
  if (!internalOrderMails && !deliveryDayMail) return null;
  const address = email?.trim();
  return (
    <StatusMessage tone="info">
      <span data-testid="buyer-mail-notice">
        {address ? (
          <>
            E-Mails zu dieser Bestellung gehen an <strong>{address}</strong>{" "}
            (Adresse des Sponsors aus dem CRM):{" "}
            {buyerMailList(internalOrderMails, deliveryDayMail)}.{" "}
            {form === "du"
              ? "Frag den Käufer, ob die Adresse stimmt. Ist sie falsch, lass sie vor dem Speichern im CRM ändern."
              : "Klären Sie mit dem Käufer, ob die Adresse stimmt, bevor Sie speichern."}
          </>
        ) : (
          <>
            Für diesen Sponsor ist keine E-Mail-Adresse hinterlegt. Der Käufer
            erhält keine E-Mails zu dieser Bestellung.
          </>
        )}
      </span>
    </StatusMessage>
  );
}
