import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useState } from "react";

import {
  ApiError,
  type BuyerMailStatusResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  Button,
  DetailSection,
  StatusMessage,
  useOptionalToast,
  type Tone,
} from "@leonaid/ui";

import { actionErrorMessage } from "../action-admin/errors";
import { commandKey, forgetCommandKey } from "../invoices/invoice-model";
import { berlinDateTime } from "./order-format";

type Kind = BuyerMailStatusResponse["kind"];
type State = BuyerMailStatusResponse["state"];
type Reason = NonNullable<BuyerMailStatusResponse["reason"]>;

export const kindLabels: Readonly<Record<Kind, string>> = {
  confirmation: "Bestellbestätigung",
  cancellation: "Stornierung",
  delivery_day: "Liefertags-E-Mail",
};

const stateLabels: Readonly<Record<State, string>> = {
  not_due: "Nicht fällig",
  queued: "Wartet",
  sent: "Gesendet",
  failed: "Fehlgeschlagen",
  skipped: "Nicht gesendet",
};

const stateTones: Readonly<Record<State, Tone>> = {
  not_due: "neutral",
  queued: "info",
  sent: "ok",
  failed: "danger",
  skipped: "neutral",
};

const reasonTexts: Readonly<Record<Reason, string>> = {
  no_email: "In der Bestellung steht keine E-Mail-Adresse des Käufers.",
  switched_off:
    "E-Mails für Bestellungen, die Mitglieder erfassen, sind in der Aktion ausgeschaltet.",
  order_draft: "Ein Entwurf sendet keine E-Mail.",
  order_cancelled: "Die Bestellung ist storniert.",
  not_requested:
    "Für diese Bestellung wurde keine E-Mail angelegt; die E-Mails der Aktion waren damals ausgeschaltet.",
  not_sent: "Beim Versand gab es nichts zu senden.",
  recipient_limit:
    "An dieses Postfach gingen in der letzten Stunde zu viele E-Mails. Senden Sie die E-Mail später erneut.",
  delivery_failed: "Der Versand ist fehlgeschlagen.",
  delivery_recorded:
    "Die Lieferung ist schon als geliefert oder nicht zugestellt erfasst.",
  scheduled: "Wird am Liefertag gesendet.",
  window_over: "Das Lieferfenster ist vorbei.",
};

/** What the row says under the kind: when it was sent, why it was not. */
export function buyerMailDetail(mail: BuyerMailStatusResponse): string {
  const sent = mail.sentAt
    ? berlinDateTime.format(new Date(mail.sentAt))
    : undefined;
  if (mail.state === "sent") return `Gesendet am ${sent}`;
  const last = sent ? ` Zuletzt gesendet am ${sent}.` : "";
  if (mail.state === "queued") return `Wartet auf den Versand.${last}`;
  return `${mail.reason ? reasonTexts[mail.reason] : stateLabels[mail.state]}${last}`;
}

export const buyerMailsKey = (actionId: string, commitmentId: string) =>
  ["buyer-mails", actionId, commitmentId] as const;

const resendStorageKey = (commitmentId: string, kind: Kind) =>
  `leonaid.buyer-mail-resend.${commitmentId}.${kind}`;

interface BuyerMailsProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  readonly commitmentId: string;
  /** Changes when the order changes (status, address): the block reloads. */
  readonly version: string;
}

/**
 * "E-Mails an den Käufer" in the order detail: one row per mail kind with
 * its state and time, and "Erneut senden" where the server allows it
 * (`canResend`). The server derives every state; nothing is decided here.
 */
export function BuyerMails({
  actionId,
  client,
  commitmentId,
  version,
}: BuyerMailsProps) {
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const [error, setError] = useState<string>();
  const queryKey = [...buyerMailsKey(actionId, commitmentId), version] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => client.listBuyerMails(actionId, commitmentId),
    // A waiting mail usually goes out within seconds.
    refetchInterval: (current) =>
      current.state.data?.mails.some((mail) => mail.state === "queued")
        ? 5000
        : false,
    retry: false,
  });
  const resend = useMutation({
    mutationFn: (kind: Kind) =>
      client.resendBuyerMail(actionId, commitmentId, kind, {
        headers: {
          // One key per attempt: a repeated click after a lost answer
          // replays, it does not send twice.
          "Idempotency-Key": commandKey(
            resendStorageKey(commitmentId, kind),
            "buyer-mail-resend",
          ),
        },
      }),
    onMutate: () => setError(undefined),
    async onSuccess(_result, kind) {
      forgetCommandKey(resendStorageKey(commitmentId, kind));
      await cache.invalidateQueries({ queryKey });
      toast?.show({
        title: `${kindLabels[kind]} wird erneut gesendet.`,
        tone: "success",
      });
    },
    async onError(cause, kind) {
      // An answer from the server ends the attempt; without one the key
      // stays, so the next click cannot send a second mail.
      if (cause instanceof ApiError)
        forgetCommandKey(resendStorageKey(commitmentId, kind));
      await cache.invalidateQueries({ queryKey });
      setError(actionErrorMessage(cause).message);
    },
  });

  return (
    <DetailSection title="E-Mails an den Käufer">
      <div data-testid="buyer-mails">
        {query.isPending ? (
          <p className="small subtle">Wird geladen …</p>
        ) : query.isError ? (
          <StatusMessage tone="error">
            Die E-Mails dieser Bestellung konnten nicht geladen werden.{" "}
            <Button
              onClick={() => void query.refetch()}
              size="sm"
              variant="ghost"
            >
              Erneut versuchen
            </Button>
          </StatusMessage>
        ) : (
          <ul className="buyer-mails">
            {query.data.mails.map((mail) => (
              <li
                data-mail-kind={mail.kind}
                data-mail-state={mail.state}
                key={mail.kind}
              >
                <span className="buyer-mail-text">
                  <span className="buyer-mail-kind">
                    {kindLabels[mail.kind]}{" "}
                    <Badge tone={stateTones[mail.state]}>
                      {stateLabels[mail.state]}
                    </Badge>
                  </span>
                  <span className="small subtle">{buyerMailDetail(mail)}</span>
                </span>
                {mail.canResend ? (
                  <Button
                    aria-label={`${kindLabels[mail.kind]} erneut senden`}
                    data-testid={`buyer-mail-resend-${mail.kind}`}
                    disabled={resend.isPending}
                    icon={Send}
                    loading={resend.isPending && resend.variables === mail.kind}
                    onClick={() => resend.mutate(mail.kind)}
                    size="sm"
                    variant="ghost"
                  >
                    Erneut senden
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
      </div>
    </DetailSection>
  );
}
