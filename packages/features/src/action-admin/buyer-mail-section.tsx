import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  type BuyerMailConfigurationResponse,
  type LeonAidApiClient,
} from "@leonaid/api-client";
import {
  Badge,
  ErrorState,
  Field,
  Select,
  SkeletonRows,
  StatusMessage,
  Switch,
  useOptionalToast,
} from "@leonaid/ui";

import { actionErrorMessage } from "./errors";

export const buyerMailConfigurationKey = (actionId: string) =>
  ["buyer-mail-configuration", actionId] as const;

interface BuyerMailSectionProps {
  readonly actionId: string;
  readonly client: LeonAidApiClient;
  /** Archived action: the switches are shown, not changed. */
  readonly disabled: boolean;
  /** The action has the function "Auslieferung" (delivery windows). */
  readonly hasDelivery: boolean;
}

type Change = Partial<
  Pick<
    BuyerMailConfigurationResponse,
    "internalOrderMails" | "deliveryDayMail" | "deliveryDaySendTime"
  >
>;

/** 05:00 to 12:00 in half hours: the times the server accepts. */
export const SEND_TIMES: readonly string[] = Array.from(
  { length: 15 },
  (_, index) =>
    `${String(5 + Math.floor(index / 2)).padStart(2, "0")}:${index % 2 ? "30" : "00"}`,
);

/**
 * "E-Mails an Käufer" in the action's settings: the switches of
 * `action_buyer_mail_configuration`. A switch saves at once with the row's
 * revision; unlike the action's functions it can change while the action
 * runs. Mails for orders of the public form are not behind a switch.
 */
export function BuyerMailSection({
  actionId,
  client,
  disabled,
  hasDelivery,
}: BuyerMailSectionProps) {
  const cache = useQueryClient();
  const toast = useOptionalToast();
  const queryKey = buyerMailConfigurationKey(actionId);
  const [error, setError] = useState<string>();
  const query = useQuery({
    queryKey,
    queryFn: () => client.getBuyerMailConfiguration(actionId),
    refetchOnWindowFocus: false,
    retry: false,
  });
  const save = useMutation({
    mutationFn: (change: Change) => {
      const current = query.data!;
      return client.saveBuyerMailConfiguration(actionId, {
        expectedRevision: current.revision,
        internalOrderMails:
          change.internalOrderMails ?? current.internalOrderMails,
        deliveryDayMail: change.deliveryDayMail ?? current.deliveryDayMail,
        deliveryDaySendTime:
          change.deliveryDaySendTime ?? current.deliveryDaySendTime,
      });
    },
    onMutate: () => setError(undefined),
    async onSuccess(result, change) {
      cache.setQueryData(queryKey, result);
      // The order list says per order whether a cancellation notifies.
      await cache.invalidateQueries({ queryKey: ["commitments", actionId] });
      if (change.internalOrderMails !== undefined) {
        toast?.show({
          title: result.internalOrderMails
            ? "Käufer erhalten ab jetzt E-Mails zu Bestellungen, die Mitglieder erfassen."
            : "Für Bestellungen, die Mitglieder erfassen, gehen keine E-Mails mehr an Käufer.",
          tone: "success",
        });
      }
      if (change.deliveryDayMail !== undefined) {
        toast?.show({
          title: result.deliveryDayMail
            ? `Käufer erhalten am Liefertag ab ${result.deliveryDaySendTime} Uhr eine E-Mail mit ihrem Lieferfenster.`
            : "Am Liefertag geht keine E-Mail mehr an Käufer.",
          tone: "success",
        });
      }
      if (change.deliveryDaySendTime !== undefined) {
        toast?.show({
          title: `Die E-Mail am Liefertag geht ab ${result.deliveryDaySendTime} Uhr hinaus.`,
          tone: "success",
        });
      }
    },
    async onError(cause) {
      // Someone else changed the switches: show their state.
      if (cause instanceof ApiError && cause.status === 409)
        await cache.invalidateQueries({ queryKey });
      setError(actionErrorMessage(cause).message);
    },
  });

  const heading = (
    <>
      <h2 className="tab-h2" id="buyer-mails-heading">
        E-Mails an Käufer
      </h2>
      <p className="small muted edit-section-intro">
        Wer über das öffentliche Bestellformular bestellt, erhält seine E-Mails
        immer. Hier legen Sie fest, welche E-Mails Käufer zusätzlich bekommen.
        Ein Schalter gilt sofort, auch während die Aktion läuft.
      </p>
      <p
        className="small muted edit-section-intro"
        data-testid="buyer-mail-privacy"
      >
        Bevor Sie einen Schalter einschalten: Die Datenschutzerklärung des Clubs
        muss diese E-Mails nennen (Abschnitt „Bestellungen, die ein Mitglied für
        Sie erfasst“). Ein System-Admin pflegt sie unter „Rechtliches“. LeonAid
        prüft das nicht.
      </p>
    </>
  );

  if (query.isPending) {
    return (
      <section
        aria-busy="true"
        aria-labelledby="buyer-mails-heading"
        className="edit-section"
        id="buyer-mails"
      >
        {heading}
        <SkeletonRows rows={2} />
      </section>
    );
  }
  if (query.isError) {
    return (
      <section
        aria-labelledby="buyer-mails-heading"
        className="edit-section"
        id="buyer-mails"
      >
        {heading}
        <ErrorState
          onRetry={() => void query.refetch()}
          title="Die E-Mail-Einstellungen konnten nicht geladen werden"
        >
          Der Server hat nicht geantwortet. Prüfen Sie die Verbindung und
          versuchen Sie es erneut.
        </ErrorState>
      </section>
    );
  }
  const configuration = query.data;
  return (
    <section
      aria-labelledby="buyer-mails-heading"
      className="edit-section"
      data-testid="buyer-mail-section"
      id="buyer-mails"
    >
      {heading}
      <ul className="choice-list">
        <li className="buyer-mail-switch">
          <div className="buyer-mail-switch-text">
            <label htmlFor="buyer-mail-internal">
              <strong>E-Mails für Bestellungen, die Mitglieder erfassen</strong>
            </label>
            <p className="small muted" id="buyer-mail-internal-description">
              Der Käufer erhält eine Bestellbestätigung, sobald die Bestellung
              prüfbereit ist, und eine Nachricht, wenn sie storniert wird. Das
              gilt für Bestellungen aus der Akquise und aus der Verwaltung, wenn
              in der Bestellung eine E-Mail-Adresse des Käufers steht. Entwürfe
              senden nichts.
            </p>
          </div>
          <Badge tone={configuration.internalOrderMails ? "ok" : "neutral"}>
            {configuration.internalOrderMails ? "An" : "Aus"}
          </Badge>
          <Switch
            aria-describedby="buyer-mail-internal-description"
            checked={configuration.internalOrderMails}
            data-testid="buyer-mail-internal"
            disabled={disabled || save.isPending}
            id="buyer-mail-internal"
            onChange={(event) =>
              save.mutate({ internalOrderMails: event.target.checked })
            }
          />
        </li>
        <li className="buyer-mail-switch">
          <div className="buyer-mail-switch-text">
            <label htmlFor="buyer-mail-delivery-day">
              <strong>E-Mail am Liefertag</strong>
            </label>
            <p className="small muted" id="buyer-mail-delivery-day-description">
              Der Käufer erhält am Tag der Lieferung eine E-Mail mit seinem
              Lieferfenster, zum Beispiel „Ihre Lieferung kommt heute zwischen
              10:00 und 12:00 Uhr“. Sie geht an jede offene Bestellung des Tages
              mit E-Mail-Adresse, auch an Bestellungen aus dem öffentlichen
              Formular. Stornierte und schon abgehakte Bestellungen bekommen
              keine.
              {hasDelivery
                ? null
                : " Diese Aktion hat die Funktion „Auslieferung“ nicht; der Schalter bleibt deshalb aus."}
            </p>
          </div>
          <Badge tone={configuration.deliveryDayMail ? "ok" : "neutral"}>
            {configuration.deliveryDayMail ? "An" : "Aus"}
          </Badge>
          <Switch
            aria-describedby="buyer-mail-delivery-day-description"
            checked={configuration.deliveryDayMail}
            data-testid="buyer-mail-delivery-day"
            disabled={
              disabled ||
              save.isPending ||
              // Switching off stays possible when the function is gone.
              (!hasDelivery && !configuration.deliveryDayMail)
            }
            id="buyer-mail-delivery-day"
            onChange={(event) =>
              save.mutate({ deliveryDayMail: event.target.checked })
            }
          />
        </li>
      </ul>
      {hasDelivery || configuration.deliveryDayMail ? (
        <Field
          className="buyer-mail-send-time"
          hint="Ortszeit der Aktion (Zeitzone der Lieferfenster). Ein Lieferfenster, das vor dieser Uhrzeit endet, bekommt keine E-Mail."
          label="E-Mail am Liefertag senden ab"
        >
          <Select
            data-testid="buyer-mail-send-time"
            disabled={disabled || save.isPending}
            onChange={(event) =>
              save.mutate({ deliveryDaySendTime: event.target.value })
            }
            value={configuration.deliveryDaySendTime}
          >
            {[...new Set([configuration.deliveryDaySendTime, ...SEND_TIMES])]
              .sort()
              .map((time) => (
                <option key={time} value={time}>
                  {time} Uhr
                </option>
              ))}
          </Select>
        </Field>
      ) : null}
      {error ? <StatusMessage tone="error">{error}</StatusMessage> : null}
    </section>
  );
}
